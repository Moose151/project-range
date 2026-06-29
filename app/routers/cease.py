from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, is_testing_state
from app.models import User, CeaseEvent, AuditLog

router = APIRouter(prefix="/cease")


def _active_cease(db: Session) -> CeaseEvent | None:
    """The current, undismissed CEASE (most recent if several somehow exist)."""
    return (
        db.query(CeaseEvent)
        .filter(
            CeaseEvent.dismissed_at == None,  # noqa: E711
            CeaseEvent.is_testing == is_testing_state(db),
        )
        .order_by(CeaseEvent.id.desc())
        .first()
    )


@router.get("/state")
async def cease_state(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Polled by every client to know whether to show the CEASE splash."""
    ev = _active_cease(db)
    if not ev:
        return JSONResponse({"active": False})
    return JSONResponse({
        "active": True,
        "id": ev.id,
        "reason": ev.reason,
        "raised_by": ev.raised_by.display_name if ev.raised_by else "Unknown",
        "raised_at": ev.raised_at.strftime("%d %b %H:%M") + "Z" if ev.raised_at else "",
    })


@router.post("/raise")
async def cease_raise(
    request: Request,
    reason: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Raise a range-wide CEASE. Any logged-in user may do this. Reason required."""
    reason = reason.strip()
    if not reason:
        return JSONResponse({"ok": False, "error": "A reason is required."}, status_code=400)

    # Don't stack ceases — if one is already active, treat this as a no-op success.
    existing = _active_cease(db)
    if existing:
        return JSONResponse({"ok": True, "id": existing.id, "already_active": True})

    ev = CeaseEvent(reason=reason, raised_by_id=current_user.id, is_testing=is_testing_state(db))
    db.add(ev)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="CEASE_RAISED",
        entity_type="CeaseEvent",
        entity_id=ev.id,
        new_value=reason,
    ))
    db.commit()
    return JSONResponse({"ok": True, "id": ev.id})


@router.post("/dismiss")
async def cease_dismiss(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dismiss the active CEASE. Any logged-in user may do this."""
    ev = _active_cease(db)
    if ev:
        ev.dismissed_by_id = current_user.id
        ev.dismissed_at = datetime.utcnow()
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="CEASE_DISMISSED",
            entity_type="CeaseEvent",
            entity_id=ev.id,
            comment=f"Dismissed by {current_user.display_name}",
        ))
        db.commit()
    return JSONResponse({"ok": True})
