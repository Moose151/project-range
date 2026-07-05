"""Standalone unit checks for app.snmp parsing (no hardware, no pytest required).

Run: python tests/test_snmp.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.snmp import (  # noqa: E402
    OID_HAWK_OUTPUT_ROUTING,
    OID_MODULE_INFO_STATUS,
    OID_MODULE_INFO_ALIAS,
    OID_MODULE_INFO_MODEL,
    OID_SYSTEM_SUMMARY_ALARM,
    _oid_tail,
    parse_routing,
    parse_modules,
    build_snapshot,
)


def test_oid_tail():
    assert _oid_tail("1.2.3.4", "1.2.3") == [4]
    assert _oid_tail("1.2.3", "1.2.3") == []
    assert _oid_tail("1.2.9", "1.2.3") is None
    assert _oid_tail("1.2.30", "1.2.3") is None  # not a real child (prefix guard)


def test_parse_routing():
    # column 2 (Route1Set), row 1 -> output 1; column 3 row 1 -> output 2; index col 1 ignored.
    vb = [
        (f"{OID_HAWK_OUTPUT_ROUTING}.1.1", "1"),   # index column -> ignored
        (f"{OID_HAWK_OUTPUT_ROUTING}.2.1", "5"),   # out 1 <- in 5
        (f"{OID_HAWK_OUTPUT_ROUTING}.3.1", "0"),   # out 2 <- none
        (f"{OID_HAWK_OUTPUT_ROUTING}.9.1", "12"),  # out 8 <- in 12 (Route8Set)
        (f"{OID_HAWK_OUTPUT_ROUTING}.2.2", "7"),   # row 2 -> out 9 <- in 7
    ]
    routing = parse_routing(vb)
    assert routing[1] == 5, routing
    assert routing[2] == 0, routing
    assert routing[8] == 12, routing
    assert routing[9] == 7, routing


def test_parse_modules():
    vb = [
        (f"{OID_MODULE_INFO_STATUS}.1", "O"),
        (f"{OID_MODULE_INFO_ALIAS}.1", "Matrix In"),
        (f"{OID_MODULE_INFO_MODEL}.1", "GNS-HWK"),
        (f"{OID_MODULE_INFO_STATUS}.2", "F"),
    ]
    modules = parse_modules(vb)
    assert modules[0] == {"status": "O", "alias": "Matrix In", "model": "GNS-HWK"}, modules
    assert modules[1] == {"status": "F"}, modules


def test_build_snapshot():
    routing_vb = [(f"{OID_HAWK_OUTPUT_ROUTING}.2.1", "3")]
    module_vb = [(f"{OID_MODULE_INFO_STATUS}.1", "F")]
    snap = build_snapshot(routing_vb, module_vb, "1")  # 1 -> fault
    assert snap.routing == {1: 3}
    assert snap.system_alarm == "fault"
    assert snap.raw[OID_SYSTEM_SUMMARY_ALARM] == "1"
    summ = snap.summary
    assert summ["outputs_routed"] == 1
    assert summ["system_alarm"] == "fault"
    assert len(summ["module_faults"]) == 1  # status "F" is a fault


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} SNMP parse tests passed.")


if __name__ == "__main__":
    main()
