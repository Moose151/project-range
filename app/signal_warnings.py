"""Compute warning flags stored on SignalLog entries.

Currently: per-signal power ceiling. A signal in the registry can carry an
optional `max_power_dbm`; when a log entry records a power above that ceiling
(converted to dBm), a warning string is stored in SignalLog.warning_flags and
surfaced on the dashboard / log views.
"""
from sqlalchemy.orm import Session

from app.models import Signal
from app.routers.calculator import convert_power


def power_warning_text(max_power_dbm, power, power_unit) -> str | None:
    if max_power_dbm is None or power is None:
        return None
    try:
        p_dbm = convert_power(float(power), power_unit or "dBm", "dBm")
    except (ValueError, TypeError):
        return None
    if p_dbm > max_power_dbm:
        return f"Power {round(p_dbm, 1):g} dBm exceeds limit {max_power_dbm:g} dBm"
    return None


def warning_flags_for(db: Session, signal_name: str, power, power_unit) -> str | None:
    """Return the warning string (or None) for a log entry's power level."""
    if power is None:
        return None
    sig = db.query(Signal).filter(Signal.name == signal_name).first()
    if not sig or sig.max_power_dbm is None:
        return None
    return power_warning_text(sig.max_power_dbm, power, power_unit)
