import csv
import io
import openpyxl
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state
from app.models import (
    Activity, ActivityType, CDATable, Serial, SerialCDATable, SerialPackage,
    SignalLog, SignalPackage, SignalPackageEntry, User, AuditLog,
)
from app.ops_health import package_health_badges, serial_readiness_badges
from app.routers.packages import _cbm_source_device, _dropdown_lists
from app.templating import templates

router = APIRouter(prefix="/activities")

CSV_FIELDS = [
    "ID", "Timestamp (Zulu)", "Operator", "Serial", "Range State", "Signal", "Status",
    "TxIF", "TxRF", "RxRF", "RxIF", "Unit", "Band",
    "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
    "Power", "Power Unit", "Eb/No", "BER", "Notes", "Type",
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
        log.ber_estimate,
        log.notes,
        log.entry_type,
    ]


def _activity_or_redirect(db: Session, activity_id: int, testing: bool) -> Activity | None:
    return db.query(Activity).filter(
        Activity.id == activity_id,
        Activity.is_testing == testing,
    ).first()


def _activity_serial(db: Session, activity_id: int, serial_id: int, testing: bool) -> Serial | None:
    return db.query(Serial).filter(
        Serial.id == serial_id,
        Serial.activity_id == activity_id,
        Serial.is_testing == testing,
    ).first()


def _activity_has_open_package(activity: Activity, package_id: int) -> bool:
    return any(
        serial.closed_at is None and link.package_id == package_id
        for serial in (activity.serials or [])
        for link in (serial.package_links or [])
    )


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
    packages = (
        db.query(SignalPackage)
        .filter(SignalPackage.is_testing == testing)
        .order_by(SignalPackage.name)
        .all()
    )
    cda_tables = (
        db.query(CDATable)
        .filter(CDATable.is_testing == testing)
        .order_by(CDATable.name)
        .all()
    )
    serials = list(activity.serials or [])
    activity_packages = {
        link.package.id: link.package
        for serial in serials
        for link in (serial.package_links or [])
        if link.package
    }.values()
    dropdowns = _dropdown_lists(db)
    return templates.TemplateResponse(request, "activity_detail.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "activity": activity,
        "activity_types": activity_types,
        "unassigned_serials": unassigned_serials,
        "packages": packages,
        "cda_tables": cda_tables,
        "serial_readiness": {serial.id: serial_readiness_badges(serial) for serial in serials},
        "package_health": {package.id: package_health_badges(package) for package in activity_packages},
        "page": "activities",
        "toast": request.query_params.get("toast", ""),
        "error": request.query_params.get("error", ""),
        **dropdowns,
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


@router.post("/{activity_id}/complete")
async def activity_complete(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an activity complete: end all its open serials (→ serial history with
    their logs) and move the activity to the Completed/history section."""
    from app.routers.serials import end_serial
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)
    ended = 0
    for serial in list(activity.serials or []):
        if serial.is_started and serial.closed_at is None:
            if end_serial(db, serial, current_user):
                ended += 1
    activity.completed_at = datetime.utcnow()
    activity.completed_by_id = current_user.id
    db.add(AuditLog(
        user_id=current_user.id, action_type="ACTIVITY_COMPLETE",
        entity_type="Activity", entity_id=activity.id, new_value=activity.name,
        comment=f"Completed; ended {ended} running serial(s).",
    ))
    db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Activity+completed", status_code=302)


@router.post("/{activity_id}/delete")
async def activity_delete(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an activity. Its serials are unassigned (kept), not deleted."""
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity:
        return RedirectResponse("/activities", status_code=302)
    for serial in list(activity.serials or []):
        serial.activity_id = None
    name = activity.name
    db.add(AuditLog(
        user_id=current_user.id, action_type="ACTIVITY_DELETE",
        entity_type="Activity", entity_id=activity.id, previous_value=name,
    ))
    db.delete(activity)
    db.commit()
    return RedirectResponse("/activities?toast=Activity+deleted", status_code=302)


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


@router.post("/{activity_id}/serials/new")
async def activity_new_serial(
    activity_id: int,
    title: str = Form(...),
    notes: str = Form(""),
    instructions: str = Form(""),
    package_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new pending serial directly inside this activity — no page hop."""
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    if not activity or not title.strip():
        return RedirectResponse(f"/activities/{activity_id}", status_code=302)
    serial = Serial(
        title=title.strip(),
        notes=notes.strip() or None,
        instructions=instructions.strip() or None,
        opened_by_id=current_user.id,
        is_testing=testing,
        activity_id=activity.id,
    )
    db.add(serial)
    db.flush()
    for pid in package_ids:
        pkg = db.query(SignalPackage).filter(
            SignalPackage.id == pid, SignalPackage.is_testing == testing,
        ).first()
        if pkg:
            db.add(SerialPackage(serial_id=serial.id, package_id=pid))
    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_CREATE",
        entity_type="Serial", entity_id=serial.id, new_value=serial.title,
    ))
    db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Serial+created", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/clone")
async def activity_clone_serial(
    activity_id: int,
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Duplicate a serial's setup (packages, CDA tables, notes/instructions) as a
    new pending serial in the same activity. Signal logs / lifecycle are not copied."""
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.is_testing == testing,
    ).first()
    orig = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_testing == testing, Serial.activity_id == activity_id,
    ).first()
    if not activity or not orig:
        return RedirectResponse(f"/activities/{activity_id}", status_code=302)
    clone = Serial(
        title=f"{orig.title} (copy)",
        notes=orig.notes,
        instructions=orig.instructions,
        opened_by_id=current_user.id,
        is_testing=testing,
        activity_id=activity.id,
    )
    db.add(clone)
    db.flush()
    for link in orig.package_links:
        db.add(SerialPackage(serial_id=clone.id, package_id=link.package_id))
    for link in orig.cda_links:
        db.add(SerialCDATable(serial_id=clone.id, cda_table_id=link.cda_table_id))
    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_CLONE",
        entity_type="Serial", entity_id=clone.id, new_value=clone.title,
    ))
    db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Serial+cloned+as+pending", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/edit")
