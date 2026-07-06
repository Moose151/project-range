import asyncio
import re
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state, require_supervisor
from app.cbm import CBMError, poll_cbm_ssh
from app.cbm_sync import sync_active_cbms
import json

from app.snmp import (
    SNMPError, poll_genus_matrix, snmp_diagnostic_walk, ENTERPRISE_ROOT,
    effective_alarm_from_modules,
)
from app.snmp_sync import (
    poll_active_snmp_devices, poll_snmp_device, ignored_module_idxs, _device_credentials,
)
from app.crypto import decrypt_secret, encrypt_secret
from app.models import RFDevice, DevicePort, DeviceLink, AuditLog, User
from app.templating import templates

router = APIRouter(prefix="/devices")

DEVICE_TYPES = [
    ("modem",              "Modem"),
    ("splitter",           "Splitter"),
    ("combiner",           "Combiner"),
    ("switch",             "RF Switch / Matrix"),
    ("ip_switch",          "IP Switch"),
    ("spectrum_analyser",  "Spectrum Analyser"),
    ("signal_generator",   "Signal Generator"),
    ("antenna",            "Antenna"),
    ("power_meter",        "Power Meter"),
    ("reference_10mhz",   "10MHz Reference"),
    ("sync_server",        "Sync Server"),
    ("dc_injector",        "DC Injector"),
    ("other",              "Other"),
]
ROUTING_TYPES = {"splitter", "combiner", "switch"}
SNMP_MONITOR_TYPES = {"splitter", "combiner"}


def _normalise_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _is_ebem_device(device_type: str, name: str | None, device_model: str | None) -> bool:
    """Only CBM/EBEM modem devices should expose/use EBEM read-only sync."""
    if device_type != "modem":
        return False
    combined = _normalise_name(f"{name or ''} {device_model or ''}")
    return "cbm" in combined or "ebem" in combined


def _device_port_counts(device_type: str, num_inputs: int, num_outputs: int) -> tuple[int, int]:
    if device_type in ROUTING_TYPES:
        return max(0, min(num_inputs, 128)), max(0, min(num_outputs, 128))
    # Non-matrix devices do not use the routing matrix UI; keep a simple shape.
    return 1, 1

LINK_TYPES = [
    ("rf",    "RF (coax/waveguide)"),
    ("ip",    "IP / Ethernet"),
    ("clock", "Clock / Timing (10MHz / 1PPS)"),
    ("power", "DC Power"),
]


# ── Reachability check ────────────────────────────────────────────────────────

async def _reachable(host: str | None, port: int | None, timeout: float = 1.0) -> str:
    """Return 'up' / 'down' / 'unknown' from a non-blocking TCP connect."""
    if not host or not port:
        return "unknown"
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return "up"
    except Exception:
        return "down"


@router.get("/status")
async def devices_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """JSON map of device id -> reachability, checked concurrently."""
    testing = is_testing_state(db)
    devices = db.query(RFDevice).filter(RFDevice.is_active == True, RFDevice.is_testing == testing).all()
    results = await asyncio.gather(*(_reachable(d.host, d.check_port) for d in devices))
    return JSONResponse({str(d.id): status for d, status in zip(devices, results)})


# ── Registry ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def devices_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    devices = db.query(RFDevice).filter(RFDevice.is_testing == testing).order_by(RFDevice.device_type, RFDevice.name).all()
    return templates.TemplateResponse(request, "devices.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "devices": devices,
        "device_types": DEVICE_TYPES,
        "routing_types": ROUTING_TYPES,
        "snmp_monitor_types": SNMP_MONITOR_TYPES,
        "ebem_device_ids": {d.id for d in devices if _is_ebem_device(d.device_type, d.name, d.device_model)},
        "toast": request.query_params.get("toast", ""),
        "page": "devices",
        "page_name": "devices",
    })


