"""Audit log retention and spreadsheet archiving."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.config import AUDIT_ARCHIVE_DIR
from app.models import AuditLog, User
from app.settings import get_audit_live_record_limit


@dataclass
class AuditRetentionResult:
    archived: int = 0
    deleted: int = 0
    path: str | None = None


def apply_audit_retention(db: Session, is_testing: bool, keep: int | None = None) -> AuditRetentionResult:
    """Apply audit retention for one workspace scope.

    Live rows are exported to an XLSX file first, then removed. Testing/sandbox
    rows are transient and are pruned without archive once newer records replace them.
    """
    keep = get_audit_live_record_limit(db) if keep is None else max(1, keep)
    total = db.query(AuditLog.id).filter(AuditLog.is_testing == is_testing).count()
    if total <= keep:
        return AuditRetentionResult()

    rows = (
        db.query(AuditLog, User.username, User.display_name)
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(AuditLog.is_testing == is_testing)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .offset(keep)
        .all()
    )
    if not rows:
        return AuditRetentionResult()

    archive_ids = [audit.id for audit, _username, _display_name in rows]
    if is_testing:
        db.query(AuditLog).filter(AuditLog.id.in_(archive_ids)).delete(synchronize_session=False)
        db.commit()
        return AuditRetentionResult(deleted=len(archive_ids))

    scope = "testing" if is_testing else "live"
    now = datetime.utcnow()
    min_id, max_id = min(archive_ids), max(archive_ids)
    AUDIT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_ARCHIVE_DIR / f"audit-{scope}-{now:%Y%m%d-%H%M%SZ}-ids-{min_id}-{max_id}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Log"
    ws.append([
        "ID", "Timestamp (Zulu)", "Username", "Display Name", "Action",
        "Entity Type", "Entity ID", "Previous Value", "New Value", "Comment", "Scope",
    ])
    for audit, username, display_name in reversed(rows):
        ts = audit.timestamp.strftime("%Y-%m-%d %H:%M:%SZ") if audit.timestamp else ""
        ws.append([
            audit.id,
            ts,
            username or "",
            display_name or "",
            audit.action_type,
            audit.entity_type or "",
            audit.entity_id or "",
            audit.previous_value or "",
            audit.new_value or "",
            audit.comment or "",
            scope,
        ])

    ws.freeze_panes = "A2"
    for col in ws.columns:
        letter = col[0].column_letter
        max_len = max(len(str(cell.value or "")) for cell in col[:100])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 60)
    wb.save(path)

    db.query(AuditLog).filter(AuditLog.id.in_(archive_ids)).delete(synchronize_session=False)
    db.commit()
    return AuditRetentionResult(archived=len(archive_ids), deleted=len(archive_ids), path=str(path))
