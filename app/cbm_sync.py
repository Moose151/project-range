"""Map read-only CBM snapshots into active Project Range signal logs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.cbm import CBMError, CBMSnapshot, poll_cbm_ssh
from app.crypto import decrypt_secret
from app.deps import get_current_range_state, is_testing_state
from app.models import AuditLog, RFDevice, Serial, SignalLog, SignalPackageEntry
from app.signal_warnings import warning_flags_for


@dataclass
class CBMSyncResult:
    updated: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def add_error(self, message: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(message)


def _mhz_from_khz_text(value: str | None) -> float | None:
    try:
        return float(value) / 1000.0 if value not in (None, "", "NoData", "No Data") else None
    except ValueError:
        return None


def _float_text(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "NoData", "No Data", "NoCarrier", "No Carrier") else None
    except ValueError:
        return None


def _status_from_snapshot(snapshot: CBMSnapshot, path: str | None) -> str:
    if path in ("rx", "dvb"):
        lock = snapshot.status.get("ACQ_STATE") or snapshot.status.get("LINK_STAT")
        return "Up" if lock in {"ACQ", "LINK_UP", "READY"} else "Down"
    return "Up" if snapshot.tx_config.get("TX_OP") == "ON" else "Down"


def _entry_values_from_snapshot(entry: SignalPackageEntry, snapshot: CBMSnapshot) -> dict:
    path = entry.cbm_path or "tx"
    summary = snapshot.summary
    values = {
        "signal_status": _status_from_snapshot(snapshot, path),
        "modulation": entry.modulation,
        "symbol_rate": entry.symbol_rate,
        "fec": entry.fec,
        "power": entry.power,
        "eb_no": entry.eb_no,
        "tx_if": entry.tx_if,
        "rx_if": entry.rx_if,
    }
    if path in ("tx", "tx_rx"):
        values.update({
            "modulation": summary.get("tx_modulation") or entry.modulation,
            "symbol_rate": summary.get("tx_symbol_rate") or entry.symbol_rate,
            "fec": summary.get("tx_code") or entry.fec,
            "power": _float_text(summary.get("tx_if_power_dbm")),
            "tx_if": _mhz_from_khz_text(summary.get("tx_if_frequency_khz")),
        })
    if path in ("rx", "tx_rx", "dvb"):
        values.update({
            "eb_no": _float_text(summary.get("rx_ebno_db")),
            "rx_if": _mhz_from_khz_text(summary.get("rx_if_frequency_khz")),
        })
        if path in ("rx", "dvb"):
            values.update({
                "modulation": summary.get("rx_modulation") or entry.modulation,
                "symbol_rate": summary.get("rx_symbol_rate") or entry.symbol_rate,
                "fec": summary.get("rx_code") or entry.fec,
            })
    return values


def _changed(latest: SignalLog | None, values: dict) -> bool:
    if latest is None:
        return True
    fields = ("signal_status", "modulation", "symbol_rate", "fec", "power", "eb_no", "tx_if", "rx_if")
    return any(getattr(latest, field) != values.get(field) for field in fields)


def sync_active_cbms(db: Session, actor_id: int) -> CBMSyncResult:
    result = CBMSyncResult(errors=[])
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    active_serials = db.query(Serial).filter(
        Serial.closed_at == None,
        Serial.is_started == True,
        Serial.is_testing == testing,
    ).all()

    mappings: list[tuple[Serial, SignalPackageEntry]] = []
    for serial in active_serials:
        for link in serial.package_links:
            for entry in link.package.signals:
                if entry.cbm_device_id:
                    mappings.append((serial, entry))

    by_key: dict[tuple[int, int, str], list[tuple[Serial, SignalPackageEntry]]] = defaultdict(list)
    for serial, entry in mappings:
        by_key[(serial.id, entry.cbm_device_id, entry.cbm_path or "tx")].append((serial, entry))

    snapshots: dict[int, CBMSnapshot] = {}
    for (_serial_id, device_id, path), items in by_key.items():
        if len(items) > 1:
            names = ", ".join(entry.signal_name for _serial, entry in items)
            result.skipped += len(items)
            result.add_error(f"Ambiguous CBM mapping on device {device_id} {path}: {names}")
            continue

        device = db.query(RFDevice).filter(RFDevice.id == device_id, RFDevice.is_testing == testing).first()
        if not device or not device.cbm_sync_enabled:
            result.skipped += 1
            continue
        if device_id not in snapshots:
            password = decrypt_secret(device.cbm_password_encrypted)
            if not device.host or not device.cbm_username or not password:
                result.skipped += 1
                result.add_error(f"{device.name}: missing or unreadable CBM credentials")
                continue
            try:
                snapshots[device_id] = poll_cbm_ssh(device.host, device.cbm_username, password)
                device.cbm_last_sync_at = datetime.utcnow()
                device.cbm_last_sync_status = "ok"
                device.cbm_last_sync_error = None
            except CBMError as exc:
                device.cbm_last_sync_at = datetime.utcnow()
                device.cbm_last_sync_status = "error"
                device.cbm_last_sync_error = str(exc)[:1000]
                result.skipped += 1
                result.add_error(f"{device.name}: {exc}")
                continue

        serial, entry = items[0]
        snapshot = snapshots[device_id]
        values = _entry_values_from_snapshot(entry, snapshot)
        latest = db.query(SignalLog).filter(
            SignalLog.serial_id == serial.id,
            SignalLog.signal_name == entry.signal_name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        ).order_by(SignalLog.timestamp.desc()).first()
        if not _changed(latest, values):
            continue

        power = values.get("power") if values.get("power") is not None else (latest.power if latest else None)
        new_entry = SignalLog(
            operator_id=actor_id,
            range_state=range_state,
            signal_name=entry.signal_name,
            signal_status=values["signal_status"],
            tx_if=values.get("tx_if") if values.get("tx_if") is not None else (latest.tx_if if latest else entry.tx_if),
            tx_rf=latest.tx_rf if latest else entry.tx_rf,
            rx_rf=latest.rx_rf if latest else entry.rx_rf,
            rx_if=values.get("rx_if") if values.get("rx_if") is not None else (latest.rx_if if latest else entry.rx_if),
            freq_unit="MHz",
            band=latest.band if latest else (entry.package.band or entry.band),
            modulation=values.get("modulation"),
            symbol_rate=values.get("symbol_rate"),
            fec=values.get("fec"),
            power=power,
            power_unit="dBm",
            eb_no=values.get("eb_no") if values.get("eb_no") is not None else (latest.eb_no if latest else entry.eb_no),
            source=latest.source if latest else entry.source,
            antenna=latest.antenna if latest else (entry.package.antenna or entry.antenna),
            serial_id=serial.id,
            entry_type="Automatic",
            updated_by_id=actor_id,
            notes=f"CBM sync from {entry.cbm_device.name} ({entry.cbm_path or 'tx'})",
            warning_flags=warning_flags_for(
                db,
                entry.signal_name,
                power,
                "dBm",
                tx_rf=latest.tx_rf if latest else entry.tx_rf,
                rx_rf=latest.rx_rf if latest else entry.rx_rf,
                freq_unit="MHz",
                band=latest.band if latest else (entry.package.band or entry.band),
            ),
        )
        db.add(new_entry)
        result.updated += 1

    db.add(AuditLog(
        user_id=actor_id,
        action_type="CBM_SYNC_ACTIVE",
        entity_type="SignalLog",
        new_value=f"updated={result.updated}, skipped={result.skipped}",
    ))
    db.commit()
    return result
