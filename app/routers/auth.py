from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import AuditLog
from app.auth import (
    authenticate_user, login_lock_remaining, register_failed_login, reset_login_attempts,
)
from app import chat_state

router = APIRouter()
from app.templating import templates


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, timeout: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {
        "error": None,
        "timeout": timeout == "1",
    })


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember: str = Form(""),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    key = f"{username.strip().casefold()}|{ip}"

    locked = login_lock_remaining(key)
    if locked:
        db.add(AuditLog(user_id=None, action_type="LOGIN_LOCKED",
                        comment=f"{username} from {ip}"))
        db.commit()
        mins = max(1, locked // 60)
        return templates.TemplateResponse(request, "login.html", {
            "error": f"Too many failed attempts. Try again in about {mins} minute(s).",
            "timeout": False,
        }, status_code=429)

    user = authenticate_user(db, username, password)
    if not user:
        register_failed_login(key)
        db.add(AuditLog(user_id=None, action_type="LOGIN_FAILED",
                        comment=f"{username} from {ip}"))
        db.commit()
        return templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password.",
            "timeout": False,
        }, status_code=401)

    reset_login_attempts(key)
    db.add(AuditLog(user_id=user.id, action_type="LOGIN_SUCCESS",
                    comment=f"{user.username} from {ip}"))
    db.commit()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["display_name"] = user.display_name
    request.session["role"] = user.role.value if hasattr(user.role, "value") else str(user.role)
    request.session["logged_in_at"] = datetime.utcnow().isoformat()
    request.session["remember"] = bool(remember)
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    user_id = request.session.get("user_id")
    if user_id:
        chat_state.forget_user(user_id)
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
