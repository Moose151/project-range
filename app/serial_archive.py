"""Archive closed serial history to server-side XLSX files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.config import SERIAL_ARCHIVE_DIR
from app.models import AuditLog, Incident, Serial, SerialCDATable, SerialPackage, SignalLog


@dataclass
class SerialArchiveResult:
    archived: bool = False
    path: str | None = None
    logs: int = 0


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return safe[:80] or "serial"


def archive_closed_serial(db: Session, serial: Serial, actor_id: int | None = None) -> SerialArchiveResult:
    """Export a closed serial and remove it from the app database."""
    if not serial.closed_at:
        return SerialArchiveResult()

    serial_id = serial.id
    serial_title = serial.title
    serial_is_testing = serial.is_testing
    logs = (
        db.query(SignalLog)
        .filter(SignalLog.serial_id == serial_id, SignalLog.is_testing == serial_is_testing)
        .order_by(SignalLog.timestamp.asc(), SignalLog.id.asc())
        .all()
    )
    scope = "testing" if serial_is_testing else "live"
    SERIAL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    opened = serial.opened_at.strftime("%Y%m%d") if serial.opened_at else datetime.utcnow().strftime("%Y%m%d")
    path = SERIAL_ARCHIVE_DIR / f"serial-{scope}-{serial_id}-{opened}-{_safe_filename(serial_title)}.xlsx"

    wb = Workbook()
    summary = wb.active
    summary.title = "Serial Summary"
    summary.append(["Field", "Value"])
    summary.append(["Serial ID", serial_id])
    summary.append(["Title", serial_title])
    summary.append(["Notes", serial.notes or ""])
    summary.append(["Scope", scope])
    summary.append(["Opened At (Zulu)", serial.opened_at.strftime("%Y-%m-%d %H:%M:%SZ") if serial.opened_at else ""])
    summary.append(["Closed At (Zulu)", serial.closed_at.strftime("%Y-%m-%d %H:%M:%SZ") if serial.closed_at else ""])
    summary.append(["Opened By", serial.opened_by.username if serial.opened_by else ""])
    summary.append(["Closed By", serial.closed_by.username if serial.closed_by else ""])
    summary.append(["Log Rows", len(logs)])

    ws = wb.create_sheet("Signal Logs")
    ws.append([
        "ID", "Timestamp (Zulu)", "Operator", "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No", "BER", "Engaged", "Activity Ref",
        "Notes", "Type", "Deleted",
    ])
    for log in logs:
        ws.append([
            log.id,
            log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ") if log.timestamp else "",
            log.operator.username if log.operator else "",
            log.range_state,
            log.signal_name,
            log.signal_status,
            log.tx_if,
            log.tx_rf,
            log.rx_rf,
            log.rx_if,
            log.freq_unit,
            log.band or "",
            log.modulation or "",
            log.symbol_rate or "",
            log.fec or "",
            log.source or "",
            log.antenna or "",
            log.power,
            log.power_unit,
            log.eb_no,
            log.ber_estimate,
            "yes" if log.engaged else "no",
            log.activity_ref or "",
            log.notes or "",
            log.entry_type,
            "yes" if log.is_deleted else "no",
        ])

    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        for col in sheet.columns:
            letter = col[0].column_letter
            max_len = max(len(str(cell.value or "")) for cell in col[:100])
            sheet.column_dimensions[letter].width = min(max(max_len + 2, 10), 60)
    wb.save(path)

    db.query(Incident).filter(Incident.serial_id == serial_id).update({"serial_id": None}, synchronize_session=False)
    db.query(SerialCDATable).filter(SerialCDATable.serial_id == serial_id).delete(synchronize_session=False)
    db.query(SerialPackage).filter(SerialPackage.serial_id == serial_id).delete(synchronize_session=False)
    db.query(SignalLog).filter(SignalLog.serial_id == serial_id).delete(synchronize_session=False)
    db.delete(serial)
    db.add(AuditLog(
        user_id=actor_id,
        action_type="SERIAL_ARCHIVE",
        entity_type="Serial",
        entity_id=serial_id,
        previous_value=serial_title,
        new_value=str(path),
        comment=f"Archived closed serial with {len(logs)} signal log rows.",
        is_testing=serial_is_testing,
    ))
    db.commit()
    return SerialArchiveResult(archived=True, path=str(path), logs=len(logs))
