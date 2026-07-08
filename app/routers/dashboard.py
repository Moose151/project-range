import json
import re
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from urllib.parse import quote_plus
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials, is_testing_state
from app.models import User, Signal, SignalLog, ModulationType, FecType, SignalSource, AntennaType, AuditLog, RangeStateLog, Serial, DocPage, SerialCDATable, CDAWindow, RFDevice, CallType, SignalPackageEntry
from app.cbm_sync import sync_active_cbms
from app.rf_config import serial_package_rf_config, recalculate_from_values
from app.signal_warnings import warning_flags_for
from app.settings import get_local_timezone
from app.routers.docs import _render_markdown


class _SignalUpdate(BaseModel):
    signal_name: str
    signal_status: str
    modulation: Optional[str] = None
    fec: Optional[str] = None
    symbol_rate: Optional[str] = None
    source: Optional[str] = None
    antenna: Optional[str] = None
    power: Optional[float] = None
    power_unit: str = "dBm"
    eb_no: Optional[float] = None
    tx_if: Optional[float] = None
    tx_rf: Optional[float] = None
    rx_rf: Optional[float] = None
    rx_if: Optional[float] = None
    notes: Optional[str] = None
    changed_fields: list[str] = Field(default_factory=list)


class _BulkUpdateBody(BaseModel):
    serial_id: Optional[int] = None
    updates: list[_SignalUpdate]


class _EngagedUpdateBody(BaseModel):
    signal_name: str
    engaged: bool
    serial_id: Optional[int] = None

router = APIRouter()
from app.templating import templates


def _latest_signal_status(db: Session, serial_id: int | None = None) -> list:
    """Return the most recent log entry per unique signal name (non-deleted).

    If serial_id is given, restrict to logs from that serial.
    Falls back to all logs when no active serials exist (legacy/no-serial mode).
    """
    q = db.query(SignalLog).filter(
        SignalLog.is_deleted == False,
        SignalLog.signal_name != "[NOTE]",
        SignalLog.is_testing == is_testing_state(db),
    )
    if serial_id is not None:
        q = q.filter(SignalLog.serial_id == serial_id)
    logs = q.order_by(SignalLog.signal_name, SignalLog.timestamp.desc()).all()
    seen: set[str] = set()
    result = []
    for log in logs:
        if log.signal_name not in seen:
            seen.add(log.signal_name)
            result.append(log)
    return result


def _buzzer_active(signals: list, range_state: str) -> bool:
    """True when range is Live or Closed Loop and at least one signal is Up."""
    if range_state == "Standby/Off":
        return False
    return any(s.signal_status == "Up" for s in signals)


def _get_mod_types(db: Session) -> list[str]:
    return [
        m.name for m in db.query(ModulationType)
        .filter(ModulationType.is_active == True)
        .order_by(ModulationType.display_order, ModulationType.name)
        .all()
    ]


def _get_fec_types(db: Session) -> list[str]:
    return [
        f.name for f in db.query(FecType)
        .filter(FecType.is_active == True)
        .order_by(FecType.display_order, FecType.name)
        .all()
    ]


def _get_sources(db: Session) -> list[str]:
    names = [
        s.name for s in db.query(SignalSource)
        .filter(SignalSource.is_active == True)
        .order_by(SignalSource.display_order, SignalSource.name)
        .all()
    ]
    modems = (
        db.query(RFDevice)
        .filter(RFDevice.is_active == True, RFDevice.device_type == "modem", RFDevice.is_testing == is_testing_state(db))
        .order_by(RFDevice.name)
        .all()
    )
    for modem in modems:
        if modem.name not in names:
            names.append(modem.name)
    return names


def _source_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _cbm_source_device(db: Session, source: str, testing: bool) -> RFDevice | None:
    name = source.strip()
    if not name:
        return None
    key = _source_key(name)
    devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.cbm_sync_enabled == True,
            RFDevice.is_testing == testing,
        )
        .order_by(RFDevice.name)
        .all()
    )
    for device in devices:
        if device.name == name or _source_key(device.name) == key:
            return device
    return None


