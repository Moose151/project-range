import time
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from app.models import User
from app.config import (
    SESSION_TIMEOUT_MINUTES, MIN_PASSWORD_LENGTH,
    LOGIN_MAX_ATTEMPTS, LOGIN_LOCKOUT_SECONDS,
)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def validate_password(password: str, username: str = "") -> str | None:
    """Return an error message if the password fails policy, else None."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if username and password.strip().casefold() == username.strip().casefold():
        return "Password must not be the same as the username."
    if password.strip().casefold() in {"password", "changeme", "12345678", "admin"}:
        return "That password is too common. Choose a stronger one."
    return None


# ── In-memory login throttling (per username+IP) ──────────────────────────────
# Suitable for a single-process deployment; resets on restart. For multi-worker
# or HA, move this to the database or a shared store.
_failed: dict[str, list[float]] = {}


def login_lock_remaining(key: str) -> int:
    """Seconds remaining on a lockout for this key, or 0 if not locked."""
    attempts = _failed.get(key, [])
    recent = [t for t in attempts if time.time() - t < LOGIN_LOCKOUT_SECONDS]
    _failed[key] = recent
    if len(recent) >= LOGIN_MAX_ATTEMPTS:
        return int(LOGIN_LOCKOUT_SECONDS - (time.time() - recent[0])) + 1
    return 0


def register_failed_login(key: str) -> None:
    _failed.setdefault(key, []).append(time.time())


def reset_login_attempts(key: str) -> None:
    _failed.pop(key, None)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.utcnow()
    db.commit()
    return user


def session_is_expired(session: dict) -> bool:
    logged_in_at = session.get("logged_in_at")
    if not logged_in_at:
        return True
    # "Remember this terminal" sessions are not subject to the inactivity timeout
    # (they last until the session cookie itself expires or the user logs out).
    if session.get("remember"):
        return False
    elapsed = datetime.utcnow() - datetime.fromisoformat(logged_in_at)
    return elapsed > timedelta(minutes=SESSION_TIMEOUT_MINUTES)
