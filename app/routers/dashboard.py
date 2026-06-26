from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials
from app.models import User, Signal, SignalLog, ModulationType, FecType, SignalSource, AntennaType, AuditLog, RangeStateLog, Serial, DocPage
from app.rf_config import serial_package_rf_config
from app.signal_warnings import warning_flags_for
from app.settings import get_local_timezone
from app.routers.docs import _render_markdown


class _SignalUpdate(BaseModel):
    signal_name: str
    signal_status: str
    power: Optional[float] = None
    power_unit: str = "dBm"


class _BulkUpdateBody(BaseModel):
    serial_id: Optional[int] = None
    updates: list[_SignalUpdate]

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
    return [
        s.name for s in db.query(SignalSource)
        .filter(SignalSource.is_active == True)
        .order_by(SignalSource.display_order, SignalSource.name)
        .all()
    ]


def _get_antennas(db: Session) -> list[str]:
    return [
        a.name for a in db.query(AntennaType)
        .filter(AntennaType.is_active == True)
        .order_by(AntennaType.display_order, AntennaType.name)
        .all()
    ]


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
            })
    else:
        # No serials running — show all logs (legacy / no-serial mode)
        signals = _latest_signal_status(db)
        all_buzzer = _buzzer_active(signals, range_state)
        serial_data = [{"serial": None, "signals": signals, "buzzer_active": all_buzzer}]

    global_signals = [s for sd in serial_data for s in sd["signals"]]
    return {
        "serial_data": serial_data,
        "active_serials": active_serials,
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


@router.get("/dashboard/fragment/{serial_id}", response_class=HTMLResponse)
async def dashboard_fragment(
    serial_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX polling endpoint — returns the serial's table + OOB summary/buzzer."""
    ctx = _dashboard_ctx(db)
    signals = _latest_signal_status(db, serial_id=serial_id)
    range_state = ctx["range_state"]
    return templates.TemplateResponse(request, "partials/dashboard_fragment.html", {
        **ctx,
        "signals": signals,
        "buzzer_active": _buzzer_active(signals, range_state),
        "serial_id": serial_id,
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

    # Copy freq/band data from the latest existing entry for this signal
    latest_query = db.query(SignalLog).filter(
        SignalLog.signal_name == signal_name, SignalLog.is_deleted == False,
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
                    SignalLog.signal_name == sib.name, SignalLog.is_deleted == False,
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
                        source=sib_latest.source,
                        antenna=sib_latest.antenna,
                        notes=f"Auto-downed: {signal_name} came Up (group: {sig_reg.exclusivity_group})",
                        entry_type="Automatic",
                        updated_by_id=current_user.id,
                        serial_id=serial_id,
                    ))

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
        source=source or (latest.source if latest else None),
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
    serial_id = body.serial_id

    for upd in body.updates:
        latest_q = db.query(SignalLog).filter(
            SignalLog.signal_name == upd.signal_name,
            SignalLog.is_deleted == False,
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
                        SignalLog.signal_name == sib.name, SignalLog.is_deleted == False,
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
                            source=sib_latest.source, antenna=sib_latest.antenna,
                            notes=f"Auto-downed: {upd.signal_name} came Up (group: {sig_reg.exclusivity_group})",
                            entry_type="Automatic", updated_by_id=current_user.id, serial_id=serial_id,
                        ))

        new_entry = SignalLog(
            operator_id=current_user.id, range_state=range_state,
            signal_name=upd.signal_name, signal_status=upd.signal_status,
            tx_if=latest.tx_if if latest else None,
            tx_rf=latest.tx_rf if latest else None,
            rx_rf=latest.rx_rf if latest else None,
            rx_if=latest.rx_if if latest else None,
            freq_unit=latest.freq_unit if latest else "MHz",
            band=latest.band if latest else None,
            modulation=latest.modulation if latest else None,
            symbol_rate=latest.symbol_rate if latest else None,
            fec=latest.fec if latest else None,
            power=upd.power if upd.power is not None else (latest.power if latest else None),
            power_unit=upd.power_unit,
            eb_no=latest.eb_no if latest else None,
            source=latest.source if latest else None,
            antenna=latest.antenna if latest else None,
            entry_type="Dashboard", updated_by_id=current_user.id,
            serial_id=serial_id if serial_id is not None else (latest.serial_id if latest else None),
            warning_flags=warning_flags_for(
                db, upd.signal_name,
                upd.power if upd.power is not None else (latest.power if latest else None),
                upd.power_unit,
                tx_rf=latest.tx_rf if latest else None,
                rx_rf=latest.rx_rf if latest else None,
                freq_unit=latest.freq_unit if latest else "MHz",
                band=latest.band if latest else None,
            ),
        )
        db.add(new_entry)

    db.flush()
    for upd in body.updates:
        db.add(AuditLog(
            user_id=current_user.id, action_type="DASHBOARD_UPDATE",
            entity_type="SignalLog",
            new_value=f"{upd.signal_name}: {upd.signal_status}",
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
