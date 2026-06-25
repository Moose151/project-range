from sqlalchemy.orm import Session

from app.models import SerialPackage


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
