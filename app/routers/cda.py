import csv
import io
from typing import Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user, require_supervisor, get_current_range_state, is_testing_state
from app.models import User, CDATable, CDAWindow, SerialCDATable, Serial, AuditLog
from app.upload_validation import validate_upload_file

router = APIRouter(prefix="/cda")
from app.templating import templates

CDA_UPLOAD_EXTENSIONS = {"csv", "txt"}


def _parse_zulu_time(t: str) -> str:
    """Accept HHMM, HH:MM, or H:MM (Zulu) → normalise to HH:MM. Raises ValueError."""
    t = t.strip().replace(":", "").replace(" ", "")
    if not t.isdigit():
        raise ValueError(f"Not a valid time: {t!r}")
    if len(t) == 3:
        t = "0" + t
    if len(t) == 4:
        h, m = int(t[:2]), int(t[2:])
        if h > 23 or m > 59:
            raise ValueError(f"Time out of range: {t!r}")
        return f"{h:02d}:{m:02d}"
    raise ValueError(f"Invalid time format: {t!r}")


@router.get("", response_class=HTMLResponse)
async def cda_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tables = db.query(CDATable).filter(CDATable.is_testing == is_testing_state(db)).order_by(CDATable.name).all()
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
        is_testing=is_testing_state(db),
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
    testing = is_testing_state(db)
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == testing).first()
    if not table:
        return RedirectResponse("/cda?toast=Table+not+found", status_code=302)
    assigned_serials = (
        db.query(Serial)
        .join(SerialCDATable, SerialCDATable.serial_id == Serial.id)
        .filter(SerialCDATable.cda_table_id == table_id, Serial.closed_at == None, Serial.is_testing == testing)
        .all()
    )
    assigned_ids = [s.id for s in assigned_serials]
    unassigned_active_serials_q = db.query(Serial).filter(
        Serial.closed_at == None,
        Serial.is_started == True,
        Serial.is_testing == testing,
    )
    if assigned_ids:
        unassigned_active_serials_q = unassigned_active_serials_q.filter(~Serial.id.in_(assigned_ids))
    unassigned_active_serials = unassigned_active_serials_q.order_by(Serial.opened_at.asc()).all()
    return templates.TemplateResponse(request, "cda_table_edit.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "table": table,
        "assigned_serials": assigned_serials,
        "unassigned_active_serials": unassigned_active_serials,
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
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
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
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
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
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)

    try:
        start_zulu = _parse_zulu_time(start_zulu)
        end_zulu = _parse_zulu_time(end_zulu)
    except ValueError as e:
        return RedirectResponse(f"/cda/{table_id}?toast=Invalid+time+format:+{e}", status_code=302)

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


@router.get("/{table_id}/export.csv")
async def cda_export_csv(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Label", "Start (Z)", "End (Z)", "Max Power dBm"])
    for w in table.windows:
        writer.writerow([
            w.label or "",
            w.start_zulu,
            w.end_zulu,
            "" if w.max_power_dbm is None else w.max_power_dbm,
        ])
    buf.seek(0)
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in table.name)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_CDA.csv"'},
    )


@router.post("/{table_id}/import")
async def cda_import_csv(
    table_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)

    try:
        raw = await file.read()
        validate_upload_file(file.filename, raw, allowed_extensions=CDA_UPLOAD_EXTENSIONS)
        text = raw.decode("utf-8-sig")  # strip Excel BOM if present
    except Exception as exc:
        return RedirectResponse(f"/cda/{table_id}?toast={quote_plus(str(exc))}", status_code=302)

    reader = csv.reader(io.StringIO(text))
    added = skipped = 0
    for i, row in enumerate(reader):
        if not row or all(c.strip() == "" for c in row):
            continue
        # Skip header row (first row where column 2 isn't a digit string)
        if i == 0 and len(row) >= 2 and not row[1].strip().replace(":", "").isdigit():
            continue
        try:
            label = row[0].strip() if len(row) > 0 else ""
            start = _parse_zulu_time(row[1]) if len(row) > 1 else None
            end = _parse_zulu_time(row[2]) if len(row) > 2 else None
            max_pwr = None
            if len(row) > 3 and row[3].strip():
                max_pwr = float(row[3].strip())
            if start and end:
                db.add(CDAWindow(
                    cda_table_id=table_id,
                    label=label or None,
                    start_zulu=start,
                    end_zulu=end,
                    max_power_dbm=max_pwr,
                ))
                added += 1
            else:
                skipped += 1
        except (ValueError, IndexError):
            skipped += 1

    if added:
        db.add(AuditLog(
            user_id=current_user.id, action_type="CDA_WINDOWS_IMPORT",
            entity_type="CDATable", entity_id=table_id,
            new_value=f"Imported {added} windows from CSV",
        ))
        db.commit()

    msg = f"{added}+window{'s' if added != 1 else ''}+imported"
    if skipped:
        msg += f",+{skipped}+row{'s' if skipped != 1 else ''}+skipped"
    return RedirectResponse(f"/cda/{table_id}?toast={msg}", status_code=302)


