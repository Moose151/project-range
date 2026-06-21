from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from app.models import User
from app.config import SESSION_TIMEOUT_MINUTES


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


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
    elapsed = datetime.utcnow() - datetime.fromisoformat(logged_in_at)
    return elapsed > timedelta(minutes=SESSION_TIMEOUT_MINUTES)