@router.post("/cbm/sync-active")
async def devices_cbm_sync_active(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    result = sync_active_cbms(db, current_user.id)
    message = f"CBM sync complete: {result.updated} updated, {result.skipped} skipped"
    if result.errors:
        message += f", {len(result.errors)} issue(s)"
    return RedirectResponse(f"/devices?toast={quote_plus(message)}", status_code=302)


@router.post("/snmp/poll-active")
async def devices_snmp_poll_active(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    result = poll_active_snmp_devices(db, current_user.id)
    message = f"SNMP poll complete: {result.polled} polled, {result.updated} observed state changed"
    if result.errors:
        message += f", {len(result.errors)} issue(s): {result.errors[0]}"
    return RedirectResponse(f"/devices?toast={quote_plus(message)}", status_code=302)


@router.post("/new")
async def device_create(
    name: str = Form(...),
    device_model: str = Form(""),
    device_type: str = Form("other"),
    host: str = Form(""),
    check_port: str = Form(""),
    has_web_gui: str = Form(""),
    cbm_sync_enabled: str = Form(""),
    cbm_username: str = Form(""),
    cbm_password: str = Form(""),
    snmp_enabled: str = Form(""),
    snmp_version: str = Form("2c"),
    snmp_port: str = Form("161"),
    snmp_community: str = Form(""),
    snmp_v3_user: str = Form(""),
    snmp_v3_auth: str = Form(""),
    snmp_v3_priv: str = Form(""),
    location: str = Form(""),
    num_inputs: int = Form(16),
    num_outputs: int = Form(16),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name:
        clean_type = device_type if device_type in dict(DEVICE_TYPES) else "other"
        clean_model = device_model.strip() or None
        is_ebem = _is_ebem_device(clean_type, name, clean_model)
        snmp_allowed = clean_type in SNMP_MONITOR_TYPES
        clean_inputs, clean_outputs = _device_port_counts(clean_type, num_inputs, num_outputs)
        dev = RFDevice(
            name=name,
            device_model=clean_model,
            device_type=clean_type,
            host=host.strip() or None,
            check_port=int(check_port) if check_port.strip().isdigit() else None,
            has_web_gui=bool(has_web_gui),
            cbm_sync_enabled=bool(cbm_sync_enabled) if is_ebem else False,
            cbm_username=(cbm_username.strip() or None) if is_ebem else None,
            cbm_password_encrypted=encrypt_secret(cbm_password.strip()) if is_ebem and cbm_password.strip() else None,
            snmp_enabled=bool(snmp_enabled) if snmp_allowed else False,
            snmp_version="3" if snmp_version == "3" else "2c",
            snmp_port=int(snmp_port) if snmp_port.strip().isdigit() else 161,
            snmp_community_encrypted=encrypt_secret(snmp_community.strip()) if snmp_allowed and snmp_community.strip() else None,
            snmp_v3_user=(snmp_v3_user.strip() or None) if snmp_allowed else None,
            snmp_v3_auth_encrypted=encrypt_secret(snmp_v3_auth.strip()) if snmp_allowed and snmp_v3_auth.strip() else None,
            snmp_v3_priv_encrypted=encrypt_secret(snmp_v3_priv.strip()) if snmp_allowed and snmp_v3_priv.strip() else None,
            location=location.strip() or None,
            num_inputs=clean_inputs,
            num_outputs=clean_outputs,
            notes=notes.strip() or None,
            is_testing=is_testing_state(db),
        )
        db.add(dev)
        db.flush()
        db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_CREATE",
                        entity_type="RFDevice", entity_id=dev.id, new_value=dev.name))
        db.commit()
    return RedirectResponse("/devices?toast=Device+added", status_code=302)


@router.post("/{dev_id}/update")
async def device_update(
    dev_id: int,
    name: str = Form(...),
    device_model: str = Form(""),
    device_type: str = Form("other"),
    host: str = Form(""),
    check_port: str = Form(""),
    has_web_gui: str = Form(""),
    cbm_sync_enabled: str = Form(""),
    cbm_username: str = Form(""),
    cbm_password: str = Form(""),
    clear_cbm_password: str = Form(""),
    snmp_enabled: str = Form(""),
    snmp_version: str = Form("2c"),
    snmp_port: str = Form("161"),
    snmp_community: str = Form(""),
    clear_snmp_community: str = Form(""),
    snmp_v3_user: str = Form(""),
    snmp_v3_auth: str = Form(""),
    snmp_v3_priv: str = Form(""),
    clear_snmp_v3: str = Form(""),
    location: str = Form(""),
    num_inputs: int = Form(16),
    num_outputs: int = Form(16),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if dev:
        dev.name = name.strip() or dev.name
        dev.device_model = device_model.strip() or None
        dev.device_type = device_type if device_type in dict(DEVICE_TYPES) else dev.device_type
        is_ebem = _is_ebem_device(dev.device_type, dev.name, dev.device_model)
        snmp_allowed = dev.device_type in SNMP_MONITOR_TYPES
        dev.host = host.strip() or None
        dev.check_port = int(check_port) if check_port.strip().isdigit() else None
        dev.has_web_gui = bool(has_web_gui)
        dev.cbm_sync_enabled = bool(cbm_sync_enabled) if is_ebem else False
        dev.cbm_username = (cbm_username.strip() or None) if is_ebem else None
        if not is_ebem:
            dev.cbm_password_encrypted = None
        elif clear_cbm_password:
            dev.cbm_password_encrypted = None
        elif cbm_password.strip():
            dev.cbm_password_encrypted = encrypt_secret(cbm_password.strip())
        # SNMP monitoring config (currently splitter/combiner matrices only).
        dev.snmp_enabled = bool(snmp_enabled) if snmp_allowed else False
        dev.snmp_version = "3" if snmp_version == "3" else "2c"
        dev.snmp_port = int(snmp_port) if snmp_port.strip().isdigit() else 161
        dev.snmp_v3_user = (snmp_v3_user.strip() or None) if snmp_allowed else None
        if not snmp_allowed:
            dev.snmp_community_encrypted = None
            dev.snmp_v3_auth_encrypted = None
            dev.snmp_v3_priv_encrypted = None
        elif clear_snmp_community:
            dev.snmp_community_encrypted = None
        elif snmp_community.strip():
            dev.snmp_community_encrypted = encrypt_secret(snmp_community.strip())
        if not snmp_allowed:
            pass
        elif clear_snmp_v3:
            dev.snmp_v3_auth_encrypted = None
            dev.snmp_v3_priv_encrypted = None
        else:
            if snmp_v3_auth.strip():
                dev.snmp_v3_auth_encrypted = encrypt_secret(snmp_v3_auth.strip())
            if snmp_v3_priv.strip():
                dev.snmp_v3_priv_encrypted = encrypt_secret(snmp_v3_priv.strip())
        dev.location = location.strip() or None
        dev.num_inputs, dev.num_outputs = _device_port_counts(dev.device_type, num_inputs, num_outputs)
        dev.notes = notes.strip() or None
        db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_UPDATE",
                        entity_type="RFDevice", entity_id=dev.id, new_value=dev.name))
        db.commit()
    return RedirectResponse("/devices?toast=Device+updated", status_code=302)


