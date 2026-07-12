import asyncio
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.config import (
    SECRET_KEY, APP_VERSION, SESSION_MAX_AGE_DAYS,
    SESSION_SAME_SITE, SESSION_HTTPS_ONLY, CBM_AUTO_SYNC_SECONDS, SNMP_AUTO_SYNC_SECONDS,
)
from app.database import SessionLocal
from app.models import User, Role
from app.cbm_sync import sync_active_cbms
from app.snmp_sync import poll_active_snmp_devices
from app.templating import templates
from app import chat_state
from app.routers import (
    auth, dashboard, calculator, logs, range_state, users, config, audit, sessions,
    packages, serials, history, docs, handover, preferences, devices, account, incidents, cda,
    cease, chat, search, activities,
)

app = FastAPI(title="SEW Range", version=APP_VERSION, docs_url=None, redoc_url=None)
_cbm_sync_running = False
_cbm_sync_task = None
_snmp_sync_running = False
_snmp_sync_task = None

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Write actions a read-only Observer IS still allowed to perform:
# raising/dismissing a CEASE, setting their own (forced) password, and choosing
# their own duty-role tag (a personal display setting, not operational data).
SAFETY_SUPERVISOR_ALLOWED_WRITES = {
    "/cease/raise", "/cease/dismiss", "/account/password", "/preferences/duty-role",
    "/dashboard/engaged-toggle", "/incidents/new",
}


def _observer_write_allowed(path: str) -> bool:
    if path in SAFETY_SUPERVISOR_ALLOWED_WRITES:
        return True
    # Calculators are non-operational utilities. Their POST routes only return
    # calculation results and may store harmless defaults in the user's session.
    if path.startswith("/calculator/"):
        return True
    # Observers may request documentation edits, but cannot approve, reject,
    # restore, create pages, or perform other write actions.
    if path == "/docs/preview":
        return True
    if path.startswith("/docs/") and path.endswith("/edit"):
        return True
    # Observers may upload a PDF to a wiki page, but it stays pending until an
    # administrator approves it (see docs.docs_upload_attachment).
    return path.startswith("/docs/") and path.endswith("/attachments")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # CSRF defence: for state-changing methods, require a same-origin Origin/Referer.
    # Combined with SameSite=strict session cookies this blocks cross-site form posts
    # without threading a token through every form.
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            host = urlparse(origin).netloc.split("@")[-1]
            if host and host != request.headers.get("host", ""):
                return PlainTextResponse("Cross-origin request blocked.", status_code=403)

        # Read-only enforcement: an Observer account may not make changes,
        # except the explicitly allowed CEASE + own-password actions above.
        user_id = request.session.get("user_id")
        if user_id and not _observer_write_allowed(request.url.path) and not request.url.path.startswith("/chat/"):
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.id == user_id, User.is_archived == False).first()
                if u and u.role == Role.SAFETY_SUPERVISOR:
                    return PlainTextResponse(
                        "This is a read-only Observer account — changes are not permitted.",
                        status_code=403,
                    )
            finally:
                db.close()

    user_id = request.session.get("user_id")
    if user_id:
        display_name = request.session.get("display_name") or "User"
        role = request.session.get("role") or ""
        chat_state.touch_user(user_id, display_name, role)

    response = await call_next(request)
    # Security headers. All assets are first-party; inline scripts/styles are used,
    # so the CSP permits 'unsafe-inline' for script/style only.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    return response


# Compress HTML/JS/CSS/JSON responses (fragments, polls, page loads) to cut
# transfer size over the LAN. Added before SessionMiddleware so Session stays the
# outermost middleware (the Observer read-only check depends on request.session
# being populated — see comment below).
app.add_middleware(GZipMiddleware, minimum_size=500)

# Added last so it is the OUTERMOST middleware (Starlette inserts each at index 0),
# i.e. it runs before security_middleware — guaranteeing request.session is
# populated when the read-only Observer check inspects it.
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=SESSION_MAX_AGE_DAYS * 86400,
    same_site=SESSION_SAME_SITE,
    https_only=SESSION_HTTPS_ONLY,
)


