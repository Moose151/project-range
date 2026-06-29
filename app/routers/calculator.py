import math
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import User, FrequencyTemplate
from app.config import FREQUENCY_BANDS

router = APIRouter(prefix="/calculator")
from app.templating import templates


# ── RF frequency maths ─────────────────────────────────────────────────────────

def _to_mhz(value: float, unit: str) -> float:
    return value * 1000 if unit == "GHz" else value


def _from_mhz(value: float, unit: str) -> float:
    return value / 1000 if unit == "GHz" else value


def calculate_rf(known: str, value_mhz: float, tx_lo: float, rx_lo: float, ttf: float, ttf_dir: str):
    """Return (tx_if, tx_rf, rx_rf, rx_if) all in MHz."""
    sign = 1 if ttf_dir == "+" else -1
    if known == "TxIF":
        tx_if = value_mhz
        tx_rf = tx_if + tx_lo
        rx_rf = tx_rf + sign * ttf
        rx_if = rx_rf - rx_lo
    elif known == "TxRF":
        tx_rf = value_mhz
        tx_if = tx_rf - tx_lo
        rx_rf = tx_rf + sign * ttf
        rx_if = rx_rf - rx_lo
    elif known == "RxRF":
        rx_rf = value_mhz
        tx_rf = rx_rf - sign * ttf
        tx_if = tx_rf - tx_lo
        rx_if = rx_rf - rx_lo
    elif known == "RxIF":
        rx_if = value_mhz
        rx_rf = rx_if + rx_lo
        tx_rf = rx_rf - sign * ttf
        tx_if = tx_rf - tx_lo
    else:
        raise ValueError(f"Unknown frequency type: {known}")
    return tx_if, tx_rf, rx_rf, rx_if


def band_warnings(tx_rf_mhz: float, rx_rf_mhz: float, band: str | None) -> list[str]:
    warnings = []
    if not band or band not in FREQUENCY_BANDS:
        return warnings
    limits = FREQUENCY_BANDS[band]
    tx_ghz = tx_rf_mhz / 1000
    rx_ghz = rx_rf_mhz / 1000
    if not (limits["tx_min"] <= tx_ghz <= limits["tx_max"]):
        warnings.append(
            f"TxRF {tx_ghz:.4f} GHz is outside the expected {band}-band Tx range "
            f"({limits['tx_min']}–{limits['tx_max']} GHz)."
        )
    if not (limits["rx_min"] <= rx_ghz <= limits["rx_max"]):
        warnings.append(
            f"RxRF {rx_ghz:.4f} GHz is outside the expected {band}-band Rx range "
            f"({limits['rx_min']}–{limits['rx_max']} GHz)."
        )
    return warnings


# ── Power maths ────────────────────────────────────────────────────────────────

def convert_power(value: float, from_unit: str, to_unit: str) -> float:
    if from_unit == to_unit:
        return value
    # Convert to Watts first
    if from_unit == "dBW":
        watts = 10 ** (value / 10)
    elif from_unit == "dBm":
        watts = 10 ** ((value - 30) / 10)
    elif from_unit == "W":
        watts = value
    else:
        raise ValueError(f"Unknown unit: {from_unit}")
    # Convert from Watts
    if to_unit == "dBW":
        if watts <= 0:
            raise ValueError("Cannot convert zero or negative power to dB")
        return 10 * math.log10(watts)
    elif to_unit == "dBm":
        if watts <= 0:
            raise ValueError("Cannot convert zero or negative power to dB")
        return 10 * math.log10(watts) + 30
    elif to_unit == "W":
        return watts
    else:
        raise ValueError(f"Unknown unit: {to_unit}")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/basic", response_class=HTMLResponse)
async def basic_calc_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "calculator_basic.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "page": "calculator", "page_name": "basic",
    })


@router.get("/rf", response_class=HTMLResponse)
async def rf_calc_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    templates_list = db.query(FrequencyTemplate).order_by(FrequencyTemplate.name).all()
    return templates.TemplateResponse(request, "calculator_rf.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "freq_templates": templates_list,
        "bands": list(FREQUENCY_BANDS.keys()),
        "config_bands": FREQUENCY_BANDS,
        "result": None,
        # Seed the unit selectors from the user's preferred default frequency unit.
        "form": {"input_unit": current_user.default_freq_unit,
                 "output_unit": current_user.default_freq_unit},
        "page": "calculator", "page_name": "rf",
    })


