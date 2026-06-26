import asyncio

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, require_supervisor
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
    devices = db.query(RFDevice).filter(RFDevice.is_active == True).all()
    results = await asyncio.gather(*(_reachable(d.host, d.check_port) for d in devices))
    return JSONResponse({str(d.id): status for d, status in zip(devices, results)})


# ── Registry ──────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def devices_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    devices = db.query(RFDevice).order_by(RFDevice.device_type, RFDevice.name).all()
    return templates.TemplateResponse(request, "devices.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "devices": devices,
        "device_types": DEVICE_TYPES,
        "routing_types": ROUTING_TYPES,
        "toast": request.query_params.get("toast", ""),
        "page": "devices",
        "page_name": "devices",
    })


@router.post("/new")
async def device_create(
    name: str = Form(...),
    device_model: str = Form(""),
    device_type: str = Form("other"),
    host: str = Form(""),
    check_port: str = Form(""),
    has_web_gui: str = Form(""),
    location: str = Form(""),
    num_inputs: int = Form(16),
    num_outputs: int = Form(16),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if name:
        dev = RFDevice(
            name=name,
            device_model=device_model.strip() or None,
            device_type=device_type if device_type in dict(DEVICE_TYPES) else "other",
            host=host.strip() or None,
            check_port=int(check_port) if check_port.strip().isdigit() else None,
            has_web_gui=bool(has_web_gui),
            location=location.strip() or None,
            num_inputs=max(0, min(num_inputs, 128)),
            num_outputs=max(0, min(num_outputs, 128)),
            notes=notes.strip() or None,
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
    location: str = Form(""),
    num_inputs: int = Form(16),
    num_outputs: int = Form(16),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id).first()
    if dev:
        dev.name = name.strip() or dev.name
        dev.device_model = device_model.strip() or None
        dev.device_type = device_type if device_type in dict(DEVICE_TYPES) else dev.device_type
        dev.host = host.strip() or None
        dev.check_port = int(check_port) if check_port.strip().isdigit() else None
        dev.has_web_gui = bool(has_web_gui)
        dev.location = location.strip() or None
        dev.num_inputs = max(0, min(num_inputs, 128))
        dev.num_outputs = max(0, min(num_outputs, 128))
        dev.notes = notes.strip() or None
        db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_UPDATE",
                        entity_type="RFDevice", entity_id=dev.id, new_value=dev.name))
        db.commit()
    return RedirectResponse("/devices?toast=Device+updated", status_code=302)


@router.post("/{dev_id}/delete")
async def device_delete(
    dev_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id).first()
    if dev:
        db.add(AuditLog(user_id=current_user.id, action_type="DEVICE_DELETE",
                        entity_type="RFDevice", entity_id=dev.id, previous_value=dev.name))
        db.delete(dev)
        db.commit()
    return RedirectResponse("/devices?toast=Device+deleted", status_code=302)


# ── Routing matrix ────────────────────────────────────────────────────────────

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
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id).first()
    if not dev:
        return RedirectResponse("/devices", status_code=302)
    _ensure_ports(db, dev)
    inputs = [p for p in dev.ports if p.direction == "in" and p.idx <= dev.num_inputs]
    outputs = [p for p in dev.ports if p.direction == "out" and p.idx <= dev.num_outputs]

    # Build auto-hint maps from DeviceLink topology: {port_idx: device_name}
    # Inputs: this device is on the "to" end  →  connected to from_device
    # Outputs: this device is on the "from" end → connected to to_device
    links = db.query(DeviceLink).filter(
        (DeviceLink.to_device_id == dev.id) | (DeviceLink.from_device_id == dev.id)
    ).all()
    input_hints: dict[int, str] = {}
    output_hints: dict[int, str] = {}
    for lnk in links:
        if lnk.to_device_id == dev.id and lnk.to_port_idx is not None:
            input_hints[lnk.to_port_idx] = lnk.from_device.name
        if lnk.from_device_id == dev.id and lnk.from_port_idx is not None:
            output_hints[lnk.from_port_idx] = lnk.to_device.name

    return templates.TemplateResponse(request, "device_routing.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "device": dev,
        "inputs": sorted(inputs, key=lambda p: p.idx),
        "outputs": sorted(outputs, key=lambda p: p.idx),
        "input_hints": input_hints,
        "output_hints": output_hints,
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
    dev = db.query(RFDevice).filter(RFDevice.id == dev_id).first()
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

@router.get("/topology", response_class=HTMLResponse)
async def topology_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    devices = db.query(RFDevice).filter(RFDevice.is_active == True).order_by(RFDevice.name).all()
    links = (
        db.query(DeviceLink)
        .order_by(DeviceLink.link_type, DeviceLink.id)
        .all()
    )
    return templates.TemplateResponse(request, "topology.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "devices": devices,
        "links": links,
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
    if from_device_id != to_device_id:
        lnk = DeviceLink(
            from_device_id=from_device_id,
            from_port=from_port.strip() or None,
            from_port_idx=int(from_port_idx) if from_port_idx.strip().isdigit() else None,
            to_device_id=to_device_id,
            to_port=to_port.strip() or None,
            to_port_idx=int(to_port_idx) if to_port_idx.strip().isdigit() else None,
            link_type=link_type if link_type in dict(LINK_TYPES) else "rf",
            label=label.strip() or None,
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
    lnk = db.query(DeviceLink).filter(DeviceLink.id == link_id).first()
    if lnk:
        desc = f"{lnk.from_device.name} → {lnk.to_device.name}"
        db.add(AuditLog(
            user_id=current_user.id, action_type="DEVICE_LINK_DELETE",
            entity_type="DeviceLink", entity_id=lnk.id, previous_value=desc,
        ))
        db.delete(lnk)
        db.commit()
    return RedirectResponse("/devices/topology?toast=Link+removed", status_code=302)