def _update_serial_package_signal_source(
    db: Session,
    serial: Serial | None,
    signal_name: str,
    source: str,
    current_user: User,
    testing: bool,
) -> tuple[str | None, int]:
    """Persist dashboard Source edits back to package signals for CBM mapping."""
    if not serial:
        return source.strip() or None, 0

    source_name = source.strip()
    cbm_device = _cbm_source_device(db, source_name, testing)
    cbm_device_id = cbm_device.id if cbm_device else None
    if cbm_device:
        source_name = cbm_device.name

    if cbm_device_id:
        _clear_modem_from_other_entries(db, cbm_device_id)

    updated = 0
    for link in serial.package_links:
        for entry in link.package.signals:
            if entry.signal_name != signal_name:
                continue
            previous = entry.source or ""
            previous_device_id = entry.cbm_device_id
            entry.source = source_name or None
            entry.cbm_device_id = cbm_device_id
            link.package.updated_at = datetime.utcnow()
            updated += 1
            if previous != (source_name or "") or previous_device_id != cbm_device_id:
                db.add(AuditLog(
                    user_id=current_user.id,
                    action_type="PACKAGE_SIGNAL_SOURCE_UPDATE",
                    entity_type="SignalPackageEntry",
                    entity_id=entry.id,
                    previous_value=previous,
                    new_value=source_name or "",
                    comment=(
                        f"Dashboard source update for {signal_name} in serial {serial.display_title}. "
                        f"CBM mapping {'set to device ' + str(cbm_device_id) if cbm_device_id else 'cleared or non-CBM source'}."
                    ),
                ))
    return source_name or None, updated


def _get_antennas(db: Session) -> list[str]:
    return [
        a.name for a in db.query(AntennaType)
        .filter(AntennaType.is_active == True)
        .order_by(AntennaType.display_order, AntennaType.name)
        .all()
    ]


def _get_call_types(db: Session) -> list[str]:
    return [
        ct.name for ct in db.query(CallType)
        .filter(CallType.is_active == True)
        .order_by(CallType.display_order, CallType.name)
        .all()
    ]


def _clear_modem_from_other_entries(db: Session, cbm_device_id: int, except_entry_id: int | None = None) -> None:
    """Enforce one-to-one modem assignment: clear this modem from any other package signal entries."""
    if not cbm_device_id:
        return
    q = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.cbm_device_id == cbm_device_id
    )
    if except_entry_id is not None:
        q = q.filter(SignalPackageEntry.id != except_entry_id)
    for entry in q.all():
        entry.cbm_device_id = None
        entry.source = None


def _cbm_status_by_source(db: Session, testing: bool) -> dict[str, dict | None]:
    """Return {device_name: sync_states_dict} for all CBM/EBEM-enabled modems.

    Callers use this to show the EBEM LED column on the dashboard: signals whose
    source matches a device name in this dict are EBEM signals; others show N/A.
    sync_states_dict has keys: ebem_sync, carrier_lock, bit_sync (True/False/None).
    """
    devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.cbm_sync_enabled == True,
            RFDevice.is_testing == testing,
        )
        .all()
    )
    result: dict[str, dict | None] = {}
    for device in devices:
        if device.cbm_sync_state_json:
            try:
                result[device.name] = json.loads(device.cbm_sync_state_json)
            except (ValueError, TypeError):
                result[device.name] = None
        else:
            result[device.name] = None
    return result


def _chameleon_base_name(signal_name: str) -> str:
    """Strip trailing -N suffix to find the family base name."""
    m = re.match(r'^(.*)-(\d+)$', signal_name)
    return m.group(1) if m else signal_name


def _next_chameleon_name(db: Session, signal_name: str) -> str:
    """Return the next available chameleon name in the family (base, base-1, base-2, ...)."""
    base = _chameleon_base_name(signal_name)
    pattern = re.compile(r'^' + re.escape(base) + r'(?:-(\d+))?$')
    existing = db.query(Signal).filter(Signal.name.like(f"{base}%")).all()
    max_n = 0
    for sig in existing:
        m = pattern.match(sig.name)
        if m:
            n = int(m.group(1)) if m.group(1) else 0
            if n > max_n:
                max_n = n
    return f"{base}-{max_n + 1}"


def _get_exclusivity_map(db: Session) -> dict[str, list[str]]:
    """Return {signal_name: [sibling_names]} for signals in exclusivity groups."""
    sigs = db.query(Signal).filter(
        Signal.exclusivity_group != None, Signal.is_active == True,
    ).all()
    # Group by exclusivity_group string
    groups: dict[str, list[str]] = {}
    for s in sigs:
        groups.setdefault(s.exclusivity_group, []).append(s.name)
    # For each signal, its siblings are all others in the same group
    result: dict[str, list[str]] = {}
    for group_members in groups.values():
        for name in group_members:
            result[name] = [m for m in group_members if m != name]
    return result


