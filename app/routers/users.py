from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state
from app.models import User, Role
from app.auth import hash_password

router = APIRouter(prefix="/users")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def user_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    users = db.query(User).order_by(User.username).all()
    return templates.TemplateResponse(request, "users.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "users": users,
        "roles": [r.value for r in Role],
        "page": "users",
    })


@router.post("/new")
async def user_create(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("operator"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        users = db.query(User).order_by(User.username).all()
        return templates.TemplateResponse(request, "users.html", {
            "user": current_user,
            "range_state": get_current_range_state(db),
            "users": users,
            "roles": [r.value for r in Role],
            "error": f"Username '{username}' already exists.",
            "page": "users",
        })
    new_user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/users", status_code=302)


@router.post("/{user_id}/toggle")
async def user_toggle_active(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != current_user.id:
        target.is_active = not target.is_active
        db.commit()
    return RedirectResponse("/users", status_code=302)


@router.post("/{user_id}/reset-password")
async def user_reset_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.password_hash = hash_password(new_password)
        db.commit()
    return RedirectResponse("/users", status_code=302)