async def activity_serial_edit(
    activity_id: int,
    serial_id: int,
    title: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = _activity_serial(db, activity_id, serial_id, testing)
    if serial and serial.closed_at is None:
        previous = serial.title
        serial.title = title.strip() or serial.title
        serial.notes = notes.strip() or None
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="ACTIVITY_SERIAL_EDIT",
            entity_type="Serial",
            entity_id=serial.id,
            previous_value=previous,
            new_value=serial.title,
        ))
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Serial+updated", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/packages/add")
async def activity_serial_add_package(
    activity_id: int,
    serial_id: int,
    package_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = _activity_serial(db, activity_id, serial_id, testing)
    package = db.query(SignalPackage).filter(
        SignalPackage.id == package_id,
        SignalPackage.is_testing == testing,
    ).first()
    if serial and package and serial.closed_at is None:
        existing = db.query(SerialPackage).filter(
            SerialPackage.serial_id == serial.id,
            SerialPackage.package_id == package.id,
        ).first()
        if not existing:
            db.add(SerialPackage(serial_id=serial.id, package_id=package.id))
            db.add(AuditLog(
                user_id=current_user.id,
                action_type="ACTIVITY_SERIAL_PACKAGE_ADD",
                entity_type="Serial",
                entity_id=serial.id,
                new_value=f"Added package: {package.name}",
            ))
            db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Package+assigned", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/packages/{package_id}/remove")