@router.post("/{dev_id}/cbm/test")
async def device_cbm_test(
    dev_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev or not _is_ebem_device(dev.device_type, dev.name, dev.device_model):
        return RedirectResponse("/devices?toast=CBM+device+not+found", status_code=302)
    if not dev.host or not dev.cbm_username or not dev.cbm_password_encrypted:
        dev.cbm_last_sync_status = "missing_credentials"
        dev.cbm_last_sync_error = "Host, username, and password are required."
        db.commit()
        return RedirectResponse("/devices?toast=CBM+credentials+required", status_code=302)

    password = decrypt_secret(dev.cbm_password_encrypted)
    if not password:
        dev.cbm_last_sync_status = "credential_error"
        dev.cbm_last_sync_error = "Stored password could not be decrypted. Check SECRET_KEY."
        db.commit()
        return RedirectResponse("/devices?toast=Stored+CBM+password+could+not+be+decrypted", status_code=302)

    try:
        snapshot = poll_cbm_ssh(dev.host, dev.cbm_username, password)
        summary = snapshot.summary
        dev.cbm_last_sync_at = datetime.utcnow()
        dev.cbm_last_sync_status = "ok"
        dev.cbm_last_sync_error = None
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="CBM_TEST",
            entity_type="RFDevice",
            entity_id=dev.id,
            new_value=f"{dev.name}: {summary.get('modem_status') or 'poll ok'}",
        ))
        db.commit()
        return RedirectResponse(
            f"/devices?toast={quote_plus('CBM poll OK: ' + dev.name)}",
            status_code=302,
        )
    except CBMError as exc:
        dev.cbm_last_sync_at = datetime.utcnow()
        dev.cbm_last_sync_status = "error"
        dev.cbm_last_sync_error = str(exc)[:1000]
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="CBM_TEST_FAILED",
            entity_type="RFDevice",
            entity_id=dev.id,
            new_value=f"{dev.name}: {dev.cbm_last_sync_error}",
        ))
        db.commit()
        return RedirectResponse(
            f"/devices?toast={quote_plus('CBM poll failed: ' + dev.name)}",
            status_code=302,
        )


