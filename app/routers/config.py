from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state, is_testing_state
from app.config import AUDIT_ARCHIVE_DIR, DATABASE_URL, SERIAL_ARCHIVE_DIR
from app.file_security import permission_status
from app.models import AuditLog, ModulationType, FecType, SignalSource, AntennaType, Signal, FrequencyTemplate, User, DutyRole, RFDevice, ActivityType, Activity, CallType
from app.settings import (
    AUDIT_LIVE_RECORD_LIMIT_KEY,
    MAX_AUDIT_LIVE_RECORD_LIMIT,
    MIN_AUDIT_LIVE_RECORD_LIMIT,
    TIME_ZONES,
    clamp_audit_live_record_limit,
    get_audit_live_record_limit,
    get_local_timezone,
    set_setting,
    LOCAL_TIMEZONE_KEY,
    CBM_EBNO_LOG_THRESHOLD_KEY,
    DEFAULT_CBM_EBNO_LOG_THRESHOLD,
    get_cbm_ebno_log_threshold,
    CBM_EBNO_LOG_ENABLED_KEY,
    DEFAULT_CBM_EBNO_LOG_ENABLED,
    get_cbm_ebno_log_enabled,
    SANDBOX_HARDWARE_SYNC_PAUSED_KEY,
    get_sandbox_hardware_sync_paused,
)

router = APIRouter(prefix="/config")
from app.templating import templates


def _sqlite_db_path() -> Path | None:
    if DATABASE_URL.startswith("sqlite:///"):
        return Path(DATABASE_URL.removeprefix("sqlite:///"))
    return None


def _archive_files(path: Path, kind: str) -> list[dict]:
    if not path.exists():
        return []
    files = []
    for file in sorted(path.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
        stat = file.stat()
        files.append({
            "name": file.name,
            "kind": kind,
            "size_kb": max(1, round(stat.st_size / 1024)),
            "modified": stat.st_mtime,
        })
    return files


def _archive_path(kind: str, filename: str) -> Path:
    base = AUDIT_ARCHIVE_DIR if kind == "audit" else SERIAL_ARCHIVE_DIR if kind == "serial" else None
    if base is None or "/" in filename or "\\" in filename or not filename.endswith(".xlsx"):
        raise HTTPException(status_code=404)
    path = base / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    return path


@router.get("", response_class=HTMLResponse)
async def config_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    mod_types = db.query(ModulationType).order_by(ModulationType.display_order, ModulationType.name).all()
    fec_types = db.query(FecType).order_by(FecType.display_order, FecType.name).all()
    signal_sources = db.query(SignalSource).order_by(SignalSource.display_order, SignalSource.name).all()
    signal_source_names = {s.name for s in signal_sources}
    cbm_source_devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.is_testing == is_testing_state(db),
        )
        .order_by(RFDevice.name)
        .all()
    )
    cbm_source_devices = [d for d in cbm_source_devices if d.name not in signal_source_names]
    antenna_types = db.query(AntennaType).order_by(AntennaType.display_order, AntennaType.name).all()
    signals = db.query(Signal).order_by(Signal.name).all()
    groups = sorted(set(s.exclusivity_group for s in signals if s.exclusivity_group))
    freq_templates = db.query(FrequencyTemplate).order_by(FrequencyTemplate.name).all()
    duty_roles = db.query(DutyRole).order_by(DutyRole.display_order, DutyRole.name).all()
    activity_types = db.query(ActivityType).order_by(ActivityType.display_order, ActivityType.name).all()
    call_types = db.query(CallType).order_by(CallType.display_order, CallType.name).all()
    db_path = _sqlite_db_path()
    db_permissions = permission_status(db_path) if db_path else {"mode": "n/a", "secure": None, "note": "Non-SQLite database."}
    audit_dir_permissions = permission_status(AUDIT_ARCHIVE_DIR, directory=True)
    serial_dir_permissions = permission_status(SERIAL_ARCHIVE_DIR, directory=True)
    archive_files = _archive_files(AUDIT_ARCHIVE_DIR, "audit") + _archive_files(SERIAL_ARCHIVE_DIR, "serial")
    return templates.TemplateResponse(request, "config.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "mod_types": mod_types,
        "fec_types": fec_types,
        "signal_sources": signal_sources,
        "cbm_source_devices": cbm_source_devices,
        "antenna_types": antenna_types,
        "signals": signals,
        "groups": groups,
        "freq_templates": freq_templates,
        "duty_roles": duty_roles,
        "activity_types": activity_types,
        "call_types": call_types,
        "bands": ["C", "X", "Ku", "Ka", "Other"],
        "time_zones": TIME_ZONES,
        "local_timezone": get_local_timezone(db),
        "audit_live_record_limit": get_audit_live_record_limit(db),
        "audit_live_record_min": MIN_AUDIT_LIVE_RECORD_LIMIT,
        "audit_live_record_max": MAX_AUDIT_LIVE_RECORD_LIMIT,
        "cbm_ebno_log_threshold": get_cbm_ebno_log_threshold(db),
        "cbm_ebno_log_enabled": get_cbm_ebno_log_enabled(db),
        "sandbox_hardware_sync_paused": get_sandbox_hardware_sync_paused(db),
        "system_health": {
            "database": str(db_path) if db_path else DATABASE_URL,
            "database_size_mb": round(db_path.stat().st_size / (1024 * 1024), 2) if db_path and db_path.exists() else None,
            "live_audit_count": db.query(AuditLog).filter(AuditLog.is_testing == False).count(),
            "testing_audit_count": db.query(AuditLog).filter(AuditLog.is_testing == True).count(),
            "audit_archive_dir": str(AUDIT_ARCHIVE_DIR),
            "serial_archive_dir": str(SERIAL_ARCHIVE_DIR),
            "audit_archive_count": len(_archive_files(AUDIT_ARCHIVE_DIR, "audit")),
            "serial_archive_count": len(_archive_files(SERIAL_ARCHIVE_DIR, "serial")),
            "database_permissions": db_permissions,
            "audit_archive_permissions": audit_dir_permissions,
            "serial_archive_permissions": serial_dir_permissions,
        },
        "archive_files": archive_files,
        "page": "config",
        "toast": request.query_params.get("toast", ""),
    })


