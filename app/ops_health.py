from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    CDATable,
    Incident,
    Serial,
    SignalLog,
    SignalPackage,
    SignalPackageEntry,
)


OPEN_INCIDENT_STATUSES = {"open", "investigating"}
RECENT_SYNC_ACTIONS = {"CBM_SYNC_ISSUE", "SNMP_POLL_ACTIVE", "SNMP_TEST_FAILED"}


def _badge(label: str, severity: str = "secondary", icon: str = "bi-info-circle", detail: str = "") -> dict:
    return {"label": label, "severity": severity, "icon": icon, "detail": detail}


def package_health_badges(package: SignalPackage) -> list[dict]:
    badges: list[dict] = []
    signals = list(package.signals or [])
    active_links = [link for link in package.serial_links or [] if link.serial and not link.serial.closed_at]
    history_links = [link for link in package.serial_links or [] if link.serial and link.serial.closed_at]

    if not signals:
        badges.append(_badge("No signals", "warning", "bi-exclamation-triangle", "Add signals before assigning this package."))
    else:
        missing_symbol = [s for s in signals if not (s.symbol_rate or "").strip()]
        if missing_symbol:
            badges.append(_badge(f"{len(missing_symbol)} missing symbol rate", "danger", "bi-speedometer", "Required for spectrum occupancy."))

        no_source = [s for s in signals if not (s.source or "").strip() and not s.cbm_device_id]
        if no_source:
            badges.append(_badge(f"{len(no_source)} no modem/source", "warning", "bi-plug", "Signal has no assigned source."))

        partial_cbm = [s for s in signals if (s.cbm_path or s.cbm_carrier) and not s.cbm_device_id]
        if partial_cbm:
            badges.append(_badge(f"{len(partial_cbm)} incomplete CBM map", "danger", "bi-router", "CBM path/carrier set without a mapped device."))

    if active_links:
        badges.append(_badge("Used by active serial", "success", "bi-play-circle", f"{len(active_links)} active assignment(s)."))
    elif history_links:
        badges.append(_badge("History only", "secondary", "bi-clock-history", "Only closed serials reference this package."))
    else:
        badges.append(_badge("Not assigned", "secondary", "bi-link-45deg", "No serial currently references this package."))

    return badges


def serial_readiness_badges(serial: Serial) -> list[dict]:
    badges: list[dict] = []
    package_links = list(serial.package_links or [])
    packages = [link.package for link in package_links if link.package]
    signals = [entry for package in packages for entry in package.signals]

    if packages:
        badges.append(_badge(f"{len(packages)} package{'s' if len(packages) != 1 else ''}", "success", "bi-box-seam"))
    else:
        badges.append(_badge("No packages", "warning", "bi-box-seam", "Serial will start without planned package signals."))

    if serial.cda_links:
        badges.append(_badge(f"{len(serial.cda_links)} CDA", "success", "bi-shield-check"))
    else:
        badges.append(_badge("No CDA", "secondary", "bi-shield-exclamation", "No controlled data area table assigned."))

    if signals:
        missing_symbol = [entry for entry in signals if not (entry.symbol_rate or "").strip()]
        if missing_symbol:
            badges.append(_badge(f"{len(missing_symbol)} missing symbol rate", "danger", "bi-speedometer"))
        else:
            badges.append(_badge("Symbol rates OK", "success", "bi-speedometer"))
            badges.append(_badge("Spectrum ready", "success", "bi-activity"))

        unmapped = [entry for entry in signals if not (entry.source or "").strip() and not entry.cbm_device_id]
        if unmapped:
            badges.append(_badge(f"{len(unmapped)} no modem/source", "warning", "bi-plug"))
        else:
            badges.append(_badge("Sources OK", "success", "bi-plug"))

    return badges


