import json
from datetime import datetime
from fastapi import APIRouter, Depends, Form, File, UploadFile, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state
from app.models import (
    User, Signal, SignalPackage, SignalPackageEntry,
    ModulationType, FecType, SignalSource, AntennaType, AuditLog, RFDevice,
)

router = APIRouter(prefix="/packages")
from app.templating import templates

BANDS = ["C", "X", "Ku", "Ka", "Other"]
FREQ_UNITS = ["MHz", "GHz"]
POWER_UNITS = ["dBm", "dBW", "W"]
CBM_PATHS = [
    ("", "None"),
    ("tx", "Tx"),
    ("rx", "Rx"),
    ("tx_rx", "Tx/Rx"),
    ("dvb", "DVB"),
]


def _dropdown_lists(db: Session) -> dict:
    testing = is_testing_state(db)
    mod_types = [m.name for m in db.query(ModulationType).filter(ModulationType.is_active == True).order_by(ModulationType.display_order).all()]
    fec_types = [f.name for f in db.query(FecType).filter(FecType.is_active == True).order_by(FecType.display_order).all()]
    sources = [s.name for s in db.query(SignalSource).filter(SignalSource.is_active == True).order_by(SignalSource.display_order).all()]
    antennas = [a.name for a in db.query(AntennaType).filter(AntennaType.is_active == True).order_by(AntennaType.display_order).all()]
    signals = [s.name for s in db.query(Signal).filter(Signal.is_active == True).order_by(Signal.name).all()]
    cbm_devices = (
        db.query(RFDevice)
        .filter(
            RFDevice.is_active == True,
            RFDevice.device_type == "modem",
            RFDevice.is_testing == testing,
        )
        .order_by(RFDevice.name)
        .all()
    )
    return {
        "mod_types": mod_types or ["BPSK", "QPSK", "8PSK", "16APSK", "32APSK"],
        "fec_types": fec_types or ["1/2", "2/3", "3/4", "5/6", "7/8", "8/9", "9/10"],
        "signal_sources": sources,
        "antenna_types": antennas,
        "registry_signals": signals,
        "cbm_devices": cbm_devices,
        "cbm_paths": CBM_PATHS,
        "bands": BANDS,
        "freq_units": FREQ_UNITS,
        "power_units": POWER_UNITS,
    }


def _package_to_dict(pkg: SignalPackage) -> dict:
    """Serialise a package to a dict for JSON export."""
    return {
        "name": pkg.name,
        "description": pkg.description or "",
        "rf_config": {
            "band": pkg.band or "",
            "antenna": pkg.antenna or "",
            "tx_lo": pkg.tx_lo,
            "rx_lo": pkg.rx_lo,
            "ttf": pkg.ttf,
            "ttf_direction": pkg.ttf_direction or "+",
            "freq_unit": pkg.freq_unit or "MHz",
        },
        "signals": [
            {
                "name": e.signal_name,
                "description": e.description or "",
                "band": e.band or "",
                "tx_if": e.tx_if,
                "tx_rf": e.tx_rf,
                "rx_rf": e.rx_rf,
                "rx_if": e.rx_if,
                "freq_unit": e.freq_unit,
                "modulation": e.modulation or "",
                "fec": e.fec or "",
                "symbol_rate": e.symbol_rate or "",
                "power": e.power,
                "power_unit": e.power_unit,
                "eb_no": e.eb_no,
                "source": e.source or "",
                "antenna": e.antenna or "",
                "cbm_device": e.cbm_device.name if e.cbm_device else "",
                "cbm_path": e.cbm_path or "",
                "cbm_carrier": e.cbm_carrier or "",
                "notes": e.notes or "",
            }
            for e in pkg.signals
        ],
    }


