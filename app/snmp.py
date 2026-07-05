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
OID_HAWK_OUTPUT_ROUTING = f"{GENUS_ROOT}.6.2.2.1"  # hawkOutputRoutingSettingsEntry
_HAWK_ROUTE_COLS = 8  # Route1Set .. Route8Set (columns 2..9)

# systemSummaryAlarm / moduleInfoSummaryStatus integer meanings.
SUMMARY_ALARM_TEXT = {"0": "ok", "1": "fault", "2": "warning"}


class SNMPError(RuntimeError):
    pass


@dataclass
class MatrixSnapshot:
    """Parsed read-only view of a Genus/VTR matrix."""

    routing: dict[int, int] = field(default_factory=dict)          # output idx -> input idx (0 = none)
    system_alarm: str | None = None                                 # ok|fault|warning
    modules: list[dict[str, str]] = field(default_factory=list)     # [{alias, model, status}]
    raw: dict[str, str] = field(default_factory=dict)               # oid -> value (audit/debug)

    @property
    def summary(self) -> dict[str, object]:
        return {
            "system_alarm": self.system_alarm,
            "outputs_routed": len([o for o, i in self.routing.items() if i]),
            "outputs_total": len(self.routing),
            "module_faults": [
                m for m in self.modules if (m.get("status") or "").lower() not in ("", "ok", "o", "0")
            ],
        }


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


def parse_routing(varbinds: list[tuple[str, str]]) -> dict[int, int]:
    """Interpret hawkOutputRoutingSettings varbinds into {output_idx: input_idx}.

    The routing entry is INDEX { hawkOutputRouteNumber } with 8 Route*Set columns.
    Best-effort layout: each row (routeNumber = bank, 1-based) carries 8 outputs, so
    output number = (routeNumber - 1) * 8 + column, and the cell value is the input
    routed to that output (0/negative = unrouted / terminated).
    """
    routing: dict[int, int] = {}
    for oid, value in varbinds:
        tail = _oid_tail(oid, OID_HAWK_OUTPUT_ROUTING)
        if not tail or len(tail) < 2:
            continue
        column, route_number = tail[0], tail[1]
        if column < 2 or column > (1 + _HAWK_ROUTE_COLS):
            continue  # skip the index column (1) and anything unexpected
        output_idx = (route_number - 1) * _HAWK_ROUTE_COLS + (column - 1)
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
    return [by_index[i] for i in sorted(by_index)]


def build_snapshot(
    routing_vb: list[tuple[str, str]],
    module_vb: list[tuple[str, str]],
    system_alarm_value: str | None,
) -> MatrixSnapshot:
    """Pure assembly of a MatrixSnapshot from raw varbind lists — unit-testable."""
    raw = {oid: val for oid, val in (*routing_vb, *module_vb)}
    if system_alarm_value is not None:
        raw[OID_SYSTEM_SUMMARY_ALARM] = system_alarm_value
    alarm = SUMMARY_ALARM_TEXT.get(str(system_alarm_value).strip()) if system_alarm_value is not None else None
    return MatrixSnapshot(
        routing=parse_routing(routing_vb),
        system_alarm=alarm,
        modules=parse_modules(module_vb),
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


async def _poll_genus_matrix_async(
    host: str, port: int, community: str | None, v3: dict | None,
    timeout: float, retries: int,
) -> MatrixSnapshot:
    try:
        from pysnmp.hlapi.asyncio import (
            SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget, ContextData,
            usmHMACSHAAuthProtocol, usmAesCfb128Protocol,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SNMPError("pysnmp is not installed; rebuild/install requirements first") from exc

    if v3:
        auth = UsmUserData(
            v3.get("user") or "",
            authKey=v3.get("auth_key") or None,
            privKey=v3.get("priv_key") or None,
            authProtocol=usmHMACSHAAuthProtocol if v3.get("auth_key") else None,
            privProtocol=usmAesCfb128Protocol if v3.get("priv_key") else None,
        )
    elif community:
        auth = CommunityData(community, mpModel=1)  # mpModel=1 -> SNMP v2c
    else:
        raise SNMPError("no SNMP credentials provided (need community or v3 user)")

    engine = SnmpEngine()
    context = ContextData()
    transport = await UdpTransportTarget.create((host, port), timeout=timeout, retries=retries)

    routing_vb = await _walk(engine, auth, transport, context, OID_HAWK_OUTPUT_ROUTING)
    module_vb = await _walk(engine, auth, transport, context, OID_MODULE_INFO_TABLE)
    system_alarm = await _get(engine, auth, transport, context, OID_SYSTEM_SUMMARY_ALARM)
    return build_snapshot(routing_vb, module_vb, system_alarm)


def _run_blocking(coro_factory) -> MatrixSnapshot:
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