class CachedStaticFiles(StaticFiles):
    """StaticFiles that lets browsers cache assets for a week.

    Safe because JS/CSS are cache-busted with a ?v=NN query string (bump the
    version to force a refetch); other assets (logo, fonts, icons) change rarely,
    so a one-week window is an acceptable trade-off for far fewer revalidations.
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers.setdefault("Cache-Control", "public, max-age=604800")
        return resp


app.mount("/static", CachedStaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(calculator.router)
app.include_router(logs.router)
app.include_router(range_state.router)
app.include_router(users.router)
app.include_router(config.router)
app.include_router(audit.router)
app.include_router(sessions.router)  # Legacy — kept for old data compatibility
app.include_router(packages.router)
app.include_router(serials.router)
app.include_router(history.router)
app.include_router(docs.router)
app.include_router(handover.router)
app.include_router(preferences.router)
app.include_router(devices.router)
app.include_router(account.router)
app.include_router(incidents.router)
app.include_router(cda.router)
app.include_router(cease.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(activities.router)


def _cbm_sync_actor_id(db) -> int | None:
    admin = (
        db.query(User)
        .filter(User.is_active == True, User.is_archived == False, User.role == Role.ADMINISTRATOR)
        .order_by(User.id)
        .first()
    )
    if admin:
        return admin.id
    user = (
        db.query(User)
        .filter(User.is_active == True, User.is_archived == False)
        .order_by(User.id)
        .first()
    )
    return user.id if user else None


def _run_auto_cbm_sync_once() -> None:
    db = SessionLocal()
    try:
        actor_id = _cbm_sync_actor_id(db)
        if actor_id is not None:
            sync_active_cbms(db, actor_id, audit_when_noop=False)
    finally:
        db.close()


async def _auto_cbm_sync_loop() -> None:
    global _cbm_sync_running
    interval = max(1, CBM_AUTO_SYNC_SECONDS)
    while True:
        await asyncio.sleep(interval)
        if _cbm_sync_running:
            continue
        _cbm_sync_running = True
        try:
            await asyncio.to_thread(_run_auto_cbm_sync_once)
        except Exception:
            pass
        finally:
            _cbm_sync_running = False


def _run_auto_snmp_poll_once() -> None:
    db = SessionLocal()
    try:
        actor_id = _cbm_sync_actor_id(db)
        if actor_id is not None:
            poll_active_snmp_devices(db, actor_id, audit_when_noop=False)
    finally:
        db.close()


async def _auto_snmp_poll_loop() -> None:
    global _snmp_sync_running
    interval = max(1, SNMP_AUTO_SYNC_SECONDS)
    while True:
        await asyncio.sleep(interval)
        if _snmp_sync_running:
            continue
        _snmp_sync_running = True
        try:
            await asyncio.to_thread(_run_auto_snmp_poll_once)
        except Exception:
            pass
        finally:
            _snmp_sync_running = False


@app.on_event("startup")
async def start_auto_cbm_sync() -> None:
    global _cbm_sync_task, _snmp_sync_task
    if _cbm_sync_task is None and CBM_AUTO_SYNC_SECONDS > 0:
        _cbm_sync_task = asyncio.create_task(_auto_cbm_sync_loop())
    if _snmp_sync_task is None and SNMP_AUTO_SYNC_SECONDS > 0:
        _snmp_sync_task = asyncio.create_task(_auto_snmp_poll_loop())


@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    location = exc.headers["Location"]
    # HTMX pollers (dashboard fragment every 5s, CEASE, active-count, …) that hit
    # an expired or kicked-out session would otherwise transparently follow the
    # 302 to /login and swap the *full login page* into their small target
    # element — tiling duplicate login forms across the screen and requiring a
    # manual refresh. Tell HTMX to perform a real full-page redirect instead.
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=302)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {
        "code": 403,
        "message": "You do not have permission to access this page.",
    }, status_code=403)
