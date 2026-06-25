import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import Incident, Serial, AuditLog, User
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
    q = db.query(Incident)
    if status in STATUSES:
        q = q.filter(Incident.status == status)
    incidents = q.order_by(Incident.created_at.desc()).all()
    open_count = db.query(Incident).filter(Incident.status.in_(["open", "investigating"])).count()
    return templates.TemplateResponse(request, "incidents.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "incidents": incidents,
        "severities": SEVERITIES,
        "statuses": STATUSES,
        "filter_status": status,
        "open_count": open_count,
        "serials": db.query(Serial).filter(Serial.closed_at == None).order_by(Serial.opened_at.desc()).all(),
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
        inc = Incident(
            title=title,
            description=description.strip() or None,
            severity=severity if severity in SEVERITIES else "medium",
            affected=affected.strip() or None,
            serial_id=int(serial_id) if serial_id.strip().isdigit() else None,
            reported_by_id=current_user.id,
        )
        db.add(inc)
        db.flush()
        db.add(AuditLog(user_id=current_user.id, action_type="INCIDENT_CREATE",
                        entity_type="Incident", entity_id=inc.id, new_value=inc.title))
        db.commit()
    return RedirectResponse("/incidents?toast=Incident+logged", status_code=302)


@router.post("/{inc_id}/update")
async def incident_update(
    inc_id: int,
    status: str = Form(...),
    resolution: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inc = db.query(Incident).filter(Incident.id == inc_id).first()
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
    incidents = db.query(Incident).order_by(Incident.created_at.desc()).all()
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
