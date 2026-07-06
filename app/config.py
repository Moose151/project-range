import os
import logging
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Session signing key. Never ship a known static default: if SECRET_KEY is unset
# (or left as the old placeholder), generate a strong ephemeral key at boot. The
# app still runs for dev, but sessions won't survive a restart — set SECRET_KEY in
# production for persistent sessions. (docker-compose already requires it.)
_INSECURE_DEFAULTS = {"", None, "dev-secret-change-in-production-please"}
SECRET_KEY = os.environ.get("SECRET_KEY")
if SECRET_KEY in _INSECURE_DEFAULTS:
    SECRET_KEY = secrets.token_hex(32)
    logging.getLogger("uvicorn.error").warning(
        "SECRET_KEY is not set — using an ephemeral random key. Sessions will not "
        "persist across restarts. Set SECRET_KEY in the environment for production."
    )

# Security knobs (overridable via env).
SESSION_SAME_SITE = os.environ.get("SESSION_SAME_SITE", "strict")   # strict|lax|none
SESSION_HTTPS_ONLY = os.environ.get("SESSION_HTTPS_ONLY", "0") == "1"  # set 1 behind TLS
MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", "6"))
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "300"))

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/range.db")

def _default_data_dir() -> Path:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = Path(DATABASE_URL.removeprefix("sqlite:///"))
        return db_path.parent if db_path.is_absolute() else (BASE_DIR / db_path).parent
    return BASE_DIR / "data"

DATA_DIR = Path(os.environ.get("DATA_DIR", str(_default_data_dir())))
AUDIT_ARCHIVE_DIR = Path(os.environ.get("AUDIT_ARCHIVE_DIR", str(DATA_DIR / "audit_archives")))
SERIAL_ARCHIVE_DIR = Path(os.environ.get("SERIAL_ARCHIVE_DIR", str(DATA_DIR / "serial_archives")))
SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "480"))
# Cookie lifetime. Normal sessions still expire after SESSION_TIMEOUT_MINUTES of
# inactivity (enforced server-side); "remember this terminal" sessions skip that
# inactivity check and persist up to this cookie lifetime.
SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "30"))
CBM_AUTO_SYNC_SECONDS = int(os.environ.get("CBM_AUTO_SYNC_SECONDS", "5"))
# Read-only SNMP polling of routing matrices (splitter/combiner). Opt-in and
# disabled by default (0) since SNMP access on the range is not yet confirmed.
SNMP_AUTO_SYNC_SECONDS = int(os.environ.get("SNMP_AUTO_SYNC_SECONDS", "0"))
# Single source of truth for the app version (shown in the top-right UI and
# reported as the FastAPI app version). Bump on each release.
APP_VERSION = "0.19.7"

FREQUENCY_BANDS = {
    "C":  {"tx_min": 5.850, "tx_max": 6.725, "rx_min": 3.625, "rx_max": 4.200},
    "X":  {"tx_min": 7.900, "tx_max": 8.400, "rx_min": 7.250, "rx_max": 7.750},
    "Ku": {"tx_min": 13.75, "tx_max": 14.50, "rx_min": 10.70, "rx_max": 12.75},
    "Ka": {"tx_min": 26.50, "tx_max": 31.00, "rx_min": 17.70, "rx_max": 21.20},
}