def _dict_to_entries(data: dict) -> list[dict]:
    """Parse a JSON package dict and return a list of entry field dicts."""
    entries = []
    for i, s in enumerate(data.get("signals", [])):
        entries.append({
            "signal_name": str(s.get("name", "")).strip(),
            "description": str(s.get("description", "")).strip() or None,
            "band": str(s.get("band", "")).strip() or None,
            "tx_if": _float_or_none(s.get("tx_if")),
            "tx_rf": _float_or_none(s.get("tx_rf")),
            "rx_rf": _float_or_none(s.get("rx_rf")),
            "rx_if": _float_or_none(s.get("rx_if")),
            "freq_unit": str(s.get("freq_unit", "MHz")).strip() or "MHz",
            "modulation": str(s.get("modulation", "")).strip() or None,
            "fec": str(s.get("fec", "")).strip() or None,
            "symbol_rate": str(s.get("symbol_rate", "")).strip() or None,
            "power": _float_or_none(s.get("power")),
            "power_unit": str(s.get("power_unit", "dBm")).strip() or "dBm",
            "eb_no": _float_or_none(s.get("eb_no")),
            "source": str(s.get("source", "")).strip() or None,
            "antenna": str(s.get("antenna", "")).strip() or None,
            "cbm_path": str(s.get("cbm_path", "")).strip() or None,
            "cbm_carrier": str(s.get("cbm_carrier", "")).strip() or None,
            "notes": str(s.get("notes", "")).strip() or None,
            "display_order": i,
        })
    return entries


def _float_or_none(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def packages_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    packages = db.query(SignalPackage).filter(SignalPackage.is_testing == testing).order_by(SignalPackage.created_at.desc()).all()
    return templates.TemplateResponse(request, "packages.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "packages": packages,
        "toast": request.query_params.get("toast", ""),
        "page": "packages",
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def package_new_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "package_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "package": None,
        "page": "packages",
        **_dropdown_lists(db),
    })


@router.post("/new")
async def package_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    antenna: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    freq_unit: str = Form("MHz"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = SignalPackage(
        name=name.strip(),
        description=description.strip() or None,
        band=band or None,
        antenna=antenna.strip() or None,
        tx_lo=tx_lo,
        rx_lo=rx_lo,
        ttf=ttf,
        ttf_direction=ttf_direction or "+",
        freq_unit=freq_unit or "MHz",
        is_testing=is_testing_state(db),
        created_by_id=current_user.id,
    )
    db.add(pkg)
    db.flush()
    db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_CREATE",
                    entity_type="SignalPackage", entity_id=pkg.id, new_value=pkg.name))
    db.commit()
    return RedirectResponse(f"/packages/{pkg.id}?toast=Package+created", status_code=302)


# ── Edit (add/update/remove signals) ─────────────────────────────────────────

@router.get("/{pkg_id:int}", response_class=HTMLResponse)
async def package_detail(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == is_testing_state(db),
    ).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    return templates.TemplateResponse(request, "package_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "package": pkg,
        "toast": request.query_params.get("toast", ""),
        "page": "packages",
        **_dropdown_lists(db),
    })


