"""Standalone unit checks for closed serial history archiving.

Run: venv/bin/python tests/test_serial_archive.py
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import AuditLog, Incident, Serial, SignalLog, User  # noqa: E402
from app.serial_archive import archive_closed_serial  # noqa: E402


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_archive_closed_serial_exports_and_removes_history():
    with tempfile.TemporaryDirectory() as tmp:
        import app.serial_archive as serial_archive

        serial_archive.SERIAL_ARCHIVE_DIR = Path(tmp)
        db = make_db()
        user = User(username="admin", password_hash="x", display_name="Admin")
        db.add(user)
        db.flush()
        serial = Serial(
            title="SER-001",
            opened_by_id=user.id,
            opened_at=datetime.utcnow(),
            closed_by_id=user.id,
            closed_at=datetime.utcnow(),
            is_started=True,
            is_testing=False,
        )
        db.add(serial)
        db.flush()
        db.add(SignalLog(
            operator_id=user.id,
            range_state="Testing",
            signal_name="SIG-01",
            signal_status="Up",
            serial_id=serial.id,
            is_testing=False,
        ))
        db.add(Incident(title="Linked incident", reported_by_id=user.id, serial_id=serial.id))
        db.commit()

        result = archive_closed_serial(db, serial, actor_id=user.id)

        assert result.archived
        assert result.logs == 1
        assert result.path and Path(result.path).exists()
        assert db.query(Serial).count() == 0
        assert db.query(SignalLog).count() == 0
        assert db.query(Incident).first().serial_id is None
        assert db.query(AuditLog).filter(AuditLog.action_type == "SERIAL_ARCHIVE").count() == 1


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} serial archive tests passed.")


if __name__ == "__main__":
    main()
