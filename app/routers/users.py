from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state
from app.models import User, Role, AuditLog
from app.auth import hash_password, validate_password

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
    def with_error(msg: str):
        users = db.query(User).order_by(User.username).all()
        return templates.TemplateResponse(request, "users.html", {
            "user": current_user,
            "range_state": get_current_range_state(db),
            "users": users,
            "roles": [r.value for r in Role],
            "error": msg,
            "page": "users",
        }, status_code=400)

    if db.query(User).filter(User.username == username.strip().lower()).first():
        return with_error(f"Username '{username}' already exists.")
    policy_error = validate_password(password, username)
    if policy_error:
        return with_error(policy_error)
    new_user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
        must_change_password=True,  # new accounts set their own password at first login
    )
    db.add(new_user)
    db.flush()
    db.add(AuditLog(user_id=current_user.id, action_type="USER_CREATE",
                    entity_type="User", entity_id=new_user.id, new_value=new_user.username))
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
        policy_error = validate_password(new_password, target.username)
        if policy_error:
            users = db.query(User).order_by(User.username).all()
            return templates.TemplateResponse(request, "users.html", {
                "user": current_user,
                "range_state": get_current_range_state(db),
                "users": users,
                "roles": [r.value for r in Role],
                "error": f"{target.username}: {policy_error}",
                "page": "users",
            }, status_code=400)
        target.password_hash = hash_password(new_password)
        target.must_change_password = True  # user picks their own at next login
        db.add(AuditLog(user_id=current_user.id, action_type="USER_RESET_PASSWORD",
                        entity_type="User", entity_id=target.id, new_value=target.username))
        db.commit()
    return RedirectResponse("/users", status_code=302)
