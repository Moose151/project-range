from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state
from app.models import (
    User, Role, AuditLog, SignalLog, RangeStateLog, SignalPackage, Serial,
    LogSession, FrequencyTemplate, DocPage, DocVersion, CDATable, Incident, CeaseEvent,
)
from app.auth import hash_password, validate_password

router = APIRouter(prefix="/users")
from app.templating import templates


def _role_values() -> list[str]:
    return [r.value for r in Role]


def _active_administrator_count(db: Session) -> int:
    return db.query(User).filter(
        User.role == Role.ADMINISTRATOR,
        User.is_archived == False,
        User.is_active == True,
    ).count()


def _is_last_active_administrator(db: Session, target: User) -> bool:
    return (
        target.role == Role.ADMINISTRATOR
        and not target.is_archived
        and target.is_active
        and _active_administrator_count(db) <= 1
    )


def _users_context(db: Session, current_user: User, show_archived: bool = False, error: str | None = None) -> dict:
    users = (
        db.query(User)
        .filter(User.is_archived == show_archived)
        .order_by(User.username)
        .all()
    )
    archived_count = db.query(User).filter(User.is_archived == True).count()
    ctx = {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "users": users,
        "roles": _role_values(),
        "show_archived": show_archived,
        "archived_count": archived_count,
        "page": "users",
    }
    if error:
        ctx["error"] = error
    return ctx