@router.post("/{table_id}/serials/assign")
async def cda_assign_serial(
    table_id: int,
    serial_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == testing).first()
    serial = db.query(Serial).filter(
        Serial.id == serial_id,
        Serial.closed_at == None,
        Serial.is_started == True,
        Serial.is_testing == testing,
    ).first()
    if table and serial:
        existing = db.query(SerialCDATable).filter(
            SerialCDATable.serial_id == serial_id,
            SerialCDATable.cda_table_id == table_id,
        ).first()
        if not existing:
            db.add(SerialCDATable(serial_id=serial_id, cda_table_id=table_id))
            db.add(AuditLog(
                user_id=current_user.id,
                action_type="CDA_ASSIGN_SERIAL",
                entity_type="CDATable",
                entity_id=table_id,
                new_value=f"{table.name} assigned to {serial.title}",
            ))
            db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=CDA+table+assigned+to+serial", status_code=302)


@router.post("/{table_id}/serials/{serial_id}/remove")
async def cda_remove_serial(
    table_id: int,
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == testing).first()
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    if not table or not serial:
        return RedirectResponse("/cda", status_code=302)
    link = db.query(SerialCDATable).filter(
        SerialCDATable.serial_id == serial_id,
        SerialCDATable.cda_table_id == table_id,
    ).first()
    if link:
        db.add(AuditLog(
            user_id=current_user.id,
            action_type="CDA_REMOVE_SERIAL",
            entity_type="CDATable",
            entity_id=table_id,
            previous_value=f"{table.name} assigned to {serial.title}",
        ))
        db.delete(link)
        db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=CDA+table+removed+from+serial", status_code=302)


@router.post("/{table_id}/windows/{window_id}/delete")
async def cda_window_delete(
    table_id: int,
    window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)
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


@router.post("/{table_id}/windows/{window_id}/edit")
async def cda_window_edit(
    table_id: int,
    window_id: int,
    label: str = Form(""),
    start_zulu: str = Form(...),
    end_zulu: str = Form(...),
    max_power_dbm: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = db.query(CDATable).filter(CDATable.id == table_id, CDATable.is_testing == is_testing_state(db)).first()
    if not table:
        return RedirectResponse("/cda", status_code=302)
    window = db.query(CDAWindow).filter(
        CDAWindow.id == window_id,
        CDAWindow.cda_table_id == table_id,
    ).first()
    if not window:
        return RedirectResponse(f"/cda/{table_id}?toast=Window+not+found", status_code=302)

    try:
        start_zulu = _parse_zulu_time(start_zulu)
        end_zulu = _parse_zulu_time(end_zulu)
    except ValueError as e:
        return RedirectResponse(f"/cda/{table_id}?toast=Invalid+time+format:+{e}", status_code=302)

    previous = f"{window.start_zulu}-{window.end_zulu}"
    window.label = label.strip() or None
    window.start_zulu = start_zulu
    window.end_zulu = end_zulu
    window.max_power_dbm = max_power_dbm
    db.add(AuditLog(
        user_id=current_user.id,
        action_type="CDA_WINDOW_EDIT",
        entity_type="CDAWindow",
        entity_id=window.id,
        previous_value=previous,
        new_value=f"{start_zulu}-{end_zulu}",
    ))
    db.commit()
    return RedirectResponse(f"/cda/{table_id}?toast=Window+updated", status_code=302)


@router.post("/{table_id}/copy-to-other")
async def cda_copy_to_other(
    table_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy a CDA table and all its windows into the other workspace (Live ↔ Sandbox)."""
    testing = is_testing_state(db)
    orig = db.query(CDATable).filter(
        CDATable.id == table_id, CDATable.is_testing == testing,
    ).first()
    if not orig:
        return RedirectResponse("/cda", status_code=302)
    target = not testing
    copy = CDATable(
        name=orig.name,
        description=orig.description,
        created_by_id=current_user.id,
        is_testing=target,
    )
    copy._preserve_testing_scope = True
    db.add(copy)
    db.flush()
    for window in orig.windows:
        db.add(CDAWindow(
            cda_table_id=copy.id,
            label=window.label,
            start_zulu=window.start_zulu,
            end_zulu=window.end_zulu,
            max_power_dbm=window.max_power_dbm,
        ))
    dest = "Sandbox" if target else "Live"
    db.add(AuditLog(
        user_id=current_user.id, action_type="CDA_COPY_WORKSPACE",
        entity_type="CDATable", entity_id=copy.id,
        new_value=f"Copied '{orig.name}' from {'Sandbox' if testing else 'Live'} to {dest}",
    ))
    db.commit()
    msg = f'CDA table "{orig.name}" copied to {dest}'
    return RedirectResponse(f"/cda?toast={quote_plus(msg)}", status_code=302)
