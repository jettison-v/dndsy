"""askdnd v2 web app."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.admin import router as admin_router
from app.admin_notes import router as admin_notes_router
from app.admin_sessions import router as admin_sessions_router
from app.api import router as api_router
from app.auth import current_user, is_admin
from app.auth import router as auth_router
from app.db import SessionLocal
from app.db import engine as db_engine
from app.models import ExtractionRun
from app.story import router as story_router
from app.templating import templates

@asynccontextmanager
async def lifespan(app: FastAPI):
    mark_interrupted_runs()
    yield


def mark_interrupted_runs() -> None:
    """A deploy restarts the server; drafts that were mid-flight won't finish."""
    if db_engine is None:
        return
    try:
        with SessionLocal() as db:
            db.execute(
                update(ExtractionRun)
                .where(ExtractionRun.status == "running")
                .values(status="error", error="Interrupted (the server restarted). Draft it again.")
            )
            db.commit()
    except Exception:
        pass  # database not ready; the page will still load


app = FastAPI(title="askdnd", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    session_cookie="askdnd_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=config.IS_PRODUCTION,
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_notes_router)
app.include_router(admin_sessions_router)
app.include_router(story_router)
app.include_router(api_router)

LOGIN_ERRORS = {
    "not_allowed": "That Google account isn't on the list for this table.",
    "failed": "Sign-in didn't complete. Please try again.",
    "not_configured": "Google sign-in isn't set up yet.",
}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": config.APP_ENV}


@app.get("/login")
def login(request: Request, error: str | None = None):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": LOGIN_ERRORS.get(error or "")})
