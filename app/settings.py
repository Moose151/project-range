from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy.orm import Session

from app.models import AppSetting, SignalLog

LOCAL_TIMEZONE_KEY = "local_timezone"
DEFAULT_LOCAL_TIMEZONE = "UTC"

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


def annotate_local_times(logs: list[SignalLog], timezone_name: str) -> None:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_LOCAL_TIMEZONE)
    for log in logs:
        if log.timestamp:
            log.local_timestamp = log.timestamp.replace(tzinfo=timezone.utc).astimezone(tz)
