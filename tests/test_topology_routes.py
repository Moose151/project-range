"""Standalone unit checks for topology live routed path derivation.

Run: python3 tests/test_topology_routes.py
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.routers.devices import (  # noqa: E402
        _auto_inferred_links,
        _device_port_counts,
        _is_ebem_device,
        _live_routed_paths,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - local dependency bootstrap
    if exc.name == "fastapi":
        print("skipped topology route tests: FastAPI is not installed in this environment")
        raise SystemExit(0)
    raise


def dev(dev_id, name, device_type, ports=None):
    return SimpleNamespace(id=dev_id, name=name, device_model=None, device_type=device_type, ports=ports or [])


def port(direction, idx, observed=None, label=None):
    return SimpleNamespace(direction=direction, idx=idx, observed_routed_from=observed, observed_label=label, label=None)


def link(from_dev, to_dev, from_idx=None, to_idx=None):
    return SimpleNamespace(
        from_device_id=from_dev.id,
        from_device=from_dev,
        from_port=None,
        from_port_idx=from_idx,
        to_device_id=to_dev.id,
        to_device=to_dev,
        to_port=None,
        to_port_idx=to_idx,
        link_type="rf",
    )


def test_splitter_routes_input_to_observed_output():
    source = dev(1, "CBM-400 1 Tx", "modem")
    splitter = dev(2, "IF-DIV-01", "splitter", [
        port("in", 1, label="Input 1"),
        port("out", 5, observed=1, label="Output 5"),
    ])
    downstream = dev(3, "Mission System 1 Tx", "other")
    routes = _live_routed_paths(
        [source, splitter, downstream],
        [link(source, splitter, to_idx=1), link(splitter, downstream, from_idx=5)],
    )
    assert len(routes) == 1
    assert routes[0]["from_device"] == "CBM-400 1 Tx"
    assert routes[0]["through_device"] == "IF-DIV-01"
    assert routes[0]["input_idx"] == 1
    assert routes[0]["output_idx"] == 5
    assert routes[0]["to_device"] == "Mission System 1 Tx"


def test_combiner_routes_observed_input_to_output():
    source = dev(1, "Mission System 1 Rx", "other")
    combiner = dev(2, "IF-COMB-01", "combiner", [
        port("in", 5, observed=15, label="Input 5"),
        port("out", 15, label="Loopback 1"),
    ])
    downstream = dev(3, "CBM-400 1 Rx", "modem")
    routes = _live_routed_paths(
        [source, combiner, downstream],
        [link(source, combiner, to_idx=5), link(combiner, downstream, from_idx=15)],
    )
    assert len(routes) == 1
    assert routes[0]["from_device"] == "Mission System 1 Rx"
    assert routes[0]["through_device"] == "IF-COMB-01"
    assert routes[0]["input_idx"] == 5
    assert routes[0]["output_idx"] == 15
    assert routes[0]["to_device"] == "CBM-400 1 Rx"


def test_auto_infers_links_from_matrix_port_aliases():
    cbm = dev(1, "CBM-400-1", "modem")
    splitter = dev(2, "IF-DIV-01", "splitter", [
        port("in", 1, label="CBM-400 1 Tx"),
        port("out", 5, label="Mission System 1 Tx"),
    ])
    mission = dev(3, "Mission-System-1", "other")
    inferred = _auto_inferred_links([cbm, splitter, mission], [])
    assert len(inferred) == 2
    assert inferred[0].from_device_id == cbm.id
    assert inferred[0].to_device_id == splitter.id
    assert inferred[0].to_port_idx == 1
    assert inferred[1].from_device_id == splitter.id
    assert inferred[1].from_port_idx == 5
    assert inferred[1].to_device_id == mission.id


def test_device_form_eligibility_helpers():
    assert _is_ebem_device("modem", "CBM-400-1", None)
    assert _is_ebem_device("modem", "Modem 1", "EBEM")
    assert not _is_ebem_device("modem", "Generic Modem", None)
    assert not _is_ebem_device("splitter", "CBM-400-1", None)
    assert _device_port_counts("modem", 16, 16) == (1, 1)
    assert _device_port_counts("splitter", 16, 16) == (16, 16)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} topology route tests passed.")


if __name__ == "__main__":
    main()
