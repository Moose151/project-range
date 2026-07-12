from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import AUDIT_ARCHIVE_DIR, DATABASE_URL, SERIAL_ARCHIVE_DIR
from app.file_security import harden_sqlite_storage

harden_sqlite_storage(DATABASE_URL, [AUDIT_ARCHIVE_DIR, SERIAL_ARCHIVE_DIR])
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL lets the frequent dashboard-poll reads run concurrently with the
        # background CBM/SNMP sync writes instead of blocking each other;
        # synchronous=NORMAL is the safe WAL companion; busy_timeout avoids
        # spurious "database is locked" errors under concurrent access.
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