@router.post("/{dev_id}/snmp/test")
async def device_snmp_test(
    dev_id: int,
    next: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    # Return to the page the poll was triggered from (routing page or devices list).
    dest = next if next.startswith("/devices") else "/devices"
    sep = "&" if "?" in dest else "?"
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev or dev.device_type not in SNMP_MONITOR_TYPES:
        return RedirectResponse("/devices?toast=SNMP+device+not+found", status_code=302)
    _ensure_ports(db, dev)
    try:
        snapshot, changed = poll_snmp_device(db, dev)
        routed = snapshot.summary["outputs_routed"] if snapshot else 0
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="SNMP_TEST",
            entity_type="RFDevice",
            entity_id=dev.id,
            new_value=f"{dev.name}: alarm={dev.snmp_system_alarm or 'n/a'}, {routed} outputs routed",
        ))
        db.commit()
        return RedirectResponse(f"{dest}{sep}toast={quote_plus('SNMP poll OK: ' + dev.name)}", status_code=302)
    except SNMPError as exc:
        dev.snmp_last_poll_at = datetime.utcnow()
        dev.snmp_last_poll_status = "error"
        dev.snmp_last_poll_error = str(exc)[:1000]
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="SNMP_TEST_FAILED",
            entity_type="RFDevice",
            entity_id=dev.id,
            new_value=f"{dev.name}: {dev.snmp_last_poll_error}",
        ))
        db.commit()
        return RedirectResponse(f"{dest}{sep}toast={quote_plus('SNMP poll failed: ' + dev.name)}", status_code=302)