@router.get("", response_class=HTMLResponse)
async def user_list(
    request: Request,
    archived: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    return templates.TemplateResponse(
        request,
        "users.html",
        _users_context(db, current_user, show_archived=(archived == "1")),
    )


@router.post("/new")
async def user_create(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    def with_error(msg: str):
        return templates.TemplateResponse(
            request,
            "users.html",
            _users_context(db, current_user, error=msg),
            status_code=400,
        )

    if db.query(User).filter(User.username == username.strip().lower()).first():
        return with_error(f"Username '{username}' already exists.")
    policy_error = validate_password(password, username)
    if policy_error:
        return with_error(policy_error)
    if role not in _role_values():
        role = Role.USER.value
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


@router.post("/{user_id}/update")
async def user_update(
    user_id: int,
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    role: str = Form("user"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/users", status_code=302)

    new_username = username.strip().lower()
    new_display = display_name.strip()
    if not new_username or not new_display:
        return templates.TemplateResponse(
            request,
            "users.html",
            _users_context(db, current_user, show_archived=target.is_archived, error="Username and display name are required."),
            status_code=400,
        )
    existing = db.query(User).filter(User.username == new_username, User.id != target.id).first()
    if existing:
        return templates.TemplateResponse(
            request,
            "users.html",
            _users_context(db, current_user, show_archived=target.is_archived, error=f"Username '{new_username}' already exists."),
            status_code=400,
        )
    if role not in _role_values():
        role = target.role.value if hasattr(target.role, "value") else str(target.role)
    if role != Role.ADMINISTRATOR.value and _is_last_active_administrator(db, target):
        return templates.TemplateResponse(
            request,
            "users.html",
            _users_context(db, current_user, show_archived=target.is_archived, error="At least one active Administrator account is required."),
            status_code=400,
        )

    previous = f"{target.username} / {target.display_name} / {target.role_label}"
    target.username = new_username
    target.display_name = new_display
    target.role = role
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="USER_UPDATE",
        entity_type="User",
        entity_id=target.id,
        previous_value=previous,
        new_value=f"{target.username} / {target.display_name} / {target.role_label}",
    ))
    db.commit()
    if target.id == current_user.id:
        request.session["username"] = target.username
        request.session["display_name"] = target.display_name
        request.session["role"] = target.role.value if hasattr(target.role, "value") else str(target.role)
    suffix = "?archived=1" if target.is_archived else ""
    return RedirectResponse(f"/users{suffix}", status_code=302)


@router.post("/{user_id}/delete")
async def user_delete(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target or target.id == current_user.id:
        return RedirectResponse("/users", status_code=302)
    if _is_last_active_administrator(db, target):
        return templates.TemplateResponse(
            request,
            "users.html",
            _users_context(db, current_user, show_archived=target.is_archived, error="At least one active Administrator account is required."),
            status_code=400,
        )

    blocking_checks = [
        ("signal logs", db.query(SignalLog).filter(SignalLog.operator_id == target.id).count()),
        ("legacy log sessions", db.query(LogSession).filter(LogSession.opened_by_id == target.id).count()),
        ("range state changes", db.query(RangeStateLog).filter(RangeStateLog.changed_by_id == target.id).count()),
        ("signal packages", db.query(SignalPackage).filter(SignalPackage.created_by_id == target.id).count()),
        ("serials opened", db.query(Serial).filter(Serial.opened_by_id == target.id).count()),
        ("frequency templates", db.query(FrequencyTemplate).filter(FrequencyTemplate.created_by_id == target.id).count()),
        ("documentation pages", db.query(DocPage).filter(DocPage.created_by_id == target.id).count()),
        ("documentation versions", db.query(DocVersion).filter(DocVersion.created_by_id == target.id).count()),
        ("CDA tables", db.query(CDATable).filter(CDATable.created_by_id == target.id).count()),
        ("incidents", db.query(Incident).filter(Incident.reported_by_id == target.id).count()),
        ("CEASE events", db.query(CeaseEvent).filter(CeaseEvent.raised_by_id == target.id).count()),
    ]
    blockers = [name for name, count in blocking_checks if count]
    if blockers:
        return templates.TemplateResponse(request, "users.html", {
            **_users_context(db, current_user, show_archived=target.is_archived),
            "error": (
                f"Cannot delete '{target.username}' because the account has "
                f"attributed records ({', '.join(blockers)}). Archive the account instead."
            ),
        }, status_code=400)

    db.query(AuditLog).filter(AuditLog.user_id == target.id).update({"user_id": None})
    db.query(SignalLog).filter(SignalLog.updated_by_id == target.id).update({"updated_by_id": None})
    db.query(Serial).filter(Serial.closed_by_id == target.id).update({"closed_by_id": None})
    db.query(LogSession).filter(LogSession.closed_by_id == target.id).update({"closed_by_id": None})
    db.query(DocPage).filter(DocPage.updated_by_id == target.id).update({"updated_by_id": None})
    db.query(DocVersion).filter(DocVersion.approved_by_id == target.id).update({"approved_by_id": None})
    db.query(Incident).filter(Incident.approved_by_id == target.id).update({"approved_by_id": None})
    db.query(Incident).filter(Incident.resolved_by_id == target.id).update({"resolved_by_id": None})
    db.query(CeaseEvent).filter(CeaseEvent.dismissed_by_id == target.id).update({"dismissed_by_id": None})
    username = target.username
    db.delete(target)
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="USER_DELETE",
        entity_type="User",
        entity_id=user_id,
        previous_value=username,
    ))
    db.commit()
    return RedirectResponse("/users?toast=Account+deleted", status_code=302)


@router.post("/{user_id}/archive")
async def user_archive(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != current_user.id:
        if _is_last_active_administrator(db, target):
            return templates.TemplateResponse(
                request,
                "users.html",
                _users_context(db, current_user, error="At least one active Administrator account is required."),
                status_code=400,
            )
        target.is_archived = True
        target.is_active = False
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="USER_ARCHIVE",
            entity_type="User",
            entity_id=target.id,
            new_value=target.username,
        ))
        db.commit()
    return RedirectResponse("/users", status_code=302)


@router.post("/{user_id}/restore")
async def user_restore(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target:
        target.is_archived = False
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="USER_RESTORE",
            entity_type="User",
            entity_id=target.id,
            new_value=target.username,
        ))
        db.commit()
    return RedirectResponse("/users?archived=1", status_code=302)


@router.post("/{user_id}/toggle")
async def user_toggle_active(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    target = db.query(User).filter(User.id == user_id).first()
    if target and target.id != current_user.id:
        if target.is_active and _is_last_active_administrator(db, target):
            return templates.TemplateResponse(
                request,
                "users.html",
                _users_context(db, current_user, show_archived=target.is_archived, error="At least one active Administrator account is required."),
                status_code=400,
            )
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
            return templates.TemplateResponse(request, "users.html", {
                **_users_context(db, current_user, show_archived=target.is_archived),
                "error": f"{target.username}: {policy_error}",
            }, status_code=400)
        target.password_hash = hash_password(new_password)
        target.must_change_password = True  # user picks their own at next login
        db.add(AuditLog(user_id=current_user.id, action_type="USER_RESET_PASSWORD",
                        entity_type="User", entity_id=target.id, new_value=target.username))
        db.commit()
    return RedirectResponse("/users", status_code=302)
