from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
import csv
import io
import openpyxl
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials, is_testing_state
from app.models import User, SignalLog, Signal, AuditLog, SignalStatus, Role, ModulationType, FecType, SignalSource, AntennaType, LogSession, Serial, RFDevice
from app.rf_config import serial_package_rf_config
from app.signal_warnings import warning_flags_for
from app.log_changes import annotate_log_changes
from app.settings import annotate_local_times, get_local_timezone

router = APIRouter(prefix="/logs")
from app.templating import templates

SIGNAL_STATUSES = [s.value for s in SignalStatus]
MODULATIONS = ["BPSK", "QPSK", "8PSK", "16APSK", "32APSK", "Other"]
FEC_RATES = ["1/2", "2/3", "3/4", "5/6", "7/8", "8/9", "9/10", "Other"]
POWER_UNITS = ["dBm", "dBW", "W"]
FREQ_UNITS = ["MHz", "GHz"]
BANDS = ["C", "X", "Ku", "Ka", "Other"]


def _db_mod_types(db: Session) -> list[str]:
    rows = db.query(ModulationType).filter(ModulationType.is_active == True).order_by(ModulationType.display_order, ModulationType.name).all()
    return [r.name for r in rows] or MODULATIONS


def _db_fec_types(db: Session) -> list[str]:
    rows = db.query(FecType).filter(FecType.is_active == True).order_by(FecType.display_order, FecType.name).all()
    return [r.name for r in rows] or FEC_RATES


def _db_sources(db: Session) -> list[str]:
    names = [r.name for r in db.query(SignalSource).filter(SignalSource.is_active == True).order_by(SignalSource.display_order, SignalSource.name).all()]
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


def _db_antennas(db: Session) -> list[str]:
    return [r.name for r in db.query(AntennaType).filter(AntennaType.is_active == True).order_by(AntennaType.display_order, AntennaType.name).all()]


LOG_PAGE_SIZE = 100


