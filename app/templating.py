"""Shared Jinja2 templates instance.

Centralising this (instead of each router building its own) gives one place to
register globals available in every template — currently the app version, which
the bottom-right badge in base.html / login.html reads.
"""
import json

from fastapi.templating import Jinja2Templates

from app.config import APP_VERSION

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION


def _sandbox_hardware_sync_paused() -> bool:
    from app.database import SessionLocal
    from app.settings import get_sandbox_hardware_sync_paused

    db = SessionLocal()
    try:
        return get_sandbox_hardware_sync_paused(db)
    finally:
        db.close()


templates.env.globals["sandbox_hardware_sync_paused"] = _sandbox_hardware_sync_paused


def _from_json(value: str | None) -> dict | list | None:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


templates.env.filters["from_json"] = _from_json