async def activity_serial_remove_package(
    activity_id: int,
    serial_id: int,
    package_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = _activity_serial(db, activity_id, serial_id, testing)
    link = db.query(SerialPackage).filter(
        SerialPackage.serial_id == serial_id,
        SerialPackage.package_id == package_id,
    ).first() if serial and serial.closed_at is None else None
    if link:
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="ACTIVITY_SERIAL_PACKAGE_REMOVE",
            entity_type="Serial",
            entity_id=serial_id,
            new_value=f"Removed package id={package_id}",
        ))
        db.delete(link)
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Package+removed", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/cda/assign")
async def activity_serial_assign_cda(
    activity_id: int,
    serial_id: int,
    cda_table_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = _activity_serial(db, activity_id, serial_id, testing)
    cda_table = db.query(CDATable).filter(
        CDATable.id == cda_table_id,
        CDATable.is_testing == testing,
    ).first()
    if serial and cda_table and serial.closed_at is None:
        existing = db.query(SerialCDATable).filter(
            SerialCDATable.serial_id == serial.id,
            SerialCDATable.cda_table_id == cda_table.id,
        ).first()
        if not existing:
            db.add(SerialCDATable(serial_id=serial.id, cda_table_id=cda_table.id))
            db.add(AuditLog(
                user_id=current_user.id,
                action_type="ACTIVITY_SERIAL_CDA_ASSIGN",
                entity_type="Serial",
                entity_id=serial.id,
                new_value=f"Assigned CDA table: {cda_table.name}",
            ))
            db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=CDA+assigned", status_code=302)


@router.post("/{activity_id}/serials/{serial_id}/cda/{cda_table_id}/remove")
async def activity_serial_remove_cda(
    activity_id: int,
    serial_id: int,
    cda_table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    testing = is_testing_state(db)
    serial = _activity_serial(db, activity_id, serial_id, testing)
    link = db.query(SerialCDATable).filter(
        SerialCDATable.serial_id == serial_id,
        SerialCDATable.cda_table_id == cda_table_id,
    ).first() if serial and serial.closed_at is None else None
    if link:
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="ACTIVITY_SERIAL_CDA_REMOVE",
            entity_type="Serial",
            entity_id=serial_id,
            new_value=f"Removed CDA table id={cda_table_id}",
        ))
        db.delete(link)
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=CDA+removed", status_code=302)


@router.post("/{activity_id}/packages/{pkg_id}/signals/{entry_id}/update")
async def activity_package_signal_update(
    activity_id: int,
    pkg_id: int,
    entry_id: int,
    signal_name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    tx_if: float | None = Form(None),
    tx_rf: float | None = Form(None),
    rx_rf: float | None = Form(None),
    rx_if: float | None = Form(None),
    freq_unit: str = Form("MHz"),
    modulation: str = Form(""),
    fec: str = Form(""),
    inner_code: str = Form(""),
    symbol_rate: str = Form(""),
    power: float | None = Form(None),
    power_unit: str = Form("dBm"),
    source: str = Form(""),
    antenna: str = Form(""),
    cbm_path: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403)
    if not symbol_rate.strip():
        return RedirectResponse(f"/activities/{activity_id}?error=Symbol+rate+is+required", status_code=302)

    testing = is_testing_state(db)
    activity = _activity_or_redirect(db, activity_id, testing)
    if not activity:
        return RedirectResponse("/activities", status_code=302)
    package = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == testing,
    ).first()
    package_is_in_activity = _activity_has_open_package(activity, pkg_id)
    entry = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.id == entry_id,
        SignalPackageEntry.package_id == pkg_id,
    ).first() if package and package_is_in_activity else None

    if entry:
        source_name = source.strip()
        cbm_device = _cbm_source_device(db, source_name, testing)
        cbm_device_id = cbm_device.id if cbm_device else None
        if cbm_device:
            source_name = cbm_device.name
        previous = entry.signal_name
        entry.signal_name = signal_name.strip()
        entry.description = description.strip() or None
        entry.band = band or None
        entry.tx_if = tx_if
        entry.tx_rf = tx_rf
        entry.rx_rf = rx_rf
        entry.rx_if = rx_if
        entry.freq_unit = freq_unit or "MHz"
        entry.modulation = modulation or None
        entry.fec = fec or None
        entry.inner_code = inner_code.strip() or None
        entry.symbol_rate = symbol_rate or None
        entry.power = power
        entry.power_unit = power_unit or "dBm"
        entry.eb_no = None
        entry.source = source_name or None
        entry.antenna = antenna.strip() or None
        entry.cbm_device_id = cbm_device_id
        entry.cbm_path = cbm_path or None
        entry.notes = notes.strip() or None
        package.updated_at = datetime.utcnow()
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="ACTIVITY_PACKAGE_SIGNAL_UPDATE",
            entity_type="SignalPackageEntry",
            entity_id=entry.id,
            previous_value=previous,
            new_value=entry.signal_name,
        ))
        db.commit()
    return RedirectResponse(f"/activities/{activity_id}?toast=Signal+updated", status_code=302)


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