def _apply_filters(query, search, status, band, date_from, date_to, activity, serial_id=None, signal_name=None, entry_type=None):
    if signal_name:
        query = query.filter(SignalLog.signal_name == signal_name)
    if search:
        query = query.filter(
            or_(
                SignalLog.signal_name.ilike(f"%{search}%"),
                SignalLog.notes.ilike(f"%{search}%"),
                SignalLog.activity_ref.ilike(f"%{search}%"),
            )
        )
    if status:
        query = query.filter(SignalLog.signal_status == status)
    if band:
        query = query.filter(SignalLog.band == band)
    if activity:
        query = query.filter(SignalLog.activity_ref.ilike(f"%{activity}%"))
    if entry_type:
        query = query.filter(SignalLog.entry_type == entry_type)
    if serial_id:
        try:
            query = query.filter(SignalLog.serial_id == int(serial_id))
        except (ValueError, TypeError):
            pass
    if date_from:
        try:
            query = query.filter(SignalLog.timestamp >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.fromisoformat(date_to)
            if "T" not in date_to and len(date_to) == 10:
                end = end + timedelta(days=1)
                query = query.filter(SignalLog.timestamp < end)
            else:
                query = query.filter(SignalLog.timestamp <= end)
        except ValueError:
            pass
    return query


_SORT_COLS = {
    "timestamp": SignalLog.timestamp,
    "signal_name": SignalLog.signal_name,
    "signal_status": SignalLog.signal_status,
    "band": SignalLog.band,
}


@router.get("", response_class=HTMLResponse)
async def log_list(
    request: Request,
    search: str = "",
    status: str = "",
    band: str = "",
    date_from: str = "",
    date_to: str = "",
    activity: str = "",
    serial_id: str = "",
    signal_name: str = "",
    entry_type: str = "",
    show_deleted: str = "",
    local_time: str = "",
    toast: str = "",
    sort: str = Query(default="timestamp"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    q = db.query(SignalLog).filter(SignalLog.is_testing == testing)
    if not (show_deleted == "1" and current_user.role == Role.SUPERVISOR):
        q = q.filter(SignalLog.is_deleted == False)
    q = _apply_filters(q, search, status, band, date_from, date_to, activity, serial_id, signal_name, entry_type)
    total = q.count()
    sort_col = _SORT_COLS.get(sort, SignalLog.timestamp)
    order = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
    logs = q.order_by(order).offset((page - 1) * LOG_PAGE_SIZE).limit(LOG_PAGE_SIZE).all()
    annotate_log_changes(db, logs)
    local_timezone = get_local_timezone(db)
    show_local_time = local_time == "1"
    if show_local_time:
        annotate_local_times(logs, local_timezone)
    total_pages = max(1, (total + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)

    # Serial lookup for filter display
    serial_obj = None
    if serial_id:
        try:
            serial_obj = db.query(Serial).filter(Serial.id == int(serial_id), Serial.is_testing == testing).first()
        except (ValueError, TypeError):
            pass

    active_serials = get_active_serials(db)
    all_serials = db.query(Serial).filter(Serial.is_testing == testing).order_by(Serial.opened_at.desc()).all()
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    quick_dates = {
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "last7": (today - timedelta(days=6)).isoformat(),
    }

    return templates.TemplateResponse(request, "logs_list.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active_serials,
        "logs": logs,
        "statuses": SIGNAL_STATUSES,
        "bands": BANDS,
        "all_serials": all_serials,
        "serial_obj": serial_obj,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "show_local_time": show_local_time,
        "local_timezone": local_timezone,
        "toast": toast,
        "quick_dates": quick_dates,
        "filters": {
            "search": search, "status": status, "band": band,
            "date_from": date_from, "date_to": date_to,
            "activity": activity, "show_deleted": show_deleted,
            "serial_id": serial_id, "signal_name": signal_name,
            "local_time": local_time, "entry_type": entry_type,
        },
        "sort": sort,
        "sort_dir": sort_dir,
        "page_name": "logs",
    })


@router.get("/new", response_class=HTMLResponse)
async def log_new(
    request: Request,
    serial_id: Optional[int] = Query(None),
    tx_if: str = Query(default=""),
    tx_rf: str = Query(default=""),
    rx_rf: str = Query(default=""),
    rx_if: str = Query(default=""),
    freq_unit: str = Query(default=""),
    band: str = Query(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    signals = db.query(Signal).filter(Signal.is_active == True).order_by(Signal.name).all()
    last_calc = {
        "tx_lo": request.session.get("last_tx_lo"),
        "rx_lo": request.session.get("last_rx_lo"),
        "ttf": request.session.get("last_ttf"),
        "ttf_direction": request.session.get("last_ttf_direction", "+"),
        "freq_unit": request.session.get("last_freq_unit", "MHz"),
        "band": request.session.get("last_band", ""),
    }
    active_serials = get_active_serials(db)
    testing = is_testing_state(db)
    all_serials = db.query(Serial).filter(Serial.closed_at == None, Serial.is_testing == testing).order_by(Serial.opened_at.desc()).all()
    preselect_serial_id = serial_id if serial_id else (active_serials[0].id if active_serials else None)

    # Look up the package RF config for the preselected serial so it can pre-fill TxLO/RxLO/TTF
    pkg_rf = serial_package_rf_config(db, preselect_serial_id) if preselect_serial_id else None
    if pkg_rf:
        # Package RF config takes priority over the user's last calculator values.
        last_calc = {**last_calc, **{k: v for k, v in pkg_rf.items() if v is not None}}

    # Freq values from calculator query params override last_calc and log_entry defaults
    prefill = {
        "tx_if": tx_if, "tx_rf": tx_rf, "rx_rf": rx_rf, "rx_if": rx_if,
        "freq_unit": freq_unit or (pkg_rf.get("freq_unit") if pkg_rf else "MHz"),
        "band": band or (pkg_rf.get("band") if pkg_rf else ""),
    } if any([tx_if, tx_rf, rx_rf, rx_if]) else None
    return templates.TemplateResponse(request, "logs_form.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active_serials,
        "all_serials": all_serials,
        "preselect_serial_id": preselect_serial_id,
        "log_entry": None,
        "signals": signals,
        "statuses": SIGNAL_STATUSES,
        "modulations": _db_mod_types(db),
        "fec_types": _db_fec_types(db),
        "signal_sources": _db_sources(db),
        "antenna_types": _db_antennas(db),
        "power_units": POWER_UNITS,
        "freq_units": FREQ_UNITS,
        "bands": BANDS,
        "last_calc": last_calc,
        "prefill": prefill,
        "pkg_rf": pkg_rf,
        "page_name": "logs",
    })


@router.post("/new", response_class=HTMLResponse)
async def log_create(
    request: Request,
    signal_name: str = Form(...),
    signal_status: str = Form(...),
    band: str = Form(""),
    modulation: str = Form(""),
    symbol_rate: str = Form(""),
    fec: str = Form(""),
    source: str = Form(""),
    antenna: str = Form(""),
    serial_id: Optional[int] = Form(None),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    activity_ref: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    if serial_id:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None
    entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name=signal_name.strip(),
        signal_status=signal_status,
        band=band or None,
        modulation=modulation or None,
        symbol_rate=symbol_rate or None,
        fec=fec or None,
        source=source.strip() or None,
        antenna=antenna.strip() or None,
        serial_id=serial_id,
        tx_if=tx_if,
        tx_rf=tx_rf,
        rx_rf=rx_rf,
        rx_if=rx_if,
        freq_unit=freq_unit,
        power=power,
        power_unit=power_unit,
        eb_no=eb_no,
        activity_ref=activity_ref.strip() or None,
        notes=notes.strip() or None,
        entry_type="Manual",
        warning_flags=warning_flags_for(
            db, signal_name.strip(), power, power_unit,
            tx_rf=tx_rf, rx_rf=rx_rf, freq_unit=freq_unit, band=band,
        ),
    )
    db.add(entry)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="LOG_CREATE",
        entity_type="SignalLog",
        entity_id=entry.id,
        new_value=signal_name,
    ))
    db.commit()
    return RedirectResponse("/logs?toast=Log+entry+created", status_code=302)


@router.get("/{log_id}/edit", response_class=HTMLResponse)
async def log_edit(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    log_entry = db.query(SignalLog).filter(SignalLog.id == log_id, SignalLog.is_testing == testing).first()
    if not log_entry:
        return RedirectResponse("/logs", status_code=302)
    signals = db.query(Signal).filter(Signal.is_active == True).order_by(Signal.name).all()
    active_serials = get_active_serials(db)
    all_serials = db.query(Serial).filter(Serial.is_testing == testing).order_by(Serial.opened_at.desc()).all()
    return templates.TemplateResponse(request, "logs_form.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active_serials,
        "all_serials": all_serials,
        "preselect_serial_id": log_entry.serial_id,
        "log_entry": log_entry,
        "signals": signals,
        "statuses": SIGNAL_STATUSES,
        "modulations": _db_mod_types(db),
        "fec_types": _db_fec_types(db),
        "signal_sources": _db_sources(db),
        "antenna_types": _db_antennas(db),
        "power_units": POWER_UNITS,
        "freq_units": FREQ_UNITS,
        "bands": BANDS,
        "last_calc": {},
        "page_name": "logs",
    })


@router.post("/{log_id}/edit", response_class=HTMLResponse)
async def log_update(
    log_id: int,
    request: Request,
    signal_name: str = Form(...),
    signal_status: str = Form(...),
    band: str = Form(""),
    modulation: str = Form(""),
    symbol_rate: str = Form(""),
    fec: str = Form(""),
    source: str = Form(""),
    antenna: str = Form(""),
    serial_id: Optional[int] = Form(None),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    activity_ref: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    log_entry = db.query(SignalLog).filter(SignalLog.id == log_id, SignalLog.is_testing == testing).first()
    if not log_entry:
        return RedirectResponse("/logs", status_code=302)
    if serial_id:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None

    old_status = log_entry.signal_status
    log_entry.signal_name = signal_name.strip()
    log_entry.signal_status = signal_status
    log_entry.band = band or None
    log_entry.modulation = modulation or None
    log_entry.symbol_rate = symbol_rate or None
    log_entry.fec = fec or None
    log_entry.source = source.strip() or None
    log_entry.antenna = antenna.strip() or None
    log_entry.serial_id = serial_id
    log_entry.tx_if = tx_if
    log_entry.tx_rf = tx_rf
    log_entry.rx_rf = rx_rf
    log_entry.rx_if = rx_if
    log_entry.freq_unit = freq_unit
    log_entry.power = power
    log_entry.power_unit = power_unit
    log_entry.eb_no = eb_no
    log_entry.activity_ref = activity_ref.strip() or None
    log_entry.notes = notes.strip() or None
    log_entry.warning_flags = warning_flags_for(
        db, log_entry.signal_name, power, power_unit,
        tx_rf=tx_rf, rx_rf=rx_rf, freq_unit=freq_unit, band=band,
    )
    log_entry.updated_at = datetime.utcnow()
    log_entry.updated_by_id = current_user.id

    db.add(AuditLog(
        user_id=current_user.id,
        action_type="LOG_EDIT",
        entity_type="SignalLog",
        entity_id=log_id,
        previous_value=old_status,
        new_value=signal_status,
    ))
    db.commit()
    return RedirectResponse("/logs?toast=Log+entry+updated", status_code=302)


@router.post("/{log_id}/delete")
async def log_soft_delete(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    log_entry = db.query(SignalLog).filter(SignalLog.id == log_id, SignalLog.is_testing == is_testing_state(db)).first()
    if log_entry:
        log_entry.is_deleted = True
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="LOG_SOFT_DELETE",
            entity_type="SignalLog",
            entity_id=log_id,
        ))
        db.commit()
    return RedirectResponse("/logs?toast=Log+entry+deleted", status_code=302)


@router.post("/{log_id}/restore")
async def log_restore(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != Role.SUPERVISOR:
        return RedirectResponse("/logs", status_code=302)
    log_entry = db.query(SignalLog).filter(SignalLog.id == log_id, SignalLog.is_testing == is_testing_state(db)).first()
    if log_entry:
        log_entry.is_deleted = False
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="LOG_RESTORE",
            entity_type="SignalLog",
            entity_id=log_id,
        ))
        db.commit()
    return RedirectResponse("/logs?show_deleted=1&toast=Log+entry+restored", status_code=302)


@router.post("/{log_id}/hard-delete")
async def log_hard_delete(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a log entry. Administrator only, and only on already
    soft-deleted entries (so it's a deliberate two-step action)."""
    if current_user.role != Role.SUPERVISOR:
        return RedirectResponse("/logs", status_code=302)
    log_entry = db.query(SignalLog).filter(SignalLog.id == log_id, SignalLog.is_testing == is_testing_state(db)).first()
    if log_entry and log_entry.is_deleted:
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="LOG_HARD_DELETE",
            entity_type="SignalLog",
            entity_id=log_id,
            previous_value=log_entry.signal_name,
        ))
        db.delete(log_entry)
        db.commit()
    return RedirectResponse("/logs?show_deleted=1&toast=Log+entry+permanently+deleted", status_code=302)


@router.get("/note", response_class=HTMLResponse)
async def log_note_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active_serials = get_active_serials(db)
    return templates.TemplateResponse(request, "logs_note.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "active_serials": active_serials,
        "page_name": "logs",
    })