@router.post("/{dev_id}/snmp/ignore-modules")
async def device_snmp_ignore_modules(
    dev_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    """Set which module indices have their fault acknowledged/ignored (e.g. empty PSU)."""
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev:
        return RedirectResponse("/devices", status_code=302)
    form = await request.form()
    idxs = sorted({
        int(v) for k, v in form.multi_items()
        if k == "ignore_module" and str(v).isdigit()
    })
    dev.snmp_ignored_modules = ",".join(str(i) for i in idxs) or None
    # Recompute the effective alarm immediately from the cached module table.
    if dev.snmp_modules_json:
        try:
            modules = json.loads(dev.snmp_modules_json)
            dev.snmp_system_alarm = effective_alarm_from_modules(modules, set(idxs), fallback=dev.snmp_system_alarm)
        except (ValueError, TypeError):
            pass
    db.add(AuditLog(user_id=current_user.id, action_type="SNMP_MODULE_MUTE",
                    entity_type="RFDevice", entity_id=dev.id,
                    new_value=f"{dev.name}: ignored modules [{dev.snmp_ignored_modules or ''}]"))
    db.commit()
    return RedirectResponse(f"/devices/{dev_id}/routing?toast=Module+acknowledgements+saved", status_code=302)


@router.get("/{dev_id}/snmp/diagnostics", response_class=PlainTextResponse)
async def device_snmp_diagnostics(
    dev_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    """Read-only raw SNMP walk of a subtree — for diagnosing what a device exposes."""
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev or dev.device_type not in SNMP_MONITOR_TYPES:
        return PlainTextResponse("Device not found or not a routing device.", status_code=404)
    community, v3 = _device_credentials(dev)
    if not dev.host or (not community and not v3):
        return PlainTextResponse("SNMP host/credentials are not configured for this device.", status_code=400)
    base_oid = (request.query_params.get("base") or "").strip() or ENTERPRISE_ROOT
    header = f"# SNMP walk of {dev.name} ({dev.host}) base={base_oid}\n"
    try:
        rows = snmp_diagnostic_walk(dev.host, port=dev.snmp_port or 161, community=community, v3=v3, base_oid=base_oid)
    except SNMPError as exc:
        return PlainTextResponse(header + f"# walk failed: {exc}\n", status_code=200)
    body = "\n".join(f"{oid} = {val}" for oid, val in rows)
    return PlainTextResponse(header + f"# {len(rows)} rows\n\n" + body + "\n")


@router.post("/{dev_id}/delete")
async def device_delete(
    dev_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if dev:
        db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_DELETE",
                        entity_type="RFDevice", entity_id=dev.id, previous_value=dev.name))
        db.delete(dev)
        db.commit()
    return RedirectResponse("/devices?toast=Device+deleted", status_code=302)


# ── Routing matrix ────────────────────────────────────────────────────────────

def _load_snmp_modules(dev: RFDevice) -> list[dict]:
    """Parse the cached SNMP module table JSON for the health/mute panel."""
    if not dev.snmp_modules_json:
        return []
    try:
        return json.loads(dev.snmp_modules_json)
    except (ValueError, TypeError):
        return []


def _ensure_ports(db: Session, dev: RFDevice):
    """Create any missing input/output port rows for the device's current counts."""
    existing = {(p.direction, p.idx) for p in dev.ports}
    created = False
    for i in range(1, dev.num_inputs + 1):
        if ("in", i) not in existing:
            db.add(DevicePort(device_id=dev.id, direction="in", idx=i))
            created = True
    for i in range(1, dev.num_outputs + 1):
        if ("out", i) not in existing:
            db.add(DevicePort(device_id=dev.id, direction="out", idx=i))
            created = True
    if created:
        db.commit()
        db.refresh(dev)


@router.get("/{dev_id}/routing", response_class=HTMLResponse)
async def device_routing_page(
    dev_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev:
        return RedirectResponse("/devices", status_code=302)
    _ensure_ports(db, dev)
    inputs = [p for p in dev.ports if p.direction == "in" and p.idx <= dev.num_inputs]
    outputs = [p for p in dev.ports if p.direction == "out" and p.idx <= dev.num_outputs]

    # Build auto-hint maps from DeviceLink topology: {port_idx: device_name}
    # Inputs: this device is on the "to" end  →  connected to from_device
    # Outputs: this device is on the "from" end → connected to to_device
    links = db.query(DeviceLink).filter(
        DeviceLink.is_testing == is_testing_state(db),
        (DeviceLink.to_device_id == dev.id) | (DeviceLink.from_device_id == dev.id)
    ).all()
    input_hints: dict[int, str] = {}
    output_hints: dict[int, str] = {}
    for lnk in links:
        if lnk.to_device_id == dev.id and lnk.to_port_idx is not None:
            input_hints[lnk.to_port_idx] = lnk.from_device.name
        if lnk.from_device_id == dev.id and lnk.from_port_idx is not None:
            output_hints[lnk.from_port_idx] = lnk.to_device.name

    inputs = sorted(inputs, key=lambda p: p.idx)
    outputs = sorted(outputs, key=lambda p: p.idx)

    # Resolved display name per port: device SNMP alias > manual label > topology hint > "Input N".
    in_name = {p.idx: (p.observed_label or p.label or input_hints.get(p.idx) or f"Input {p.idx}") for p in inputs}
    out_name = {p.idx: (p.observed_label or p.label or output_hints.get(p.idx) or f"Output {p.idx}") for p in outputs}

    routing_mode = "input_to_output" if dev.device_type == "combiner" else "output_to_input"

    # Live fan-out/fan-in from observed routing. Splitters store routing on output
    # ports (output -> input); combiners store routing on input ports (input -> output).
    input_feeds: dict[int, list[int]] = {}
    output_feeds: dict[int, list[int]] = {}
    if routing_mode == "input_to_output":
        for ip in inputs:
            if ip.observed_routed_from:
                output_feeds.setdefault(ip.observed_routed_from, []).append(ip.idx)
                input_feeds.setdefault(ip.idx, []).append(ip.observed_routed_from)
    else:
        for op in outputs:
            if op.observed_routed_from:
                input_feeds.setdefault(op.observed_routed_from, []).append(op.idx)
                output_feeds.setdefault(op.idx, []).append(op.observed_routed_from)

    has_observed_routing = any(
        p.observed_routed_from is not None
        for p in (inputs if routing_mode == "input_to_output" else outputs)
    )

    return templates.TemplateResponse(request, "device_routing.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "device": dev,
        "inputs": inputs,
        "outputs": outputs,
        "input_hints": input_hints,
        "output_hints": output_hints,
        "input_labels": {p.idx: (p.label or input_hints.get(p.idx) or "") for p in inputs},
        "in_name": in_name,
        "out_name": out_name,
        "input_feeds": input_feeds,
        "output_feeds": output_feeds,
        "routing_mode": routing_mode,
        "snmp_modules": _load_snmp_modules(dev),
        "ignored_modules": ignored_module_idxs(dev),
        "has_observed_routing": has_observed_routing,
        "toast": request.query_params.get("toast", ""),
        "page": "devices",
    })


@router.post("/{dev_id}/routing")
async def device_routing_save(
    dev_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id, RFDevice.is_testing == is_testing_state(db)).first()
    if not dev:
        return RedirectResponse("/devices", status_code=302)
    form = await request.form()
    by_key = {(p.direction, p.idx): p for p in dev.ports}
    # Inputs: label only. Outputs: label + routed_from.
    for i in range(1, dev.num_inputs + 1):
        p = by_key.get(("in", i))
        if p is not None:
            p.label = (form.get(f"in_label_{i}", "") or "").strip() or None
    for i in range(1, dev.num_outputs + 1):
        p = by_key.get(("out", i))
        if p is not None:
            p.label = (form.get(f"out_label_{i}", "") or "").strip() or None
            src = (form.get(f"out_src_{i}", "") or "").strip()
            p.routed_from = int(src) if src.isdigit() else None
    db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_ROUTING",
                    entity_type="RFDevice", entity_id=dev.id, new_value=dev.name))
    db.commit()
    return RedirectResponse(f"/devices/{dev_id}/routing?toast=Routing+saved", status_code=302)