def _dashboard_ctx(db: Session) -> dict:
    """Shared context dict for dashboard + fragment endpoints."""
    range_state = get_current_range_state(db)
    last_state_change = db.query(RangeStateLog).order_by(RangeStateLog.id.desc()).first()
    mod_types = _get_mod_types(db)
    fec_types = _get_fec_types(db)
    signal_sources = _get_sources(db)
    antenna_types = _get_antennas(db)
    exclusivity_map = _get_exclusivity_map(db)

    call_types = _get_call_types(db)
    active_serials = get_active_serials(db)

    if active_serials:
        serial_data = []
        all_buzzer = False
        for serial in active_serials:
            signals = _latest_signal_status(db, serial_id=serial.id)
            buzzer = _buzzer_active(signals, range_state)
            if buzzer:
                all_buzzer = True
            serial_data.append({
                "serial": serial,
                "signals": signals,
                "buzzer_active": buzzer,
                "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial.id, signals),
                "has_cbm_mapping": any(
                    entry.cbm_device_id
                    for link in serial.package_links
                    for entry in link.package.signals
                ),
            })
    else:
        # No serials running — show all logs (legacy / no-serial mode)
        signals = _latest_signal_status(db)
        all_buzzer = _buzzer_active(signals, range_state)
        serial_data = [{"serial": None, "signals": signals, "buzzer_active": all_buzzer, "has_cbm_mapping": False}]

    # CDA data: map serial_id → list of {table_name, windows: [{start, end, label, max_power_dbm}]}
    cda_by_serial: dict[int, list] = {}
    for serial in active_serials:
        links = db.query(SerialCDATable).filter(SerialCDATable.serial_id == serial.id).all()
        tables = []
        for link in links:
            windows = db.query(CDAWindow).filter(
                CDAWindow.cda_table_id == link.cda_table_id
            ).order_by(CDAWindow.start_zulu).all()
            tables.append({
                "table_id": link.cda_table_id,
                "table_name": link.cda_table.name,
                "windows": [
                    {
                        "id": w.id,
                        "start": w.start_zulu,
                        "end": w.end_zulu,
                        "label": w.label or "",
                        "max_power_dbm": w.max_power_dbm,
                        "type": "reduced_power" if w.max_power_dbm is not None else "no_fire",
                        "type_label": w.window_type_label,
                    }
                    for w in windows
                ],
            })
        if tables:
            cda_by_serial[serial.id] = tables

    global_signals = [s for sd in serial_data for s in sd["signals"]]
    testing = is_testing_state(db)
    return {
        "serial_data": serial_data,
        "active_serials": active_serials,
        "cbm_status_by_source": _cbm_status_by_source(db, testing),
        # Flat signals list kept for the OOB buzzer swap (any signal across all serials)
        "signals": global_signals,
        # Global aggregates for the summary cards (kept fresh on every poll via OOB)
        "up_count": sum(1 for s in global_signals if s.signal_status == "Up"),
        "faulted_count": sum(1 for s in global_signals if s.signal_status == "Faulted"),
        "any_buzzer": all_buzzer,
        "range_state": range_state,
        "buzzer_active": all_buzzer,
        "mod_types": mod_types,
        "fec_types": fec_types,
        "signal_sources": signal_sources,
        "antenna_types": antenna_types,
        "last_state_change": last_state_change,
        "exclusivity_map": exclusivity_map,
        "local_timezone": get_local_timezone(db),
        "cda_by_serial": cda_by_serial,
        "call_types": call_types,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    toast: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ctx = _dashboard_ctx(db)
    ctx.update({
        "user": current_user,
        "toast": toast,
        "page": "dashboard",
        "doc_pages": db.query(DocPage).filter(DocPage.is_published == True).order_by(DocPage.title).all(),
    })
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.post("/dashboard/cbm-sync")
async def dashboard_cbm_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = sync_active_cbms(db, current_user.id)
    message = f"CBM update complete: {result.updated} updated, {result.skipped} skipped"
    if result.errors:
        first_issue = result.errors[0]
        message += f", {len(result.errors)} issue(s): {first_issue[:120]}"
    return RedirectResponse(f"/?toast={quote_plus(message)}", status_code=302)


@router.post("/dashboard/signal-call")
async def dashboard_signal_call(
    signal_name: str = Form(...),
    serial_id: Optional[int] = Form(None),
    call_type: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an effect log entry for a signal, capturing modem state at time of the effect."""
    testing = is_testing_state(db)
    range_state = get_current_range_state(db)

    latest_q = db.query(SignalLog).filter(
        SignalLog.signal_name == signal_name,
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
    latest = latest_q.order_by(SignalLog.timestamp.desc()).first()

    # Build modem state string from EBEM status if the signal has a CBM source
    modem_parts = []
    if latest and latest.eb_no is not None:
        modem_parts.append(f"Eb/No: {latest.eb_no} dB")
    else:
        modem_parts.append("Eb/No: —")

    cbm_status = _cbm_status_by_source(db, testing)
    source = latest.source if latest else None
    if source and source in cbm_status:
        ebem = cbm_status[source]
        if ebem:
            modem_parts.append(f"Channel Sync: {'OK' if ebem.get('ebem_sync') == True else ('Fault' if ebem.get('ebem_sync') == False else '—')}")
            modem_parts.append(f"Carrier Lock: {'OK' if ebem.get('carrier_lock') == True else ('Fault' if ebem.get('carrier_lock') == False else '—')}")
            modem_parts.append(f"Mod Lock: {'OK' if ebem.get('bit_sync') == True else ('Fault' if ebem.get('bit_sync') == False else '—')}")
        else:
            modem_parts += ["Channel Sync: —", "Carrier Lock: —", "Mod Lock: —"]
    else:
        modem_parts += ["Channel Sync: —", "Carrier Lock: —", "Mod Lock: —"]

    notes_text = f"Effect: {call_type} | " + " | ".join(modem_parts)

    new_entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name=signal_name,
        signal_status=latest.signal_status if latest else "Down",
        tx_if=latest.tx_if if latest else None,
        tx_rf=latest.tx_rf if latest else None,
        rx_rf=latest.rx_rf if latest else None,
        rx_if=latest.rx_if if latest else None,
        freq_unit=latest.freq_unit if latest else "MHz",
        band=latest.band if latest else None,
        modulation=latest.modulation if latest else None,
        symbol_rate=latest.symbol_rate if latest else None,
        fec=latest.fec if latest else None,
        power=latest.power if latest else None,
        power_unit=latest.power_unit if latest else "dBm",
        eb_no=latest.eb_no if latest else None,
        engaged=latest.engaged if latest else False,
        source=latest.source if latest else None,
        antenna=latest.antenna if latest else None,
        notes=notes_text,
        entry_type="Effect",
        updated_by_id=current_user.id,
        serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
        is_testing=testing,
    )
    db.add(new_entry)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="SIGNAL_EFFECT_LOG",
        entity_type="SignalLog",
        new_value=f"{signal_name}: {call_type}",
        comment=notes_text,
    ))
    db.commit()
    return RedirectResponse(f"/?toast={quote_plus(f'Effect logged: {call_type} for {signal_name}')}", status_code=302)


@router.post("/dashboard/chameleon")
async def dashboard_chameleon(
    signal_name: str = Form(...),
    serial_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a chameleon signal: a duplicate with an incremented name suffix, no modem source."""
    testing = is_testing_state(db)
    range_state = get_current_range_state(db)

    new_name = _next_chameleon_name(db, signal_name)

    # Ensure the new name doesn't already exist as a Signal registry entry
    if not db.query(Signal).filter(Signal.name == new_name).first():
        original_sig = db.query(Signal).filter(Signal.name == _chameleon_base_name(signal_name)).first()
        db.add(Signal(
            name=new_name,
            description=f"Chameleon of {signal_name}",
            default_band=original_sig.default_band if original_sig else None,
            default_modulation=original_sig.default_modulation if original_sig else None,
            default_symbol_rate=original_sig.default_symbol_rate if original_sig else None,
            default_fec=original_sig.default_fec if original_sig else None,
            max_power_dbm=original_sig.max_power_dbm if original_sig else None,
        ))

    # Copy latest log entry for the original signal — no source/modem
    latest_q = db.query(SignalLog).filter(
        SignalLog.signal_name == signal_name,
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
    latest = latest_q.order_by(SignalLog.timestamp.desc()).first()

    initial_entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name=new_name,
        signal_status=latest.signal_status if latest else "Down",
        tx_if=latest.tx_if if latest else None,
        tx_rf=latest.tx_rf if latest else None,
        rx_rf=latest.rx_rf if latest else None,
        rx_if=latest.rx_if if latest else None,
        freq_unit=latest.freq_unit if latest else "MHz",
        band=latest.band if latest else None,
        modulation=latest.modulation if latest else None,
        symbol_rate=latest.symbol_rate if latest else None,
        fec=latest.fec if latest else None,
        power=latest.power if latest else None,
        power_unit=latest.power_unit if latest else "dBm",
        eb_no=None,
        engaged=False,
        source=None,
        antenna=latest.antenna if latest else None,
        notes=f"Chameleon of {signal_name}",
        entry_type="Chameleon",
        updated_by_id=current_user.id,
        serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
        is_testing=testing,
    )
    db.add(initial_entry)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="SIGNAL_CHAMELEON",
        entity_type="SignalLog",
        new_value=new_name,
        comment=f"Chameleon created from {signal_name} → {new_name}",
    ))
    db.commit()
    return RedirectResponse(f"/?toast={quote_plus(f'Chameleon created: {new_name}')}", status_code=302)


