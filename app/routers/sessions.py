from datetime import datetime
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, get_active_session
from app.models import User, LogSession

router = APIRouter(prefix="/sessions")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def session_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = db.query(LogSession).order_by(LogSession.opened_at.desc()).all()
    active = get_active_session(db)
    return templates.TemplateResponse(request, "sessions.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "sessions": sessions,
        "active_session": active,
        "page": "sessions",
        "toast": request.query_params.get("toast", ""),
    })


@router.post("/open")
async def session_open(
    request: Request,
    name: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/sessions?toast=Name+required", status_code=302)
    session = LogSession(
        name=name,
        notes=notes.strip() or None,
        opened_by_id=current_user.id,
    )
    db.add(session)
    db.commit()
    return RedirectResponse(f"/sessions?toast=Session+opened", status_code=302)


@router.post("/{session_id}/close")
async def session_close(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = db.query(LogSession).filter(LogSession.id == session_id).first()
    if session and not session.closed_at:
        session.closed_at = datetime.utcnow()
        session.closed_by_id = current_user.id
        db.commit()
    return RedirectResponse("/sessions?toast=Session+closed", status_code=302)


@router.get("/{session_id}", response_class=HTMLResponse)
async def session_detail(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Redirect to logs list filtered by this session."""
    return RedirectResponse(f"/logs?session_id={session_id}", status_code=302)
