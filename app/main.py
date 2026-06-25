from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.config import SECRET_KEY, APP_VERSION, SESSION_MAX_AGE_DAYS
from app.templating import templates
from app.routers import auth, dashboard, calculator, logs, range_state, users, config, audit, sessions, packages, serials, history, docs, handover, preferences

app = FastAPI(title="Project Range", version=APP_VERSION, docs_url=None, redoc_url=None)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_MAX_AGE_DAYS * 86400)

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


@app.exception_handler(302)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(exc.headers["Location"], status_code=302)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {
        "code": 403,
        "message": "You do not have permission to access this page.",
    }, status_code=403)
