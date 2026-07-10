import json
import re
from typing import Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from urllib.parse import quote_plus
from app.chameleon import chameleon_base_name, next_chameleon_name
from app.config import CBM_AUTO_SYNC_SECONDS
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials, is_testing_state
from app.models import User, Signal, SignalLog, ModulationType, FecType, SignalSource, AntennaType, AuditLog, RangeStateLog, Serial, DocPage, SerialCDATable, CDAWindow, RFDevice, CallType, SignalPackageEntry, SerialPackage
from app.cbm_sync import sync_active_cbms
from app.rf_config import serial_package_rf_config, recalculate_from_values
from app.signal_warnings import warning_flags_for
from app.settings import get_local_timezone
from app.routers.docs import _render_markdown


class _SignalUpdate(BaseModel):
    signal_name: str
    signal_new_name: Optional[str] = None
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


def _active_serial_signals(db: Session) -> list:
    """Latest log per signal, restricted to serials that are currently running.

    A signal can only be considered "Up"/transmitting while it belongs to a
    started, open serial. Signals whose latest log is on a closed (historical)
    serial, or that carry no serial at all, are excluded — they must never count
    as Up for the transmitting badge or the active-signal count.
    """
    active_ids = [s.id for s in get_active_serials(db)]
    if not active_ids:
        return []
    logs = (
        db.query(SignalLog)
        .filter(
            SignalLog.is_deleted == False,
            SignalLog.signal_name != "[NOTE]",
            SignalLog.is_testing == is_testing_state(db),
            SignalLog.serial_id.in_(active_ids),
        )
        .order_by(SignalLog.signal_name, SignalLog.timestamp.desc())
        .all()
    )
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


