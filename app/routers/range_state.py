from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state
from app.models import (
    User, RangeStateLog, AuditLog, RangeState, Role,
    RFDevice, DevicePort, DeviceLink, CDATable, CDAWindow,
)
from app.auth import verify_password

router = APIRouter(prefix="/range-state")
from app.templating import templates

VALID_STATES = [s.value for s in RangeState]


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


def _render_change(request, db, current_user, current, error):
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": "Live",
        "valid_states": _available_states(current, current_user),
        "range_state": current,
        "error": error,
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
    return templates.TemplateResponse(request, "range_state_confirm.html", {
        "user": current_user,
        "current_state": current,
        "target_state": target,
        "valid_states": _available_states(current, current_user),
        "range_state": current,
        "page": "range_state",
    })


@router.post("/change", response_class=HTMLResponse)
async def change_state_submit(
    request: Request,
    new_state: str = Form(...),
    reason: str = Form(...),
    acknowledge: str = Form(""),
    supervisor_username: str = Form(""),
    supervisor_password: str = Form(""),
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
                              "Only an administrator can change the range out of Testing.")
    if new_state == RangeState.TESTING.value and current_user.role != Role.SUPERVISOR:
        return _render_change(request, db, current_user, current,
                              "Only an administrator can place the range into Testing.")

    reason = reason.strip()
    approver = current_user  # who authorised the change

    # Going Live requires a safety acknowledgment and administrator authorisation.
    if new_state == "Live":
        if acknowledge != "1":
            return _render_change(request, db, current_user, current,
                                  "You must confirm the safety acknowledgment before going Live.")
        if current_user.role != Role.SUPERVISOR:
            sup = db.query(User).filter(
                User.username == supervisor_username.strip().lower(),
                User.is_active == True,
                User.is_archived == False,
                User.role == Role.SUPERVISOR,
            ).first()
            if not sup or not verify_password(supervisor_password, sup.password_hash):
                return _render_change(request, db, current_user, current,
                                      "A valid administrator username and password are required to go Live.")
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
