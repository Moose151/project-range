"""Standalone checks for audit log integrity hashes.

Run: venv/bin/python tests/test_audit_integrity.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.audit_integrity import backfill_audit_hashes, verify_audit_scope  # noqa: E402
from app.database import Base  # noqa: E402
from app.models import AuditLog  # noqa: E402


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_new_audit_rows_are_chained():
    db = make_db()
    db.add(AuditLog(action_type="ONE", is_testing=False))
    db.add(AuditLog(action_type="TWO", is_testing=False))
    db.commit()

    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    assert rows[0].record_hash
    assert rows[0].previous_hash is None
    assert rows[1].previous_hash == rows[0].record_hash
    assert verify_audit_scope(db, is_testing=False).ok is True


def test_tampered_audit_row_is_detected():
    db = make_db()
    db.add(AuditLog(action_type="ONE", new_value="original", is_testing=False))
    db.commit()

    row = db.query(AuditLog).first()
    row.new_value = "changed after signing"
    db.commit()

    status = verify_audit_scope(db, is_testing=False)
    assert status.ok is False
    assert status.broken == 1
    assert status.first_problem_id == row.id


def test_backfill_signs_unsigned_existing_rows():
    db = make_db()
    now = datetime.utcnow()
    for i in range(3):
        db.add(AuditLog(
            timestamp=now + timedelta(seconds=i),
            action_type=f"OLD_{i}",
            is_testing=False,
        ))
    db.commit()
    db.query(AuditLog).update(
        {"previous_hash": None, "record_hash": None},
        synchronize_session=False,
    )
    db.commit()

    assert verify_audit_scope(db, is_testing=False).ok is False
    changed = backfill_audit_hashes(db, is_testing=False)
    assert changed == 3
    assert verify_audit_scope(db, is_testing=False).ok is True


def test_backfill_does_not_repair_tampered_signed_rows():
    db = make_db()
    db.add(AuditLog(action_type="SIGNED", new_value="original", is_testing=False))
    db.commit()

    row = db.query(AuditLog).first()
    original_hash = row.record_hash
    row.new_value = "tampered"
    db.commit()

    changed = backfill_audit_hashes(db, is_testing=False)
    db.refresh(row)
    assert changed == 0
    assert row.record_hash == original_hash
    assert verify_audit_scope(db, is_testing=False).ok is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(tests)} audit integrity tests passed.")
