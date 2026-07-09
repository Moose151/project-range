from __future__ import annotations

from math import isclose
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import SignalLog


CHANGE_FIELDS = [
    ("signal_status", "Status"),
    ("tx_if", "TxIF"),
    ("tx_rf", "TxRF"),
    ("rx_rf", "RxRF"),
    ("rx_if", "RxIF"),
    ("freq_unit", "Unit"),
    ("band", "Band"),
    ("modulation", "Mod"),
    ("symbol_rate", "Sym"),
    ("fec", "FEC"),
    ("source", "Source"),
    ("antenna", "Antenna"),
    ("power", "Power"),
    ("eb_no", "Eb/No"),
    ("ber_estimate", "BER"),
]


def _display_value(log: SignalLog | None, field: str) -> str:
    if log is None:
        return "blank"
    if field == "power":
        if log.power is None:
            return "blank"
        return f"{log.power:g} {log.power_unit or ''}".strip()
    value = getattr(log, field)
    if value is None or value == "":
        return "blank"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _values_equal(current: SignalLog, previous: SignalLog, field: str) -> bool:
    if field == "power":
        return _values_equal(current, previous, "power_unit") and _values_equal(current, previous, "_power_value")

    current_value: Any = current.power if field == "_power_value" else getattr(current, field)
    previous_value: Any = previous.power if field == "_power_value" else getattr(previous, field)

    if current_value is None and previous_value in (None, ""):
        return True
    if previous_value is None and current_value in (None, ""):
        return True
    if isinstance(current_value, float) or isinstance(previous_value, float):
        if current_value is None or previous_value is None:
            return False
        return isclose(float(current_value), float(previous_value), rel_tol=1e-9, abs_tol=1e-9)
    return current_value == previous_value


def previous_signal_log(db: Session, log: SignalLog) -> SignalLog | None:
    if log.signal_name == "[NOTE]":
        return None

    q = db.query(SignalLog).filter(
        SignalLog.is_deleted == False,
        SignalLog.signal_name == log.signal_name,
        SignalLog.id != log.id,
    )
    if log.serial_id is None:
        q = q.filter(SignalLog.serial_id == None)
    else:
        q = q.filter(SignalLog.serial_id == log.serial_id)

    q = q.filter(
        or_(
            SignalLog.timestamp < log.timestamp,
            (SignalLog.timestamp == log.timestamp) & (SignalLog.id < log.id),
        )
    )
    return q.order_by(SignalLog.timestamp.desc(), SignalLog.id.desc()).first()


def annotate_log_changes(db: Session, logs: list[SignalLog]) -> None:
    for log in logs:
        previous = previous_signal_log(db, log)
        details = []
        if previous is not None:
            for field, label in CHANGE_FIELDS:
                if not _values_equal(log, previous, field):
                    details.append({
                        "field": field,
                        "label": label,
                        "before": _display_value(previous, field),
                        "after": _display_value(log, field),
                    })
        log.changed_fields = {item["field"] for item in details}
        log.changed_details = details
        log.change_title = "; ".join(
            f"{item['label']}: {item['before']} -> {item['after']}" for item in details
        )