@router.post("/note")
async def log_note_save(
    request: Request,
    notes: str = Form(...),
    activity_ref: str = Form(""),
    serial_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    if serial_id:
        serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
        if not serial:
            serial_id = None
    entry = SignalLog(
        operator_id=current_user.id,
        range_state=range_state,
        signal_name="[NOTE]",
        signal_status="Note",
        freq_unit="MHz",
        power_unit="dBm",
        activity_ref=activity_ref.strip() or None,
        notes=notes.strip(),
        entry_type="Narrative",
        serial_id=serial_id,
    )
    db.add(entry)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="LOG_NOTE",
        entity_type="SignalLog",
        entity_id=entry.id,
        new_value=notes[:200],
    ))
    db.commit()
    return RedirectResponse("/logs?toast=Note+saved", status_code=302)


@router.get("/export/csv")
async def export_csv(
    search: str = "",
    status: str = "",
    band: str = "",
    date_from: str = "",
    date_to: str = "",
    activity: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(SignalLog).filter(SignalLog.is_deleted == False, SignalLog.is_testing == is_testing_state(db))
    q = _apply_filters(q, search, status, band, date_from, date_to, activity)
    logs = q.order_by(SignalLog.timestamp.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Timestamp (Zulu)", "Operator", "Session", "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Freq Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No",
        "Activity Ref", "Notes", "Entry Type", "Warnings",
    ])
    for log in logs:
        writer.writerow([
            log.id, log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ"), log.operator.username if log.operator else "",
            log.session.name if log.session else "",
            log.range_state, log.signal_name, log.signal_status,
            log.tx_if, log.tx_rf, log.rx_rf, log.rx_if, log.freq_unit, log.band,
            log.modulation, log.symbol_rate, log.fec, log.source, log.antenna,
            log.power, log.power_unit, log.eb_no,
            log.activity_ref, log.notes, log.entry_type, log.warning_flags,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=range_logs.csv"},
    )


@router.get("/export/xlsx")
async def export_xlsx(
    search: str = "",
    status: str = "",
    band: str = "",
    date_from: str = "",
    date_to: str = "",
    activity: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(SignalLog).filter(SignalLog.is_deleted == False, SignalLog.is_testing == is_testing_state(db))
    q = _apply_filters(q, search, status, band, date_from, date_to, activity)
    logs = q.order_by(SignalLog.timestamp.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Range Logs"
    headers = [
        "ID", "Timestamp (Zulu)", "Operator", "Session", "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Freq Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No",
        "Activity Ref", "Notes", "Entry Type", "Warnings",
    ]
    ws.append(headers)
    for log in logs:
        ws.append([
            log.id, log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ"), log.operator.username if log.operator else "",
            log.session.name if log.session else "",
            log.range_state, log.signal_name, log.signal_status,
            log.tx_if, log.tx_rf, log.rx_rf, log.rx_if, log.freq_unit, log.band,
            log.modulation, log.symbol_rate, log.fec, log.source, log.antenna,
            log.power, log.power_unit, log.eb_no,
            log.activity_ref, log.notes, log.entry_type, log.warning_flags,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=range_logs.xlsx"},
    )
