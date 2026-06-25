from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import User, AuditLog
from app.auth import hash_password, verify_password, validate_password
from app.templating import templates

router = APIRouter(prefix="/account")


@router.get("/password", response_class=HTMLResponse)
async def password_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "account_password.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "must_change": current_user.must_change_password,
        "error": None,
        "page": "account",
    })


@router.post("/password", response_class=HTMLResponse)
async def password_save(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    def fail(msg: str):
        return templates.TemplateResponse(request, "account_password.html", {
            "user": current_user,
            "range_state": get_current_range_state(db),
            "must_change": current_user.must_change_password,
            "error": msg,
            "page": "account",
        }, status_code=400)

    if not verify_password(current_password, current_user.password_hash):
        return fail("Current password is incorrect.")
    if new_password != confirm_password:
        return fail("New password and confirmation do not match.")
    if verify_password(new_password, current_user.password_hash):
        return fail("New password must be different from the current one.")
    policy_error = validate_password(new_password, current_user.username)
    if policy_error:
        return fail(policy_error)

    current_user.password_hash = hash_password(new_password)
    current_user.must_change_password = False
    db.add(AuditLog(user_id=current_user.id, action_type="PASSWORD_CHANGE",
                    entity_type="User", entity_id=current_user.id))
    db.commit()
    return RedirectResponse("/?toast=Password+updated", status_code=302)
