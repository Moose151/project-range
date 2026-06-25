"""Shared Jinja2 templates instance.

Centralising this (instead of each router building its own) gives one place to
register globals available in every template — currently the app version, which
the bottom-right badge in base.html / login.html reads.
"""
from fastapi.templating import Jinja2Templates

from app.config import APP_VERSION

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION
