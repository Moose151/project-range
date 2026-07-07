import csv
import io
import openpyxl
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state
from app.models import Activity, ActivityType, Serial, SignalLog, User, AuditLog
from app.templating import templates

router = APIRouter(prefix="/activities")

CSV_FIELDS = [
    "ID", "Timestamp (Zulu)", "Operator", "Serial", "Range State", "Signal", "Status",
    "TxIF", "TxRF", "RxRF", "RxIF", "Unit", "Band",
    "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
    "Power", "Power Unit", "Eb/No", "Notes", "Type",
]


def _log_row(log, serial_title):
    return [
        log.id,
        log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ"),
        log.operator.username if log.operator else "",
        serial_title,
        log.range_state,
        log.signal_name,
        log.signal_status,
        log.tx_if,
        log.tx_rf,
        log.rx_rf,
        log.rx_if,
        log.freq_unit,
        log.band,
        log.modulation,
        log.symbol_rate,
        log.fec,
        log.source,
        log.antenna,
        log.power,
        log.power_unit,
        log.eb_no,
        log.notes,
        log.entry_type,
    ]


@router.get("", response_class=HTMLResponse)
async def activities_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    activities = (
        db.query(Activity)
        .filter(Activity.is_testing == testing)
        .order_by(Activity.created_at.desc())
        .all()
    )
    activity_types = (
        db.query(ActivityType)
        .filter(ActivityType.is_active == True)
        .order_by(ActivityType.display_order, ActivityType.name)
        .all()
    )
    return templates.TemplateResponse(request, "activities.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "activities": activities,
        "activity_types": activity_types,
        "page": "activities",
        "toast": request.query_params.get("toast", ""),
    })


@router.post("/new")
async def activity_create(
    request: Request,
    name: str = Form(...),
    activity_type_id: int = Form(0),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    activity = Activity(
        name=name.strip(),
        activity_type_id=activity_type_id if activity_type_id > 0 else None,
        description=description.strip() or None,
        created_by_id=current_user.id,
    )
    db.add(activity)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id, action_type="ACTIVITY_CREATE",
        entity_type="Activity", entity_id=activity.id, new_value=activity.name,
    ))
    db.commit()
    return RedirectResponse(f"/activities/{activity.id}", status_code=302)


@router.get("/{activity_id}", response_class=HTMLResponse)
async def activity_detail(
    activity_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)

    activity_types = (
        db.query(ActivityType)
        .filter(ActivityType.is_active == True)
        .order_by(ActivityType.display_order, ActivityType.name)
        .all()
    )
    unassigned_serials = (
        db.query(Serial)
        .filter(
            Serial.is_testing == testing,
            Serial.activity_id == None,
        )
        .order_by(Serial.opened_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "activity_detail.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "activity": activity,
        "activity_types": activity_types,
        "unassigned_serials": unassigned_serials,
        "page": "activities",
        "toast": request.query_params.get("toast", ""),
    })


@router.post("/{activity_id}/edit")
async def activity_edit(
    activity_id: int,
    name: str = Form(...),
    activity_type_id: int = Form(0),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)
    activity.name = name.strip() or activity.name
    activity.activity_type_id = activity_type_id if activity_type_id > 0 else None
    activity.description = description.strip() or None
    db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Activity+updated", status_code=302)


@router.post("/{activity_id}/assign-serial")
async def activity_assign_serial(
    activity_id: int,
    serial_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    serial = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_testing == testing,
    ).first()
    if activity and serial:
        serial.activity_id = activity.id
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Serial+assigned", status_code=302)


@router.post("/{activity_id}/unassign-serial/{serial_id}")
async def activity_unassign_serial(
    activity_id: int,
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_testing == testing, Serial.activity_id == activity_id,
    ).first()
    if serial:
        serial.activity_id = None
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Serial+unassigned", status_code=302)


@router.get("/{activity_id}/export/csv")
async def activity_export_csv(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for serial in sorted(activity.serials, key=lambda s: s.opened_at or s.id):
        logs = (
            db.query(SignalLog)
            .filter(
                SignalLog.serial_id == serial.id,
                SignalLog.is_deleted == False,
                SignalLog.is_testing == testing,
            )
            .order_by(SignalLog.timestamp.asc())
            .all()
        )
        for log in logs:
            writer.writerow(_log_row(log, serial.title))
    output.seek(0)
    fname = (activity.name.replace(" ", "_").replace("/", "-")[:60]) + ".csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{activity_id}/export/xlsx")
async def activity_export_xlsx(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Activity Log"
    ws.append(CSV_FIELDS)
    for serial in sorted(activity.serials, key=lambda s: s.opened_at or s.id):
        logs = (
            db.query(SignalLog)
            .filter(
                SignalLog.serial_id == serial.id,
                SignalLog.is_deleted == False,
                SignalLog.is_testing == testing,
            )
            .order_by(SignalLog.timestamp.asc())
            .all()
        )
        for log in logs:
            ws.append(_log_row(log, serial.title))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = (activity.name.replace(" ", "_").replace("/", "-")[:60]) + ".xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
