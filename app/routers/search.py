from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, is_testing_state
from app.models import DocPage, RFDevice, Serial, SignalLog, SignalPackage, User

router = APIRouter(prefix="/quick-search")


def _item(label: str, url: str, kind: str, detail: str = "", icon: str = "bi-search") -> dict:
    return {"label": label, "url": url, "kind": kind, "detail": detail, "icon": icon}


STATIC_ITEMS = [
    _item("Dashboard", "/", "Page", "Live range overview", "bi-speedometer2"),
    _item("Signal Logs", "/logs", "Page", "Search and export signal logs", "bi-journal-text"),
    _item("New Log Entry", "/logs/new", "Action", "Create a signal log entry", "bi-plus-lg"),
    _item("Add Note", "/logs/note", "Action", "Create a narrative note", "bi-sticky"),
    _item("Serials", "/serials", "Page", "Active and pending serials", "bi-collection-play"),
    _item("History", "/history", "Page", "Closed serial history", "bi-clock-history"),
    _item("Signal Packages", "/packages", "Page", "Package library", "bi-box-seam"),
    _item("Devices", "/devices", "Page", "Device registry", "bi-hdd-network"),
    _item("Topology", "/devices/topology", "Page", "Device connection map", "bi-diagram-3"),
    _item("Wiki", "/docs", "Page", "Wiki home", "bi-book"),
    _item("RF Frequency Calculator", "/calculator/rf", "Calculator", "Tx/Rx IF/RF conversions", "bi-broadcast"),
    _item("Power Calculator", "/calculator/power", "Calculator", "dBm/dBW/W conversion", "bi-lightning-charge"),
    _item("Basic Calculator", "/calculator/basic", "Calculator", "Quick arithmetic", "bi-calculator"),
    _item("CDA", "/cda", "Page", "CDA windows and assignments", "bi-shield-exclamation"),
    _item("Incidents", "/incidents", "Page", "Fault and incident tracking", "bi-exclamation-octagon"),
    _item("Handover", "/handover", "Page", "Shift handover export", "bi-arrow-left-right"),
]


@router.get("")
async def quick_search(
    q: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    testing = is_testing_state(db)
    term = q.strip()
    needle = f"%{term}%"
    results: list[dict] = []

    for item in STATIC_ITEMS:
        if not term or term.lower() in f"{item['label']} {item['detail']} {item['kind']}".lower():
            results.append(item)

    if term:
        devices = (
            db.query(RFDevice)
            .filter(
                RFDevice.is_testing == testing,
                RFDevice.is_active == True,
                or_(RFDevice.name.ilike(needle), RFDevice.device_model.ilike(needle), RFDevice.location.ilike(needle)),
            )
            .order_by(RFDevice.name)
            .limit(8)
            .all()
        )
        results.extend(
            _item(d.name, f"/devices/{d.id}/routing" if d.is_routing else "/devices", "Device", d.device_model or d.device_type, "bi-hdd-network")
            for d in devices
        )

        serials = (
            db.query(Serial)
            .filter(Serial.is_testing == testing, Serial.title.ilike(needle))
            .order_by(Serial.opened_at.desc())
            .limit(8)
            .all()
        )
        results.extend(
            _item(s.title, f"/history/{s.id}" if s.closed_at else f"/logs?serial_id={s.id}", "Serial", "Closed" if s.closed_at else "Active/Pending", "bi-collection-play")
            for s in serials
        )

        packages = (
            db.query(SignalPackage)
            .filter(SignalPackage.is_testing == testing, SignalPackage.name.ilike(needle))
            .order_by(SignalPackage.name)
            .limit(8)
            .all()
        )
        results.extend(_item(p.name, f"/packages/{p.id}", "Package", p.description or "", "bi-box-seam") for p in packages)

        docs = (
            db.query(DocPage)
            .filter(
                DocPage.is_published == True,
                or_(
                    DocPage.title.ilike(needle),
                    DocPage.content.ilike(needle),
                    DocPage.category.ilike(needle),
                    DocPage.tags.ilike(needle),
                ),
            )
            .order_by(DocPage.title)
            .limit(8)
            .all()
        )
        results.extend(
            _item(d.title, f"/docs/{d.slug}", "Wiki", d.category or "Wiki page", "bi-file-earmark-text")
            for d in docs
        )

        logs = (
            db.query(SignalLog.signal_name)
            .filter(SignalLog.is_testing == testing, SignalLog.signal_name.ilike(needle))
            .group_by(SignalLog.signal_name)
            .order_by(SignalLog.signal_name)
            .limit(8)
            .all()
        )
        results.extend(_item(name, f"/logs?signal_name={name}", "Signal", "Signal log history", "bi-activity") for (name,) in logs)

    if current_user.role == "administrator":
        admin_items = [
            _item("Admin Config", "/config", "Admin", "System and reference settings", "bi-sliders"),
            _item("Audit Log", "/audit", "Admin", "Audit records", "bi-shield-check"),
            _item("Users", "/users", "Admin", "Account management", "bi-people"),
        ]
        for item in admin_items:
            if not term or term.lower() in f"{item['label']} {item['detail']}".lower():
                results.append(item)

    seen = set()
    unique = []
    for result in results:
        key = (result["label"], result["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
        if len(unique) >= 24:
            break
    return JSONResponse({"results": unique})
