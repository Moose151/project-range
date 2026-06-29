from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import User, DutyRole
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
    duty_roles = db.query(DutyRole).filter(DutyRole.is_active == True).order_by(
        DutyRole.display_order, DutyRole.name
    ).all()
    return templates.TemplateResponse(request, "preferences.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "freq_units": FREQ_UNITS,
        "power_units": POWER_UNITS,
        "duty_roles": duty_roles,
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


@router.post("/duty-role")
async def duty_role_save(
    duty_role: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the current user's own duty-role tag. Available to every account type
    (including read-only Observers) — it's a personal display setting."""
    name = duty_role.strip()
    if not name:
        current_user.duty_role = None
        current_user.duty_role_color = None
    else:
        role = db.query(DutyRole).filter(
            DutyRole.name == name, DutyRole.is_active == True
        ).first()
        if role:
            current_user.duty_role = role.name
            current_user.duty_role_color = role.color
    db.commit()
    return RedirectResponse("/preferences?toast=Role+updated", status_code=302)