@router.post("/{pkg_id:int}/update")
async def package_update_meta(
    pkg_id: int,
    name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    antenna: str = Form(""),
    tx_lo: Optional[float] = Form(None),
    rx_lo: Optional[float] = Form(None),
    ttf: Optional[float] = Form(None),
    ttf_direction: str = Form("+"),
    freq_unit: str = Form("MHz"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if pkg:
        pkg.name = name.strip() or pkg.name
        pkg.description = description.strip() or None
        pkg.band = band or None
        pkg.antenna = antenna.strip() or None
        pkg.tx_lo = tx_lo
        pkg.rx_lo = rx_lo
        pkg.ttf = ttf
        pkg.ttf_direction = ttf_direction or "+"
        pkg.freq_unit = freq_unit or "MHz"
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Package+updated", status_code=302)


@router.post("/{pkg_id:int}/signals/add")
async def package_signal_add(
    pkg_id: int,
    signal_name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    modulation: str = Form(""),
    fec: str = Form(""),
    symbol_rate: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    source: str = Form(""),
    antenna: str = Form(""),
    cbm_device_id: Optional[int] = Form(None),
    cbm_path: str = Form(""),
    cbm_carrier: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    if cbm_device_id:
        device = db.query(RFDevice).filter(RFDevice.id == cbm_device_id, RFDevice.is_testing == testing).first()
        cbm_device_id = device.id if device else None
    order = len(pkg.signals)
    entry = SignalPackageEntry(
        package_id=pkg_id,
        display_order=order,
        signal_name=signal_name.strip(),
        description=description.strip() or None,
        band=band or None,
        tx_if=tx_if, tx_rf=tx_rf, rx_rf=rx_rf, rx_if=rx_if,
        freq_unit=freq_unit or "MHz",
        modulation=modulation or None,
        fec=fec or None,
        symbol_rate=symbol_rate or None,
        power=power, power_unit=power_unit or "dBm",
        eb_no=eb_no,
        source=source.strip() or None,
        antenna=antenna.strip() or None,
        cbm_device_id=cbm_device_id,
        cbm_path=cbm_path or None,
        cbm_carrier=cbm_carrier.strip() or None,
        notes=notes.strip() or None,
    )
    pkg.updated_at = datetime.utcnow()
    db.add(entry)
    db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+added", status_code=302)


@router.post("/{pkg_id:int}/signals/{entry_id:int}/update")
async def package_signal_update(
    pkg_id: int,
    entry_id: int,
    signal_name: str = Form(...),
    description: str = Form(""),
    band: str = Form(""),
    tx_if: Optional[float] = Form(None),
    tx_rf: Optional[float] = Form(None),
    rx_rf: Optional[float] = Form(None),
    rx_if: Optional[float] = Form(None),
    freq_unit: str = Form("MHz"),
    modulation: str = Form(""),
    fec: str = Form(""),
    symbol_rate: str = Form(""),
    power: Optional[float] = Form(None),
    power_unit: str = Form("dBm"),
    eb_no: Optional[float] = Form(None),
    source: str = Form(""),
    antenna: str = Form(""),
    cbm_device_id: Optional[int] = Form(None),
    cbm_path: str = Form(""),
    cbm_carrier: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    if cbm_device_id:
        device = db.query(RFDevice).filter(RFDevice.id == cbm_device_id, RFDevice.is_testing == testing).first()
        cbm_device_id = device.id if device else None
    entry = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.id == entry_id,
        SignalPackageEntry.package_id == pkg_id,
    ).first() if pkg else None
    if entry:
        entry.signal_name = signal_name.strip()
        entry.description = description.strip() or None
        entry.band = band or None
        entry.tx_if = tx_if; entry.tx_rf = tx_rf
        entry.rx_rf = rx_rf; entry.rx_if = rx_if
        entry.freq_unit = freq_unit or "MHz"
        entry.modulation = modulation or None
        entry.fec = fec or None
        entry.symbol_rate = symbol_rate or None
        entry.power = power; entry.power_unit = power_unit or "dBm"
        entry.eb_no = eb_no
        entry.source = source.strip() or None
        entry.antenna = antenna.strip() or None
        entry.cbm_device_id = cbm_device_id
        entry.cbm_path = cbm_path or None
        entry.cbm_carrier = cbm_carrier.strip() or None
        entry.notes = notes.strip() or None
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+updated", status_code=302)


@router.post("/{pkg_id:int}/signals/{entry_id:int}/delete")
async def package_signal_delete(
    pkg_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    entry = db.query(SignalPackageEntry).filter(
        SignalPackageEntry.id == entry_id,
        SignalPackageEntry.package_id == pkg_id,
    ).first() if pkg else None
    if entry:
        db.delete(entry)
        pkg.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Signal+removed", status_code=302)


@router.post("/{pkg_id:int}/duplicate")
async def package_duplicate(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    orig = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == testing).first()
    if not orig:
        return RedirectResponse("/packages", status_code=302)
    copy = SignalPackage(
        name=f"{orig.name} (copy)",
        description=orig.description,
        band=orig.band,
        antenna=orig.antenna,
        tx_lo=orig.tx_lo,
        rx_lo=orig.rx_lo,
        ttf=orig.ttf,
        ttf_direction=orig.ttf_direction,
        freq_unit=orig.freq_unit,
        is_testing=testing,
        created_by_id=current_user.id,
    )
    db.add(copy)
    db.flush()
    for entry in orig.signals:
        db.add(SignalPackageEntry(
            package_id=copy.id,
            display_order=entry.display_order,
            signal_name=entry.signal_name,
            description=entry.description,
            band=entry.band,
            tx_if=entry.tx_if, tx_rf=entry.tx_rf,
            rx_rf=entry.rx_rf, rx_if=entry.rx_if,
            freq_unit=entry.freq_unit,
            modulation=entry.modulation,
            fec=entry.fec,
            symbol_rate=entry.symbol_rate,
            power=entry.power, power_unit=entry.power_unit,
            eb_no=entry.eb_no,
            source=entry.source,
            antenna=entry.antenna,
            cbm_device_id=entry.cbm_device_id,
            cbm_path=entry.cbm_path,
            cbm_carrier=entry.cbm_carrier,
            notes=entry.notes,
        ))
    db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_DUPLICATE",
                    entity_type="SignalPackage", entity_id=copy.id,
                    new_value=f"Copy of {orig.name}"))
    db.commit()
    return RedirectResponse(f"/packages/{copy.id}?toast=Package+duplicated", status_code=302)


@router.post("/{pkg_id:int}/signals/reorder")
async def package_signals_reorder(
    pkg_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form = await request.form()
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    for key, val in form.items():
        if key.startswith("order_"):
            entry_id = int(key.split("_")[1])
            entry = db.query(SignalPackageEntry).filter(
                SignalPackageEntry.id == entry_id,
                SignalPackageEntry.package_id == pkg_id,
            ).first()
            if entry:
                try:
                    entry.display_order = int(val)
                except ValueError:
                    pass
    db.commit()
    return RedirectResponse(f"/packages/{pkg_id}?toast=Order+saved", status_code=302)


@router.post("/{pkg_id:int}/delete")
async def package_delete(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(
        SignalPackage.id == pkg_id,
        SignalPackage.is_testing == is_testing_state(db),
    ).first()
    if pkg:
        db.delete(pkg)
        db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_DELETE",
                        entity_type="SignalPackage", entity_id=pkg_id, new_value=pkg.name))
        db.commit()
    return RedirectResponse("/packages?toast=Package+deleted", status_code=302)


# ── Export / Import ───────────────────────────────────────────────────────────

@router.get("/{pkg_id:int}/export")
async def package_export(
    pkg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pkg = db.query(SignalPackage).filter(SignalPackage.id == pkg_id, SignalPackage.is_testing == is_testing_state(db)).first()
    if not pkg:
        return RedirectResponse("/packages", status_code=302)
    data = json.dumps(_package_to_dict(pkg), indent=2)
    filename = pkg.name.replace(" ", "_").replace("/", "-")[:60] + ".json"
    return StreamingResponse(
        iter([data]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/import", response_class=HTMLResponse)
async def package_import_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "package_import.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "packages",
        "error": None,
    })


@router.post("/import")
async def package_import_submit(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    error = None
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict) or "signals" not in data:
            raise ValueError("File must be a JSON object with a 'signals' list.")
        rf = data.get("rf_config", {}) or {}
        pkg = SignalPackage(
            name=str(data.get("name", file.filename or "Imported Package")).strip(),
            description=str(data.get("description", "")).strip() or None,
            band=str(rf.get("band", "")).strip() or None,
            antenna=str(rf.get("antenna", "")).strip() or None,
            # Accept legacy "buc"/"lo" keys from packages exported before the rename.
            tx_lo=_float_or_none(rf.get("tx_lo", rf.get("buc"))),
            rx_lo=_float_or_none(rf.get("rx_lo", rf.get("lo"))),
            ttf=_float_or_none(rf.get("ttf")),
            ttf_direction=str(rf.get("ttf_direction", "+")) or "+",
            freq_unit=str(rf.get("freq_unit", "MHz")) or "MHz",
            created_by_id=current_user.id,
            is_testing=is_testing_state(db),
        )
        db.add(pkg)
        db.flush()
        for fields in _dict_to_entries(data):
            if not fields["signal_name"]:
                continue
            db.add(SignalPackageEntry(package_id=pkg.id, **fields))
        db.add(AuditLog(user_id=current_user.id, action_type="PACKAGE_IMPORT",
                        entity_type="SignalPackage", entity_id=pkg.id, new_value=pkg.name))
        db.commit()
        return RedirectResponse(f"/packages/{pkg.id}?toast=Package+imported", status_code=302)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "package_import.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "packages",
        "error": error,
    })
