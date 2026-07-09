"""Regression checks for CBM/EBEM ICC parsing (no hardware, no pytest required).

Run: python tests/test_cbm.py

Fixtures mirror the real EBEM shell output documented in the CBM-400 EBEM manual,
including the echoed command line that previously corrupted the first parsed field.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cbm import parse_icc_response, CBMSnapshot  # noqa: E402
from app.cbm_sync import (  # noqa: E402
    _status_from_snapshot, _entry_values_from_snapshot, _ebno_changed, _non_ebno_changed,
    sync_states_from_snapshot,
)


class _Log:
    def __init__(self, **kw):
        defaults = dict(signal_status=None, modulation=None, symbol_rate=None, fec=None,
                        power=None, eb_no=None, tx_if=None, tx_rf=None, rx_rf=None, rx_if=None)
        defaults.update(kw)
        self.__dict__.update(defaults)


def test_ebno_threshold_small_change_ignored():
    # Within +/-3 dB: not a change.
    assert _ebno_changed(7.8, 8.0, 3.0) is False
    assert _ebno_changed(7.8, 10.7, 3.0) is False
    # Beyond threshold: a change.
    assert _ebno_changed(7.8, 11.0, 3.0) is True
    # Carrier lost / acquired always counts.
    assert _ebno_changed(7.8, None, 3.0) is True
    assert _ebno_changed(None, 7.8, 3.0) is True
    assert _ebno_changed(None, None, 3.0) is False


def test_changed_ignores_small_ebno_but_catches_other_fields():
    latest = _Log(signal_status="Up", power=-10.0, eb_no=7.8)
    # Only a tiny Eb/No drift -> no non-ebno change, and the drift is within threshold.
    assert _non_ebno_changed(latest, {"signal_status": "Up", "power": -10.0, "eb_no": 8.5}) is False
    assert _ebno_changed(7.8, 8.5, 3.0) is False
    # Power change -> a non-ebno change is caught regardless of Eb/No drift.
    assert _non_ebno_changed(latest, {"signal_status": "Up", "power": -12.0, "eb_no": 8.5}) is True


# Real format: the shell echoes "tx_cfg ?" before the "TX_CFG ..." response, and the
# response wraps over several lines.
TX_CFG_RAW = """tx_cfg ?
TX_CFG TX_OP=ON,TXIF_LVL=-
10.00,TXIF_FRQ=1300000,TX_MOP=EBEM,TX_SMOP=TURBO,TX_MOD=BPSK,TX_DR=16384000,TX_SR=32980728.0,
TX_CODE=1/2TURBO:16384,TX_DIFF=OFF,ITA_ENGAGE=AUTO
"""

# ALL_STAT with a receiving/locked demod (real Eb/No value present).
ALL_STAT_RAW = """all_stat ?
ALL_STAT ITT_NCHGS=0,AUPC_STAT=DISENGAGED,RXIF_LVL=-45.5,RX_EBNO=7.8,RX_ESNO=No
Carrier,RX_BEREST=1.2E-7,ACQ_STATE=ACQUIRED,BSYNC_STAT=SYNC,ESYNC_STAT=SYNC,MDM_STAT=ONLINE,LINK_STAT=LINK_UP,FLT_STAT=NONE
"""

ALL_STAT_NO_CARRIER = """all_stat ?
ALL_STAT ITT_NCHGS=0,RXIF_LVL=No Data,RX_EBNO=No Carrier,ACQ_STATE=IDLE,LINK_STAT=LINK_DOWN
"""


def test_tx_cfg_echo_not_corrupting_first_field():
    cfg = parse_icc_response(TX_CFG_RAW, "TX_CFG")
    # The bug produced key "?TX_CFGTX_OP"; the fix must yield a clean TX_OP.
    assert cfg.get("TX_OP") == "ON", cfg
    assert "?TX_CFGTX_OP" not in cfg
    assert cfg.get("TX_MOD") == "BPSK"
    assert cfg.get("TXIF_FRQ") == "1300000"


def test_all_stat_first_field_and_ebno():
    st = parse_icc_response(ALL_STAT_RAW, "ALL_STAT")
    assert st.get("ITT_NCHGS") == "0", st        # first field no longer corrupted
    assert st.get("RX_EBNO") == "7.8"
    assert st.get("RX_BEREST") == "1.2E-7"
    assert st.get("ACQ_STATE") == "ACQUIRED"


def test_status_up_when_tx_on():
    snap = CBMSnapshot(
        tx_config=parse_icc_response(TX_CFG_RAW, "TX_CFG"),
        rx_config={},
        status=parse_icc_response(ALL_STAT_RAW, "ALL_STAT"),
    )
    assert _status_from_snapshot(snap, "tx") == "Up"


def test_status_down_when_tx_off_despite_itt_engaged():
    # Real CBM-400-4 capture: TX_OP=OFF, yet ITT_STAT reports ENGAGED. TX_OP is
    # authoritative — the signal must read Down, not "transmitting".
    snap = CBMSnapshot(
        tx_config={"TX_OP": "OFF", "ITT_OP": "DISABLE"},
        rx_config={"RX_OP": "OFF"},
        status={"ITT_STAT": "ENGAGED", "ACQ_STATE": "IDLE",
                "BSYNC_STAT": "NOSYNC", "ESYNC_STAT": "NOSYNC", "MDM_STAT": "DISABLED"},
    )
    assert _status_from_snapshot(snap, "tx") == "Down"
    assert _status_from_snapshot(snap, "tx_rx") == "Down"
    assert _status_from_snapshot(snap, "rx") == "Down"


def test_ebno_populates_for_tx_path():
    class _Entry:
        cbm_path = "tx"
        modulation = symbol_rate = fec = power = eb_no = tx_if = rx_if = None
    snap = CBMSnapshot(
        tx_config=parse_icc_response(TX_CFG_RAW, "TX_CFG"),
        rx_config={},
        status=parse_icc_response(ALL_STAT_RAW, "ALL_STAT"),
    )
    values = _entry_values_from_snapshot(_Entry(), snap)
    assert values["signal_status"] == "Up"
    assert values["eb_no"] == 7.8   # read even on a tx-path mapping
    assert values["ber_estimate"] == 1.2e-7


def test_ber_estimate_cached_for_dashboard():
    snap = CBMSnapshot(
        tx_config=parse_icc_response(TX_CFG_RAW, "TX_CFG"),
        rx_config={},
        status=parse_icc_response(ALL_STAT_RAW, "ALL_STAT"),
    )
    assert snap.summary["rx_ber_estimate"] == "1.2E-7"
    state = sync_states_from_snapshot(snap)
    assert state["ebem_sync"] is True
    assert state["carrier_lock"] is True
    assert state["bit_sync"] is True
    assert state["ber_estimate"] == 1.2e-7


def test_ebno_none_when_no_carrier():
    class _Entry:
        cbm_path = "tx"
        modulation = symbol_rate = fec = power = tx_if = rx_if = None
        eb_no = None
    snap = CBMSnapshot(
        tx_config=parse_icc_response(TX_CFG_RAW, "TX_CFG"),
        rx_config={},
        status=parse_icc_response(ALL_STAT_NO_CARRIER, "ALL_STAT"),
    )
    values = _entry_values_from_snapshot(_Entry(), snap)
    assert values["eb_no"] is None   # "No Carrier" -> not a number
    assert sync_states_from_snapshot(snap)["ber_estimate"] is None


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} CBM parser tests passed.")


if __name__ == "__main__":
    main()