def _rename_dashboard_signal(
    db: Session,
    serial: Serial | None,
    serial_id: int | None,
    testing: bool,
    old_name: str,
    new_name: str,
    current_user: User,
) -> int:
    """Rename a signal within the dashboard's serial/package context."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name or old_name == new_name:
        return 0

    latest_names = [log.signal_name for log in _latest_signal_status(db, serial_id=serial_id)]
    if any(name == new_name for name in latest_names if name != old_name):
        raise ValueError(f"Another dashboard signal is already named {new_name}.")

    changed = 0
    if serial:
        package_ids = [link.package_id for link in serial.package_links]
        if package_ids:
            entries = db.query(SignalPackageEntry).filter(
                SignalPackageEntry.package_id.in_(package_ids),
                SignalPackageEntry.signal_name == old_name,
            ).all()
            for entry in entries:
                entry.signal_name = new_name
                entry.package.updated_at = datetime.utcnow()
                changed += 1

    logs_q = db.query(SignalLog).filter(
        SignalLog.signal_name == old_name,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        logs_q = logs_q.filter(SignalLog.serial_id == serial_id)
    logs = logs_q.all()
    for log in logs:
        log.signal_name = new_name
        log.updated_by_id = current_user.id
        changed += 1

    if changed:
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="DASHBOARD_SIGNAL_RENAME",
            entity_type="Serial" if serial_id is not None else "SignalLog",
            entity_id=serial_id,
            previous_value=old_name,
            new_value=new_name,
            comment="Renamed from dashboard quick edit.",
        ))
    return changed


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


def _reassign_modem_source(
    db: Session,
    serial_id: int | None,
    testing: bool,
    range_state: str,
    keep_signal_name: str,
    device_name: str,
    current_user: User,
) -> list[str]:
    """Enforce dashboard modem-source uniqueness across displayed signals.

    When a modem is assigned to ``keep_signal_name``, any *other* signal that
    currently shows that same modem as its source has a fresh log written with
    source and Eb/No cleared, so the dashboard reflects the move immediately
    (not just in the underlying package entries).
    """
    if not device_name:
        return []
    # Latest log per signal in this serial that still carries this modem source.
    q = db.query(SignalLog).filter(
        SignalLog.source == device_name,
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
        SignalLog.signal_name != keep_signal_name,
    )
    if serial_id is not None:
        q = q.filter(SignalLog.serial_id == serial_id)
    seen: set[str] = set()
    displaced: list[str] = []
    for log in q.order_by(SignalLog.timestamp.desc()).all():
        if log.signal_name in seen:
            continue
        seen.add(log.signal_name)
        # Only act if this is still the signal's current (latest) source.
        latest_q = db.query(SignalLog).filter(
            SignalLog.signal_name == log.signal_name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        )
        if serial_id is not None:
            latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
        latest = latest_q.order_by(SignalLog.timestamp.desc()).first()
        if not latest or latest.source != device_name:
            continue
        db.add(SignalLog(
            operator_id=current_user.id,
            range_state=range_state,
            signal_name=log.signal_name,
            signal_status=latest.signal_status,
            tx_if=latest.tx_if, tx_rf=latest.tx_rf, rx_rf=latest.rx_rf, rx_if=latest.rx_if,
            freq_unit=latest.freq_unit, band=latest.band,
            modulation=latest.modulation, symbol_rate=latest.symbol_rate, fec=latest.fec,
            power=latest.power, power_unit=latest.power_unit,
            eb_no=None,                 # modem gone → no valid Eb/No
            ber_estimate=None,          # modem gone → no valid BER estimate
            engaged=latest.engaged,
            source=None,                # modem reassigned elsewhere
            antenna=latest.antenna,
            notes=f"Modem {device_name} reassigned to {keep_signal_name}",
            entry_type="Automatic",
            updated_by_id=current_user.id,
            serial_id=serial_id,
            is_testing=testing,
        ))
        displaced.append(log.signal_name)
    return displaced


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

    Stored state is only trusted when the device's last poll was recent and OK;
    otherwise the LEDs go grey ("no data") rather than showing a stale (possibly
    green) reading from a poll taken while a carrier was still present.
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
    # Generous window so a normal poll cadence never flickers to grey, but a
    # stopped/failed poller doesn't leave stale LEDs lit indefinitely.
    stale_after = timedelta(seconds=max(30, CBM_AUTO_SYNC_SECONDS * 6))
    now = datetime.utcnow()
    result: dict[str, dict | None] = {}
    for device in devices:
        fresh = (
            device.cbm_last_sync_status == "ok"
            and device.cbm_last_sync_at is not None
            and (now - device.cbm_last_sync_at) <= stale_after
        )
        state = None
        if fresh and device.cbm_sync_state_json:
            try:
                state = json.loads(device.cbm_sync_state_json)
            except (ValueError, TypeError):
                state = None
        result[device.name] = state
    return result


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


def _display_order_by_signal(db: Session, serial_id: int | None, signals: list) -> dict:
    """Map each displayed signal name to its package-entry display_order (if any).

    Mirrors _priority_by_signal: display_order lives on the signal package entry,
    so we resolve it by name across the packages assigned to the serial. This is
    what the dashboard widget's drag-to-reorder persists to.
    """
    if serial_id is None:
        return {}
    names = {log.signal_name.strip().casefold() for log in signals}
    if not names:
        return {}
    rows = (
        db.query(SignalPackageEntry.signal_name, SignalPackageEntry.display_order)
        .join(SerialPackage, SerialPackage.package_id == SignalPackageEntry.package_id)
        .filter(SerialPackage.serial_id == serial_id)
        .order_by(SignalPackageEntry.display_order)
        .all()
    )
    out: dict[str, int] = {}
    for name, order in rows:
        if name.strip().casefold() in names and name not in out:
            out[name] = order if order is not None else 0
    return out


def _order_signals(db: Session, serial_id: int | None, signals: list) -> list:
    """Sort a serial's signals by their package display_order, then name.

    Signals with no package entry (or an unreordered serial where every entry is
    display_order 0) fall back to the alphabetical order they arrive in — the sort
    is stable, so name order from _latest_signal_status is preserved for ties.
    """
    if serial_id is None or not signals:
        return signals
    order = _display_order_by_signal(db, serial_id, signals)
    return sorted(signals, key=lambda log: order.get(log.signal_name, 10 ** 6))


def _dashboard_ctx(db: Session, current_user: User | None = None) -> dict:
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
            signals = _order_signals(db, serial.id, _latest_signal_status(db, serial_id=serial.id))
            buzzer = _buzzer_active(signals, range_state)
            if buzzer:
                all_buzzer = True
            serial_data.append({
                "serial": serial,
                "signals": signals,
                "buzzer_active": buzzer,
                "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial.id, signals),
                "priority_by_signal": _priority_by_signal(db, serial.id, signals),
                "has_cbm_mapping": any(
                    entry.cbm_device_id
                    for link in serial.package_links
                    for entry in link.package.signals
                ),
            })
    else:
        # No serials running — show all logs for reference (legacy / no-serial mode),
        # but nothing can be transmitting: with no active serial no signal is "Up".
        signals = _latest_signal_status(db)
        all_buzzer = False
        serial_data = [{"serial": None, "signals": signals, "buzzer_active": False, "has_cbm_mapping": False}]

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
                        "max_power_dbw": w.max_power_dbw,
                        "max_power_w": w.max_power_w,
                        "max_power_all": w.max_power_all_label,
                        "type": "reduced_power" if w.max_power_dbm is not None else "no_fire",
                        "type_label": w.window_type_label,
                    }
                    for w in windows
                ],
            })
        if tables:
            cda_by_serial[serial.id] = tables

    global_signals = [s for sd in serial_data for s in sd["signals"]]
    # Transmitting + Up/Faulted counts are authoritative from ACTIVE serials only,
    # so a signal in a closed/historical serial (or with no serial) can never make
    # the dashboard read "transmitting" or inflate the Up count.
    active_signals = _active_serial_signals(db)
    up_count = sum(1 for s in active_signals if s.signal_status == "Up")
    faulted_count = sum(1 for s in active_signals if s.signal_status == "Faulted")
    any_buzzer = _buzzer_active(active_signals, range_state)
    testing = is_testing_state(db)
    return {
        "serial_data": serial_data,
        "active_serials": active_serials,
        "cbm_status_by_source": _cbm_status_by_source(db, testing),
        # Flat signals list kept for the OOB buzzer swap (any signal across all serials)
        "signals": global_signals,
        # Global aggregates for the summary cards (kept fresh on every poll via OOB)
        "up_count": up_count,
        "faulted_count": faulted_count,
        "any_buzzer": any_buzzer,
        "range_state": range_state,
        "buzzer_active": any_buzzer,
        "mod_types": mod_types,
        "fec_types": fec_types,
        "signal_sources": signal_sources,
        "antenna_types": antenna_types,
        "last_state_change": last_state_change,
        "exclusivity_map": exclusivity_map,
        "local_timezone": get_local_timezone(db),
        "cda_by_serial": cda_by_serial,
        "call_types": call_types,
        "can_edit": bool(current_user and current_user.role != "observer"),
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    toast: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ctx = _dashboard_ctx(db, current_user)
    ctx.update({
        "user": current_user,
        "toast": toast,
        "page": "dashboard",
        "doc_pages": db.query(DocPage).filter(DocPage.is_published == True).order_by(DocPage.title).all(),
        "registry_signals": [
            s.name for s in db.query(Signal)
            .filter(Signal.is_active == True).order_by(Signal.name).all()
        ],
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

    # Capture the signal's modem state at the moment of the effect. Stored as a
    # pipe-delimited "Key: Value" string so the Signal Logs view can render it as
    # a clean, readable effect row (see logs_list.html) without needing the edit
    # panel. Order is fixed: Effect, Source, modem metrics, and lock states.
    source = latest.source if latest else None
    cbm_status = _cbm_status_by_source(db, testing)

    def _lock(value) -> str:
        return "OK" if value is True else ("Fault" if value is False else "—")

    ebno_label = f"{latest.eb_no} dB" if (latest and latest.eb_no is not None) else "—"
    ber_label = f"{latest.ber_estimate:g}" if (latest and latest.ber_estimate is not None) else "—"
    mod_label = (latest.modulation if latest and latest.modulation else "—")
    if latest and latest.power is not None:
        power_label = f"{latest.power} {latest.power_unit or 'dBm'}"
    else:
        power_label = "—"
    if source and source in cbm_status and cbm_status[source]:
        ebem = cbm_status[source]
        carrier = _lock(ebem.get("carrier_lock"))
        channel = _lock(ebem.get("ebem_sync"))
        mod_lock = _lock(ebem.get("bit_sync"))
    else:
        carrier = channel = mod_lock = "—"

    notes_text = (
        f"Effect: {call_type} | Source: {source or 'No modem assigned'} | Mod: {mod_label} "
        f"| Power: {power_label} | Eb/No: {ebno_label} "
        f"| BER Estimate: {ber_label} | Carrier Lock: {carrier} | Channel Sync: {channel} | Mod Lock: {mod_lock}"
    )

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
        ber_estimate=latest.ber_estimate if latest else None,
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
    return JSONResponse({
        "ok": True,
        "message": f"Effect logged: {call_type} for {signal_name}",
        "signal_name": signal_name,
        "call_type": call_type,
    })


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

    # Count chameleons within THIS serial's signals so the -N continues from any
    # planned chameleons loaded from the package (e.g. 201-1/-2/-3 → 201-4), while
    # a fresh signal in a fresh serial starts at -1.
    existing_names = [log.signal_name for log in _latest_signal_status(db, serial_id=serial_id)]
    new_name = next_chameleon_name(signal_name, existing_names)

    # Ensure the new name doesn't already exist as a Signal registry entry
    if not db.query(Signal).filter(Signal.name == new_name).first():
        original_sig = db.query(Signal).filter(Signal.name == chameleon_base_name(signal_name)).first()
        db.add(Signal(
            name=new_name,
            description=f"Chameleon of {signal_name}",
            default_band=original_sig.default_band if original_sig else None,
            default_modulation=original_sig.default_modulation if original_sig else None,
            default_symbol_rate=original_sig.default_symbol_rate if original_sig else None,
            default_fec=original_sig.default_fec if original_sig else None,
            max_power_dbm=original_sig.max_power_dbm if original_sig else None,
        ))

    # Clone the parent's package entry (minus modem source) so the chameleon is a
    # first-class package signal — this makes EBEM parameter sync and modem-source
    # uniqueness work for it exactly like any other package signal.
    if serial_id is not None:
        serial_obj = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if serial_obj:
            parent_entry = None
            already_exists = False
            for link in serial_obj.package_links:
                for entry in link.package.signals:
                    if entry.signal_name == new_name:
                        already_exists = True
                    if entry.signal_name == signal_name and parent_entry is None:
                        parent_entry = entry
            if parent_entry and not already_exists:
                db.add(SignalPackageEntry(
                    package_id=parent_entry.package_id,
                    display_order=len(parent_entry.package.signals),
                    priority=parent_entry.priority,
                    signal_name=new_name,
                    description=f"Chameleon of {signal_name}",
                    band=parent_entry.band,
                    tx_if=parent_entry.tx_if, tx_rf=parent_entry.tx_rf,
                    rx_rf=parent_entry.rx_rf, rx_if=parent_entry.rx_if,
                    freq_unit=parent_entry.freq_unit,
                    modulation=parent_entry.modulation,
                    fec=parent_entry.fec,
                    inner_code=parent_entry.inner_code,
                    symbol_rate=parent_entry.symbol_rate,
                    power=parent_entry.power, power_unit=parent_entry.power_unit,
                    eb_no=None,
                    source=None,                 # modem source must NOT copy across
                    antenna=parent_entry.antenna,
                    cbm_device_id=None,
                    cbm_path=None,
                    cbm_carrier=None,
                    notes=parent_entry.notes,
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
        ber_estimate=None,
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


@router.get("/api/time")
async def api_time(current_user: User = Depends(get_current_user)):
    """Authoritative server time so all clients agree regardless of device clock.

    Returns Unix epoch milliseconds (UTC); clients compute an offset against
    their own clock and render Zulu/local from it.
    """
    return JSONResponse({"epoch_ms": int(datetime.now().timestamp() * 1000)})


@router.get("/dashboard/fragment", response_class=HTMLResponse)
async def dashboard_fragment_legacy(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX polling — fallback when no serial is active (all signals)."""
    ctx = _dashboard_ctx(db, current_user)
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