@router.get("/dashboard/fragment", response_class=HTMLResponse)
async def dashboard_fragment_legacy(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX polling — fallback when no serial is active (all signals)."""
    ctx = _dashboard_ctx(db)
    signals = _latest_signal_status(db)
    range_state = ctx["range_state"]
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, range_state),
        "serial_id": None,
    })


def _pkg_rf_for_serial(db: Session, serial_id: int) -> dict | None:
    """Return the first configured package-level RF plan for a serial."""
    return serial_package_rf_config(db, serial_id)


def _pkg_rf_by_signal(db: Session, serial_id: int, signals: list[SignalLog]) -> dict:
    """Map each displayed signal to the RF plan of its assigned package."""
    return {
        log.signal_name: serial_package_rf_config(db, serial_id, log.signal_name)
        for log in signals
    }


def _blank_to_none(value):
    return None if value == "" else value


def _dashboard_values_from_update(
    db: Session,
    serial_id: int | None,
    latest: SignalLog | None,
    upd: _SignalUpdate,
) -> dict:
    values = {
        "signal_status": upd.signal_status,
        "tx_if": upd.tx_if if "tx_if" in upd.changed_fields else (latest.tx_if if latest else None),
        "tx_rf": upd.tx_rf if "tx_rf" in upd.changed_fields else (latest.tx_rf if latest else None),
        "rx_rf": upd.rx_rf if "rx_rf" in upd.changed_fields else (latest.rx_rf if latest else None),
        "rx_if": upd.rx_if if "rx_if" in upd.changed_fields else (latest.rx_if if latest else None),
        "freq_unit": latest.freq_unit if latest else "MHz",
        "band": latest.band if latest else None,
        "modulation": _blank_to_none(upd.modulation) if "modulation" in upd.changed_fields else (latest.modulation if latest else None),
        "symbol_rate": _blank_to_none(upd.symbol_rate) if "symbol_rate" in upd.changed_fields else (latest.symbol_rate if latest else None),
        "fec": _blank_to_none(upd.fec) if "fec" in upd.changed_fields else (latest.fec if latest else None),
        "power": upd.power if "power" in upd.changed_fields else (latest.power if latest else None),
        "power_unit": upd.power_unit or (latest.power_unit if latest else "dBm"),
        "eb_no": upd.eb_no if "eb_no" in upd.changed_fields else (latest.eb_no if latest else None),
        "source": _blank_to_none(upd.source) if "source" in upd.changed_fields else (latest.source if latest else None),
        "antenna": _blank_to_none(upd.antenna) if "antenna" in upd.changed_fields else (latest.antenna if latest else None),
    }
    if serial_id is not None:
        rf = serial_package_rf_config(db, serial_id, upd.signal_name)
        freq_changed = [f for f in ("tx_if", "tx_rf", "rx_rf", "rx_if") if f in upd.changed_fields]
        values = recalculate_from_values(values, rf, preferred=freq_changed or None)
        if rf:
            values["band"] = values.get("band") or rf.get("band")
            values["antenna"] = values.get("antenna") or rf.get("antenna")
    return values


@router.get("/dashboard/fragment/{serial_id}", response_class=HTMLResponse)
async def dashboard_fragment(
    serial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX polling endpoint — returns the serial's table + OOB summary/buzzer."""
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    if not serial:
        return HTMLResponse("")
    ctx = _dashboard_ctx(db)
    signals = _latest_signal_status(db, serial_id=serial_id)
    range_state = ctx["range_state"]
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, range_state),
        "serial_id": serial_id,
        "closed_loop": bool(serial and serial.is_closed_loop),
        "pkg_rf": _pkg_rf_for_serial(db, serial_id),
        "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial_id, signals),
    })


