"""Archive signal logs for old closed serials to XLSX, then prune from the live table.

The serial record itself is kept so the serial still shows in History. Only the
individual signal_log rows are exported and removed, keeping the live table small.

Testing-scope logs are deleted without archiving (transient data).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.config import SERIAL_ARCHIVE_DIR
from app.models import AuditLog, Serial, SignalLog


@dataclass
class SignalLogArchiveResult:
    serials_processed: int = 0
    logs_archived: int = 0
    logs_deleted: int = 0
    paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.dry_run:
            return (
                f"Dry run: {self.serials_processed} closed serials found older than "
                f"the retention period with {self.logs_archived + self.logs_deleted} log rows."
            )
        parts = []
        if self.logs_archived:
            parts.append(f"{self.logs_archived} live log rows archived to XLSX")
        if self.logs_deleted:
            parts.append(f"{self.logs_deleted} testing log rows deleted")
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        return "; ".join(parts) if parts else "Nothing to archive."


def archive_old_signal_logs(
    db: Session,
    retain_months: int = 12,
    actor_id: int | None = None,
    dry_run: bool = False,
) -> SignalLogArchiveResult:
    """Export and delete signal_logs for closed serials older than retain_months.

    Caller is responsible for beginning/committing a transaction if operating
    outside a request context.
    """
    cutoff = datetime.utcnow() - timedelta(days=retain_months * 30)
    result = SignalLogArchiveResult(dry_run=dry_run)

    old_serials = (
        db.query(Serial)
        .filter(Serial.closed_at != None, Serial.closed_at < cutoff)
        .order_by(Serial.closed_at.asc())
        .all()
    )

    for serial in old_serials:
        logs = (
            db.query(SignalLog)
            .filter(SignalLog.serial_id == serial.id)
            .order_by(SignalLog.timestamp.asc(), SignalLog.id.asc())
            .all()
        )
        if not logs:
            result.serials_processed += 1
            continue

        log_ids = [lg.id for lg in logs]
        n = len(logs)

        if dry_run:
            result.serials_processed += 1
            if serial.is_testing:
                result.logs_deleted += n
            else:
                result.logs_archived += n
            continue

        if serial.is_testing:
            db.query(SignalLog).filter(SignalLog.id.in_(log_ids)).delete(synchronize_session=False)
            result.logs_deleted += n
        else:
            try:
                path = _export_serial_logs(serial, logs)
                result.paths.append(str(path))
            except Exception as exc:
                result.errors.append(f"Serial {serial.id} ({serial.title!r}): {exc}")
                continue
            db.query(SignalLog).filter(SignalLog.id.in_(log_ids)).delete(synchronize_session=False)
            result.logs_archived += n

        db.add(AuditLog(
            user_id=actor_id,
            action_type="SIGNAL_LOG_ARCHIVE",
            entity_type="Serial",
            entity_id=serial.id,
            new_value=str(n),
            comment=(
                f"Archived {n} signal log rows for serial {serial.id!r} "
                f"(closed {serial.closed_at:%Y-%m-%d}); retain_months={retain_months}."
            ),
            is_testing=serial.is_testing,
        ))
        result.serials_processed += 1

    if not dry_run and (result.logs_archived or result.logs_deleted):
        db.commit()

    return result


def _export_serial_logs(serial: Serial, logs: list[SignalLog]) -> Path:
    """Write signal logs for one serial to an XLSX file and return its path."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", serial.title or "serial").strip("_")[:60] or "serial"
    scope = "testing" if serial.is_testing else "live"
    opened = serial.opened_at.strftime("%Y%m%d") if serial.opened_at else datetime.utcnow().strftime("%Y%m%d")
    SERIAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = SERIAL_ARCHIVE_DIR / f"logs-{scope}-{serial.id}-{opened}-{safe}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Signal Logs"
    ws.append([
        "ID", "Timestamp (Zulu)", "Operator", "Serial ID", "Serial Title",
        "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Freq Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No", "BER",
        "Activity Ref", "Notes", "Entry Type", "Deleted",
    ])
    for lg in logs:
        ws.append([
            lg.id,
            lg.timestamp.strftime("%Y-%m-%d %H:%M:%SZ") if lg.timestamp else "",
            lg.operator.username if lg.operator else "",
            serial.id,
            serial.title or "",
            lg.range_state or "",
            lg.signal_name or "",
            lg.signal_status or "",
            lg.tx_if,
            lg.tx_rf,
            lg.rx_rf,
            lg.rx_if,
            lg.freq_unit or "",
            lg.band or "",
            lg.modulation or "",
            lg.symbol_rate or "",
            lg.fec or "",
            lg.source or "",
            lg.antenna or "",
            lg.power,
            lg.power_unit or "",
            lg.eb_no,
            lg.ber_estimate,
            lg.activity_ref or "",
            lg.notes or "",
            lg.entry_type or "",
            "yes" if lg.is_deleted else "no",
        ])

    ws.freeze_panes = "A2"
    for col in ws.columns:
        letter = col[0].column_letter
        max_len = max(len(str(cell.value or "")) for cell in col[:200])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 60)

    wb.save(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
