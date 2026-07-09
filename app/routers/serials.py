from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials, is_testing_state
from app.models import (
    User, Serial, SerialPackage, SignalPackage, SignalLog, AuditLog,
    CDATable, SerialCDATable, Activity,
)
from app.rf_config import serial_package_rf_config
from app.ops_health import serial_readiness_badges

router = APIRouter(prefix="/serials")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def serials_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    active = db.query(Serial).filter(
        Serial.closed_at == None, Serial.is_started == True, Serial.is_testing == testing,
    ).order_by(Serial.opened_at.asc()).all()
    pending = db.query(Serial).filter(
        Serial.closed_at == None, Serial.is_started == False, Serial.is_testing == testing,
    ).order_by(Serial.opened_at.desc()).all()
    packages = db.query(SignalPackage).filter(SignalPackage.is_testing == testing).order_by(SignalPackage.name).all()
    cda_tables = db.query(CDATable).filter(CDATable.is_testing == testing).order_by(CDATable.name).all()
    activities = (
        db.query(Activity)
        .filter(Activity.is_testing == testing)
        .order_by(Activity.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "serials.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active,
        "pending_serials": pending,
        "serial_readiness": {
            serial.id: serial_readiness_badges(serial)
            for serial in [*pending, *active]
        },
        "packages": packages,
        "cda_tables": cda_tables,
        "activities": activities,
        "toast": request.query_params.get("toast", ""),
        "page": "serials",
    })


@router.post("/new")
async def serial_create(
    request: Request,
    title: str = Form(...),
    notes: str = Form(""),
    instructions: str = Form(""),
    package_ids: list[int] = Form(default=[]),
    action: str = Form("start"),
    activity_id: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = Serial(
        title=title.strip(),
        notes=notes.strip() or None,
        instructions=instructions.strip() or None,
        opened_by_id=current_user.id,
        is_testing=testing,
    )
    db.add(serial)
    db.flush()

    if activity_id > 0:
        act = db.query(Activity).filter(Activity.id == activity_id, Activity.is_testing == testing).first()
        if act:
            serial.activity_id = act.id

    for pid in package_ids:
        pkg = db.query(SignalPackage).filter(SignalPackage.id == pid, SignalPackage.is_testing == testing).first()
        if pkg:
            db.add(SerialPackage(serial_id=serial.id, package_id=pid))

    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_CREATE",
        entity_type="Serial", entity_id=serial.id, new_value=serial.title,
    ))
    db.commit()
    if action == "save":
        return RedirectResponse("/serials?toast=Serial+saved+as+pending", status_code=302)
    return RedirectResponse(f"/serials/{serial.id}/start", status_code=302)


@router.get("/{serial_id}/start", response_class=HTMLResponse)
async def serial_start_page(
    serial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirmation page before pre-populating signals from packages."""
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    if not serial:
        return RedirectResponse("/serials", status_code=302)

    # Gather signals from all assigned packages
    preview_signals = []
    for sp in serial.package_links:
        for entry in sp.package.signals:
            preview_signals.append((sp.package.name, entry))

    return templates.TemplateResponse(request, "serial_start.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "serial": serial,
        "preview_signals": preview_signals,
        "page": "serials",
    })


@router.post("/{serial_id}/start")
async def serial_start(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create initial SignalLog entries for all package signals and log the start."""
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    if not serial:
        return RedirectResponse("/serials", status_code=302)

    range_state = get_current_range_state(db)

    # Opening narrative entry
    db.add(SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name="[NOTE]",
        signal_status="Note",
        freq_unit="MHz",
        power_unit="dBm",
        notes=f"Serial started: {serial.title}",
        entry_type="SerialStart",
        serial_id=serial.id,
    ))

    # Initial entries for every signal in assigned packages
    seen_names: set[str] = set()
    for sp in serial.package_links:
        pkg = sp.package
        for entry in pkg.signals:
            if entry.signal_name in seen_names:
                continue
            seen_names.add(entry.signal_name)
            db.add(SignalLog(
                operator_id=current_user.id,
                range_state=range_state,
                signal_name=entry.signal_name,
                signal_status="Planned",
                band=pkg.band or entry.band,
                tx_if=entry.tx_if,
                tx_rf=entry.tx_rf,
                rx_rf=entry.rx_rf,
                rx_if=entry.rx_if,
                freq_unit=pkg.freq_unit or entry.freq_unit or "MHz",
                modulation=entry.modulation,
                fec=entry.fec,
                symbol_rate=entry.symbol_rate,
                power=entry.power,
                power_unit=entry.power_unit or "dBm",
                eb_no=None,
                source=entry.source,
                antenna=pkg.antenna or entry.antenna,
                notes=f"Initial load from package: {pkg.name}",
                entry_type="SerialStart",
                serial_id=serial.id,
            ))

    serial.is_started = True
    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_START",
        entity_type="Serial", entity_id=serial.id, new_value=serial.title,
    ))
    db.commit()
    return RedirectResponse(f"/?toast=Serial+started%3A+{serial.title}", status_code=302)