@router.get("/archives/{kind}/{filename}")
async def archive_download(
    kind: str,
    filename: str,
    current_user: User = Depends(require_supervisor),
):
    path = _archive_path(kind, filename)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


# ── Desktop shortcuts ─────────────────────────────────────────────────────────
# Generate a double-clickable launcher that opens this dashboard, built against
# the host/port the admin is currently using so it works on the local network.
# The logo icon on the launcher itself is best delivered by "Install app" (PWA);
# these files guarantee easy one-click access on any Windows or Ubuntu desktop.

@router.get("/shortcut/windows")
async def shortcut_windows(
    request: Request,
    current_user: User = Depends(require_supervisor),
):
    base = str(request.base_url)  # e.g. http://10.0.0.5:8000/
    content = (
        "[InternetShortcut]\r\n"
        f"URL={base}\r\n"
        "IconIndex=0\r\n"
        f"IconFile={base}static/img/range-icon.ico\r\n"
    )
    return Response(
        content=content,
        media_type="application/x-mswinurl",
        headers={"Content-Disposition": 'attachment; filename="Range Dashboard.url"'},
    )


@router.get("/shortcut/linux")
async def shortcut_linux(
    request: Request,
    current_user: User = Depends(require_supervisor),
):
    base = str(request.base_url)
    content = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Range Dashboard\n"
        "Comment=SEW Range Dashboard\n"
        f"Exec=xdg-open {base}\n"
        "Icon=web-browser\n"
        "Terminal=false\n"
        "Categories=Network;\n"
        "StartupNotify=true\n"
    )
    return Response(
        content=content,
        media_type="application/x-desktop",
        headers={"Content-Disposition": 'attachment; filename="Range Dashboard.desktop"'},
    )


