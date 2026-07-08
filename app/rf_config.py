from sqlalchemy.orm import Session

from app.models import SerialPackage


def round_freq(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def recalculate_frequencies(
    *,
    known: str,
    value: float | None,
    tx_lo: float | None,
    rx_lo: float | None,
    ttf: float | None,
    ttf_direction: str = "+",
) -> dict[str, float | None]:
    """Calculate TxIF/TxRF/RxRF/RxIF from one known value, all in package units."""
    if value is None or tx_lo is None or rx_lo is None or ttf is None:
        return {}
    sign = -1 if ttf_direction == "-" else 1
    if known == "tx_if":
        tx_if = value
        tx_rf = tx_if + tx_lo
        rx_rf = tx_rf + sign * ttf
        rx_if = rx_rf - rx_lo
    elif known == "tx_rf":
        tx_rf = value
        tx_if = tx_rf - tx_lo
        rx_rf = tx_rf + sign * ttf
        rx_if = rx_rf - rx_lo
    elif known == "rx_rf":
        rx_rf = value
        tx_rf = rx_rf - sign * ttf
        tx_if = tx_rf - tx_lo
        rx_if = rx_rf - rx_lo
    elif known == "rx_if":
        rx_if = value
        rx_rf = rx_if + rx_lo
        tx_rf = rx_rf - sign * ttf
        tx_if = tx_rf - tx_lo
    else:
        return {}
    return {
        "tx_if": round_freq(tx_if),
        "tx_rf": round_freq(tx_rf),
        "rx_rf": round_freq(rx_rf),
        "rx_if": round_freq(rx_if),
    }


def frequencies_from_dual_if(tx_if: float | None, rx_if: float | None, rf: dict | None) -> dict:
    """Derive TxRF from TxLO and RxRF from RxLO when both IFs are independently known.

    Used for live modem readings where the TX and RX IF are each measured directly.
    The single-known-value path (``recalculate_frequencies``) chains TX→RX through
    TTF, which mislabels RxRF (it ends up TxLO/TTF-based, never using RxLO). When we
    genuinely know both IFs, each RF must come from its own LO.
    """
    if not rf:
        return {}
    tx_lo = rf.get("tx_lo")
    rx_lo = rf.get("rx_lo")
    out: dict[str, float | None] = {}
    if tx_if is not None and tx_lo is not None:
        out["tx_rf"] = round_freq(tx_if + tx_lo)
    if rx_if is not None and rx_lo is not None:
        out["rx_rf"] = round_freq(rx_if + rx_lo)
    return out


def recalculate_from_values(values: dict, rf: dict | None, preferred: list[str] | None = None) -> dict:
    """Return values with all frequencies recalculated when a usable RF plan exists."""
    if not rf:
        return values
    fields = preferred or ["tx_if", "tx_rf", "rx_rf", "rx_if"]
    known = next((field for field in fields if values.get(field) is not None), None)
    if not known:
        return values
    calculated = recalculate_frequencies(
        known=known,
        value=values.get(known),
        tx_lo=rf.get("tx_lo"),
        rx_lo=rf.get("rx_lo"),
        ttf=rf.get("ttf"),
        ttf_direction=rf.get("ttf_direction") or "+",
    )
    if calculated:
        values.update(calculated)
        values["freq_unit"] = rf.get("freq_unit") or values.get("freq_unit") or "MHz"
    return values


def package_has_rf_config(package) -> bool:
    """Return whether a package contains any package-level RF setting."""
    return any(value is not None for value in (package.tx_lo, package.rx_lo, package.ttf)) or bool(
        package.band or package.antenna
    )


def package_rf_config(package) -> dict:
    return {
        "package_id": package.id,
        "package_name": package.name,
        "tx_lo": package.tx_lo,
        "rx_lo": package.rx_lo,
        "ttf": package.ttf,
        "ttf_direction": package.ttf_direction or "+",
        "freq_unit": package.freq_unit or "MHz",
        "band": package.band,
        "antenna": package.antenna,
    }


def serial_package_rf_config(
    db: Session, serial_id: int, signal_name: str | None = None,
) -> dict | None:
    """Find the best package RF config for a serial.

    When a signal is supplied, prefer the assigned package containing that signal.
    Otherwise use the first assigned package that actually has RF configuration.
    """
    links = (
        db.query(SerialPackage)
        .filter(SerialPackage.serial_id == serial_id)
        .order_by(SerialPackage.id)
        .all()
    )
    configured = [link.package for link in links if package_has_rf_config(link.package)]
    if signal_name:
        wanted = signal_name.strip().casefold()
        for package in configured:
            if any(entry.signal_name.casefold() == wanted for entry in package.signals):
                return package_rf_config(package)
    return package_rf_config(configured[0]) if configured else None
