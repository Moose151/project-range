"""Standalone unit checks for app.snmp parsing (no hardware, no pytest required).

Run: python tests/test_snmp.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.snmp import (  # noqa: E402
    MATRIX_PROFILES,
    OID_MODULE_INFO_STATUS,
    OID_MODULE_INFO_ALIAS,
    OID_MODULE_INFO_MODEL,
    OID_SYSTEM_SUMMARY_ALARM,
    _oid_tail,
    parse_routing,
    parse_aliases,
    parse_modules,
    build_snapshot,
)

VTR101 = next(p for p in MATRIX_PROFILES if p.name == "vtr101")  # 16 route columns
VTRC101 = next(p for p in MATRIX_PROFILES if p.name == "vtrc101")


def test_vtrc_alias_oids_mirrored():
    # Combiner alias tables are swapped vs splitter (Ip=.6, Op=.5).
    assert VTR101.input_alias_oid.endswith(".9.5.1") and VTR101.output_alias_oid.endswith(".9.6.1")
    assert VTRC101.input_alias_oid.endswith(".10.6.1") and VTRC101.output_alias_oid.endswith(".10.5.1")
    assert VTR101.routing_mode == "output_to_input"
    assert VTRC101.routing_mode == "input_to_output"


def test_parse_aliases():
    base = VTR101.input_alias_oid  # 16 cols: column c -> port (c-1) on row 1
    vb = [
        (f"{base}.1.1", "0"),               # index col ignored
        (f"{base}.2.1", "CBM-400 1 Tx"),    # input 1
        (f"{base}.3.1", "  "),              # blank -> skipped
        (f"{base}.17.1", "Loopback 1"),     # input 16
    ]
    aliases = parse_aliases(vb, base, VTR101.route_cols)
    assert aliases[1] == "CBM-400 1 Tx"
    assert 2 not in aliases
    assert aliases[16] == "Loopback 1"


def test_oid_tail():
    assert _oid_tail("1.2.3.4", "1.2.3") == [4]
    assert _oid_tail("1.2.3", "1.2.3") == []
    assert _oid_tail("1.2.9", "1.2.3") is None
    assert _oid_tail("1.2.30", "1.2.3") is None  # not a real child (prefix guard)


def test_parse_routing_vtr101():
    base = VTR101.routing_oid  # 16 columns -> column c maps to output (c-1) on row 1
    vb = [
        (f"{base}.1.1", "1"),    # index column -> ignored
        (f"{base}.2.1", "5"),    # Route1Set  -> out 1 <- in 5
        (f"{base}.3.1", "0"),    # Route2Set  -> out 2 <- terminated
        (f"{base}.17.1", "13"),  # Route16Set -> out 16 <- in 13
    ]
    routing = parse_routing(vb, base, VTR101.route_cols)
    assert routing[1] == 5, routing
    assert routing[2] == 0, routing
    assert routing[16] == 13, routing


def test_parse_routing_vtrc101():
    base = VTRC101.routing_oid  # 16 columns -> column c maps to input (c-1) on row 1
    vb = [
        (f"{base}.1.1", "1"),    # index column -> ignored
        (f"{base}.2.1", "15"),   # Route1Set  -> in 1 -> out 15
        (f"{base}.3.1", "0"),    # Route2Set  -> in 2 terminated/not routed
        (f"{base}.17.1", "16"),  # Route16Set -> in 16 -> out 16
    ]
    routing = parse_routing(vb, base, VTRC101.route_cols, VTRC101.routing_mode)
    assert routing[1] == 15, routing
    assert routing[2] == 0, routing
    assert routing[16] == 16, routing


def test_parse_modules_severity():
    vb = [
        (f"{OID_MODULE_INFO_STATUS}.1", "0"),   # OK
        (f"{OID_MODULE_INFO_ALIAS}.1", "PSU1"),
        (f"{OID_MODULE_INFO_MODEL}.1", "MPS1170"),
        (f"{OID_MODULE_INFO_STATUS}.2", "3"),   # General Alarm -> fault
        (f"{OID_MODULE_INFO_ALIAS}.2", "PSU2"),
    ]
    modules = parse_modules(vb)
    assert modules[0]["idx"] == 1 and modules[0]["severity"] == "ok"
    assert modules[0]["status_text"] == "ok"
    assert modules[1]["idx"] == 2 and modules[1]["severity"] == "fault"
    assert modules[1]["alias"] == "PSU2"


def test_effective_alarm_mutes_module():
    # PSU2 (idx 2) faulted; muting it drops the effective alarm to ok.
    module_vb = [
        (f"{OID_MODULE_INFO_STATUS}.1", "0"),
        (f"{OID_MODULE_INFO_STATUS}.2", "3"),
    ]
    snap = build_snapshot([], module_vb, "1", VTR101)  # device rollup says fault
    assert snap.effective_alarm(set()) == "fault"       # nothing muted
    assert snap.effective_alarm({2}) == "ok"            # PSU2 muted -> ok


def test_build_snapshot():
    base = VTR101.routing_oid
    routing_vb = [(f"{base}.2.1", "3")]
    module_vb = [(f"{OID_MODULE_INFO_STATUS}.1", "3")]
    snap = build_snapshot(routing_vb, module_vb, "1", VTR101)  # 1 -> fault
    assert snap.routing == {1: 3}
    assert snap.routing_mode == "output_to_input"
    assert snap.system_alarm == "fault"
    assert snap.profile == "vtr101"
    assert snap.raw[OID_SYSTEM_SUMMARY_ALARM] == "1"
    summ = snap.summary
    assert summ["outputs_routed"] == 1
    assert len(summ["module_faults"]) == 1  # status "3" is a fault


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} SNMP parse tests passed.")


if __name__ == "__main__":
    main()