@router.get("/dashboard/doc-widget/{slug}", response_class=HTMLResponse)
async def dashboard_doc_widget(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = db.query(DocPage).filter(DocPage.slug == slug, DocPage.is_published == True).first()
    if not doc:
        return HTMLResponse('<div class="text-muted small p-2">Document not found.</div>')
    html = _render_markdown(doc.content)
    return HTMLResponse(
        f'<div class="doc-widget-content doc-content">{html}</div>'
        f'<div class="pt-2"><a href="/docs/{doc.slug}" class="btn btn-sm btn-outline-secondary">'
        f'<i class="bi bi-box-arrow-up-right me-1"></i>Open full doc</a></div>'
    )


@router.post("/dashboard/quick-update", response_class=HTMLResponse)
async def dashboard_quick_update(
    request: Request,
    signal_name: str = Form(...),
    signal_status: str = Form(...),
    modulation: str = Form(""),
    fec: str = Form(""),
    symbol_rate: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    source: str = Form(""),
    antenna: str = Form(""),
    notes: str = Form(""),
    serial_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    serial = None
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None

    # Copy freq/band data from the latest existing entry for this signal
    latest_query = db.query(SignalLog).filter(
        SignalLog.signal_name == signal_name,
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        latest_query = latest_query.filter(SignalLog.serial_id == serial_id)
    latest = latest_query.order_by(SignalLog.timestamp.desc()).first()

    # Exclusivity group enforcement: if setting to Up, auto-down others in the same group
    if signal_status == "Up":
        sig_reg = db.query(Signal).filter(Signal.name == signal_name).first()
        if sig_reg and sig_reg.exclusivity_group:
            siblings = (
                db.query(Signal)
                .filter(
                    Signal.exclusivity_group == sig_reg.exclusivity_group,
                    Signal.name != signal_name,
                )
                .all()
            )
            for sib in siblings:
                sib_query = db.query(SignalLog).filter(
                    SignalLog.signal_name == sib.name,
                    SignalLog.is_deleted == False,
                    SignalLog.is_testing == testing,
                )
                if serial_id is not None:
                    sib_query = sib_query.filter(SignalLog.serial_id == serial_id)
                sib_latest = sib_query.order_by(SignalLog.timestamp.desc()).first()
                if sib_latest and sib_latest.signal_status == "Up":
                    db.add(SignalLog(
                        operator_id=current_user.id,
                        range_state=range_state,
                        signal_name=sib.name,
                        signal_status="Down",
                        tx_if=sib_latest.tx_if,
                        tx_rf=sib_latest.tx_rf,
                        rx_rf=sib_latest.rx_rf,
                        rx_if=sib_latest.rx_if,
                        freq_unit=sib_latest.freq_unit,
                        band=sib_latest.band,
                        modulation=sib_latest.modulation,
                        symbol_rate=sib_latest.symbol_rate,
                        fec=sib_latest.fec,
                        power=sib_latest.power,
                        power_unit=sib_latest.power_unit,
                        eb_no=sib_latest.eb_no,
                        engaged=sib_latest.engaged,
                        source=sib_latest.source,
                        antenna=sib_latest.antenna,
                        notes=f"Auto-downed: {signal_name} came Up (group: {sig_reg.exclusivity_group})",
                        entry_type="Automatic",
                        updated_by_id=current_user.id,
                        serial_id=serial_id,
                    ))

    effective_source, package_sources_updated = _update_serial_package_signal_source(
        db, serial, signal_name, source, current_user, testing,
    )

    new_entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name=signal_name,
        signal_status=signal_status,
        tx_if=latest.tx_if if latest else None,
        tx_rf=latest.tx_rf if latest else None,
        rx_rf=latest.rx_rf if latest else None,
        rx_if=latest.rx_if if latest else None,
        freq_unit=latest.freq_unit if latest else "MHz",
        band=latest.band if latest else None,
        modulation=modulation or (latest.modulation if latest else None),
        symbol_rate=symbol_rate or (latest.symbol_rate if latest else None),
        fec=fec or (latest.fec if latest else None),
        power=power if power is not None else (latest.power if latest else None),
        power_unit=power_unit,
        eb_no=eb_no if eb_no is not None else (latest.eb_no if latest else None),
        engaged=latest.engaged if latest else False,
        source=effective_source if source.strip() or package_sources_updated else (latest.source if latest else None),
        antenna=antenna or (latest.antenna if latest else None),
        notes=notes.strip() or None,
        entry_type="Dashboard",
        updated_by_id=current_user.id,
        serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
        warning_flags=warning_flags_for(
            db, signal_name, power if power is not None else (latest.power if latest else None),
            power_unit,
            tx_rf=latest.tx_rf if latest else None,
            rx_rf=latest.rx_rf if latest else None,
            freq_unit=latest.freq_unit if latest else "MHz",
            band=latest.band if latest else None,
        ),
    )
    db.add(new_entry)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="DASHBOARD_UPDATE",
        entity_type="SignalLog",
        entity_id=new_entry.id,
        new_value=f"{signal_name}: {signal_status}",
        comment=(
            f"Dashboard Source applied to {package_sources_updated} package signal mapping(s): {effective_source or 'cleared'}"
            if package_sources_updated else None
        ),
    ))
    db.commit()

    ctx = _dashboard_ctx(db)
    effective_serial_id = serial_id if serial_id is not None else None
    signals = _latest_signal_status(db, serial_id=effective_serial_id)
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, ctx["range_state"]),  # this widget's badge
        "serial_id": effective_serial_id,
        "pkg_rf": _pkg_rf_for_serial(db, effective_serial_id) if effective_serial_id else None,
        "pkg_rf_by_signal": (
            _pkg_rf_by_signal(db, effective_serial_id, signals) if effective_serial_id else {}
        ),
    })