@router.post("/rf", response_class=HTMLResponse)
async def rf_calc_submit(
    request: Request,
    known_freq: str = Form(...),
    known_value: float = Form(...),
    input_unit: str = Form("MHz"),
    tx_lo: float = Form(...),
    rx_lo: float = Form(...),
    ttf: float = Form(...),
    ttf_direction: str = Form("+"),
    output_unit: str = Form("MHz"),
    band: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    templates_list = db.query(FrequencyTemplate).order_by(FrequencyTemplate.name).all()
    form_data = {
        "known_freq": known_freq, "known_value": known_value,
        "input_unit": input_unit, "tx_lo": tx_lo, "rx_lo": rx_lo,
        "ttf": ttf, "ttf_direction": ttf_direction,
        "output_unit": output_unit, "band": band,
    }
    result = None
    warnings = []
    error = None
    try:
        # All input converted to MHz for calculation
        val_mhz = _to_mhz(known_value, input_unit)
        tx_lo_mhz = _to_mhz(tx_lo, input_unit)
        rx_lo_mhz = _to_mhz(rx_lo, input_unit)
        ttf_mhz = _to_mhz(ttf, input_unit)

        tx_if, tx_rf, rx_rf, rx_if = calculate_rf(known_freq, val_mhz, tx_lo_mhz, rx_lo_mhz, ttf_mhz, ttf_direction)
        warnings = band_warnings(tx_rf, rx_rf, band or None)
        result = {
            "tx_if": round(_from_mhz(tx_if, output_unit), 6),
            "tx_rf": round(_from_mhz(tx_rf, output_unit), 6),
            "rx_rf": round(_from_mhz(rx_rf, output_unit), 6),
            "rx_if": round(_from_mhz(rx_if, output_unit), 6),
            "unit": output_unit,
            "warnings": warnings,
        }
        # Persist conversion values so the log form can pre-fill them
        request.session["last_tx_lo"] = tx_lo
        request.session["last_rx_lo"] = rx_lo
        request.session["last_ttf"] = ttf
        request.session["last_ttf_direction"] = ttf_direction
        request.session["last_freq_unit"] = input_unit
        request.session["last_band"] = band
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "calculator_rf.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "freq_templates": templates_list,
        "bands": list(FREQUENCY_BANDS.keys()),
        "config_bands": FREQUENCY_BANDS,
        "result": result,
        "form": form_data,
        "error": error,
        "page": "calculator", "page_name": "rf",
    })


@router.get("/power", response_class=HTMLResponse)
async def power_calc_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "calculator_power.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "result": None,
        "chain_result": None,
        # Seed unit selectors from the user's preferred default power unit.
        "form": {"from_unit": current_user.default_power_unit,
                 "start_unit": current_user.default_power_unit},
        "page": "calculator", "page_name": "power",
    })


@router.post("/power", response_class=HTMLResponse)
async def power_calc_submit(
    request: Request,
    power_value: float = Form(...),
    from_unit: str = Form(...),
    to_unit: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = None
    error = None
    try:
        converted = convert_power(power_value, from_unit, to_unit)
        result = {
            "input": power_value, "from_unit": from_unit,
            "output": round(converted, 4), "to_unit": to_unit,
        }
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "calculator_power.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "result": result,
        "chain_result": None,
        "form": {"power_value": power_value, "from_unit": from_unit, "to_unit": to_unit},
        "error": error,
        "page": "calculator", "page_name": "power",
    })


@router.get("/eirp", response_class=HTMLResponse)
async def eirp_calc_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "calculator_eirp.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "result": None,
        "form": {},
        "error": None,
        "page": "calculator", "page_name": "eirp",
    })


@router.post("/eirp", response_class=HTMLResponse)
async def eirp_calc_submit(
    request: Request,
    tx_power: float = Form(...),
    tx_unit: str = Form("dBm"),
    cable_loss: float = Form(0.0),
    antenna_gain: float = Form(...),
    other_losses: float = Form(0.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form_data = {
        "tx_power": tx_power, "tx_unit": tx_unit,
        "cable_loss": cable_loss, "antenna_gain": antenna_gain,
        "other_losses": other_losses,
    }
    result = None
    error = None
    try:
        tx_dbw = convert_power(tx_power, tx_unit, "dBW")
        power_at_antenna_dbw = tx_dbw - cable_loss
        eirp_dbw = power_at_antenna_dbw + antenna_gain - other_losses
        eirp_dbm = eirp_dbw + 30
        eirp_w = 10 ** (eirp_dbw / 10)
        result = {
            "tx_dbw": round(tx_dbw, 4),
            "power_at_antenna_dbw": round(power_at_antenna_dbw, 4),
            "eirp_dbw": round(eirp_dbw, 4),
            "eirp_dbm": round(eirp_dbm, 4),
            "eirp_w": round(eirp_w, 4),
            "eirp_kw": round(eirp_w / 1000, 6),
        }
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "calculator_eirp.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "result": result,
        "form": form_data,
        "error": error,
        "page": "calculator", "page_name": "eirp",
    })


@router.post("/power/chain", response_class=HTMLResponse)
async def power_chain_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    form = await request.form()
    start_power = float(form.get("start_power", 0))
    start_unit = form.get("start_unit", "dBm")

    # Collect stages: stage_name_N, stage_value_N, stage_type_N (gain/loss)
    stages = []
    i = 0
    while f"stage_name_{i}" in form:
        name = form.get(f"stage_name_{i}", "").strip()
        value = float(form.get(f"stage_value_{i}", 0))
        stype = form.get(f"stage_type_{i}", "loss")
        if name:
            stages.append({"name": name, "value": value, "type": stype})
        i += 1

    # Calculate running power in dBm
    try:
        current_dbm = convert_power(start_power, start_unit, "dBm")
        chain = []
        for s in stages:
            delta = s["value"] if s["type"] == "gain" else -s["value"]
            current_dbm += delta
            chain.append({
                "name": s["name"],
                "delta": delta,
                "power_dbm": round(current_dbm, 4),
                "power_dbw": round(current_dbm - 30, 4),
                "power_w": round(10 ** ((current_dbm - 30) / 10), 6),
            })
        chain_result = {
            "start_dbm": round(convert_power(start_power, start_unit, "dBm"), 4),
            "final_dbm": round(current_dbm, 4),
            "final_dbw": round(current_dbm - 30, 4),
            "final_w": round(10 ** ((current_dbm - 30) / 10), 6),
            "stages": chain,
        }
    except Exception as e:
        chain_result = None

    return templates.TemplateResponse(request, "calculator_power.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "result": None,
        "chain_result": chain_result,
        "form": dict(form),
        "page": "calculator", "page_name": "power",
    })
