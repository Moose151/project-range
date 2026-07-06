"""Tamper-evident audit log hash chain helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from app.config import AUDIT_HASH_SECRET

HASH_VERSION = 1


@dataclass
class AuditIntegrityStatus:
    checked: int = 0
    unsigned: int = 0
    broken: int = 0
    anchored: bool = False
    first_problem_id: int | None = None
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.broken == 0 and self.unsigned == 0


def _normalise_timestamp(value) -> str:
    if isinstance(value, datetime):
        return value.replace(microsecond=value.microsecond).isoformat()
    return str(value or "")


def audit_hash_payload(audit, previous_hash: str | None) -> dict:
    return {
        "hash_version": HASH_VERSION,
        "timestamp": _normalise_timestamp(getattr(audit, "timestamp", None)),
        "user_id": getattr(audit, "user_id", None),
        "action_type": getattr(audit, "action_type", "") or "",
        "entity_type": getattr(audit, "entity_type", None),
        "entity_id": getattr(audit, "entity_id", None),
        "previous_value": getattr(audit, "previous_value", None),
        "new_value": getattr(audit, "new_value", None),
        "comment": getattr(audit, "comment", None),
        "is_testing": bool(getattr(audit, "is_testing", False)),
        "previous_hash": previous_hash or "",
    }


def calculate_audit_hash(audit, previous_hash: str | None) -> str:
    payload = audit_hash_payload(audit, previous_hash)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hmac.new(
        AUDIT_HASH_SECRET.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign_audit_row(audit, previous_hash: str | None) -> None:
    audit.previous_hash = previous_hash or None
    audit.hash_version = HASH_VERSION
    audit.record_hash = calculate_audit_hash(audit, audit.previous_hash)


def verify_audit_rows(rows: Iterable) -> AuditIntegrityStatus:
    status = AuditIntegrityStatus()
    expected_previous: str | None = None
    first = True
    for audit in rows:
        status.checked += 1
        previous_hash = getattr(audit, "previous_hash", None)
        record_hash = getattr(audit, "record_hash", None)
        if not previous_hash and first:
            expected_previous = None
        elif first:
            status.anchored = True
            expected_previous = previous_hash
        elif previous_hash != expected_previous:
            status.broken += 1
            status.first_problem_id = status.first_problem_id or getattr(audit, "id", None)
            expected_previous = record_hash
            first = False
            continue

        if not record_hash:
            status.unsigned += 1
            status.first_problem_id = status.first_problem_id or getattr(audit, "id", None)
        else:
            calculated = calculate_audit_hash(audit, previous_hash)
            if calculated != record_hash:
                status.broken += 1
                status.first_problem_id = status.first_problem_id or getattr(audit, "id", None)
        expected_previous = record_hash
        first = False

    if status.checked == 0:
        status.note = "No audit records in this scope."
    elif status.ok and status.anchored:
        status.note = "Current live chain verifies from an archived/pruned anchor."
    elif status.ok:
        status.note = "Audit hash chain verifies."
    elif status.unsigned:
        status.note = "One or more audit records are not signed."
    else:
        status.note = "Audit hash chain is broken."
    return status


def verify_audit_scope(db, *, is_testing: bool) -> AuditIntegrityStatus:
    from app.models import AuditLog

    rows = (
        db.query(AuditLog)
        .filter(AuditLog.is_testing == is_testing)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    return verify_audit_rows(rows)


def backfill_audit_hashes(db, *, is_testing: bool) -> int:
    from app.models import AuditLog

    rows = (
        db.query(AuditLog)
        .filter(AuditLog.is_testing == is_testing)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    previous_hash = None
    changed = 0
    for audit in rows:
        if not audit.record_hash:
            audit.previous_hash = previous_hash
            audit.record_hash = calculate_audit_hash(audit, previous_hash)
            audit.hash_version = HASH_VERSION
            changed += 1
        previous_hash = audit.record_hash
    if changed:
        db.commit()
    return changed