@router.post("/dashboard/bulk-update", response_class=HTMLResponse)
async def dashboard_bulk_update(
    request: Request,
    body: _BulkUpdateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply status/power changes for multiple signals in one DB transaction."""
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    serial_id = body.serial_id
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None

    for upd in body.updates:
        latest_q = db.query(SignalLog).filter(
            SignalLog.signal_name == upd.signal_name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        )
        if serial_id is not None:
            latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
        latest = latest_q.order_by(SignalLog.timestamp.desc()).first()

        # Exclusivity group enforcement
        if upd.signal_status == "Up":
            sig_reg = db.query(Signal).filter(Signal.name == upd.signal_name).first()
            if sig_reg and sig_reg.exclusivity_group:
                siblings = db.query(Signal).filter(
                    Signal.exclusivity_group == sig_reg.exclusivity_group,
                    Signal.name != upd.signal_name,
                ).all()
                for sib in siblings:
                    sib_q = db.query(SignalLog).filter(
                        SignalLog.signal_name == sib.name,
                        SignalLog.is_deleted == False,
                        SignalLog.is_testing == testing,
                    )
                    if serial_id is not None:
                        sib_q = sib_q.filter(SignalLog.serial_id == serial_id)
                    sib_latest = sib_q.order_by(SignalLog.timestamp.desc()).first()
                    if sib_latest and sib_latest.signal_status == "Up":
                        db.add(SignalLog(
                            operator_id=current_user.id, range_state=range_state,
                            signal_name=sib.name, signal_status="Down",
                            tx_if=sib_latest.tx_if, tx_rf=sib_latest.tx_rf,
                            rx_rf=sib_latest.rx_rf, rx_if=sib_latest.rx_if,
                            freq_unit=sib_latest.freq_unit, band=sib_latest.band,
                            modulation=sib_latest.modulation, symbol_rate=sib_latest.symbol_rate,
                            fec=sib_latest.fec, power=sib_latest.power,
                            power_unit=sib_latest.power_unit, eb_no=sib_latest.eb_no,
                            engaged=sib_latest.engaged,
                            source=sib_latest.source, antenna=sib_latest.antenna,
                            notes=f"Auto-downed: {upd.signal_name} came Up (group: {sig_reg.exclusivity_group})",
                            entry_type="Automatic", updated_by_id=current_user.id, serial_id=serial_id,
                        ))

        effective_source = None
        if "source" in upd.changed_fields:
            effective_source, _ = _update_serial_package_signal_source(
                db, serial, upd.signal_name, upd.source or "", current_user, testing,
            )

        values = _dashboard_values_from_update(db, serial_id, latest, upd)
        if "source" in upd.changed_fields:
            values["source"] = effective_source

        new_entry = SignalLog(
            operator_id=current_user.id, range_state=range_state,
            signal_name=upd.signal_name, signal_status=values["signal_status"],
            tx_if=values["tx_if"],
            tx_rf=values["tx_rf"],
            rx_rf=values["rx_rf"],
            rx_if=values["rx_if"],
            freq_unit=values["freq_unit"],
            band=values["band"],
            modulation=values["modulation"],
            symbol_rate=values["symbol_rate"],
            fec=values["fec"],
            power=values["power"],
            power_unit=values["power_unit"],
            eb_no=values["eb_no"],
            engaged=latest.engaged if latest else False,
            source=values["source"],
            antenna=values["antenna"],
            notes=(upd.notes or "").strip() or None,
            entry_type="Dashboard", updated_by_id=current_user.id,
            serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
            warning_flags=warning_flags_for(
                db, upd.signal_name,
                values["power"],
                values["power_unit"],
                tx_rf=values["tx_rf"],
                rx_rf=values["rx_rf"],
                freq_unit=values["freq_unit"],
                band=values["band"],
            ),
        )
        db.add(new_entry)

    db.flush()
    for upd in body.updates:
        db.add(AuditLog(
            user_id=current_user.id, action_type="DASHBOARD_UPDATE",
            entity_type="SignalLog",
            new_value=f"{upd.signal_name}: {upd.signal_status}",
            comment=", ".join(upd.changed_fields) if upd.changed_fields else None,
        ))
    db.commit()

    ctx = _dashboard_ctx(db)
    signals = _latest_signal_status(db, serial_id=serial_id)
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, ctx["range_state"]),
        "serial_id": serial_id,
        "pkg_rf": _pkg_rf_for_serial(db, serial_id) if serial_id else None,
        "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial_id, signals) if serial_id else {},
    })


@router.post("/dashboard/engaged-toggle")
async def dashboard_engaged_toggle(
    body: _EngagedUpdateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Immediately set the visual mission-system engagement flag for a signal."""
    testing = is_testing_state(db)
    serial_id = body.serial_id
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None

    latest_q = db.query(SignalLog).filter(
        SignalLog.signal_name == body.signal_name,
        SignalLog.signal_name != "[NOTE]",
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
    latest = latest_q.order_by(SignalLog.timestamp.desc()).first()
    if not latest:
        return JSONResponse({"error": "Signal not found"}, status_code=404)

    previous = bool(latest.engaged)
    latest.engaged = body.engaged
    latest.updated_by_id = current_user.id
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="SIGNAL_ENGAGED_TOGGLE",
        entity_type="SignalLog",
        entity_id=latest.id,
        previous_value="On" if previous else "Off",
        new_value=f"{latest.signal_name}: {'On' if latest.engaged else 'Off'}",
    ))
    db.commit()
    return {"engaged": bool(latest.engaged)}


