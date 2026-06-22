from datetime import datetime
from collections import Counter

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_serials
from app.models import User, SignalLog, RangeStateLog
from app.routers.dashboard import _latest_signal_status, _buzzer_active

router = APIRouter(prefix="/handover")
templates = Jinja2Templates(directory="app/templates")


def _handover_ctx(db: Session) -> dict:
    """Assemble a point-in-time snapshot of range state for shift handover."""
    range_state = get_current_range_state(db)
    active_serials = get_active_serials(db)

    serial_data = []
    total_up = 0
    any_buzzer = False
    for serial in active_serials:
        signals = _latest_signal_status(db, serial_id=serial.id)
        buzzer = _buzzer_active(signals, range_state)
        any_buzzer = any_buzzer or buzzer
        status_counts = Counter(s.signal_status for s in signals)
        total_up += status_counts.get("Up", 0)
        serial_data.append({
            "serial": serial,
            "signals": signals,
            "buzzer_active": buzzer,
            "status_counts": dict(status_counts),
        })

    recent_state_changes = (
        db.query(RangeStateLog).order_by(RangeStateLog.id.desc()).limit(8).all()
    )
    recent_notes = (
        db.query(SignalLog)
        .filter(SignalLog.is_deleted == False, SignalLog.entry_type == "Narrative")
        .order_by(SignalLog.timestamp.desc())
        .limit(8)
        .all()
    )

    return {
        "range_state": range_state,
        "serial_data": serial_data,
        "total_up": total_up,
        "any_buzzer": any_buzzer,
        "recent_state_changes": recent_state_changes,
        "recent_notes": recent_notes,
        "generated_at": datetime.utcnow(),
    }


@router.get("", response_class=HTMLResponse)
async def handover_view(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "handover.html", {
        "user": current_user,
        "page": "handover",
        **_handover_ctx(db),
    })


@router.get("/print", response_class=HTMLResponse)
async def handover_print(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(request, "handover_print.html", {
        "user": current_user,
        **_handover_ctx(db),
    })