# ── System settings ──────────────────────────────────────────────────────────

@router.post("/system")
async def system_settings_save(
    local_timezone: str = Form("UTC"),
    audit_live_record_limit: str = Form("1000"),
    cbm_ebno_log_threshold: str = Form("3"),
    cbm_ebno_log_enabled: str = Form(""),
    sandbox_hardware_sync_paused: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    if local_timezone in TIME_ZONES:
        set_setting(db, LOCAL_TIMEZONE_KEY, local_timezone)
    set_setting(db, AUDIT_LIVE_RECORD_LIMIT_KEY, str(clamp_audit_live_record_limit(audit_live_record_limit)))
    try:
        ebno_thr = max(0.0, float(cbm_ebno_log_threshold))
    except (TypeError, ValueError):
        ebno_thr = DEFAULT_CBM_EBNO_LOG_THRESHOLD
    set_setting(db, CBM_EBNO_LOG_THRESHOLD_KEY, f"{ebno_thr:g}")
    set_setting(db, CBM_EBNO_LOG_ENABLED_KEY, "1" if cbm_ebno_log_enabled == "1" else "0")
    set_setting(db, SANDBOX_HARDWARE_SYNC_PAUSED_KEY, "1" if sandbox_hardware_sync_paused == "1" else "0")
    db.commit()
    return RedirectResponse("/config?toast=System+settings+saved", status_code=302)


@router.post("/sandbox-hardware-sync")
async def sandbox_hardware_sync_toggle(
    request: Request,
    paused: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "observer":
        raise HTTPException(status_code=403, detail="Observer accounts cannot change sandbox sync settings")
    set_setting(db, SANDBOX_HARDWARE_SYNC_PAUSED_KEY, "1" if paused == "1" else "0")
    db.commit()
    dest = request.headers.get("referer") or "/"
    if not dest.startswith(str(request.base_url)) and not dest.startswith("/"):
        dest = "/"
    label = "paused" if paused == "1" else "enabled"
    sep = "&" if "?" in dest else "?"
    return RedirectResponse(f"{dest}{sep}toast=Sandbox+hardware+sync+{label}", status_code=302)


# ── Modulation types ────────────────────────────────────────────────────────────

@router.post("/modulation/add")
async def mod_add(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip().upper()
    if name and not db.query(ModulationType).filter(ModulationType.name == name).first():
        max_order = db.query(ModulationType).count()
        db.add(ModulationType(name=name, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Modulation+type+added", status_code=302)


@router.post("/modulation/{mod_id}/toggle")
async def mod_toggle(
    mod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    mod = db.query(ModulationType).filter(ModulationType.id == mod_id).first()
    if mod:
        mod.is_active = not mod.is_active
        db.commit()
    return RedirectResponse("/config", status_code=302)


@router.post("/modulation/{mod_id}/delete")
async def mod_delete(
    mod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    mod = db.query(ModulationType).filter(ModulationType.id == mod_id).first()
    if mod:
        db.delete(mod)
        db.commit()
    return RedirectResponse("/config?toast=Modulation+type+deleted", status_code=302)


@router.post("/modulation/reorder")
async def mod_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            mod_id = int(key.split("_")[1])
            mod = db.query(ModulationType).filter(ModulationType.id == mod_id).first()
            if mod:
                try:
                    mod.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved", status_code=302)


@router.post("/fec/reorder")
async def fec_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            fec_id = int(key.split("_")[1])
            fec = db.query(FecType).filter(FecType.id == fec_id).first()
            if fec:
                try:
                    fec.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved", status_code=302)


@router.post("/sources/reorder")
async def source_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            src_id = int(key.split("_")[1])
            src = db.query(SignalSource).filter(SignalSource.id == src_id).first()
            if src:
                try:
                    src.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved", status_code=302)


@router.post("/antennas/reorder")
async def antenna_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            ant_id = int(key.split("_")[1])
            ant = db.query(AntennaType).filter(AntennaType.id == ant_id).first()
            if ant:
                try:
                    ant.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved", status_code=302)


# ── Duty roles (visual position tags) ───────────────────────────────────────────

@router.post("/duty-roles/add")
async def duty_role_add(
    name: str = Form(...),
    color: str = Form("#0d6efd"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    color = (color.strip() or "#0d6efd")
    if name and not db.query(DutyRole).filter(DutyRole.name == name).first():
        max_order = db.query(DutyRole).count()
        db.add(DutyRole(name=name, color=color, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Duty+role+added#cfg-roles", status_code=302)


@router.post("/duty-roles/{role_id}/update")
async def duty_role_update(
    role_id: int,
    name: str = Form(...),
    color: str = Form("#0d6efd"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    role = db.query(DutyRole).filter(DutyRole.id == role_id).first()
    if role:
        old_name = role.name
        new_name = name.strip() or role.name
        role.name = new_name
        role.color = color.strip() or role.color
        # Keep the denormalised tag on any user currently wearing this role in sync.
        for u in db.query(User).filter(User.duty_role == old_name).all():
            u.duty_role = new_name
            u.duty_role_color = role.color
        db.commit()
    return RedirectResponse("/config?toast=Duty+role+updated#cfg-roles", status_code=302)


@router.post("/duty-roles/{role_id}/toggle")
async def duty_role_toggle(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    role = db.query(DutyRole).filter(DutyRole.id == role_id).first()
    if role:
        role.is_active = not role.is_active
        db.commit()
    return RedirectResponse("/config#cfg-roles", status_code=302)


@router.post("/duty-roles/{role_id}/delete")
async def duty_role_delete(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    role = db.query(DutyRole).filter(DutyRole.id == role_id).first()
    if role:
        # Clear the tag from anyone currently wearing it.
        for u in db.query(User).filter(User.duty_role == role.name).all():
            u.duty_role = None
            u.duty_role_color = None
        db.delete(role)
        db.commit()
    return RedirectResponse("/config?toast=Duty+role+deleted#cfg-roles", status_code=302)


@router.post("/duty-roles/reorder")
async def duty_role_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            role_id = int(key.split("_")[1])
            role = db.query(DutyRole).filter(DutyRole.id == role_id).first()
            if role:
                try:
                    role.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved#cfg-roles", status_code=302)


# ── Signal registry ─────────────────────────────────────────────────────────────

@router.post("/signals/add")
async def signal_add(
    name: str = Form(...),
    description: str = Form(""),
    exclusivity_group: str = Form(""),
    max_power_dbm: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(Signal).filter(Signal.name == name).first():
        db.add(Signal(
            name=name,
            description=description.strip() or None,
            exclusivity_group=exclusivity_group.strip() or None,
            max_power_dbm=max_power_dbm,
        ))
        db.commit()
    return RedirectResponse("/config?toast=Signal+added+to+registry", status_code=302)


@router.post("/signals/{sig_id}/update")
async def signal_update(
    sig_id: int,
    description: str = Form(""),
    exclusivity_group: str = Form(""),
    max_power_dbm: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    sig = db.query(Signal).filter(Signal.id == sig_id).first()
    if sig:
        sig.description = description.strip() or None
        sig.exclusivity_group = exclusivity_group.strip() or None
        sig.max_power_dbm = max_power_dbm
        db.commit()
    return RedirectResponse("/config?toast=Signal+updated", status_code=302)


@router.post("/signals/{sig_id}/toggle")
async def signal_toggle(
    sig_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    sig = db.query(Signal).filter(Signal.id == sig_id).first()
    if sig:
        sig.is_active = not sig.is_active
        db.commit()
    return RedirectResponse("/config", status_code=302)


@router.post("/signals/{sig_id}/delete")
async def signal_delete(
    sig_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    sig = db.query(Signal).filter(Signal.id == sig_id).first()
    if sig:
        db.delete(sig)
        db.commit()
    return RedirectResponse("/config?toast=Signal+removed+from+registry", status_code=302)


# ── FEC types ────────────────────────────────────────────────────────────────────

@router.post("/fec/add")
async def fec_add(
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(FecType).filter(FecType.name == name).first():
        max_order = db.query(FecType).count()
        db.add(FecType(name=name, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=FEC+type+added", status_code=302)


@router.post("/fec/{fec_id}/toggle")
async def fec_toggle(
    fec_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    fec = db.query(FecType).filter(FecType.id == fec_id).first()
    if fec:
        fec.is_active = not fec.is_active
        db.commit()
    return RedirectResponse("/config", status_code=302)


@router.post("/fec/{fec_id}/delete")
async def fec_delete(
    fec_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    fec = db.query(FecType).filter(FecType.id == fec_id).first()
    if fec:
        db.delete(fec)
        db.commit()
    return RedirectResponse("/config?toast=FEC+type+deleted", status_code=302)


# ── Signal sources ────────────────────────────────────────────────────────────────

@router.post("/sources/add")
async def source_add(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(SignalSource).filter(SignalSource.name == name).first():
        max_order = db.query(SignalSource).count()
        db.add(SignalSource(name=name, description=description.strip() or None, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Signal+source+added", status_code=302)


@router.post("/sources/{src_id}/toggle")
async def source_toggle(
    src_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    src = db.query(SignalSource).filter(SignalSource.id == src_id).first()
    if src:
        src.is_active = not src.is_active
        db.commit()
    return RedirectResponse("/config", status_code=302)


@router.post("/sources/{src_id}/delete")
async def source_delete(
    src_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    src = db.query(SignalSource).filter(SignalSource.id == src_id).first()
    if src:
        db.delete(src)
        db.commit()
    return RedirectResponse("/config?toast=Signal+source+deleted", status_code=302)


# ── Antenna types ─────────────────────────────────────────────────────────────────

@router.post("/antennas/add")
async def antenna_add(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(AntennaType).filter(AntennaType.name == name).first():
        max_order = db.query(AntennaType).count()
        db.add(AntennaType(name=name, description=description.strip() or None, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Antenna+added", status_code=302)


@router.post("/antennas/{ant_id}/toggle")
async def antenna_toggle(
    ant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    ant = db.query(AntennaType).filter(AntennaType.id == ant_id).first()
    if ant:
        ant.is_active = not ant.is_active
        db.commit()
    return RedirectResponse("/config", status_code=302)


@router.post("/antennas/{ant_id}/delete")
async def antenna_delete(
    ant_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    ant = db.query(AntennaType).filter(AntennaType.id == ant_id).first()
    if ant:
        db.delete(ant)
        db.commit()
    return RedirectResponse("/config?toast=Antenna+deleted", status_code=302)


# ── Frequency templates ───────────────────────────────────────────────────────────

@router.post("/freq-templates/add")
async def freq_template_add(
    request: Request,
    name: str = Form(...),
    band: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    default_unit: str = Form("MHz"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(FrequencyTemplate).filter(FrequencyTemplate.name == name).first():
        db.add(FrequencyTemplate(
            name=name,
            band=band or None,
            tx_lo=tx_lo,
            rx_lo=rx_lo,
            ttf=ttf,
            ttf_direction=ttf_direction or "+",
            default_unit=default_unit or "MHz",
            notes=notes.strip() or None,
            created_by_id=current_user.id,
        ))
        db.commit()
    return RedirectResponse("/config?toast=Frequency+template+added", status_code=302)


@router.post("/freq-templates/{tmpl_id}/update")
async def freq_template_update(
    tmpl_id: int,
    request: Request,
    name: str = Form(...),
    band: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    default_unit: str = Form("MHz"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    tmpl = db.query(FrequencyTemplate).filter(FrequencyTemplate.id == tmpl_id).first()
    if tmpl:
        tmpl.name = name.strip() or tmpl.name
        tmpl.band = band or None
        tmpl.tx_lo = tx_lo
        tmpl.rx_lo = rx_lo
        tmpl.ttf = ttf
        tmpl.ttf_direction = ttf_direction or "+"
        tmpl.default_unit = default_unit or "MHz"
        tmpl.notes = notes.strip() or None
        db.commit()
    return RedirectResponse("/config?toast=Template+updated", status_code=302)


@router.post("/freq-templates/{tmpl_id}/delete")
async def freq_template_delete(
    tmpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    tmpl = db.query(FrequencyTemplate).filter(FrequencyTemplate.id == tmpl_id).first()
    if tmpl:
        db.delete(tmpl)
        db.commit()
    return RedirectResponse("/config?toast=Template+deleted", status_code=302)


# ── Activity types ───────────────────────────────────────────────────────────────

@router.post("/activity-type/add")
async def activity_type_add(
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(ActivityType).filter(ActivityType.name == name).first():
        max_order = db.query(ActivityType).count()
        db.add(ActivityType(name=name, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Activity+type+added#cfg-activity-types", status_code=302)


@router.post("/activity-type/{type_id}/edit")
async def activity_type_edit(
    type_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    at = db.query(ActivityType).filter(ActivityType.id == type_id).first()
    if at:
        at.name = name.strip() or at.name
        db.commit()
    return RedirectResponse("/config?toast=Activity+type+updated#cfg-activity-types", status_code=302)


@router.post("/activity-type/{type_id}/toggle")
async def activity_type_toggle(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    at = db.query(ActivityType).filter(ActivityType.id == type_id).first()
    if at:
        at.is_active = not at.is_active
        db.commit()
    return RedirectResponse("/config#cfg-activity-types", status_code=302)


@router.post("/activity-type/{type_id}/delete")
async def activity_type_delete(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    at = db.query(ActivityType).filter(ActivityType.id == type_id).first()
    if at:
        in_use = db.query(Activity).filter(Activity.activity_type_id == type_id).first()
        if not in_use:
            db.delete(at)
            db.commit()
    return RedirectResponse("/config?toast=Activity+type+deleted#cfg-activity-types", status_code=302)


@router.post("/activity-types/order")
async def activity_type_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            type_id = int(key.split("_")[1])
            at = db.query(ActivityType).filter(ActivityType.id == type_id).first()
            if at:
                try:
                    at.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved#cfg-activity-types", status_code=302)


# ── Effects (admin-configurable list; stored as CallType for back-compat) ──────

@router.post("/call-type/add")
async def call_type_add(
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name and not db.query(CallType).filter(CallType.name == name).first():
        max_order = db.query(CallType).count()
        db.add(CallType(name=name, display_order=max_order))
        db.commit()
    return RedirectResponse("/config?toast=Call+type+added#cfg-call-types", status_code=302)


@router.post("/call-type/{type_id}/edit")
async def call_type_edit(
    type_id: int,
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    ct = db.query(CallType).filter(CallType.id == type_id).first()
    if ct:
        ct.name = name.strip() or ct.name
        db.commit()
    return RedirectResponse("/config?toast=Call+type+updated#cfg-call-types", status_code=302)


@router.post("/call-type/{type_id}/toggle")
async def call_type_toggle(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    ct = db.query(CallType).filter(CallType.id == type_id).first()
    if ct:
        ct.is_active = not ct.is_active
        db.commit()
    return RedirectResponse("/config#cfg-call-types", status_code=302)


@router.post("/call-type/{type_id}/delete")
async def call_type_delete(
    type_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    ct = db.query(CallType).filter(CallType.id == type_id).first()
    if ct:
        db.delete(ct)
        db.commit()
    return RedirectResponse("/config?toast=Call+type+deleted#cfg-call-types", status_code=302)


@router.post("/call-types/order")
async def call_type_reorder(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    form = await request.form()
    for key, val in form.items():
        if key.startswith("order_"):
            type_id = int(key.split("_")[1])
            ct = db.query(CallType).filter(CallType.id == type_id).first()
            if ct:
                try:
                    ct.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse("/config?toast=Order+saved#cfg-call-types", status_code=302)