def end_serial(db: Session, serial: Serial, current_user: User) -> bool:
    """Close a serial: down any Up signals, write the SerialEnd marker, audit.
    Does not commit (the caller does). Returns False if already closed / no-op."""
    if not serial or serial.closed_at:
        return False
    range_state = get_current_range_state(db)
    testing = serial.is_testing
    serial.closed_at = datetime.utcnow()
    serial.closed_by_id = current_user.id

    # Ending a serial stops its signals: no signal on a historical serial may
    # remain "Up". Append a Down log for any signal currently Up in this serial.
    up_logs = (
        db.query(SignalLog)
        .filter(
            SignalLog.serial_id == serial.id,
            SignalLog.is_deleted == False,
            SignalLog.signal_name != "[NOTE]",
            SignalLog.is_testing == testing,
        )
        .order_by(SignalLog.signal_name, SignalLog.timestamp.desc())
        .all()
    )
    seen: set[str] = set()
    for log in up_logs:
        if log.signal_name in seen:
            continue
        seen.add(log.signal_name)
        if log.signal_status == "Up":
            db.add(SignalLog(
                operator_id=current_user.id,
                range_state=range_state,
                signal_name=log.signal_name,
                signal_status="Down",
                tx_if=log.tx_if, tx_rf=log.tx_rf, rx_rf=log.rx_rf, rx_if=log.rx_if,
                freq_unit=log.freq_unit, band=log.band,
                modulation=log.modulation, symbol_rate=log.symbol_rate, fec=log.fec,
                power=log.power, power_unit=log.power_unit,
                eb_no=None,
                engaged=log.engaged,
                source=log.source, antenna=log.antenna,
                notes=f"Auto-down: serial ended ({serial.title})",
                entry_type="Automatic",
                updated_by_id=current_user.id,
                serial_id=serial.id,
                is_testing=testing,
            ))

    db.add(SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name="[NOTE]",
        signal_status="Note",
        freq_unit="MHz",
        power_unit="dBm",
        notes=f"Serial ended: {serial.title}",
        entry_type="SerialEnd",
        serial_id=serial.id,
    ))
    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_END",
        entity_type="Serial", entity_id=serial.id,
    ))
    return True


