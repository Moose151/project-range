"""Read-only telemetry from the Airbus RICS (Ranger Integrated Control System).

RICS serves a Flask + Socket.IO web GUI over HTTPS (self-signed cert on the LAN,
e.g. https://10.74.10.100). The dashboard is populated by Socket.IO events on the
``/index`` namespace, each event being ``[name, value]`` — for example
``["sspb.0.TXPower", "303"]`` (raw ÷10 = 30.3 dBm) or ``["antenna.EIRP", "0"]``.

This module logs in, connects as a Socket.IO client, collects **one snapshot** of
the values we care about (SSPB TX power and antenna EIRP, plus useful context),
then disconnects. It is strictly read-only — we never emit control events.

Verified scalings from a live CBM/RICS capture:
  sspb.0.TXPower      raw ÷ 10   → dBm   ("303"  → 30.3 dBm)
  sspb.0.Temperature  raw ÷ 10   → °C    ("421"  → 42.1 °C)
  sspb.0.LOFreq       raw ÷ 100  → GHz   ("1280" → 12.8 GHz)
  antenna.EIRP        (to confirm live once antenna details are configured in RICS)
"""

from __future__ import annotations

import argparse
import threading
import time
import warnings
from dataclasses import dataclass, field
from typing import Optional

# The two metrics the dashboard widgets need, plus context we display alongside.
SSPB_TX_POWER = "sspb.0.TXPower"
ANTENNA_EIRP = "antenna.EIRP"
_CONTEXT_EVENTS = (
    "sspb.0.ConnectionStatus", "sspb.0.TXEnable", "sspb.0.Temperature",
    "sspb.0.Fault", "sspb.0.Model", "sspb.0.LOFreq",
)


class RicsError(RuntimeError):
    pass


@dataclass
class RicsSnapshot:
    """A single read of RICS telemetry. Fields are None when not reported."""
    tx_power_dbm: Optional[float] = None
    tx_power_w: Optional[float] = None
    eirp_dbw: Optional[float] = None
    temperature_c: Optional[float] = None
    tx_enable: Optional[bool] = None
    sspb_connected: Optional[bool] = None
    fault: Optional[str] = None
    model: Optional[str] = None
    lo_freq_ghz: Optional[float] = None
    raw: dict = field(default_factory=dict)   # every event name → last raw string


def _to_float(value) -> Optional[float]:
    try:
        text = str(value).strip()
        if text in ("", "---", "None"):
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _dbm_to_watts(dbm: Optional[float]) -> Optional[float]:
    return None if dbm is None else 10 ** ((dbm - 30.0) / 10.0)


def _snapshot_from_raw(raw: dict, eirp_scale: float) -> RicsSnapshot:
    snap = RicsSnapshot(raw=dict(raw))
    tx = _to_float(raw.get(SSPB_TX_POWER))
    if tx is not None:
        snap.tx_power_dbm = round(tx / 10.0, 2)
        snap.tx_power_w = round(_dbm_to_watts(snap.tx_power_dbm), 4)
    eirp = _to_float(raw.get(ANTENNA_EIRP))
    if eirp is not None:
        snap.eirp_dbw = round(eirp / eirp_scale, 2)
    temp = _to_float(raw.get("sspb.0.Temperature"))
    if temp is not None:
        snap.temperature_c = round(temp / 10.0, 1)
    lo = _to_float(raw.get("sspb.0.LOFreq"))
    if lo is not None:
        snap.lo_freq_ghz = round(lo / 100.0, 3)
    if "sspb.0.TXEnable" in raw:
        snap.tx_enable = str(raw["sspb.0.TXEnable"]).strip() in ("1", "true", "True")
    if "sspb.0.ConnectionStatus" in raw:
        snap.sspb_connected = str(raw["sspb.0.ConnectionStatus"]).strip() == "1"
    snap.fault = (str(raw["sspb.0.Fault"]).strip() or None) if "sspb.0.Fault" in raw else None
    snap.model = (str(raw["sspb.0.Model"]).strip() or None) if "sspb.0.Model" in raw else None
    return snap