# ── Topology ──────────────────────────────────────────────────────────────────

def _port_display(link_port: str | None, port_idx: int | None, fallback: str) -> str:
    if port_idx and link_port:
        return f"Port {port_idx} - {link_port}"
    if port_idx:
        return f"Port {port_idx}"
    return link_port or fallback


def _device_port_names(dev: RFDevice) -> dict[tuple[str, int], str]:
    return {
        (p.direction, p.idx): (p.observed_label or p.label or f"{'Input' if p.direction == 'in' else 'Output'} {p.idx}")
        for p in dev.ports
    }


def _matching_device_for_alias(alias: str | None, devices: list[RFDevice], matrix_id: int) -> RFDevice | None:
    alias_norm = _normalise_name(alias)
    if not alias_norm:
        return None
    candidates = []
    for dev in devices:
        if dev.id == matrix_id or dev.device_type in {"splitter", "combiner", "switch"}:
            continue
        name_norm = _normalise_name(dev.name)
        model_norm = _normalise_name(dev.device_model)
        if name_norm and name_norm in alias_norm:
            candidates.append((len(name_norm), dev))
        elif model_norm and model_norm in alias_norm:
            candidates.append((len(model_norm), dev))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def _auto_inferred_links(devices: list[RFDevice], links: list[DeviceLink]) -> list[SimpleNamespace]:
    """Infer display-only RF topology links from matrix port aliases.

    If an SNMP/manual port label mentions a registered device name, topology can
    draw the physical connection even before an administrator adds a permanent
    DeviceLink. Existing manual links for that matrix port win.
    """
    occupied_inputs = {(lnk.to_device_id, lnk.to_port_idx) for lnk in links if lnk.link_type == "rf" and lnk.to_port_idx}
    occupied_outputs = {(lnk.from_device_id, lnk.from_port_idx) for lnk in links if lnk.link_type == "rf" and lnk.from_port_idx}
    inferred: list[SimpleNamespace] = []

    for matrix in devices:
        if matrix.device_type not in {"splitter", "combiner", "switch"}:
            continue
        for port in matrix.ports:
            alias = port.observed_label or port.label
            matched = _matching_device_for_alias(alias, devices, matrix.id)
            if not matched:
                continue
            if port.direction == "in":
                if (matrix.id, port.idx) in occupied_inputs:
                    continue
                inferred.append(SimpleNamespace(
                    id=f"auto-in-{matrix.id}-{port.idx}-{matched.id}",
                    from_device_id=matched.id,
                    from_device=matched,
                    from_port=None,
                    from_port_idx=None,
                    to_device_id=matrix.id,
                    to_device=matrix,
                    to_port=alias,
                    to_port_idx=port.idx,
                    link_type="rf",
                    label="auto from port name",
                    inferred=True,
                ))
            elif port.direction == "out":
                if (matrix.id, port.idx) in occupied_outputs:
                    continue
                inferred.append(SimpleNamespace(
                    id=f"auto-out-{matrix.id}-{port.idx}-{matched.id}",
                    from_device_id=matrix.id,
                    from_device=matrix,
                    from_port=alias,
                    from_port_idx=port.idx,
                    to_device_id=matched.id,
                    to_device=matched,
                    to_port=None,
                    to_port_idx=None,
                    link_type="rf",
                    label="auto from port name",
                    inferred=True,
                ))
    return inferred


