import csv
import io
import openpyxl
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.database import get_db
from app.deps import get_current_user, get_current_range_state, is_testing_state, require_supervisor
from app.models import User, Serial, SignalLog
from app.serial_archive import archive_closed_serial
from app.log_changes import annotate_log_changes
from app.settings import annotate_local_times, get_local_timezone

router = APIRouter(prefix="/history")
from app.templating import templates

PAGE_SIZE = 20  # serials per page on the history list


@router.get("", response_class=HTMLResponse)
async def history_list(
    request: Request,
    search: str = "",
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    q = db.query(Serial).filter(Serial.closed_at != None, Serial.is_testing == testing)
    if search:
        q = q.filter(Serial.title.ilike(f"%{search}%"))
    total = q.count()
    serials = q.order_by(Serial.opened_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(request, "history.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "serials": serials,
        "search": search,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "toast": request.query_params.get("toast", ""),
        "page_name": "history",
    })


@router.get("/{serial_id}", response_class=HTMLResponse)
async def history_detail(
    serial_id: int,
    request: Request,
    search: str = "",
    local_time: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    if not serial:
        return RedirectResponse("/history", status_code=302)

    q = db.query(SignalLog).filter(
        SignalLog.serial_id == serial_id,
        SignalLog.is_deleted == False,
        SignalLog.is_testing == testing,
    )
    if search:
        q = q.filter(or_(
            SignalLog.signal_name.ilike(f"%{search}%"),
            SignalLog.notes.ilike(f"%{search}%"),
        ))
    logs = q.order_by(SignalLog.timestamp.asc()).all()
    annotate_log_changes(db, logs)
    local_timezone = get_local_timezone(db)
    show_local_time = local_time == "1"
    if show_local_time:
        annotate_local_times(logs, local_timezone)

    return templates.TemplateResponse(request, "history_detail.html", {
        "user": current_user,
        "range_state": get_current_range_state(db),
        "serial": serial,
        "logs": logs,
        "search": search,
        "show_local_time": show_local_time,
        "local_timezone": local_timezone,
        "page_name": "history",
    })


@router.get("/{serial_id}/export/csv")
async def history_export_csv(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    if not serial:
        return RedirectResponse("/history", status_code=302)

    logs = (
        db.query(SignalLog)
        .filter(SignalLog.serial_id == serial_id, SignalLog.is_deleted == False, SignalLog.is_testing == testing)
        .order_by(SignalLog.timestamp.asc())
        .all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Timestamp (Zulu)", "Operator", "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No", "Activity Ref", "Notes", "Type",
    ])
    for log in logs:
        writer.writerow([
            log.id, log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ"),
            log.operator.username if log.operator else "",
            log.range_state, log.signal_name, log.signal_status,
            log.tx_if, log.tx_rf, log.rx_rf, log.rx_if, log.freq_unit, log.band,
            log.modulation, log.symbol_rate, log.fec, log.source, log.antenna,
            log.power, log.power_unit, log.eb_no,
            log.activity_ref, log.notes, log.entry_type,
        ])
    output.seek(0)
    fname = serial.display_title.replace(" ", "_").replace("/", "-")[:60] + ".csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{serial_id}/export/xlsx")
async def history_export_xlsx(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(Serial.id == serial_id, Serial.is_testing == testing).first()
    if not serial:
        return RedirectResponse("/history", status_code=302)

    logs = (
        db.query(SignalLog)
        .filter(SignalLog.serial_id == serial_id, SignalLog.is_deleted == False, SignalLog.is_testing == testing)
        .order_by(SignalLog.timestamp.asc())
        .all()
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Serial Log"
    ws.append([
        "ID", "Timestamp (Zulu)", "Operator", "Range State", "Signal", "Status",
        "TxIF", "TxRF", "RxRF", "RxIF", "Unit", "Band",
        "Modulation", "Symbol Rate", "FEC", "Source", "Antenna",
        "Power", "Power Unit", "Eb/No", "Activity Ref", "Notes", "Type",
    ])
    for log in logs:
        ws.append([
            log.id, log.timestamp.strftime("%Y-%m-%d %H:%M:%SZ"), log.operator.username if log.operator else "",
            log.range_state, log.signal_name, log.signal_status,
            log.tx_if, log.tx_rf, log.rx_rf, log.rx_if, log.freq_unit, log.band,
            log.modulation, log.symbol_rate, log.fec, log.source, log.antenna,
            log.power, log.power_unit, log.eb_no,
            log.activity_ref, log.notes, log.entry_type,
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = serial.display_title.replace(" ", "_").replace("/", "-")[:60] + ".xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/{serial_id}/archive")
async def history_archive_serial(
    serial_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):
    testing = is_testing_state(db)
    serial = db.query(Serial).filter(
        Serial.id == serial_id,
        Serial.closed_at != None,
        Serial.is_testing == testing,
    ).first()
    if not serial:
        return RedirectResponse("/history?toast=Serial+not+found", status_code=302)
    result = archive_closed_serial(db, serial, current_user.id)
    if result.archived:
        return RedirectResponse("/history?toast=Serial+archived+to+server+spreadsheet", status_code=302)
    return RedirectResponse("/history?toast=Serial+could+not+be+archived", status_code=302)
