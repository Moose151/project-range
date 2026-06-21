from datetime import datetime
from fastapi import Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Role, LogSession, Serial
from app.auth import session_is_expired


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id or session_is_expired(request.session):
        request.session.clear()
        raise HTTPException(status_code=302, headers={"Location": "/login?timeout=1"})
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    # Refresh session activity timestamp
    request.session["logged_in_at"] = datetime.utcnow().isoformat()
    return user


def require_supervisor(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != Role.SUPERVISOR:
        raise HTTPException(status_code=403, detail="Supervisor access required")
    return current_user


def get_current_range_state(db: Session) -> str:
    from app.models import RangeStateLog
    latest = db.query(RangeStateLog).order_by(RangeStateLog.id.desc()).first()
    return latest.new_state if latest else "Standby/Off"


def get_active_session(db: Session) -> LogSession | None:
    """Legacy helper — returns the most recent open LogSession (old data only)."""
    return (
        db.query(LogSession)
        .filter(LogSession.closed_at == None)
        .order_by(LogSession.opened_at.desc())
        .first()
    )


def get_active_serials(db: Session) -> list[Serial]:
    """Return all started, open Serials ordered by start time."""
    return (
        db.query(Serial)
        .filter(Serial.closed_at == None, Serial.is_started == True)
        .order_by(Serial.opened_at.asc())
        .all()
    )