def _login(host: str, username: str, password: str, *, verify: bool, timeout: float):
    """Best-effort Flask login → return a requests.Session carrying the cookie.

    RICS uses a standard Flask ``session`` cookie. If your RICS login form differs,
    adjust login_path / field names below (or pass a session cookie directly).
    """
    import requests

    base = host if host.startswith("http") else f"https://{host}"
    session = requests.Session()
    session.verify = verify
    login_url = f"{base}/login"
    data = {"username": username, "password": password}
    # Pull a CSRF token if the login page exposes one.
    try:
        page = session.get(login_url, timeout=timeout)
        import re
        m = re.search(r'name=["\']csrf_token["\']\s+[^>]*value=["\']([^"\']+)', page.text)
        if m:
            data["csrf_token"] = m.group(1)
    except requests.RequestException:
        pass
    try:
        session.post(login_url, data=data, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise RicsError(f"login request failed: {exc}") from exc
    if not session.cookies.get("session"):
        raise RicsError(
            "login did not yield a 'session' cookie — check credentials or the "
            "login endpoint/field names (or pass session_cookie directly)."
        )
    return session, base


def poll_rics(
    host: str,
    *,
    username: str = "admin",
    password: str = "admin",
    session_cookie: Optional[str] = None,
    namespace: str = "/index",
    timeout: float = 20.0,
    settle: float = 1.5,
    verify: bool = False,
    eirp_scale: float = 10.0,
) -> RicsSnapshot:
    """Connect to RICS, collect one telemetry snapshot, and return it.

    Pass ``session_cookie`` (the value of the RICS ``session`` cookie from a
    browser) to skip the login step — handy for testing the read path before the
    login form is confirmed. Otherwise we log in with username/password.
    """
    import socketio

    base = host if host.startswith("http") else f"https://{host}"
    cookie_header = None
    if session_cookie:
        cookie_header = session_cookie if "=" in session_cookie else f"session={session_cookie}"
    else:
        session, base = _login(host, username, password, verify=verify, timeout=timeout)
        cookie_header = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    raw: dict = {}
    got_key = threading.Event()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silence self-signed TLS warnings
        sio = socketio.Client(ssl_verify=verify, reconnection=False, request_timeout=timeout)

        def _record(event, *vals):
            # Catch-all: called as (event_name, *args). Metrics carry one value.
            data = vals[0] if vals else None
            if isinstance(data, (list, tuple)):
                data = data[0] if data else None
            raw[event] = data
            if event == SSPB_TX_POWER:
                got_key.set()

        sio.on("*", _record, namespace=namespace)

        headers = {"Cookie": cookie_header} if cookie_header else {}
        try:
            sio.connect(
                base, headers=headers, transports=["websocket"],
                namespaces=[namespace], wait_timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - surface any connect failure uniformly
            raise RicsError(f"socket.io connect failed: {exc}") from exc

        try:
            # Wait for the TX power value (RICS dumps current state on connect),
            # then a short settle window to catch EIRP/temperature in the same burst.
            deadline = time.monotonic() + timeout
            got_key.wait(timeout=timeout)
            settle_until = time.monotonic() + settle
            while time.monotonic() < min(deadline, settle_until):
                time.sleep(0.1)
        finally:
            try:
                sio.disconnect()
            except Exception:  # noqa: BLE001
                pass

    if not raw:
        raise RicsError(
            "connected but received no telemetry events — the namespace may be "
            f"wrong (tried {namespace!r}; the sidebar uses '/app') or auth is stale."
        )
    return _snapshot_from_raw(raw, eirp_scale)


def _main() -> None:
    ap = argparse.ArgumentParser(description="Test the RICS telemetry poller.")
    ap.add_argument("host", help="RICS host, e.g. 10.74.10.100")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--cookie", default=None, help="session cookie value (skips login)")
    ap.add_argument("--namespace", default="/index")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()
    try:
        snap = poll_rics(
            args.host, username=args.user, password=args.password,
            session_cookie=args.cookie, namespace=args.namespace, timeout=args.timeout,
        )
    except RicsError as exc:
        print(f"RICS poll failed: {exc}")
        raise SystemExit(1)
    print("SSPB TX Power :", snap.tx_power_dbm, "dBm /", snap.tx_power_w, "W")
    print("Antenna EIRP  :", snap.eirp_dbw, "dBW  (raw", snap.raw.get(ANTENNA_EIRP), "- confirm scale)")
    print("SSPB Temp     :", snap.temperature_c, "°C")
    print("TX Enable     :", snap.tx_enable, "| Connected:", snap.sspb_connected, "| Fault:", snap.fault)
    print("Model         :", snap.model, "| LO:", snap.lo_freq_ghz, "GHz")
    print("--- all events seen ---")
    for k in sorted(snap.raw):
        print(f"  {k} = {snap.raw[k]!r}")


if __name__ == "__main__":
    _main()