@router.post("/{serial_id}/end")
async def serial_end(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    if not end_serial(db, serial, current_user):
        return RedirectResponse("/serials", status_code=302)
    db.commit()
    return RedirectResponse("/?toast=Serial+closed", status_code=302)


@router.post("/{serial_id}/delete")
async def serial_delete(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a pending (not yet started) serial."""
    serial = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_started == False, Serial.closed_at == None,
        Serial.is_testing == is_testing_state(db),
    ).first()
    if serial:
        db.add(AuditLog(
            user_id=current_user.id, action_type="SERIAL_DELETE",
            entity_type="Serial", entity_id=serial_id, new_value=serial.title,
        ))
        db.delete(serial)
        db.commit()
    return RedirectResponse("/serials?toast=Pending+serial+discarded", status_code=302)


@router.post("/{serial_id}/details")
async def serial_update_details(
    serial_id: int,
    title: str = Form(""),
    notes: str = Form(""),
    instructions: str = Form(""),
    redirect: str = Form("/serials"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a serial's title, notes and operational instructions (before close)."""
    serial = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_testing == is_testing_state(db),
    ).first()
    if serial and serial.closed_at is None:
        if title.strip():
            serial.title = title.strip()
        serial.notes = notes.strip() or None
        serial.instructions = instructions.strip() or None
        db.add(AuditLog(
            user_id=current_user.id, action_type="SERIAL_UPDATE",
            entity_type="Serial", entity_id=serial_id, new_value=serial.title,
            comment="Updated serial title/notes/instructions",
        ))
        db.commit()
    target = redirect if redirect.startswith("/") else "/serials"
    return RedirectResponse(f"{target}?toast=Serial+updated", status_code=302)


@router.post("/{serial_id}/packages/add")
async def serial_add_package(
    serial_id: int,
    package_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    package = db.query(SignalPackage).filter(SignalPackage.id == package_id, SignalPackage.is_testing == testing).first()
    if serial and package and serial.closed_at is None:
        existing = db.query(SerialPackage).filter(
            SerialPackage.serial_id == serial_id,
            SerialPackage.package_id == package_id,
        ).first()
        if not existing:
            db.add(SerialPackage(serial_id=serial_id, package_id=package_id))
            db.commit()
    return RedirectResponse(f"/serials?toast=Package+added+to+serial", status_code=302)



@router.post("/{serial_id}/cda/assign")
async def serial_assign_cda(
    serial_id: int,
    cda_table_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    cda_table = db.query(CDATable).filter(CDATable.id == cda_table_id, CDATable.is_testing == testing).first()
    if serial and cda_table:
        existing = db.query(SerialCDATable).filter(
            SerialCDATable.serial_id == serial_id,
            SerialCDATable.cda_table_id == cda_table_id,
        ).first()
        if not existing:
            db.add(SerialCDATable(serial_id=serial_id, cda_table_id=cda_table_id))
            db.add(AuditLog(
                user_id=current_user.id, action_type="SERIAL_CDA_ASSIGN",
                entity_type="Serial", entity_id=serial_id,
                new_value=f"Assigned CDA table: {cda_table.name}",
            ))
            db.commit()
    return RedirectResponse(f"/serials?toast=CDA+table+assigned", status_code=302)


@router.post("/{serial_id}/cda/{cda_table_id}/remove")
async def serial_remove_cda(
    serial_id: int,
    cda_table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    cda_table = db.query(CDATable).filter(CDATable.id == cda_table_id, CDATable.is_testing == testing).first()
    link = db.query(SerialCDATable).filter(
        SerialCDATable.serial_id == serial_id,
        SerialCDATable.cda_table_id == cda_table_id,
    ).first() if serial and cda_table else None
    if link:
        db.add(AuditLog(
            user_id=current_user.id, action_type="SERIAL_CDA_REMOVE",
            entity_type="Serial", entity_id=serial_id,
            new_value=f"Removed CDA table id={cda_table_id}",
        ))
        db.delete(link)
        db.commit()
    return RedirectResponse(f"/serials?toast=CDA+table+removed", status_code=302)


@router.get("/{serial_id}/rf-config")
async def serial_rf_config(
    serial_id: int,
    signal_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the best matching package RF config assigned to this serial (JSON).

    If signal_name is supplied, its package is preferred. Used by the log form to
    auto-populate TxLO/RxLO/TTF/band/antenna. Returns nulls when no package has RF config.
    """
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    if not serial:
        return JSONResponse({"tx_lo": None, "rx_lo": None, "ttf": None,
                             "ttf_direction": "+", "freq_unit": "MHz",
                             "band": None, "antenna": None})
    config = serial_package_rf_config(db, serial_id, signal_name)
    if not config:
        return JSONResponse({"tx_lo": None, "rx_lo": None, "ttf": None,
                             "ttf_direction": "+", "freq_unit": "MHz",
                             "band": None, "antenna": None})
    return JSONResponse(config)


@router.post("/{serial_id}/copy-to-other")
async def serial_copy_to_other(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy a serial (as Pending) into the other workspace (Live ↔ Sandbox).

    Packages are also carried across: for each package assigned to the serial, if a
    package with the same name already exists in the target workspace it is reused;
    otherwise it is copied. Signal logs and CDA assignments are not copied — the serial
    arrives in the target workspace as a fresh Pending serial ready to start.
    """
    from urllib.parse import quote_plus
    from app.routers.packages import _copy_package_to_workspace

    testing = is_testing_state(db)
    orig = db.query(Serial).filter(
        Serial.id == serial_id, Serial.is_testing == testing,
    ).first()
    if not orig:
        return RedirectResponse("/serials", status_code=302)

    target = not testing
    dest = "Sandbox" if target else "Live"

    # Resolve or copy packages into the target workspace.
    target_pkg_ids: list[int] = []
    for link in orig.package_links:
        pkg = link.package
        if pkg is None:
            continue
        existing = db.query(SignalPackage).filter(
            SignalPackage.name == pkg.name,
            SignalPackage.is_testing == target,
        ).first()
        if existing:
            target_pkg_ids.append(existing.id)
        else:
            copy_pkg = _copy_package_to_workspace(db, pkg, target, current_user.id)
            db.flush()
            target_pkg_ids.append(copy_pkg.id)

    # Create the serial in the target workspace (Pending, not started).
    new_serial = Serial(
        title=orig.title,
        notes=orig.notes,
        instructions=orig.instructions,
        opened_by_id=current_user.id,
        is_testing=target,
    )
    new_serial._preserve_testing_scope = True
    db.add(new_serial)
    db.flush()

    for pkg_id in target_pkg_ids:
        db.add(SerialPackage(serial_id=new_serial.id, package_id=pkg_id))

    db.add(AuditLog(
        user_id=current_user.id, action_type="SERIAL_COPY_WORKSPACE",
        entity_type="Serial", entity_id=new_serial.id,
        new_value=f"Copied '{orig.title}' from {'Sandbox' if testing else 'Live'} to {dest}",
    ))
    db.commit()
    msg = f'Serial "{orig.title}" copied to {dest} as Pending'
    return RedirectResponse(f"/serials?toast={quote_plus(msg)}", status_code=302)