def _live_routed_paths(devices: list[RFDevice], links: list[DeviceLink | SimpleNamespace]) -> list[dict]:
    """Derive end-to-end RF paths through splitter/combiner/switch devices.

    DeviceLink rows describe the physical cables to matrix ports. SNMP observed
    routing describes the internal matrix cross-connect. This joins the two so
    topology can show which upstream device is currently routed to which downstream
    device through each routing matrix.
    """
    input_links: dict[tuple[int, int], list[DeviceLink]] = {}
    output_links: dict[tuple[int, int], list[DeviceLink]] = {}
    for lnk in links:
        if lnk.link_type != "rf":
            continue
        if lnk.to_port_idx:
            input_links.setdefault((lnk.to_device_id, lnk.to_port_idx), []).append(lnk)
        if lnk.from_port_idx:
            output_links.setdefault((lnk.from_device_id, lnk.from_port_idx), []).append(lnk)

    paths: list[dict] = []
    for dev in devices:
        if dev.device_type not in {"splitter", "combiner", "switch"}:
            continue
        port_names = _device_port_names(dev)
        inputs = [p for p in dev.ports if p.direction == "in" and p.observed_routed_from]
        outputs = [p for p in dev.ports if p.direction == "out" and p.observed_routed_from]

        if dev.device_type == "combiner":
            route_pairs = [(p.idx, p.observed_routed_from) for p in inputs]
        else:
            route_pairs = [(p.observed_routed_from, p.idx) for p in outputs]

        for input_idx, output_idx in route_pairs:
            if not input_idx or not output_idx:
                continue
            upstream = input_links.get((dev.id, input_idx), [])
            downstream = output_links.get((dev.id, output_idx), [])
            for in_lnk in upstream:
                for out_lnk in downstream:
                    if in_lnk.from_device_id == out_lnk.to_device_id:
                        continue
                    paths.append({
                        "from_device_id": in_lnk.from_device_id,
                        "from_device": in_lnk.from_device.name,
                        "from_port": _port_display(in_lnk.from_port, in_lnk.from_port_idx, "Output"),
                        "through_device_id": dev.id,
                        "through_device": dev.name,
                        "through_type": dev.device_type,
                        "input_idx": input_idx,
                        "input_label": port_names.get(("in", input_idx), f"Input {input_idx}"),
                        "output_idx": output_idx,
                        "output_label": port_names.get(("out", output_idx), f"Output {output_idx}"),
                        "to_device_id": out_lnk.to_device_id,
                        "to_device": out_lnk.to_device.name,
                        "to_port": _port_display(out_lnk.to_port, out_lnk.to_port_idx, "Input"),
                        "link_type": "rf",
                    })
    return paths


