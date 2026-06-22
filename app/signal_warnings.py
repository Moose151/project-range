"""Compute warning flags stored on SignalLog entries.

Two checks, combined into one ` · `-joined string on SignalLog.warning_flags:
  * per-signal power ceiling — a registry signal may carry an optional
    `max_power_dbm`; a logged power above it (converted to dBm) warns.
  * band/frequency validation — TxRF/RxRF outside the configured range for the
    entry's band warns (reuses the calculator's band_warnings).

Surfaced in the dashboard "Warn" column and anywhere warning_flags is shown.
"""
from sqlalchemy.orm import Session

from app.models import Signal
from app.routers.calculator import convert_power, band_warnings


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


def _to_mhz(value, unit) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 1000 if (unit or "MHz") == "GHz" else float(value)
    except (ValueError, TypeError):
        return None


def warning_flags_for(
    db: Session, signal_name: str, power, power_unit,
    tx_rf=None, rx_rf=None, freq_unit="MHz", band=None,
) -> str | None:
    """Return a combined warning string (or None) for a log entry."""
    warnings: list[str] = []

    sig = db.query(Signal).filter(Signal.name == signal_name).first()
    if sig and sig.max_power_dbm is not None:
        pw = power_warning_text(sig.max_power_dbm, power, power_unit)
        if pw:
            warnings.append(pw)

    tx_mhz = _to_mhz(tx_rf, freq_unit)
    rx_mhz = _to_mhz(rx_rf, freq_unit)
    if tx_mhz is not None and rx_mhz is not None and band:
        warnings.extend(band_warnings(tx_mhz, rx_mhz, band))

    return " · ".join(warnings) if warnings else None
