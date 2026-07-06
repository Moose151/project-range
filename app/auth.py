import time
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from app.models import User
from app.config import (
    SESSION_TIMEOUT_MINUTES, SESSION_MAX_AGE_DAYS, MIN_PASSWORD_LENGTH,
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
    user = db.query(User).filter(
        User.username == username,
        User.is_active == True,
        User.is_archived == False,
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.utcnow()
    db.commit()
    return user


def start_authenticated_session(session: dict, user: User, session_token: str, remember: bool) -> None:
    """Replace any anonymous/pre-login session state with authenticated claims.

    Starlette's signed cookie session has no server-side session id to rotate, so
    clearing before setting auth claims is the fixation defence: any state that
    existed before login is discarded and a fresh signed cookie is emitted.
    """
    now = datetime.utcnow().isoformat()
    session.clear()
    session["user_id"] = user.id
    session["username"] = user.username
    session["display_name"] = user.display_name
    session["role"] = user.role.value if hasattr(user.role, "value") else str(user.role)
    session["logged_in_at"] = now
    session["session_issued_at"] = now
    session["remember"] = bool(remember)
    session["session_token"] = session_token


def session_is_expired(session: dict) -> bool:
    logged_in_at = session.get("logged_in_at")
    if not logged_in_at:
        return True
    issued_at = session.get("session_issued_at")
    if issued_at:
        try:
            if datetime.utcnow() - datetime.fromisoformat(issued_at) > timedelta(days=SESSION_MAX_AGE_DAYS):
                return True
        except ValueError:
            return True
    # "Remember this terminal" sessions are not subject to the inactivity timeout
    # (they last until the session cookie itself expires or the user logs out).
    if session.get("remember"):
        return False
    try:
        elapsed = datetime.utcnow() - datetime.fromisoformat(logged_in_at)
    except ValueError:
        return True
    return elapsed > timedelta(minutes=SESSION_TIMEOUT_MINUTES)
