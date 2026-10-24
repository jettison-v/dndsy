"""askdnd v2 web app."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.admin import router as admin_router
from app.admin_notes import router as admin_notes_router
from app.manage_table import router as manage_table_router
from app.manage_accounts import router as manage_accounts_router
from app.tool_corrections_pages import router as tool_corrections_router
from app.admin_sessions import router as admin_sessions_router
from app.admin_usage import router as admin_usage_router
from app.api import router as api_router
from app.atlas import router as atlas_router
from app.auth import current_user
from app.auth import router as auth_router
from app.view_as import ViewAs
from app.view_as import router as view_as_router
from app.character_pages import router as character_router
from app.help_pages import router as help_router
from app.live import router as live_router
from app.table_rolls import router as table_rolls_router
from app.manage import router as manage_router
from app.player_notes import router as notes_router
from app.history_pages import router as history_router
from app.house_rules_pages import router as house_rules_router
from app.campaigns_admin import router as campaigns_router
from app.dice import router as dice_router
from app.entity_pages import router as entity_router
from app.db import SessionLocal
from app.db import engine as db_engine
from app.models import ExtractionRun
from app.story import router as story_router
from app.suggestions import router as suggestions_router
from app.campaign_paths import CampaignPaths
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


@app.exception_handler(StarletteHTTPException)
async def not_found_page(request: Request, exc: StarletteHTTPException):
    """A friendly Not found page for people (old bookmarks: every page has one address since 2026-10-23); the API and
    other errors answer as before."""
    if exc.status_code == 404 and not request.url.path.startswith("/api/") and "application/json" not in request.headers.get("accept", ""):
        from app.web import not_found

        return not_found(request, "There's no page at this address. If it's an old bookmark, open the page from the menu and save it again.")
    return await http_exception_handler(request, exc)
app.add_middleware(CampaignPaths)  # inside the session middleware (added last), so it knows who's asking
app.add_middleware(ViewAs)  # between the two: an admin viewing as someone else (app/view_as.py)
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
app.include_router(view_as_router)
app.include_router(admin_router)
app.include_router(admin_notes_router)
app.include_router(manage_table_router)
app.include_router(manage_accounts_router)
app.include_router(tool_corrections_router)
app.include_router(admin_sessions_router)
app.include_router(suggestions_router)
app.include_router(story_router)
app.include_router(character_router)
app.include_router(live_router)
app.include_router(table_rolls_router)
app.include_router(entity_router)
app.include_router(api_router)
app.include_router(admin_usage_router)
app.include_router(help_router)
app.include_router(atlas_router)
app.include_router(manage_router)
app.include_router(notes_router)
app.include_router(history_router)
app.include_router(house_rules_router)
app.include_router(campaigns_router)
app.include_router(dice_router)

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