def _window_minutes(start_zulu: str, end_zulu: str, now: datetime) -> tuple[int, int]:
    start_h, start_m = [int(part) for part in start_zulu.split(":")]
    end_h, end_m = [int(part) for part in end_zulu.split(":")]
    today = now.replace(second=0, microsecond=0)
    start = today.replace(hour=start_h, minute=start_m)
    end = today.replace(hour=end_h, minute=end_m)
    if end <= start:
        end += timedelta(days=1)
    if now > end:
        start += timedelta(days=1)
        end += timedelta(days=1)
    elif now < start and start - now > timedelta(hours=12):
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    return int((start - now).total_seconds() // 60), int((end - now).total_seconds() // 60)


def cda_window_alerts(active_serials: Iterable[Serial], soon_minutes: int = 30) -> list[dict]:
    alerts: list[dict] = []
    now = datetime.utcnow()
    seen: set[tuple[int, int, int]] = set()
    for serial in active_serials:
        for link in serial.cda_links or []:
            table = link.cda_table
            for window in table.windows or []:
                key = (serial.id, table.id, window.id)
                if key in seen:
                    continue
                seen.add(key)
                starts_in, ends_in = _window_minutes(window.start_zulu, window.end_zulu, now)
                if starts_in <= 0 < ends_in:
                    alerts.append({
                        "title": f"{table.name} active on {serial.title}",
                        "detail": f"{window.start_zulu}-{window.end_zulu}Z · {window.window_type_label}",
                        "severity": "danger",
                        "icon": "bi-shield-fill-exclamation",
                    })
                elif 0 < starts_in <= soon_minutes:
                    alerts.append({
                        "title": f"{table.name} due in {starts_in} min on {serial.title}",
                        "detail": f"{window.start_zulu}-{window.end_zulu}Z · {window.window_type_label}",
                        "severity": "warning",
                        "icon": "bi-shield-exclamation",
                    })
    return alerts[:8]


def handover_open_issues(db: Session, active_serials: list[Serial], testing: bool, recent_limit: int = 5) -> dict:
    serial_ids = [serial.id for serial in active_serials]
    latest_faults: list[SignalLog] = []
    if serial_ids:
        latest_by_signal: dict[tuple[int | None, str], SignalLog] = {}
        recent_logs = (
            db.query(SignalLog)
            .filter(
                SignalLog.serial_id.in_(serial_ids),
                SignalLog.is_deleted == False,
                SignalLog.is_testing == testing,
            )
            .order_by(SignalLog.timestamp.desc())
            .limit(300)
            .all()
        )
        for log in recent_logs:
            key = (log.serial_id, log.signal_name)
            if key not in latest_by_signal:
                latest_by_signal[key] = log
        latest_faults = [
            log for log in latest_by_signal.values()
            if log.signal_status == "Faulted"
        ][:10]

    open_incidents = (
        db.query(Incident)
        .filter(
            Incident.is_testing == testing,
            Incident.approval_status == "approved",
            Incident.status.in_(OPEN_INCIDENT_STATUSES),
        )
        .order_by(Incident.severity.desc(), Incident.created_at.desc())
        .limit(10)
        .all()
    )

    package_warnings = []
    seen_packages: set[int] = set()
    for serial in active_serials:
        for link in serial.package_links or []:
            package = link.package
            if not package or package.id in seen_packages:
                continue
            seen_packages.add(package.id)
            warnings = [badge for badge in package_health_badges(package) if badge["severity"] in {"warning", "danger"}]
            for warning in warnings:
                package_warnings.append({"package": package, "badge": warning})

    recent_sync = (
        db.query(AuditLog)
        .filter(AuditLog.is_testing == testing, AuditLog.action_type.in_(RECENT_SYNC_ACTIONS), AuditLog.comment.isnot(None))
        .order_by(AuditLog.timestamp.desc())
        .limit(recent_limit)
        .all()
    )

    return {
        "faulted_signals": latest_faults,
        "open_incidents": open_incidents,
        "cda_alerts": cda_window_alerts(active_serials),
        "package_warnings": package_warnings[:10],
        "recent_sync": recent_sync,
    }
