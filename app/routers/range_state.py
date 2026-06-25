from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import User, RangeStateLog, AuditLog, RangeState, Role
from app.auth import verify_password

router = APIRouter(prefix="/range-state")
from app.templating import templates

VALID_STATES = [s.value for s in RangeState]


def _render_change(request, db, current_user, current, error):
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": "Live",
        "valid_states": [s for s in VALID_STATES if s != current],
        "range_state": current,
        "error": error,
        "page": "range_state",
    }, status_code=400)


@router.get("/change", response_class=HTMLResponse)
async def change_state_page(
    request: Request,
    target: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current = get_current_range_state(db)
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": target,
        "valid_states": [s for s in VALID_STATES if s != current],
        "range_state": current,
        "page": "range_state",
    })


@router.post("/change", response_class=HTMLResponse)
async def change_state_submit(
    request: Request,
    new_state: str = Form(...),
    reason: str = Form(...),
    acknowledge: str = Form(""),
    supervisor_username: str = Form(""),
    supervisor_password: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if new_state not in VALID_STATES:
        return RedirectResponse("/range-state/change", status_code=302)

    current = get_current_range_state(db)
    if new_state == current:
        return RedirectResponse("/", status_code=302)

    reason = reason.strip()
    approver = current_user  # who authorised the change

    # Going Live requires a safety acknowledgment and supervisor authorisation.
    if new_state == "Live":
        if acknowledge != "1":
            return _render_change(request, db, current_user, current,
                                  "You must confirm the safety acknowledgment before going Live.")
        if current_user.role != Role.SUPERVISOR:
            sup = db.query(User).filter(
                User.username == supervisor_username.strip().lower(),
                User.is_active == True, User.role == Role.SUPERVISOR,
            ).first()
            if not sup or not verify_password(supervisor_password, sup.password_hash):
                return _render_change(request, db, current_user, current,
                                      "A valid supervisor username and password are required to go Live.")
            approver = sup
            reason = f"{reason} [Authorised by {sup.display_name}; initiated by {current_user.display_name}]"

    entry = RangeStateLog(
        previous_state=current,
        new_state=new_state,
        changed_by_id=current_user.id,
        reason=reason,
    )
    db.add(entry)

    audit = AuditLog(
        user_id=current_user.id,
        action_type="RANGE_STATE_CHANGE",
        entity_type="RangeStateLog",
        previous_value=current,
        new_value=new_state,
        comment=(reason + (f" (approved by {approver.username})" if approver.id != current_user.id else "")),
    )
    db.add(audit)
    db.commit()

    from urllib.parse import quote
    msg = quote(f"Range state changed to {new_state}")
    return RedirectResponse(f"/?toast={msg}", status_code=302)
