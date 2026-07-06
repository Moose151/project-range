"""Read-only SNMP polling of ETL Systems Genus / VTR matrices (splitter/combiner).

Reads the live routing crossbar (which input feeds each output) plus system/module
health from the vendor MIB tree, so operators can compare what the hardware is
*actually* doing against the manually-entered plan. Read-only: this module never
issues SNMP SET.

OID map (resolved from the ETL Systems MIBs under System Manuals/, enterprise 20938):
    etlsystems            1.3.6.1.4.1.20938
    etlProducts.misc.genus 1.3.6.1.4.1.20938.1.7.5          (= GENUS_ROOT)
      systemSummaryAlarm   genus.1   scalar .0  INTEGER ok(0)/fault(1)/warning(2)
      moduleInfoTable      genus.2   entry .1  col2=SummaryStatus col3=Alias col4=Model
      genusMatrix          genus.6
        hawkOutput         genusMatrix.2
          hawkOutputRoutingSettingsTable  hawkOutput.2  entry .1
            col1 = hawkOutputRouteNumber
            col2..col9 = hawkOutputRoute1Set .. hawkOutputRoute8Set (input routed to output)

Exact routing-table semantics must be confirmed against real hardware (see the
handover's hardware-validation gap); the interpretation here is best-effort and the
raw varbinds are always retained.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

GENUS_ROOT = "1.3.6.1.4.1.20938.1.7.5"

OID_SYSTEM_SUMMARY_ALARM = f"{GENUS_ROOT}.1.0"
OID_MODULE_INFO_TABLE = f"{GENUS_ROOT}.2.1"
OID_MODULE_INFO_STATUS = f"{GENUS_ROOT}.2.1.2"   # moduleInfoSummaryStatus column
OID_MODULE_INFO_ALIAS = f"{GENUS_ROOT}.2.1.3"    # moduleInfoAlias column
OID_MODULE_INFO_MODEL = f"{GENUS_ROOT}.2.1.4"    # moduleInfoModelNumber column

ENTERPRISE_ROOT = "1.3.6.1.4.1.20938"  # ETL Systems — diagnostic walk base
GENUS_MATRIX = f"{GENUS_ROOT}.6"       # genusMatrix branch


@dataclass(frozen=True)
class MatrixProfile:
    """A Genus matrix family's routing table. All share the same row/column shape:
    entry column 1 = RouteNumber (row index), columns 2.. = Route{n}Set (input routed
    to output, 0 = terminated). Only the base OID and column count differ per model."""
    name: str
    routing_oid: str   # ...RoutingSettingsEntry
    route_cols: int    # number of Route*Set columns


# Tried in order during auto-detection; first table that returns rows wins.
# genusMatrix index per module verified from the ETL MIBs; RoutingSettingsTable = .2,
# entry = .1, columns 2.. = Route{n}Set. VTR/VTRC families are 16-wide; Hawk is 8-wide.
MATRIX_PROFILES = [
    MatrixProfile("vtr101", f"{GENUS_MATRIX}.9.2.1", 16),
    MatrixProfile("vtr100", f"{GENUS_MATRIX}.7.2.1", 16),
    MatrixProfile("vtr102", f"{GENUS_MATRIX}.11.2.1", 16),
    MatrixProfile("vtrc100", f"{GENUS_MATRIX}.8.2.1", 16),
    MatrixProfile("vtrc101", f"{GENUS_MATRIX}.10.2.1", 16),
    MatrixProfile("vtrc102", f"{GENUS_MATRIX}.12.2.1", 16),
    MatrixProfile("hawk", f"{GENUS_MATRIX}.2.2.1", 8),
]

# systemSummaryAlarm integer meanings.
SUMMARY_ALARM_TEXT = {"0": "ok", "1": "fault", "2": "warning"}

# moduleInfoSummaryStatus is a single char (see ETLSYSTEMS-GENUS-MIB):
#   'A' Absent, 'X'/'Y' Upgrading, 'C' Comms Issue, 'W' Warning, 'I' Invisible,
#   '0' OK, '1' Monitoring Not Set, '2' Temperature Alarm, '3' General Alarm.
MODULE_STATUS_TEXT = {
    "A": "absent", "X": "upgrading", "Y": "upgrading", "C": "comms issue",
    "W": "warning", "I": "invisible", "0": "ok", "1": "monitoring not set",
    "2": "temperature alarm", "3": "alarm",
}
# Statuses that should raise the effective alarm. 'A'/'I'/'X'/'Y'/'0'/'1' are
# treated as benign (absent slot, invisible, upgrading, ok, not-monitored).
MODULE_FAULT_STATUSES = {"C", "2", "3"}
MODULE_WARNING_STATUSES = {"W"}


class SNMPError(RuntimeError):
    pass


@dataclass
class MatrixSnapshot:
    """Parsed read-only view of a Genus/VTR matrix."""

    routing: dict[int, int] = field(default_factory=dict)          # output idx -> input idx (0 = none)
    system_alarm: str | None = None                                 # ok|fault|warning
    modules: list[dict[str, str]] = field(default_factory=list)     # [{alias, model, status}]
    profile: str | None = None                                      # detected matrix family (vtr101/hawk/...)
    raw: dict[str, str] = field(default_factory=dict)               # oid -> value (audit/debug)

    @property
    def summary(self) -> dict[str, object]:
        return {
            "system_alarm": self.system_alarm,
            "outputs_routed": len([o for o, i in self.routing.items() if i]),
            "outputs_total": len(self.routing),
            "module_faults": [m for m in self.modules if _module_severity(m.get("status")) == "fault"],
        }

    def effective_alarm(self, ignored_idxs: set[int] | None = None) -> str:
        return effective_alarm_from_modules(self.modules, ignored_idxs, fallback=self.system_alarm)


def effective_alarm_from_modules(
    modules: list[dict], ignored_idxs: set[int] | None = None, fallback: str | None = None
) -> str:
    """Worst status across modules, ignoring muted module indices.

    Derived from moduleInfoTable (not the device's own systemSummaryAlarm rollup) so
    operators can mute expected conditions such as an empty/unpowered PSU slot. Falls
    back to `fallback` when the module table is unavailable.
    """
    ignored_idxs = ignored_idxs or set()
    if not modules:
        return fallback or "unknown"
    worst = "ok"
    for m in modules:
        if m.get("idx") in ignored_idxs:
            continue
        sev = _module_severity(m.get("status"))
        if sev == "fault":
            return "fault"
        if sev == "warning":
            worst = "warning"
    return worst


def _module_severity(status: str | None) -> str:
    """Classify a moduleInfoSummaryStatus char into ok|warning|fault."""
    ch = (status or "").strip()[:1]
    if ch in MODULE_FAULT_STATUSES:
        return "fault"
    if ch in MODULE_WARNING_STATUSES:
        return "warning"
    return "ok"


def _oid_tail(oid: str, base: str) -> list[int] | None:
    """Return the trailing index ints of `oid` under `base`, or None if not under it."""
    base = base.rstrip(".")
    if oid == base:
        return []
    if not oid.startswith(base + "."):
        return None
    tail = oid[len(base) + 1:]
    try:
        return [int(part) for part in tail.split(".") if part != ""]
    except ValueError:
        return None


def parse_routing(varbinds: list[tuple[str, str]], base_oid: str, route_cols: int) -> dict[int, int]:
    """Interpret a Genus RoutingSettings table into {output_idx: input_idx}.

    The entry is INDEX { RouteNumber } (column 1) with `route_cols` Route{n}Set columns
    (OID columns 2..route_cols+1). Each cell value is the input routed to that output
    (0 = terminated). Layout: output = (RouteNumber - 1) * route_cols + column_position,
    so a single-row table maps columns directly onto outputs 1..route_cols.
    """
    routing: dict[int, int] = {}
    for oid, value in varbinds:
        tail = _oid_tail(oid, base_oid)
        if not tail or len(tail) < 2:
            continue
        column, route_number = tail[0], tail[1]
        if column < 2 or column > (1 + route_cols):
            continue  # skip the index column (1) and anything unexpected
        output_idx = (route_number - 1) * route_cols + (column - 1)
        try:
            input_idx = int(value)
        except (TypeError, ValueError):
            continue
        routing[output_idx] = max(input_idx, 0)
    return routing


def parse_modules(varbinds: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Collect per-module alias/model/status rows from moduleInfoTable varbinds."""
    by_index: dict[int, dict[str, str]] = {}
    columns = {
        OID_MODULE_INFO_STATUS: "status",
        OID_MODULE_INFO_ALIAS: "alias",
        OID_MODULE_INFO_MODEL: "model",
    }
    for oid, value in varbinds:
        for col_oid, key in columns.items():
            tail = _oid_tail(oid, col_oid)
            if tail and len(tail) == 1:
                by_index.setdefault(tail[0], {})[key] = value
                break
    modules = []
    for i in sorted(by_index):
        row = by_index[i]
        row["idx"] = i
        row["status_text"] = MODULE_STATUS_TEXT.get((row.get("status") or "").strip()[:1], row.get("status") or "")
        row["severity"] = _module_severity(row.get("status"))
        modules.append(row)
    return modules


def build_snapshot(
    routing_vb: list[tuple[str, str]],
    module_vb: list[tuple[str, str]],
    system_alarm_value: str | None,
    profile: MatrixProfile | None = None,
) -> MatrixSnapshot:
    """Pure assembly of a MatrixSnapshot from raw varbind lists — unit-testable."""
    raw = {oid: val for oid, val in (*routing_vb, *module_vb)}
    if system_alarm_value is not None:
        raw[OID_SYSTEM_SUMMARY_ALARM] = system_alarm_value
    alarm = SUMMARY_ALARM_TEXT.get(str(system_alarm_value).strip()) if system_alarm_value is not None else None
    routing = parse_routing(routing_vb, profile.routing_oid, profile.route_cols) if profile else {}
    return MatrixSnapshot(
        routing=routing,
        system_alarm=alarm,
        modules=parse_modules(module_vb),
        profile=profile.name if profile else None,
        raw=raw,
    )


async def _walk(engine, auth, transport, context, base_oid: str) -> list[tuple[str, str]]:
    """SNMP WALK a subtree, returning [(oid_str, value_str)]."""
    from pysnmp.hlapi.asyncio import ObjectType, ObjectIdentity, walk_cmd

    results: list[tuple[str, str]] = []
    async for error_indication, error_status, error_index, var_binds in walk_cmd(
        engine, auth, transport, context,
        ObjectType(ObjectIdentity(base_oid)),
        lexicographicMode=False,
    ):
        if error_indication:
            raise SNMPError(str(error_indication))
        if error_status:
            raise SNMPError(f"{error_status.prettyPrint()} at {error_index}")
        for name, val in var_binds:
            results.append((str(name), val.prettyPrint()))
    return results


async def _get(engine, auth, transport, context, oid: str) -> str | None:
    from pysnmp.hlapi.asyncio import ObjectType, ObjectIdentity, get_cmd

    error_indication, error_status, _error_index, var_binds = await get_cmd(
        engine, auth, transport, context, ObjectType(ObjectIdentity(oid))
    )
    if error_indication or error_status:
        return None
    for _name, val in var_binds:
        return val.prettyPrint()
    return None


def _make_auth(community: str | None, v3: dict | None):
    """Build a pysnmp auth object (v2c community or v3 user). Lazy-imports pysnmp."""
    try:
        from pysnmp.hlapi.asyncio import (
            CommunityData, UsmUserData, usmHMACSHAAuthProtocol, usmAesCfb128Protocol,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SNMPError("pysnmp is not installed; rebuild/install requirements first") from exc

    if v3:
        return UsmUserData(
            v3.get("user") or "",
            authKey=v3.get("auth_key") or None,
            privKey=v3.get("priv_key") or None,
            authProtocol=usmHMACSHAAuthProtocol if v3.get("auth_key") else None,
            privProtocol=usmAesCfb128Protocol if v3.get("priv_key") else None,
        )
    if community:
        return CommunityData(community, mpModel=1)  # mpModel=1 -> SNMP v2c
    raise SNMPError("no SNMP credentials provided (need community or v3 user)")


async def _poll_genus_matrix_async(
    host: str, port: int, community: str | None, v3: dict | None,
    timeout: float, retries: int,
) -> MatrixSnapshot:
    from pysnmp.hlapi.asyncio import SnmpEngine, UdpTransportTarget, ContextData

    auth = _make_auth(community, v3)
    engine = SnmpEngine()
    context = ContextData()
    transport = await UdpTransportTarget.create((host, port), timeout=timeout, retries=retries)

    # Auto-detect the matrix family: walk each profile's routing table, first with rows wins.
    routing_vb: list[tuple[str, str]] = []
    matched: MatrixProfile | None = None
    for prof in MATRIX_PROFILES:
        rows = await _walk(engine, auth, transport, context, prof.routing_oid)
        if rows:
            routing_vb, matched = rows, prof
            break

    module_vb = await _walk(engine, auth, transport, context, OID_MODULE_INFO_TABLE)
    system_alarm = await _get(engine, auth, transport, context, OID_SYSTEM_SUMMARY_ALARM)
    return build_snapshot(routing_vb, module_vb, system_alarm, matched)


async def _diag_walk_async(
    host: str, port: int, community: str | None, v3: dict | None,
    base_oid: str, timeout: float, retries: int,
) -> list[tuple[str, str]]:
    from pysnmp.hlapi.asyncio import SnmpEngine, UdpTransportTarget, ContextData

    auth = _make_auth(community, v3)
    engine = SnmpEngine()
    context = ContextData()
    transport = await UdpTransportTarget.create((host, port), timeout=timeout, retries=retries)
    return await _walk(engine, auth, transport, context, base_oid)


def _run_blocking(coro_factory):
    """Run an async coroutine to completion on a private event loop in a worker thread.

    pysnmp 7.x is asyncio-only. Using a dedicated thread keeps poll_genus_matrix safe to
    call from both a running FastAPI request handler and a plain worker thread, avoiding
    "asyncio.run() cannot be called from a running event loop".
    """
    box: dict[str, object] = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


def poll_genus_matrix(
    host: str,
    *,
    port: int = 161,
    community: str | None = None,
    v3: dict | None = None,
    timeout: float = 6.0,
    retries: int = 1,
) -> MatrixSnapshot:
    """Poll a Genus/VTR matrix read-only over SNMP (v2c community or v3 user).

    Synchronous wrapper around the asyncio pysnmp client. `v3` (when given) is a dict
    with keys: user, auth_key, priv_key.
    """
    if not community and not v3:
        raise SNMPError("no SNMP credentials provided (need community or v3 user)")

    def factory():
        return _poll_genus_matrix_async(host, port, community, v3, timeout, retries)

    try:
        return _run_blocking(factory)
    except SNMPError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise any transport error
        raise SNMPError(str(exc)) from exc


def snmp_diagnostic_walk(
    host: str,
    *,
    port: int = 161,
    community: str | None = None,
    v3: dict | None = None,
    base_oid: str = ENTERPRISE_ROOT,
    timeout: float = 6.0,
    retries: int = 1,
    max_rows: int = 2000,
) -> list[tuple[str, str]]:
    """Read-only WALK of a subtree, returning [(oid, value)] for diagnostics.

    Used to discover what a specific device actually exposes (routing OIDs, module
    layout, PSU status, etc.) when the default matrix reader finds nothing.
    """
    if not community and not v3:
        raise SNMPError("no SNMP credentials provided (need community or v3 user)")

    def factory():
        return _diag_walk_async(host, port, community, v3, base_oid, timeout, retries)

    try:
        rows = _run_blocking(factory)
    except SNMPError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise any transport error
        raise SNMPError(str(exc)) from exc
    return rows[:max_rows]
