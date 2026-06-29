from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime
from typing import Optional
from app.database import get_db
from app.deps import require_supervisor, get_current_range_state, is_testing_state
from app.models import AuditLog, User

router = APIRouter(prefix="/audit")
from app.templating import templates

PAGE_SIZE = 100

ACTION_TYPES = [
    "LOG_CREATE", "LOG_EDIT", "LOG_SOFT_DELETE", "LOG_RESTORE",
    "DASHBOARD_UPDATE", "RANGE_STATE_CHANGE",
    "CBM_SYNC_ACTIVE", "CBM_SYNC_ISSUE", "CBM_TEST", "CBM_TEST_FAILED",
    "USER_CREATE", "USER_TOGGLE", "USER_RESET_PASSWORD",
    "LOGIN", "LOGOUT",
]


@router.get("", response_class=HTMLResponse)
async def audit_list(
    request: Request,
    action: str = "",
    username: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    q = (
        db.query(AuditLog)
        .join(User, AuditLog.user_id == User.id, isouter=True)
        .filter(AuditLog.is_testing == is_testing_state(db))
    )

    if action:
        q = q.filter(AuditLog.action_type == action)
    if username:
        q = q.filter(User.username.ilike(f"%{username}%"))
    if date_from:
        try:
            q = q.filter(AuditLog.timestamp >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(AuditLog.timestamp <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    total = q.count()
    entries = (
        q.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    # Eagerly load user display names into a dict to avoid N+1
    user_ids = {e.user_id for e in entries if e.user_id}
    users_map = {
        u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    return templates.TemplateResponse(request, "audit_log.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "entries": entries,
        "users_map": users_map,
        "action_types": ACTION_TYPES,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "filters": {
            "action": action,
            "username": username,
            "date_from": date_from,
            "date_to": date_to,
        },
        "page_name": "audit",
    })
