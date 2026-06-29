from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.config import (
    SECRET_KEY, APP_VERSION, SESSION_MAX_AGE_DAYS,
    SESSION_SAME_SITE, SESSION_HTTPS_ONLY,
)
from app.database import SessionLocal
from app.models import User, Role
from app.templating import templates
from app import chat_state
from app.routers import (
    auth, dashboard, calculator, logs, range_state, users, config, audit, sessions,
    packages, serials, history, docs, handover, preferences, devices, account, incidents, cda,
    cease, chat,
)

app = FastAPI(title="SEW Range", version=APP_VERSION, docs_url=None, redoc_url=None)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Write actions a read-only Observer IS still allowed to perform:
# raising/dismissing a CEASE, setting their own (forced) password, and choosing
# their own duty-role tag (a personal display setting, not operational data).
SAFETY_SUPERVISOR_ALLOWED_WRITES = {
    "/cease/raise", "/cease/dismiss", "/account/password", "/preferences/duty-role",
}


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
        if user_id and request.url.path not in SAFETY_SUPERVISOR_ALLOWED_WRITES and not request.url.path.startswith("/chat/"):
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


app.mount("/static", StaticFiles(directory="app/static"), name="static")

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


@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(exc.headers["Location"], status_code=302)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {
        "code": 403,
        "message": "You do not have permission to access this page.",
    }, status_code=403)
