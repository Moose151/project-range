import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state, require_supervisor
from app.models import Incident, Serial, AuditLog, User, Role
from app.templating import templates

router = APIRouter(prefix="/incidents")

SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = ["open", "investigating", "resolved", "closed"]
CLOSED_STATUSES = {"resolved", "closed"}


@router.get("", response_class=HTMLResponse)
async def incidents_list(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    q = db.query(Incident).filter(
        Incident.is_testing == testing,
        Incident.approval_status == "approved",
    )
    if status in STATUSES:
        q = q.filter(Incident.status == status)
    incidents = q.order_by(Incident.created_at.desc()).all()
    open_count = db.query(Incident).filter(
        Incident.status.in_(["open", "investigating"]),
        Incident.is_testing == testing,
        Incident.approval_status == "approved",
    ).count()
    pending_q = db.query(Incident).filter(
        Incident.is_testing == testing,
        Incident.approval_status == "pending",
    )
    if current_user.role != Role.ADMINISTRATOR:
        pending_q = pending_q.filter(Incident.reported_by_id == current_user.id)
    pending_incidents = pending_q.order_by(Incident.created_at.asc()).all()
    return templates.TemplateResponse(request, "incidents.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "incidents": incidents,
        "severities": SEVERITIES,
        "statuses": STATUSES,
        "filter_status": status,
        "open_count": open_count,
        "pending_incidents": pending_incidents,
        "serials": db.query(Serial).filter(Serial.closed_at == None, Serial.is_testing == testing).order_by(Serial.opened_at.desc()).all(),
        "toast": request.query_params.get("toast", ""),
        "page": "incidents",
    })


@router.post("/new")
async def incident_create(
    title: str = Form(...),
    description: str = Form(""),
    severity: str = Form("medium"),
    affected: str = Form(""),
    serial_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    title = title.strip()
    if title:
        testing = is_testing_state(db)
        serial = (
            db.query(Serial)
            .filter(Serial.id == int(serial_id), Serial.is_testing == testing)
            .first()
            if serial_id.strip().isdigit()
            else None
        )
        inc = Incident(
            title=title,
            description=description.strip() or None,
            severity=severity if severity in SEVERITIES else "medium",
            affected=affected.strip() or None,
            serial_id=serial.id if serial else None,
            reported_by_id=current_user.id,
            is_testing=testing,
            approval_status="pending" if current_user.role == Role.OBSERVER else "approved",
        )
        db.add(inc)
        db.flush()
        if inc.approval_status == "pending":
            action = "INCIDENT_SUBMIT_PENDING"
            toast = "Incident+submitted+for+administrator+approval"
        else:
            action = "INCIDENT_CREATE"
            toast = "Incident+logged"
        db.add(AuditLog(user_id=current_user.id, action_type=action,
                        entity_type="Incident", entity_id=inc.id, new_value=inc.title))
        db.commit()
        return RedirectResponse(f"/incidents?toast={toast}", status_code=302)
    return RedirectResponse("/incidents", status_code=302)


@router.post("/{inc_id}/approve")
async def incident_approve(
    inc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    inc = db.query(Incident).filter(
        Incident.id == inc_id,
        Incident.is_testing == is_testing_state(db),
        Incident.approval_status == "pending",
    ).first()
    if inc:
        inc.approval_status = "approved"
        inc.approved_by_id = current_user.id
        inc.approved_at = datetime.utcnow()
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="INCIDENT_APPROVE",
            entity_type="Incident",
            entity_id=inc.id,
            new_value=inc.title,
        ))
        db.commit()
    return RedirectResponse("/incidents?toast=Incident+approved", status_code=302)


@router.post("/{inc_id}/reject")
async def incident_reject(
    inc_id: int,
    rejection_reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    inc = db.query(Incident).filter(
        Incident.id == inc_id,
        Incident.is_testing == is_testing_state(db),
        Incident.approval_status == "pending",
    ).first()
    if inc:
        inc.approval_status = "rejected"
        inc.rejection_reason = rejection_reason.strip() or None
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="INCIDENT_REJECT",
            entity_type="Incident",
            entity_id=inc.id,
            previous_value=inc.title,
            new_value=inc.rejection_reason,
        ))
        db.commit()
    return RedirectResponse("/incidents?toast=Incident+rejected", status_code=302)


@router.post("/{inc_id}/update")
async def incident_update(
    inc_id: int,
    status: str = Form(...),
    resolution: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inc = db.query(Incident).filter(
        Incident.id == inc_id,
        Incident.is_testing == is_testing_state(db),
        Incident.approval_status == "approved",
    ).first()
    if inc:
        prev = inc.status
        if status in STATUSES:
            inc.status = status
        inc.resolution = resolution.strip() or inc.resolution
        if status in CLOSED_STATUSES and not inc.resolved_at:
            inc.resolved_at = datetime.utcnow()
            inc.resolved_by_id = current_user.id
        elif status not in CLOSED_STATUSES:
            inc.resolved_at = None
            inc.resolved_by_id = None
        db.add(AuditLog(user_id=current_user.id, action_type="INCIDENT_UPDATE",
                        entity_type="Incident", entity_id=inc.id,
                        previous_value=prev, new_value=inc.status))
        db.commit()
    return RedirectResponse("/incidents?toast=Incident+updated", status_code=302)


@router.get("/export.csv")
async def incidents_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    incidents = db.query(Incident).filter(
        Incident.is_testing == is_testing_state(db),
        Incident.approval_status == "approved",
    ).order_by(Incident.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Created", "Severity", "Status", "Title", "Affected",
                "Description", "Reported by", "Resolved", "Resolution"])
    for i in incidents:
        w.writerow([
            i.id, i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else "",
            i.severity, i.status, i.title, i.affected or "", i.description or "",
            i.reported_by.display_name if i.reported_by else "",
            i.resolved_at.strftime("%Y-%m-%d %H:%M") if i.resolved_at else "",
            i.resolution or "",
        ])
    buf.seek(0)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=incidents_{stamp}.csv"},
    )
