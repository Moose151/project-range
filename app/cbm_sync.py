"""Map read-only CBM snapshots into active Project Range signal logs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.cbm import CBMError, CBMSnapshot, poll_cbm_ssh
from app.crypto import decrypt_secret
from app.deps import get_current_range_state, is_testing_state
from app.models import AuditLog, RFDevice, Serial, SignalLog, SignalPackageEntry
from app.rf_config import serial_package_rf_config, recalculate_from_values
from app.settings import (
    get_cbm_ebno_log_threshold,
    get_cbm_ebno_log_enabled,
    get_sandbox_hardware_sync_paused,
)
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
    raw = (value or "").strip()
    if raw.replace(" ", "") in {"", "NoData", "NoCarrier", "NoLock", "Unavailable", "N/A"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _symbol_rate_from_cbm(value: str | None) -> str | None:
    raw = _float_text(value)
    if raw is None:
        return None
    return f"{raw / 1000.0:.6f}".rstrip("0").rstrip(".")


def _fec_rate_from_cbm_code(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    base = raw.split(":", 1)[0]
    for marker in ("TURBO", "LDPC", "VITERBI", "RS", "TPC"):
        idx = base.upper().find(marker)
        if idx > 0:
            return base[:idx].strip() or None
    return base.strip() or None


def _normalise_state(value: str | None) -> str:
    return (value or "").strip().upper().replace(" ", "").replace("-", "_")


def _is_positive_state(value: str | None) -> bool:
    return _normalise_state(value) in {
        "ON", "ENABLE", "ENABLED", "ACTIVE", "ENGAGED", "ACQ", "LINK_UP",
        "READY", "LOCK", "LOCKED", "SYNC", "INSYNC", "IN_SYNC", "OK",
        "GREEN", "TRUE", "1",
    }


def _is_negative_state(value: str | None) -> bool:
    return _normalise_state(value) in {
        "OFF", "DISABLE", "DISABLED", "INACTIVE", "DISENGAGED", "IDLE",
        "LINK_DOWN", "NOLOCK", "NO_LOCK", "NOSYNC", "NO_SYNC", "DOWN",
        "RED", "FALSE", "0",
    }


def _led_state(value: str | None) -> bool | None:
    """Convert a raw modem status string to a tri-state LED value."""
    if _is_positive_state(value):
        return True
    if _is_negative_state(value):
        return False
    return None


def sync_states_from_snapshot(snapshot: "CBMSnapshot") -> dict:
    """Extract the three EBEM LED states from a snapshot for dashboard display.

    Returns a dict suitable for JSON storage on RFDevice.cbm_sync_state_json:
      ebem_sync    — ESYNC_STAT (Embedded Channel Sync)
      carrier_lock — ACQ_STATE  (Carrier / acquisition lock)
      bit_sync     — BSYNC_STAT (Bit sync)
    Values are True (green), False (red), or None (grey / no data).
    """
    s = snapshot.status
    return {
        "ebem_sync": _led_state(s.get("ESYNC_STAT")),
        "carrier_lock": _led_state(s.get("ACQ_STATE")),
        "bit_sync": _led_state(s.get("BSYNC_STAT")),
    }


def _status_from_snapshot(snapshot: CBMSnapshot, path: str | None) -> str | None:
    if path in ("rx", "dvb"):
        states = [snapshot.status.get(field) for field in ("ACQ_STATE", "LINK_STAT", "BSYNC_STAT", "ESYNC_STAT")]
        if any(_is_positive_state(value) for value in states):
            return "Up"
        if any(_is_negative_state(value) for value in states):
            return "Down"
        return None
    states = [
        snapshot.tx_config.get("TX_OP"),
        snapshot.status.get("TX_OP"),
        snapshot.summary.get("tx_if_enabled"),
        snapshot.summary.get("ita_tx_status"),
    ]
    if any(_is_positive_state(value) for value in states):
        return "Up"
    if any(_is_negative_state(value) for value in states):
        return "Down"
    return None


def _entry_values_from_snapshot(entry: SignalPackageEntry, snapshot: CBMSnapshot) -> dict:
    path = entry.cbm_path or "tx"
    summary = snapshot.summary
    # Eb/No is the modem's live receive-demod reading. It is authoritative: when the
    # modem reports "No Carrier" (not receiving) it parses to None and Eb/No is CLEARED,
    # rather than keeping a stale value from when a carrier was present. Using the modem
    # value directly (including None) also stops the sync from logging a spurious change
    # every poll when the stored value and the live value disagree.
    modem_ebno = _float_text(summary.get("rx_ebno_db"))
    values = {
        "signal_status": _status_from_snapshot(snapshot, path),
        "modulation": entry.modulation,
        "symbol_rate": entry.symbol_rate,
        "fec": entry.fec,
        "power": entry.power,
        "eb_no": modem_ebno,
        "tx_if": entry.tx_if,
        "rx_if": entry.rx_if,
    }
    if path in ("tx", "tx_rx"):
        values.update({
            "modulation": summary.get("tx_modulation") or entry.modulation,
            "symbol_rate": _symbol_rate_from_cbm(summary.get("tx_symbol_rate")) or entry.symbol_rate,
            "fec": _fec_rate_from_cbm_code(summary.get("tx_code")) or entry.fec,
            "power": _float_text(summary.get("tx_if_power_dbm")),
            "tx_if": _mhz_from_khz_text(summary.get("tx_if_frequency_khz")),
        })
    if path in ("rx", "tx_rx", "dvb"):
        values.update({
            "rx_if": _mhz_from_khz_text(summary.get("rx_if_frequency_khz")),
        })
        if path in ("rx", "dvb"):
            values.update({
                "modulation": summary.get("rx_modulation") or entry.modulation,
                "symbol_rate": _symbol_rate_from_cbm(summary.get("rx_symbol_rate")) or entry.symbol_rate,
                "fec": _fec_rate_from_cbm_code(summary.get("rx_code")) or entry.fec,
            })
    return values


def _ebno_changed(old, new, threshold: float) -> bool:
    """Eb/No is noisy: only count a change worth logging when it crosses the threshold,
    OR when a carrier appears/disappears (a value <-> no-value transition)."""
    if (old is None) != (new is None):
        return True          # carrier acquired or lost
    if old is None and new is None:
        return False
    try:
        return abs(float(new) - float(old)) >= threshold
    except (TypeError, ValueError):
        return old != new


_NON_EBNO_FIELDS = ("signal_status", "modulation", "symbol_rate", "fec", "power", "tx_if", "tx_rf", "rx_rf", "rx_if")


def _non_ebno_changed(latest: SignalLog | None, values: dict) -> bool:
    if latest is None:
        return True
    return any(getattr(latest, f) != values.get(f) for f in _NON_EBNO_FIELDS)


def _latest_or_entry_status(latest: SignalLog | None, entry: SignalPackageEntry) -> str:
    return latest.signal_status if latest else "Configured"


def sync_active_cbms(db: Session, actor_id: int | None, audit_when_noop: bool = True) -> CBMSyncResult:
    result = CBMSyncResult(errors=[])
    range_state = get_current_range_state(db)
    testing = is_testing_state(db)
    if testing and get_sandbox_hardware_sync_paused(db):
        result.skipped = 1
        result.add_error("Sandbox hardware sync is paused; EBEM/CBM sync skipped")
        if audit_when_noop:
            db.add(AuditLog(
                user_id=actor_id,
                action_type="CBM_SYNC_PAUSED",
                entity_type="SignalLog",
                new_value="Sandbox hardware sync paused",
            ))
            db.commit()
        return result
    ebno_threshold = get_cbm_ebno_log_threshold(db)
    ebno_log_enabled = get_cbm_ebno_log_enabled(db)
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
        serial, entry = items[0]
        if not device:
            result.skipped += 1
            result.add_error(f"{entry.signal_name}: mapped CBM device id {device_id} was not found in this range state")
            continue
        if device.device_type != "modem" or not device.cbm_sync_enabled:
            # Non-CBM modem sources such as CDMs may still be valid signal
            # sources, but they are not EBEM/CBM poll targets.
            continue
        if device_id not in snapshots:
            password = decrypt_secret(device.cbm_password_encrypted)
            if not device.host or not device.cbm_username or not password:
                result.skipped += 1
                result.add_error(f"{entry.signal_name}: {device.name} missing host, username, or readable CBM password")
                continue
            try:
                snapshots[device_id] = poll_cbm_ssh(device.host, device.cbm_username, password)
                device.cbm_last_sync_at = datetime.utcnow()
                device.cbm_last_sync_status = "ok"
                device.cbm_last_sync_error = None
                device.cbm_sync_state_json = json.dumps(
                    sync_states_from_snapshot(snapshots[device_id])
                )
            except CBMError as exc:
                device.cbm_last_sync_at = datetime.utcnow()
                device.cbm_last_sync_status = "error"
                device.cbm_last_sync_error = str(exc)[:1000]
                result.skipped += 1
                result.add_error(f"{device.name}: {exc}")
                continue

        snapshot = snapshots[device_id]
        values = _entry_values_from_snapshot(entry, snapshot)
        latest = db.query(SignalLog).filter(
            SignalLog.serial_id == serial.id,
            SignalLog.signal_name == entry.signal_name,
            SignalLog.is_deleted == False,
            SignalLog.is_testing == testing,
        ).order_by(SignalLog.timestamp.desc()).first()
        if values.get("signal_status") is None:
            values["signal_status"] = _latest_or_entry_status(latest, entry)
        baseline = {
            "tx_if": values.get("tx_if") if values.get("tx_if") is not None else (latest.tx_if if latest else entry.tx_if),
            "tx_rf": latest.tx_rf if latest else entry.tx_rf,
            "rx_rf": latest.rx_rf if latest else entry.rx_rf,
            "rx_if": values.get("rx_if") if values.get("rx_if") is not None else (latest.rx_if if latest else entry.rx_if),
            "freq_unit": "MHz",
        }
        values.update(recalculate_from_values(
            baseline,
            serial_package_rf_config(db, serial.id, entry.signal_name),
            preferred=[field for field in ("tx_if", "rx_if") if values.get(field) is not None],
        ))
        other_changed = _non_ebno_changed(latest, values)
        ebno_significant = _ebno_changed(
            latest.eb_no if latest else None,
            values.get("eb_no"),
            ebno_threshold,
        )
        should_log = latest is None or other_changed or (ebno_significant and ebno_log_enabled)
        if not should_log:
            # No new row needed. Update Eb/No in-place so the dashboard reflects the
            # live modem reading even when the change is below the log threshold.
            if latest is not None and latest.eb_no != values.get("eb_no"):
                latest.eb_no = values.get("eb_no")
            continue

        power = values.get("power") if values.get("power") is not None else (latest.power if latest else None)
        new_entry = SignalLog(
            operator_id=actor_id,
            range_state=range_state,
            signal_name=entry.signal_name,
            signal_status=values["signal_status"],
            tx_if=values.get("tx_if"),
            tx_rf=values.get("tx_rf"),
            rx_rf=values.get("rx_rf"),
            rx_if=values.get("rx_if"),
            freq_unit="MHz",
            band=latest.band if latest else (entry.package.band or entry.band),
            modulation=values.get("modulation"),
            symbol_rate=values.get("symbol_rate"),
            fec=values.get("fec"),
            power=power,
            power_unit="dBm",
            eb_no=values.get("eb_no"),  # modem-authoritative; None when no carrier
            engaged=latest.engaged if latest else False,
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
                tx_rf=values.get("tx_rf"),
                rx_rf=values.get("rx_rf"),
                freq_unit="MHz",
                band=latest.band if latest else (entry.package.band or entry.band),
            ),
        )
        db.add(new_entry)
        result.updated += 1

    if not audit_when_noop and result.updated == 0 and result.skipped == 0 and not result.errors:
        db.commit()
        return result

    summary = f"updated={result.updated}, skipped={result.skipped}, issues={len(result.errors or [])}"
    issue_text = "\n".join(result.errors or [])
    db.add(AuditLog(
        user_id=actor_id,
        action_type="CBM_SYNC_ACTIVE",
        entity_type="SignalLog",
        new_value=summary,
        comment=issue_text or None,
    ))
    if result.errors:
        db.add(AuditLog(
            user_id=actor_id,
            action_type="CBM_SYNC_ISSUE",
            entity_type="RFDevice",
            new_value=f"{len(result.errors)} issue(s) during active CBM sync",
            comment=issue_text,
        ))
    db.commit()
    return result