def _priority_by_signal(db: Session, serial_id: int | None, signals: list[SignalLog]) -> dict:
    """Map each displayed signal name to its package-entry priority (if any).

    Priority lives on the signal package entry, so we resolve it by name across
    the packages assigned to the serial. Case-insensitive on the signal name.
    """
    if serial_id is None:
        return {}
    names = {log.signal_name.strip().casefold() for log in signals}
    if not names:
        return {}
    rows = (
        db.query(SignalPackageEntry.signal_name, SignalPackageEntry.priority)
        .join(SerialPackage, SerialPackage.package_id == SignalPackageEntry.package_id)
        .filter(SerialPackage.serial_id == serial_id)
        .all()
    )
    out: dict[str, int] = {}
    for name, priority in rows:
        if priority is not None and name.strip().casefold() in names:
            out[name] = priority
    return out


def _blank_to_none(value):
    return None if value == "" else value


def _dashboard_values_from_update(
    db: Session,
    serial_id: int | None,
    latest: SignalLog | None,
    upd: _SignalUpdate,
    signal_name: str | None = None,
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
        "ber_estimate": latest.ber_estimate if latest else None,
        "source": _blank_to_none(upd.source) if "source" in upd.changed_fields else (latest.source if latest else None),
        "antenna": _blank_to_none(upd.antenna) if "antenna" in upd.changed_fields else (latest.antenna if latest else None),
    }
    if serial_id is not None:
        rf = serial_package_rf_config(db, serial_id, signal_name or upd.signal_name)
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
    ctx = _dashboard_ctx(db, current_user)
    signals = _order_signals(db, serial_id, _latest_signal_status(db, serial_id=serial_id))
    range_state = ctx["range_state"]
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, range_state),
        "serial_id": serial_id,
        "closed_loop": bool(serial and serial.is_closed_loop),
        "pkg_rf": _pkg_rf_for_serial(db, serial_id),
        "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial_id, signals),
        "priority_by_signal": _priority_by_signal(db, serial_id, signals),
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
                        ber_estimate=sib_latest.ber_estimate,
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
    if source.strip():
        device = _cbm_source_device(db, source.strip(), testing)
        if device:
            _reassign_modem_source(
                db, serial_id, testing, range_state, signal_name, device.name, current_user,
            )

    resolved_source = effective_source if source.strip() or package_sources_updated else (latest.source if latest else None)
    # Live modem metrics are invalid without a modem source or when the signal is not Up.
    resolved_eb_no = eb_no if eb_no is not None else (latest.eb_no if latest else None)
    resolved_ber = latest.ber_estimate if latest else None
    if not resolved_source or signal_status != "Up":
        resolved_eb_no = None
        resolved_ber = None

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
        eb_no=resolved_eb_no,
        ber_estimate=resolved_ber,
        engaged=latest.engaged if latest else False,
        source=resolved_source,
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

    ctx = _dashboard_ctx(db, current_user)
    effective_serial_id = serial_id if serial_id is not None else None
    signals = _order_signals(db, effective_serial_id, _latest_signal_status(db, serial_id=effective_serial_id))
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, ctx["range_state"]),  # this widget's badge
        "serial_id": effective_serial_id,
        "pkg_rf": _pkg_rf_for_serial(db, effective_serial_id) if effective_serial_id else None,
        "pkg_rf_by_signal": (
            _pkg_rf_by_signal(db, effective_serial_id, signals) if effective_serial_id else {}
        ),
        "priority_by_signal": (
            _priority_by_signal(db, effective_serial_id, signals) if effective_serial_id else {}
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
    serial = None
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None
            serial = None

    for upd in body.updates:
        old_signal_name = upd.signal_name.strip()
        new_signal_name = (upd.signal_new_name or old_signal_name).strip()
        if "signal_name" in upd.changed_fields:
            if not new_signal_name:
                return HTMLResponse("Signal name is required.", status_code=400)
            try:
                _rename_dashboard_signal(
                    db, serial, serial_id, testing, old_signal_name, new_signal_name, current_user
                )
            except ValueError as exc:
                return HTMLResponse(str(exc), status_code=400)

        latest_q = db.query(SignalLog).filter(
            SignalLog.signal_name == new_signal_name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        )
        if serial_id is not None:
            latest_q = latest_q.filter(SignalLog.serial_id == serial_id)
        latest = latest_q.order_by(SignalLog.timestamp.desc()).first()

        # Exclusivity group enforcement
        if upd.signal_status == "Up":
            sig_reg = db.query(Signal).filter(Signal.name == new_signal_name).first()
            if sig_reg and sig_reg.exclusivity_group:
                siblings = db.query(Signal).filter(
                    Signal.exclusivity_group == sig_reg.exclusivity_group,
                    Signal.name != new_signal_name,
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
                            ber_estimate=sib_latest.ber_estimate,
                            engaged=sib_latest.engaged,
                            source=sib_latest.source, antenna=sib_latest.antenna,
                            notes=f"Auto-downed: {new_signal_name} came Up (group: {sig_reg.exclusivity_group})",
                            entry_type="Automatic", updated_by_id=current_user.id, serial_id=serial_id,
                        ))

        effective_source = None
        if "source" in upd.changed_fields:
            effective_source, _ = _update_serial_package_signal_source(
                db, serial, new_signal_name, upd.source or "", current_user, testing,
            )
            # Dashboard modem-source uniqueness: if the new source is a modem,
            # clear it from any other signal that still shows it.
            device = _cbm_source_device(db, (upd.source or "").strip(), testing)
            if device:
                _reassign_modem_source(
                    db, serial_id, testing, range_state, new_signal_name, device.name, current_user,
                )

        values = _dashboard_values_from_update(db, serial_id, latest, upd, signal_name=new_signal_name)
        if "source" in upd.changed_fields:
            values["source"] = effective_source
            # Removing the modem source invalidates live modem metrics.
            if not effective_source:
                values["eb_no"] = None
                values["ber_estimate"] = None
        # Live modem metrics are only meaningful while the signal is transmitting/Up.
        if values["signal_status"] != "Up":
            values["eb_no"] = None
            values["ber_estimate"] = None

        new_entry = SignalLog(
            operator_id=current_user.id, range_state=range_state,
            signal_name=new_signal_name, signal_status=values["signal_status"],
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
            ber_estimate=values["ber_estimate"],
            engaged=latest.engaged if latest else False,
            source=values["source"],
            antenna=values["antenna"],
            notes=(upd.notes or "").strip() or None,
            entry_type="Dashboard", updated_by_id=current_user.id,
            serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
            warning_flags=warning_flags_for(
                db, new_signal_name,
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
        new_signal_name = (upd.signal_new_name or upd.signal_name).strip()
        db.add(AuditLog(
            user_id=current_user.id, action_type="DASHBOARD_UPDATE",
            entity_type="SignalLog",
            new_value=f"{new_signal_name}: {upd.signal_status}",
            comment=", ".join(upd.changed_fields) if upd.changed_fields else None,
        ))
    db.commit()

    ctx = _dashboard_ctx(db, current_user)
    signals = _order_signals(db, serial_id, _latest_signal_status(db, serial_id=serial_id))
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, ctx["range_state"]),
        "serial_id": serial_id,
        "pkg_rf": _pkg_rf_for_serial(db, serial_id) if serial_id else None,
        "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial_id, signals) if serial_id else {},
        "priority_by_signal": _priority_by_signal(db, serial_id, signals) if serial_id else {},
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


def _render_serial_fragment(request: Request, db: Session, current_user: User, serial_id: int | None):
    """Re-render a serial's signal table fragment (with OOB indicators)."""
    ctx = _dashboard_ctx(db, current_user)
    signals = _order_signals(db, serial_id, _latest_signal_status(db, serial_id=serial_id))
    serial = None
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == is_testing_state(db)).first()
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, ctx["range_state"]),
        "serial_id": serial_id,
        "closed_loop": bool(serial and serial.is_closed_loop),
        "pkg_rf": _pkg_rf_for_serial(db, serial_id) if serial_id else None,
        "pkg_rf_by_signal": _pkg_rf_by_signal(db, serial_id, signals) if serial_id else {},
        "priority_by_signal": _priority_by_signal(db, serial_id, signals) if serial_id else {},
    })


