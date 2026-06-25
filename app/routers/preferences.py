from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import User
from app.templating import templates

router = APIRouter(prefix="/preferences")

FREQ_UNITS = ["MHz", "GHz"]
POWER_UNITS = ["dBm", "dBW", "W"]


@router.get("", response_class=HTMLResponse)
async def preferences_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "preferences.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "freq_units": FREQ_UNITS,
        "power_units": POWER_UNITS,
        "toast": request.query_params.get("toast", ""),
        "page": "preferences",
    })


@router.post("")
async def preferences_save(
    default_freq_unit: str = Form("MHz"),
    default_power_unit: str = Form("dBm"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if default_freq_unit in FREQ_UNITS:
        current_user.default_freq_unit = default_freq_unit
    if default_power_unit in POWER_UNITS:
        current_user.default_power_unit = default_power_unit
    db.commit()
    return RedirectResponse("/preferences?toast=Preferences+saved", status_code=302)
