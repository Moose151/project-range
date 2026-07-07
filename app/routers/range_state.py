import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import (
    User, RangeStateLog, AuditLog, RangeState, Role,
    RFDevice, DevicePort, DeviceLink, CDATable, CDAWindow, RoutingPreset,
)
from app.auth import verify_password

router = APIRouter(prefix="/range-state")
from app.templating import templates

VALID_STATES = [s.value for s in RangeState]


def _routing_mismatches(db: Session, target_state: str) -> list[dict]:
    """Return per-device lists of routing changes required to match the preset for target_state.

    Only includes devices that have SNMP polling enabled and have been polled at least once
    (i.e. have observed_routed_from data). A device with a preset but no observed data is
    flagged separately so the operator knows the check couldn't be performed.
    """
    presets = db.query(RoutingPreset).filter(RoutingPreset.range_state == target_state).all()
    result: list[dict] = []
    for preset in presets:
        try:
            routes: dict[str, int] = json.loads(preset.routes_json or "{}")
        except (ValueError, TypeError):
            continue
        if not routes:
            continue
        dev = preset.device
        if not dev:
            continue

        routing_mode = "input_to_output" if dev.device_type == "combiner" else "output_to_input"

        # Map port idx → observed routing value
        observed: dict[str, int | None] = {}
        if routing_mode == "input_to_output":
            for p in dev.ports:
                if p.direction == "in" and p.idx is not None:
                    observed[str(p.idx)] = p.observed_routed_from
        else:
            for p in dev.ports:
                if p.direction == "out" and p.idx is not None:
                    observed[str(p.idx)] = p.observed_routed_from

        # Has the device been polled at all?
        has_observed = any(v is not None for v in observed.values())

        # Build port label maps for readable output
        in_name: dict[int, str] = {}
        out_name: dict[int, str] = {}
        for p in dev.ports:
            if p.direction == "in":
                in_name[p.idx] = p.observed_label or p.label or f"Input {p.idx}"
            else:
                out_name[p.idx] = p.observed_label or p.label or f"Output {p.idx}"

        changes: list[dict] = []
        unverified: list[dict] = []

        for port_key, target_from in routes.items():
            port_idx = int(port_key)
            current_from = observed.get(port_key)

            if routing_mode == "output_to_input":
                port_label = out_name.get(port_idx, f"Output {port_idx}")
                required_label = in_name.get(target_from, f"Input {target_from}")
                current_label = in_name.get(current_from, f"Input {current_from}") if current_from else "not routed"
            else:
                port_label = in_name.get(port_idx, f"Input {port_idx}")
                required_label = out_name.get(target_from, f"Output {target_from}")
                current_label = out_name.get(current_from, f"Output {current_from}") if current_from else "not routed"

            if not has_observed or port_key not in observed:
                unverified.append({"port": port_label, "required": required_label})
            elif current_from != target_from:
                changes.append({
                    "port": port_label,
                    "required": required_label,
                    "current": current_label,
                })

        if changes or unverified:
            result.append({
                "device": dev.name,
                "device_id": dev.id,
                "changes": changes,
                "unverified": unverified,
                "polled": has_observed,
            })

    return result


def _state_payload(db: Session) -> dict:
    state = get_current_range_state(db)
    latest = db.query(RangeStateLog).order_by(RangeStateLog.timestamp.desc()).first()
    return {
        "state": state,
        "is_testing": state == RangeState.TESTING.value,
        "changed_at": latest.timestamp.isoformat() if latest else "",
        "changed_by": latest.changed_by_user.display_name if latest and latest.changed_by_user else "",
    }


def _available_states(current: str, current_user: User) -> list[str]:
    if current == RangeState.TESTING.value and current_user.role != Role.SUPERVISOR:
        return []
    states = [s for s in VALID_STATES if s != current]
    if current_user.role != Role.SUPERVISOR:
        states = [s for s in states if s != RangeState.TESTING.value]
    return states


def _ensure_testing_workspace(db: Session, current_user: User) -> None:
    """Seed Testing with editable copies of operational devices and CDA tables."""
    if db.query(RFDevice).filter(RFDevice.is_testing == True).first() is None:
        id_map: dict[int, int] = {}
        devices = db.query(RFDevice).filter(RFDevice.is_testing == False).order_by(RFDevice.id).all()
        for dev in devices:
            clone = RFDevice(
                name=dev.name,
                device_model=dev.device_model,
                device_type=dev.device_type,
                host=dev.host,
                check_port=dev.check_port,
                has_web_gui=dev.has_web_gui,
                cbm_sync_enabled=dev.cbm_sync_enabled,
                cbm_username=dev.cbm_username,
                cbm_password_encrypted=dev.cbm_password_encrypted,
                cbm_last_sync_at=dev.cbm_last_sync_at,
                cbm_last_sync_status=dev.cbm_last_sync_status,
                cbm_last_sync_error=dev.cbm_last_sync_error,
                location=dev.location,
                notes=dev.notes,
                num_inputs=dev.num_inputs,
                num_outputs=dev.num_outputs,
                is_active=dev.is_active,
                is_testing=True,
            )
            db.add(clone)
            db.flush()
            id_map[dev.id] = clone.id
            for port in dev.ports:
                db.add(DevicePort(
                    device_id=clone.id,
                    direction=port.direction,
                    idx=port.idx,
                    label=port.label,
                    routed_from=port.routed_from,
                ))
        db.flush()
        links = db.query(DeviceLink).filter(DeviceLink.is_testing == False).order_by(DeviceLink.id).all()
        for link in links:
            if link.from_device_id in id_map and link.to_device_id in id_map:
                db.add(DeviceLink(
                    from_device_id=id_map[link.from_device_id],
                    from_port=link.from_port,
                    from_port_idx=link.from_port_idx,
                    to_device_id=id_map[link.to_device_id],
                    to_port=link.to_port,
                    to_port_idx=link.to_port_idx,
                    link_type=link.link_type,
                    label=link.label,
                    is_testing=True,
                ))

    if db.query(CDATable).filter(CDATable.is_testing == True).first() is None:
        tables = db.query(CDATable).filter(CDATable.is_testing == False).order_by(CDATable.id).all()
        for table in tables:
            clone = CDATable(
                name=table.name,
                description=table.description,
                created_by_id=current_user.id,
                is_testing=True,
            )
            db.add(clone)
            db.flush()
            for window in table.windows:
                db.add(CDAWindow(
                    cda_table_id=clone.id,
                    label=window.label,
                    start_zulu=window.start_zulu,
                    end_zulu=window.end_zulu,
                    max_power_dbm=window.max_power_dbm,
                ))