@router.post("/dashboard/signals/reorder", response_class=HTMLResponse)
async def dashboard_signals_reorder(
    request: Request,
    serial_id: int = Form(...),
    order: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a drag-to-reorder of a serial's signals onto the package entries.

    The dashboard widget mirrors the package screen's reorder: the new ordinal of
    each signal name is written to the display_order of the matching package
    entries across the serial's assigned packages, so it survives reloads.
    """
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    if not serial or current_user.role == "observer":
        return HTMLResponse("", status_code=403)
    order_map = {name: i for i, name in enumerate(order)}
    package_ids = [link.package_id for link in serial.package_links]
    changed = 0
    if package_ids:
        entries = db.query(SignalPackageEntry).filter(
            SignalPackageEntry.package_id.in_(package_ids)
        ).all()
        for entry in entries:
            if entry.signal_name in order_map and entry.display_order != order_map[entry.signal_name]:
                entry.display_order = order_map[entry.signal_name]
                entry.package.updated_at = datetime.utcnow()
                changed += 1
    if changed:
        db.add(AuditLog(
            user_id=current_user.id, action_type="DASHBOARD_SIGNAL_REORDER",
            entity_type="Serial", entity_id=serial_id,
            new_value=f"Reordered {changed} signal(s) in serial {serial.display_title}",
        ))
        db.commit()
    return _render_serial_fragment(request, db, current_user, serial_id)


def _auto_down_exclusivity(db: Session, signal_name: str, serial_id: int | None,
                           testing: bool, range_state: str, current_user: User) -> None:
    """Bringing a signal Up auto-downs any Up siblings in its exclusivity group."""
    sig_reg = db.query(Signal).filter(Signal.name == signal_name).first()
    if not (sig_reg and sig_reg.exclusivity_group):
        return
    siblings = db.query(Signal).filter(
        Signal.exclusivity_group == sig_reg.exclusivity_group,
        Signal.name != signal_name,
    ).all()
    for sib in siblings:
        q = db.query(SignalLog).filter(
            SignalLog.signal_name == sib.name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        )
        if serial_id is not None:
            q = q.filter(SignalLog.serial_id == serial_id)
        latest = q.order_by(SignalLog.timestamp.desc()).first()
        if latest and latest.signal_status == "Up":
            db.add(SignalLog(
                operator_id=current_user.id, range_state=range_state,
                signal_name=sib.name, signal_status="Down",
                tx_if=latest.tx_if, tx_rf=latest.tx_rf, rx_rf=latest.rx_rf, rx_if=latest.rx_if,
                freq_unit=latest.freq_unit, band=latest.band,
                modulation=latest.modulation, symbol_rate=latest.symbol_rate, fec=latest.fec,
                power=latest.power, power_unit=latest.power_unit,
                eb_no=latest.eb_no, ber_estimate=latest.ber_estimate,
                engaged=latest.engaged, source=latest.source, antenna=latest.antenna,
                notes=f"Auto-downed: {signal_name} added Up (group: {sig_reg.exclusivity_group})",
                entry_type="Automatic", updated_by_id=current_user.id, serial_id=serial_id,
            ))


@router.post("/dashboard/signals/add", response_class=HTMLResponse)
async def dashboard_signal_add(
    request: Request,
    signal_name: str = Form(...),
    serial_id: Optional[int] = Form(None),
    signal_status: str = Form("Planned"),
    source: str = Form(""),
    modulation: str = Form(""),
    fec: str = Form(""),
    symbol_rate: str = Form(""),
    antenna: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new signal to a serial's dashboard widget as a fresh log entry.

    This is the live, in-widget counterpart to the full New Log form: it creates a
    SignalLog for the serial so the signal appears in the widget immediately, then
    returns the re-rendered fragment. Frequencies are stored as entered; if the
    serial's package supplies RF config for this name, the missing legs are filled.
    """
    testing = is_testing_state(db)
    if current_user.role == "observer":
        return HTMLResponse("", status_code=403)
    name = signal_name.strip()
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None
    if not name:
        return _render_serial_fragment(request, db, current_user, serial_id)

    range_state = get_current_range_state(db)

    # Complete the RF legs from the serial's package config where possible.
    values = {"tx_if": tx_if, "tx_rf": tx_rf, "rx_rf": rx_rf, "rx_if": rx_if,
              "freq_unit": freq_unit or "MHz", "band": None, "antenna": antenna.strip() or None}
    if serial_id is not None:
        rf = serial_package_rf_config(db, serial_id, name)
        if rf:
            preferred = [f for f in ("tx_if", "tx_rf", "rx_rf", "rx_if")
                         if values[f] is not None]
            values = recalculate_from_values(values, rf, preferred=preferred or None)
            values["band"] = values.get("band") or rf.get("band")
            values["antenna"] = values.get("antenna") or rf.get("antenna")

    if signal_status == "Up":
        _auto_down_exclusivity(db, name, serial_id, testing, range_state, current_user)

    resolved_source = source.strip() or None
    resolved_eb_no = eb_no if (resolved_source and signal_status == "Up") else None

    entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name=name,
        signal_status=signal_status,
        tx_if=values["tx_if"], tx_rf=values["tx_rf"], rx_rf=values["rx_rf"], rx_if=values["rx_if"],
        freq_unit=values["freq_unit"], band=values["band"],
        modulation=modulation.strip() or None,
        symbol_rate=symbol_rate.strip() or None,
        fec=fec.strip() or None,
        power=power, power_unit=power_unit or "dBm",
        eb_no=resolved_eb_no,
        source=resolved_source,
        antenna=values["antenna"],
        notes=notes.strip() or None,
        entry_type="Dashboard",
        updated_by_id=current_user.id,
        serial_id=serial_id,
        warning_flags=warning_flags_for(
            db, name, power, power_unit or "dBm",
            tx_rf=values["tx_rf"], rx_rf=values["rx_rf"],
            freq_unit=values["freq_unit"], band=values["band"],
        ),
    )
    db.add(entry)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id, action_type="DASHBOARD_SIGNAL_ADD",
        entity_type="SignalLog", entity_id=entry.id,
        new_value=f"{name}: {signal_status}",
    ))
    db.commit()
    return _render_serial_fragment(request, db, current_user, serial_id)


