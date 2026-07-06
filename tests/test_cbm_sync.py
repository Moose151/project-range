"""Standalone checks for EBEM/CBM dashboard sync mapping.

Run: venv/bin/python tests/test_cbm_sync.py
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cbm import CBMSnapshot  # noqa: E402
from app.cbm_sync import (  # noqa: E402
    _entry_values_from_snapshot,
    _float_text,
    _status_from_snapshot,
)


def entry(path: str = "tx"):
    return SimpleNamespace(
        cbm_path=path,
        modulation="BPSK",
        symbol_rate="1000",
        fec="1/2",
        power=None,
        eb_no=None,
        tx_if=None,
        rx_if=None,
    )


def test_tx_status_accepts_active_variants():
    snapshot = CBMSnapshot(
        tx_config={"TX_OP": "on"},
        rx_config={},
        status={},
    )
    assert _status_from_snapshot(snapshot, "tx") == "Up"

    snapshot = CBMSnapshot(
        tx_config={},
        rx_config={},
        status={"TXIF_EN": "Enabled"},
    )
    assert _status_from_snapshot(snapshot, "tx") == "Up"


def test_missing_tx_status_does_not_force_down():
    snapshot = CBMSnapshot(tx_config={}, rx_config={}, status={})
    assert _status_from_snapshot(snapshot, "tx") is None


def test_rx_status_uses_any_positive_lock_indicator():
    snapshot = CBMSnapshot(
        tx_config={},
        rx_config={},
        status={"ACQ_STATE": "IDLE", "LINK_STAT": "LINK_UP"},
    )
    assert _status_from_snapshot(snapshot, "rx") == "Up"


def test_ebno_aliases_and_units_are_mapped():
    assert _float_text("12.4 dB") == 12.4
    snapshot = CBMSnapshot(
        tx_config={},
        rx_config={},
        status={"EBNO": "11.7 dB", "LINK_STAT": "LINK_UP"},
    )
    values = _entry_values_from_snapshot(entry("rx"), snapshot)
    assert values["signal_status"] == "Up"
    assert values["eb_no"] == 11.7


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(tests)} CBM sync tests passed.")
