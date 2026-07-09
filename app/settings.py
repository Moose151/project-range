from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy.orm import Session

from app.models import AppSetting, SignalLog

LOCAL_TIMEZONE_KEY = "local_timezone"
DEFAULT_LOCAL_TIMEZONE = "UTC"
AUDIT_LIVE_RECORD_LIMIT_KEY = "audit_live_record_limit"
DEFAULT_AUDIT_LIVE_RECORD_LIMIT = 1000
MIN_AUDIT_LIVE_RECORD_LIMIT = 250
MAX_AUDIT_LIVE_RECORD_LIMIT = 10000

# Minimum Eb/No change (dB) that counts as a real change worth logging during CBM sync.
# Smaller drifts are ignored to avoid log spam; a carrier appearing/disappearing (a
# value <-> no-value transition) always logs regardless of this threshold.
CBM_EBNO_LOG_THRESHOLD_KEY = "cbm_ebno_log_threshold"
DEFAULT_CBM_EBNO_LOG_THRESHOLD = 3.0

# Whether Eb/No changes are ever written as new log entries during CBM sync.
# When False, Eb/No still updates in-place on the existing log row so the dashboard
# reflects the live modem reading, but no new log rows are created for Eb/No changes.
CBM_EBNO_LOG_ENABLED_KEY = "cbm_ebno_log_enabled"
DEFAULT_CBM_EBNO_LOG_ENABLED = True

# Minimum BER estimate change that counts as worth logging during CBM sync.
# BER is a unitless ratio and is typically reported in scientific notation by
# the EBEM as RX_BEREST. It still updates in-place on the dashboard regardless
# of whether BER change logging is enabled.
CBM_BER_LOG_THRESHOLD_KEY = "cbm_ber_log_threshold"
DEFAULT_CBM_BER_LOG_THRESHOLD = 1e-7

# BER logging is off by default because BER can drift frequently. When False,
# BER still updates on the dashboard but does not create new log rows by itself.
CBM_BER_LOG_ENABLED_KEY = "cbm_ber_log_enabled"
DEFAULT_CBM_BER_LOG_ENABLED = False

# Testing/Sandbox-only pause for read-only hardware sync. When enabled, automatic
# and active EBEM/CBM + SNMP syncs do not update Testing workspace rows, letting
# users rehearse manual changes without modem/matrix reads immediately overriding them.
SANDBOX_HARDWARE_SYNC_PAUSED_KEY = "sandbox_hardware_sync_paused"
DEFAULT_SANDBOX_HARDWARE_SYNC_PAUSED = False

try:
    TIME_ZONES = ["UTC"] + sorted(tz for tz in available_timezones() if tz != "UTC")
except Exception:
    TIME_ZONES = [
        "UTC", "Australia/Brisbane", "Australia/Sydney", "Australia/Perth",
        "Australia/Adelaide", "Australia/Darwin", "Pacific/Auckland",
        "Asia/Singapore", "Europe/London", "America/New_York",
        "America/Los_Angeles",
    ]


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def get_local_timezone(db: Session) -> str:
    tz = get_setting(db, LOCAL_TIMEZONE_KEY, DEFAULT_LOCAL_TIMEZONE)
    return tz if tz in TIME_ZONES else DEFAULT_LOCAL_TIMEZONE


def clamp_audit_live_record_limit(value: int | str | None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_AUDIT_LIVE_RECORD_LIMIT
    return max(MIN_AUDIT_LIVE_RECORD_LIMIT, min(parsed, MAX_AUDIT_LIVE_RECORD_LIMIT))


def get_audit_live_record_limit(db: Session) -> int:
    return clamp_audit_live_record_limit(
        get_setting(db, AUDIT_LIVE_RECORD_LIMIT_KEY, str(DEFAULT_AUDIT_LIVE_RECORD_LIMIT))
    )


def get_cbm_ebno_log_enabled(db: Session) -> bool:
    raw = get_setting(db, CBM_EBNO_LOG_ENABLED_KEY, "1")
    return raw.lower() not in ("0", "false", "no", "off")


def get_cbm_ber_log_enabled(db: Session) -> bool:
    raw = get_setting(db, CBM_BER_LOG_ENABLED_KEY, "0")
    return raw.lower() in ("1", "true", "yes", "on")


def get_sandbox_hardware_sync_paused(db: Session) -> bool:
    raw = get_setting(db, SANDBOX_HARDWARE_SYNC_PAUSED_KEY, "0")
    return raw.lower() in ("1", "true", "yes", "on")


def get_cbm_ebno_log_threshold(db: Session) -> float:
    raw = get_setting(db, CBM_EBNO_LOG_THRESHOLD_KEY, str(DEFAULT_CBM_EBNO_LOG_THRESHOLD))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CBM_EBNO_LOG_THRESHOLD
    return value if value >= 0 else DEFAULT_CBM_EBNO_LOG_THRESHOLD


def get_cbm_ber_log_threshold(db: Session) -> float:
    raw = get_setting(db, CBM_BER_LOG_THRESHOLD_KEY, str(DEFAULT_CBM_BER_LOG_THRESHOLD))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_CBM_BER_LOG_THRESHOLD
    return value if value >= 0 else DEFAULT_CBM_BER_LOG_THRESHOLD


def annotate_local_times(logs: list[SignalLog], timezone_name: str) -> None:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_LOCAL_TIMEZONE)
    for log in logs:
        if log.timestamp:
            log.local_timestamp = log.timestamp.replace(tzinfo=timezone.utc).astimezone(tz)
