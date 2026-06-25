from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import require_supervisor, get_current_range_state
from app.models import ModulationType, FecType, SignalSource, AntennaType, Signal, FrequencyTemplate, User

router = APIRouter(prefix="/config")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def config_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    mod_types = db.query(ModulationType).order_by(ModulationType.display_order, ModulationType.name).all()
    fec_types = db.query(FecType).order_by(FecType.display_order, FecType.name).all()
    signal_sources = db.query(SignalSource).order_by(SignalSource.display_order, SignalSource.name).all()
    antenna_types = db.query(AntennaType).order_by(AntennaType.display_order, AntennaType.name).all()
    signals = db.query(Signal).order_by(Signal.name).all()
    groups = sorted(set(s.exclusivity_group for s in signals if s.exclusivity_group))
    freq_templates = db.query(FrequencyTemplate).order_by(FrequencyTemplate.name).all()
    return templates.TemplateResponse(request, "config.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "mod_types": mod_types,
        "fec_types": fec_types,
        "signal_sources": signal_sources,
        "antenna_types": antenna_types,
        "signals": signals,
        "groups": groups,
        "freq_templates": freq_templates,
        "bands": ["C", "X", "Ku", "Ka", "Other"],
        "page": "config",
        "toast": request.query_params.get("toast", ""),
    })


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
