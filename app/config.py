import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production-please")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/range.db")
SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "480"))
# Cookie lifetime. Normal sessions still expire after SESSION_TIMEOUT_MINUTES of
# inactivity (enforced server-side); "remember this terminal" sessions skip that
# inactivity check and persist up to this cookie lifetime.
SESSION_MAX_AGE_DAYS = int(os.environ.get("SESSION_MAX_AGE_DAYS", "30"))
# Single source of truth for the app version (shown bottom-right in the UI and
# reported as the FastAPI app version). Bump on each release.
APP_VERSION = "0.7.0"

FREQUENCY_BANDS = {
    "C":  {"tx_min": 5.850, "tx_max": 6.725, "rx_min": 3.625, "rx_max": 4.200},
    "X":  {"tx_min": 7.900, "tx_max": 8.400, "rx_min": 7.250, "rx_max": 7.750},
    "Ku": {"tx_min": 13.75, "tx_max": 14.50, "rx_min": 10.70, "rx_max": 12.75},
    "Ka": {"tx_min": 26.50, "tx_max": 31.00, "rx_min": 17.70, "rx_max": 21.20},
}
