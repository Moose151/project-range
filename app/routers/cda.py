from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state
from app.models import User, CDATable, CDAWindow, SerialCDATable, Serial, AuditLog

router = APIRouter(prefix="/cda")
from app.templating import templates


@router.get("", response_class=HTMLResponse)
async def cda_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tables = db.query(CDATable).order_by(CDATable.name).all()
    return templates.TemplateResponse(request, "cda_tables.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "cda_tables": tables,
        "toast": request.query_params.get("toast", ""),
        "page": "cda",
    })


@router.post("/new")
async def cda_create(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/cda?toast=Name+is+required", status_code=302)
    table = CDATable(
        name=name,
        description=description.strip() or None,
        created_by_id=current_user.id,
    )
    db.add(table)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id, action_type="CDA_TABLE_CREATE",
        entity_type="CDATable", entity_id=table.id, new_value=table.name,
    ))
    db.commit()
    return RedirectResponse(f"/cda/{table.id}?toast=CDA+table+created", status_code=302)


@router.get("/{table_id}", response_class=HTMLResponse)
async def cda_detail(
    table_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id).first()
    if not table:
        return RedirectResponse("/cda?toast=Table+not+found", status_code=302)
    assigned_serials = (
        db.query(Serial)
        .join(SerialCDATable, SerialCDATable.serial_id == Serial.id)
        .filter(SerialCDATable.cda_table_id == table_id, Serial.closed_at == None)
        .all()
    )
    return templates.TemplateResponse(request, "cda_table_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "table": table,
        "assigned_serials": assigned_serials,
        "toast": request.query_params.get("toast", ""),
        "page": "cda",
    })


@router.post("/{table_id}/edit")
async def cda_edit(
    table_id: int,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    table = db.query(CDATable).filter(CDATable.id == table_id).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)
    table.name = name.strip()
    table.description = description.strip() or None
    db.add(AuditLog(
        user_id=current_user.id, action_type="CDA_TABLE_EDIT",
        entity_type="CDATable", entity_id=table.id, new_value=table.name,
    ))
    db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=CDA+table+updated", status_code=302)


@router.post("/{table_id}/delete")
async def cda_delete(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    table = db.query(CDATable).filter(CDATable.id == table_id).first()
    if table:
        db.add(AuditLog(
            user_id=current_user.id, action_type="CDA_TABLE_DELETE",
            entity_type="CDATable", entity_id=table_id, new_value=table.name,
        ))
        db.delete(table)
        db.commit()
    return RedirectResponse("/cda?toast=CDA+table+deleted", status_code=302)


@router.post("/{table_id}/windows/add")
async def cda_window_add(
    table_id: int,
    label: str = Form(""),
    start_zulu: str = Form(...),
    end_zulu: str = Form(...),
    max_power_dbm: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    table = db.query(CDATable).filter(CDATable.id == table_id).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)

    # Normalise HH:MM
    start_zulu = start_zulu.strip()
    end_zulu = end_zulu.strip()

    window = CDAWindow(
        cda_table_id=table_id,
        label=label.strip() or None,
        start_zulu=start_zulu,
        end_zulu=end_zulu,
        max_power_dbm=max_power_dbm,
    )
    db.add(window)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id, action_type="CDA_WINDOW_ADD",
        entity_type="CDAWindow", entity_id=window.id,
        new_value=f"{start_zulu}–{end_zulu} on table {table.name}",
    ))
    db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=Window+added", status_code=302)


@router.post("/{table_id}/windows/{window_id}/delete")
async def cda_window_delete(
    table_id: int,
    window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    window = db.query(CDAWindow).filter(
        CDAWindow.id == window_id, CDAWindow.cda_table_id == table_id,
    ).first()
    if window:
        db.add(AuditLog(
            user_id=current_user.id, action_type="CDA_WINDOW_DELETE",
            entity_type="CDAWindow", entity_id=window_id,
            new_value=f"{window.start_zulu}–{window.end_zulu}",
        ))
        db.delete(window)
        db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=Window+removed", status_code=302)