def _render_change(request, db, current_user, current, error,
                   target_state="", routing_mismatches=None, routing_confirmed=False):
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": target_state or "Live",
        "valid_states": _available_states(current, current_user),
        "range_state": current,
        "error": error,
        "routing_mismatches": routing_mismatches or [],
        "routing_confirmed": routing_confirmed,
        "page": "range_state",
    }, status_code=400)


@router.get("/change", response_class=HTMLResponse)
async def change_state_page(
    request: Request,
    target: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current = get_current_range_state(db)
    mismatches = _routing_mismatches(db, target) if target else []
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": target,
        "valid_states": _available_states(current, current_user),
        "range_state": current,
        "routing_mismatches": mismatches,
        "routing_confirmed": False,
        "page": "range_state",
    })


@router.get("/status")
async def range_state_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return JSONResponse(_state_payload(db))


@router.post("/change", response_class=HTMLResponse)
async def change_state_submit(
    request: Request,
    new_state: str = Form(...),
    reason: str = Form(...),
    acknowledge: str = Form(""),
    supervisor_username: str = Form(""),
    supervisor_password: str = Form(""),
    routing_confirmed: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if new_state not in VALID_STATES:
        return RedirectResponse("/range-state/change", status_code=302)

    current = get_current_range_state(db)
    if new_state == current:
        return RedirectResponse("/", status_code=302)
    if current == RangeState.TESTING.value and current_user.role != Role.SUPERVISOR:
        return _render_change(request, db, current_user, current,
                              "Only an administrator can change the range out of Testing.",
                              target_state=new_state)
    if new_state == RangeState.TESTING.value and current_user.role != Role.SUPERVISOR:
        return _render_change(request, db, current_user, current,
                              "Only an administrator can place the range into Testing.",
                              target_state=new_state)

    reason = reason.strip()
    approver = current_user  # who authorised the change

    # Routing preset check — show before Live auth so supervisor creds aren't needed twice.
    # Advisory only: operator can proceed by confirming they've reviewed the routing.
    if routing_confirmed != "1":
        mismatches = _routing_mismatches(db, new_state)
        if mismatches:
            return templates.TemplateResponse(request, "range_state_confirm.html", {
                "user": current_user,
                "current_state": current,
                "target_state": new_state,
                "valid_states": _available_states(current, current_user),
                "range_state": current,
                "error": None,
                "routing_mismatches": mismatches,
                "routing_confirmed": False,
                "acknowledge_value": acknowledge,
                "reason_value": reason,
                "page": "range_state",
            }, status_code=200)

    # Going Live requires a safety acknowledgment and administrator authorisation.
    if new_state == "Live":
        if acknowledge != "1":
            return _render_change(request, db, current_user, current,
                                  "You must confirm the safety acknowledgment before going Live.",
                                  target_state=new_state)
        if current_user.role != Role.SUPERVISOR:
            sup = db.query(User).filter(
                User.username == supervisor_username.strip().lower(),
                User.is_active == True,
                User.is_archived == False,
                User.role == Role.SUPERVISOR,
            ).first()
            if not sup or not verify_password(supervisor_password, sup.password_hash):
                return _render_change(request, db, current_user, current,
                                      "A valid administrator username and password are required to go Live.",
                                      target_state=new_state)
            approver = sup
            reason = f"{reason} [Authorised by {sup.display_name}; initiated by {current_user.display_name}]"

    entry = RangeStateLog(
        previous_state=current,
        new_state=new_state,
        changed_by_id=current_user.id,
        reason=reason,
    )
    db.add(entry)
    if new_state == RangeState.TESTING.value:
        _ensure_testing_workspace(db, current_user)

    audit = AuditLog(
        user_id=current_user.id,
        action_type="RANGE_STATE_CHANGE",
        entity_type="RangeStateLog",
        previous_value=current,
        new_value=new_state,
        comment=(reason + (f" (approved by {approver.username})" if approver.id != current_user.id else "")),
    )
    db.add(audit)
    db.commit()

    from urllib.parse import quote
    msg = quote(f"Range state changed to {new_state}")
    return RedirectResponse(f"/?toast={msg}", status_code=302)