@router.post("/dashboard/signals/delete")
async def dashboard_signal_delete(
    signal_name: str = Form(...),
    serial_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a signal from the dashboard widget by soft-deleting its logs.

    Refused for signals that are currently Up (transmitting): an active signal must
    be brought Down before it can be removed. The underlying package entry is left
    intact — this only clears the signal from the live widget/log view.
    """
    testing = is_testing_state(db)
    if current_user.role == "observer":
        return RedirectResponse("/", status_code=302)
    if serial_id is not None:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None

    q = db.query(SignalLog).filter(
        SignalLog.signal_name == signal_name,
        SignalLog.signal_name != "[NOTE]",
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if serial_id is not None:
        q = q.filter(SignalLog.serial_id == serial_id)
    logs = q.order_by(SignalLog.timestamp.desc()).all()
    if not logs:
        return RedirectResponse("/", status_code=302)

    # An Up (transmitting) signal must be brought Down before removal.
    if logs[0].signal_status == "Up":
        msg = f"Cannot remove {signal_name} while it is Up — bring it Down first."
        return RedirectResponse(f"/?toast={quote_plus(msg)}", status_code=302)

    for log in logs:
        log.is_deleted = True
        log.updated_by_id = current_user.id
    db.add(AuditLog(
        user_id=current_user.id, action_type="DASHBOARD_SIGNAL_DELETE",
        entity_type="SignalLog", entity_id=logs[0].id,
        new_value=f"Removed {signal_name} from dashboard"
                  + (f" (serial {serial_id})" if serial_id is not None else ""),
    ))
    db.commit()
    return RedirectResponse(f"/?toast={quote_plus(f'Removed {signal_name} from dashboard')}", status_code=302)


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
    signals = _active_serial_signals(db)
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
    signals = _active_serial_signals(db)
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
    signals = _active_serial_signals(db)
    active = _buzzer_active(signals, range_state)
    return templates.TemplateResponse(request, "partials/buzzer_badge.html", {
        "buzzer_active": active,
        "range_state": range_state,
    })