@router.get("/status/serials", response_class=HTMLResponse)
async def serials_fragment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight HTMX endpoint — active serials badge for the nav banner."""
    active_serials = get_active_serials(db)
    return templates.TemplateResponse(request, "partials/active_serials_badge.html", {
        "active_serials": active_serials,
    })


@router.get("/status/active-count", response_class=HTMLResponse)
async def active_count_fragment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight endpoint — Up-signal count for the banner badge."""
    signals = _latest_signal_status(db)
    up = sum(1 for s in signals if s.signal_status == "Up")
    icon = '<i class="bi bi-broadcast me-1"></i>'
    return HTMLResponse(f'{icon}{up} Up')


@router.get("/status/active-count-raw", response_class=HTMLResponse)
async def active_count_raw(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Just the number — for the Active Signals dashboard widget."""
    signals = _latest_signal_status(db)
    up = sum(1 for s in signals if s.signal_status == "Up")
    return HTMLResponse(str(up))


@router.get("/status/spectrum-signals")
async def spectrum_signals_json(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return currently Up signals for the live spectrum dashboard widget."""
    open_serials = get_active_serials(db)
    result = []
    seen: set[str] = set()
    for serial in open_serials:
        latest = _latest_signal_status(db, serial_id=serial.id)
        package_signals = {
            entry.signal_name: entry
            for link in serial.package_links
            for entry in link.package.signals
        }
        for log in latest:
            if log.signal_status != "Up":
                continue
            key = f"{serial.id}:{log.signal_name}"
            if key in seen:
                continue
            seen.add(key)
            package_entry = package_signals.get(log.signal_name)
            result.append({
                "name": log.signal_name,
                "serialName": serial.title,
                "txIf": log.tx_if if log.tx_if is not None else (package_entry.tx_if if package_entry else None),
                "rxIf": log.rx_if if log.rx_if is not None else (package_entry.rx_if if package_entry else None),
                "txRf": log.tx_rf if log.tx_rf is not None else (package_entry.tx_rf if package_entry else None),
                "rxRf": log.rx_rf if log.rx_rf is not None else (package_entry.rx_rf if package_entry else None),
                "freqUnit": log.freq_unit or (package_entry.freq_unit if package_entry else "MHz"),
                "symbolRate": log.symbol_rate or (package_entry.symbol_rate if package_entry else None),
                "power": log.power,
                "modulation": log.modulation or (package_entry.modulation if package_entry else None),
                "isUp": log.signal_status == "Up",
                "dimmed": False,
            })
    return JSONResponse({"signals": result})


@router.get("/status/buzzer", response_class=HTMLResponse)
async def buzzer_fragment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight HTMX endpoint — just the buzzer badge for the nav banner."""
    range_state = get_current_range_state(db)
    signals = _latest_signal_status(db)
    active = _buzzer_active(signals, range_state)
    return templates.TemplateResponse(request, "partials/buzzer_badge.html", {
        "buzzer_active": active,
        "range_state": range_state,
    })
