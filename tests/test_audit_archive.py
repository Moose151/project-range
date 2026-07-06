"""Standalone unit checks for audit retention/archive.

Run: venv/bin/python tests/test_audit_archive.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.audit_archive import apply_audit_retention  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import AuditLog  # noqa: E402


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, count, is_testing):
    now = datetime.utcnow()
    for i in range(count):
        db.add(AuditLog(
            timestamp=now - timedelta(minutes=i),
            action_type=f"TEST_{i}",
            is_testing=is_testing,
        ))
    db.commit()
    db.query(AuditLog).update({"is_testing": is_testing}, synchronize_session=False)
    db.commit()


def test_live_rows_archive_then_delete():
    with tempfile.TemporaryDirectory() as tmp:
        import app.audit_archive as audit_archive

        audit_archive.AUDIT_ARCHIVE_DIR = Path(tmp)
        db = make_db()
        seed(db, 5, is_testing=False)
        result = apply_audit_retention(db, is_testing=False, keep=2)
        assert result.archived == 3
        assert result.deleted == 3
        assert result.path and Path(result.path).exists()
        assert db.query(AuditLog).filter(AuditLog.is_testing == False).count() == 2  # noqa: E712


def test_testing_rows_prune_without_archive():
    with tempfile.TemporaryDirectory() as tmp:
        import app.audit_archive as audit_archive

        audit_archive.AUDIT_ARCHIVE_DIR = Path(tmp)
        db = make_db()
        seed(db, 5, is_testing=True)
        result = apply_audit_retention(db, is_testing=True, keep=2)
        assert result.archived == 0
        assert result.deleted == 3
        assert result.path is None
        assert not list(Path(tmp).glob("*.xlsx"))
        assert db.query(AuditLog).filter(AuditLog.is_testing == True).count() == 2  # noqa: E712


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} audit retention tests passed.")


if __name__ == "__main__":
    main()
