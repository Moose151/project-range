from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials
from app.models import (
    User, Serial, SerialPackage, SignalPackage, SignalLog, AuditLog,
)
from app.rf_config import serial_package_rf_config

router = APIRouter(prefix="/serials")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def serials_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active = db.query(Serial).filter(
        Serial.closed_at == None, Serial.is_started == True,
    ).order_by(Serial.opened_at.asc()).all()
    pending = db.query(Serial).filter(
        Serial.closed_at == None, Serial.is_started == False,
    ).order_by(Serial.opened_at.desc()).all()
    packages = db.query(SignalPackage).order_by(SignalPackage.name).all()
    return templates.TemplateResponse(request, "serials.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active,
        "pending_serials": pending,
        "packages": packages,
        "toast": request.query_params.get("toast", ""),
        "page": "serials",
    })


@router.post("/new")
async def serial_create(
    request: Request,
    title: str = Form(...),
    notes: str = Form(""),
    package_ids: list[int] = Form(default=[]),
    action: str = Form("start"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    serial = Serial(
        title=title.strip(),
        notes=notes.strip() or None,
        opened_by_id=current_user.id,
    )
    db.add(serial)
    db.flush()

    for pid in package_ids:
        pkg = db.query(SignalPackage).filter(SignalPackage.id == pid).first()
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
    serial = db.query(Serial).filter(Serial.id == serial_id).first()
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
    serial = db.query(Serial).filter(Serial.id == serial_id).first()
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
                eb_no=entry.eb_no,
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


@router.post("/{serial_id}/end")
async def serial_end(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    serial = db.query(Serial).filter(Serial.id == serial_id).first()
    if not serial or serial.closed_at:
        return RedirectResponse("/serials", status_code=302)

    range_state = get_current_range_state(db)
    serial.closed_at = datetime.utcnow()
    serial.closed_by_id = current_user.id

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
    ).first()
    if serial:
        db.add(AuditLog(
            user_id=current_user.id, action_type="SERIAL_DELETE",
            entity_type="Serial", entity_id=serial_id, new_value=serial.title,
        ))
        db.delete(serial)
        db.commit()
    return RedirectResponse("/serials?toast=Pending+serial+discarded", status_code=302)


@router.post("/{serial_id}/packages/add")
async def serial_add_package(
    serial_id: int,
    package_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    serial = db.query(Serial).filter(Serial.id == serial_id).first()
    if serial and serial.closed_at is None:
        existing = db.query(SerialPackage).filter(
            SerialPackage.serial_id == serial_id,
            SerialPackage.package_id == package_id,
        ).first()
        if not existing:
            db.add(SerialPackage(serial_id=serial_id, package_id=package_id))
            db.commit()
    return RedirectResponse(f"/serials?toast=Package+added+to+serial", status_code=302)



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
    config = serial_package_rf_config(db, serial_id, signal_name)
    if not config:
        return JSONResponse({"tx_lo": None, "rx_lo": None, "ttf": None,
                             "ttf_direction": "+", "freq_unit": "MHz",
                             "band": None, "antenna": None})
    return JSONResponse(config)
