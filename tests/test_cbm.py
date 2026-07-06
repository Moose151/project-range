"""Regression checks for CBM/EBEM ICC parsing (no hardware, no pytest required).

Run: python tests/test_cbm.py

Fixtures mirror the real EBEM shell output documented in the CBM-400 EBEM manual,
including the echoed command line that previously corrupted the first parsed field.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cbm import parse_icc_response, CBMSnapshot  # noqa: E402
from app.cbm_sync import _status_from_snapshot, _entry_values_from_snapshot  # noqa: E402


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
Carrier,ACQ_STATE=ACQUIRED,BSYNC_STAT=SYNC,MDM_STAT=ONLINE,LINK_STAT=LINK_UP,FLT_STAT=NONE
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
    assert st.get("ACQ_STATE") == "ACQUIRED"


def test_status_up_when_tx_on():
    snap = CBMSnapshot(
        tx_config=parse_icc_response(TX_CFG_RAW, "TX_CFG"),
        rx_config={},
        status=parse_icc_response(ALL_STAT_RAW, "ALL_STAT"),
    )
    assert _status_from_snapshot(snap, "tx") == "Up"


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


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} CBM parser tests passed.")


if __name__ == "__main__":
    main()