@router.get("/topology", response_class=HTMLResponse)
async def topology_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    devices = db.query(RFDevice).filter(RFDevice.is_active == True, RFDevice.is_testing == testing).order_by(RFDevice.name).all()
    links = (
        db.query(DeviceLink)
        .filter(DeviceLink.is_testing == testing)
        .order_by(DeviceLink.link_type, DeviceLink.id)
        .all()
    )
    inferred_links = _auto_inferred_links(devices, links)
    topology_links = [*links, *inferred_links]
    live_routes = _live_routed_paths(devices, topology_links)
    return templates.TemplateResponse(request, "topology.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "devices": devices,
        "links": topology_links,
        "manual_links": links,
        "inferred_links": inferred_links,
        "live_routes": live_routes,
        "device_types": DEVICE_TYPES,
        "link_types": LINK_TYPES,
        "toast": request.query_params.get("toast", ""),
        "page": "devices",
    })


@router.post("/links/new")
async def link_create(
    from_device_id: int = Form(...),
    from_port: str = Form(""),
    from_port_idx: str = Form(""),
    to_device_id: int = Form(...),
    to_port: str = Form(""),
    to_port_idx: str = Form(""),
    link_type: str = Form("rf"),
    label: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    testing = is_testing_state(db)
    from_dev = db.query(RFDevice).filter(RFDevice.id == from_device_id, RFDevice.is_testing == testing).first()
    to_dev = db.query(RFDevice).filter(RFDevice.id == to_device_id, RFDevice.is_testing == testing).first()
    if from_dev and to_dev and from_device_id != to_device_id:
        lnk = DeviceLink(
            from_device_id=from_device_id,
            from_port=from_port.strip() or None,
            from_port_idx=int(from_port_idx) if from_port_idx.strip().isdigit() else None,
            to_device_id=to_device_id,
            to_port=to_port.strip() or None,
            to_port_idx=int(to_port_idx) if to_port_idx.strip().isdigit() else None,
            link_type=link_type if link_type in dict(LINK_TYPES) else "rf",
            label=label.strip() or None,
            is_testing=testing,
        )
        db.add(lnk)
        db.flush()
        db.add(AuditLog(
            user_id=current_user.id, action_type="DEVICE_LINK_CREATE",
            entity_type="DeviceLink", entity_id=lnk.id,
            new_value=f"{lnk.from_device.name} → {lnk.to_device.name} ({link_type})",
        ))
        db.commit()
    return RedirectResponse("/devices/topology?toast=Link+added", status_code=302)


@router.post("/links/{link_id}/delete")
async def link_delete(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    lnk = db.query(DeviceLink).filter(DeviceLink.id == link_id, DeviceLink.is_testing == is_testing_state(db)).first()
    if lnk:
        desc = f"{lnk.from_device.name} → {lnk.to_device.name}"
        db.add(AuditLog(
            user_id=current_user.id, action_type="DEVICE_LINK_DELETE",
            entity_type="DeviceLink", entity_id=lnk.id, previous_value=desc,
        ))
        db.delete(lnk)
        db.commit()
    return RedirectResponse("/devices/topology?toast=Link+removed", status_code=302)
