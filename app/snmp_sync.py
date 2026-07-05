"""Map read-only SNMP matrix snapshots onto RFDevice / DevicePort observed state.

Mirrors app.cbm_sync: poll enabled routing devices, write the live observed routing
onto each device's DevicePort rows (without touching the manually-entered plan) plus
a device-level health/status cache, and audit only when the observed routing changes.
Read-only: never issues SNMP SET.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.crypto import decrypt_secret
from app.deps import is_testing_state
from app.models import AuditLog, DevicePort, RFDevice
from app.snmp import MatrixSnapshot, SNMPError, poll_genus_matrix

ROUTING_TYPES = {"splitter", "combiner", "switch"}


@dataclass
class SNMPSyncResult:
    updated: int = 0            # devices whose observed routing changed
    polled: int = 0            # devices successfully polled
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)


def _device_credentials(dev: RFDevice) -> tuple[str | None, dict | None]:
    """Return (community, v3_dict) decrypted for the device, or (None, None) if unusable."""
    if dev.snmp_version == "3":
        user = dev.snmp_v3_user
        if not user:
            return None, None
        return None, {
            "user": user,
            "auth_key": decrypt_secret(dev.snmp_v3_auth_encrypted),
            "priv_key": decrypt_secret(dev.snmp_v3_priv_encrypted),
        }
    community = decrypt_secret(dev.snmp_community_encrypted)
    return community, None


def poll_snmp_device(db: Session, dev: RFDevice) -> tuple[MatrixSnapshot | None, bool]:
    """Poll one device and write observed state. Returns (snapshot, changed).

    Raises SNMPError on poll failure (caller records it); on success updates the
    device's snmp_last_poll_* cache and the observed routing on its output ports.
    """
    community, v3 = _device_credentials(dev)
    if not dev.host or (not community and not v3):
        dev.snmp_last_poll_at = datetime.utcnow()
        dev.snmp_last_poll_status = "missing_credentials"
        dev.snmp_last_poll_error = "Host and SNMP community (v2c) or v3 user are required."
        raise SNMPError(dev.snmp_last_poll_error)

    snapshot = poll_genus_matrix(dev.host, port=dev.snmp_port or 161, community=community, v3=v3)

    changed = False
    outputs = {p.idx: p for p in dev.ports if p.direction == "out"}
    for output_idx, input_idx in snapshot.routing.items():
        port = outputs.get(output_idx)
        if port is None:
            continue
        new_val = input_idx or None
        if port.observed_routed_from != new_val:
            port.observed_routed_from = new_val
            changed = True

    dev.snmp_last_poll_at = datetime.utcnow()
    dev.snmp_last_poll_status = "ok"
    dev.snmp_last_poll_error = None
    dev.snmp_system_alarm = snapshot.system_alarm
    return snapshot, changed


def poll_active_snmp_devices(
    db: Session, actor_id: int | None, audit_when_noop: bool = True
) -> SNMPSyncResult:
    """Poll every SNMP-enabled routing device in the current range-state scope."""
    result = SNMPSyncResult()
    testing = is_testing_state(db)
    devices = db.query(RFDevice).filter(
        RFDevice.snmp_enabled == True,   # noqa: E712
        RFDevice.is_testing == testing,
    ).all()

    for dev in devices:
        if dev.device_type not in ROUTING_TYPES:
            continue
        try:
            _snapshot, changed = poll_snmp_device(db, dev)
            result.polled += 1
            if changed:
                result.updated += 1
        except SNMPError as exc:
            dev.snmp_last_poll_at = datetime.utcnow()
            dev.snmp_last_poll_status = "error"
            dev.snmp_last_poll_error = str(exc)[:1000]
            result.skipped += 1
            result.add_error(f"{dev.name}: {exc}")

    if not audit_when_noop and result.updated == 0 and result.skipped == 0 and not result.errors:
        db.commit()
        return result

    summary = f"polled={result.polled}, routing_changed={result.updated}, issues={len(result.errors)}"
    db.add(AuditLog(
        user_id=actor_id,
        action_type="SNMP_POLL_ACTIVE",
        entity_type="RFDevice",
        new_value=summary,
        comment="\n".join(result.errors) or None,
    ))
    db.commit()
    return result
