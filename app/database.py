from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import AUDIT_ARCHIVE_DIR, DATABASE_URL, SERIAL_ARCHIVE_DIR
from app.file_security import harden_sqlite_storage

harden_sqlite_storage(DATABASE_URL, [AUDIT_ARCHIVE_DIR, SERIAL_ARCHIVE_DIR])
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
