"""askdnd v2 web app."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app import characters, config, errors, realtime
from app.admin import router as admin_router
from app.admin_notes import router as admin_notes_router
from app.admin_sessions import router as admin_sessions_router
from app.admin_usage import router as admin_usage_router
from app.api import router as api_router
from app.areas import router as areas_router
from app.atlas import router as atlas_router
from app.auth import ReturnAfterSignIn, back_to, current_user
from app.auth import router as auth_router
from app.campaign_paths import CampaignPaths
from app.campaigns_admin import router as campaigns_router
from app.casting import router as casting_router
from app.character_pages import router as character_router
from app.check_numbers import router as check_numbers_router
from app.companions import router as companions_router
from app.creature_hp import router as creature_hp_router
from app.db import SessionLocal
from app.db import engine as db_engine
from app.ddb_bridge import router as ddb_bridge_router
from app.death_saves import router as death_saves_router
from app.dice import router as dice_router
from app.digest import router as digest_router
from app.documents import router as documents_router
from app.entity_pages import router as entity_router
from app.errors import router as errors_router
from app.feedback import router as feedback_router
from app.fog import router as fog_router
from app.giving import router as giving_router
from app.help_pages import router as help_router
from app.history_pages import router as history_router
from app.hit_points import router as hit_points_router
from app.homebrew import router as homebrew_router
from app.house_rules_pages import router as house_rules_router
from app.initiative import router as initiative_router
from app.inventory import router as inventory_router
from app.item_browser import router as item_browser_router
from app.item_creatures import router as item_creatures_router
from app.item_use import router as item_use_router
from app.level_up import router as level_up_router
from app.live import router as live_router
from app.manage import router as manage_router
from app.manage_accounts import router as manage_accounts_router
from app.manage_table import router as manage_table_router
from app.models import ExtractionRun
from app.narration import router as narration_router
from app.picture_window import router as picture_window_router
from app.places import router as places_router
from app.player_notes import router as notes_router
from app.preparing import router as preparing_router
from app.readying import router as readying_router
from app.realtime import router as realtime_router
from app.resources import router as resources_router
from app.rests import router as rests_router
from app.scene_notes import router as scene_notes_router
from app.search import router as search_router
from app.shifting import router as shifting_router
from app.story import router as story_router
from app.suggestions import router as suggestions_router
from app.table_creatures import router as table_creatures_router
from app.table_fight import router as table_fight_router
from app.table_page import router as table_router
from app.table_rolls import router as table_rolls_router
from app.templating import templates
from app.tokens import router as tokens_router
from app.tool_corrections_pages import router as tool_corrections_router
from app.trophies import router as trophies_router
from app.turn_bar import router as turn_bar_router
from app.usage import router as usage_router
from app.view_as import ViewAs
from app.view_as import router as view_as_router
from app.your_notes import router as your_notes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    mark_interrupted_runs()
    try:  # file storage's S3 client, made before the first page of pictures asks for it (app/files.py)
        from app import files

        files.storage()
    except Exception:
        pass
    # The live table connection: this copy hears every copy's changes through Postgres (app/realtime.py)
    listener = asyncio.create_task(realtime.listen()) if db_engine is not None and db_engine.dialect.name == "postgresql" else None
    reparsing = asyncio.create_task(asyncio.to_thread(reparse_old_summaries))  # (beside the first pages, not before them)
    # Sheets no extension watches, read every 30 seconds while the bridge is awake (app/unwatched.py)
    from app import unwatched

    reading = (asyncio.create_task(unwatched.loop()) if config.DDB_BRIDGE and unwatched.TICK and listener is not None else None)
    from app import digest  # the Inbox digest, once a day where email is set up (app/digest.py)

    mailing = asyncio.create_task(digest.loop()) if digest.enabled() and listener is not None else None
    yield
    await reparsing
    for task in (listener, reading, mailing):
        if task:
            task.cancel()


def reparse_old_summaries() -> None:
    """After a deploy with a new D&D Beyond parser, every sheet's summary in the new shape (app/characters.py)."""
    if db_engine is None:
        return
    try:
        with SessionLocal() as db:
            characters.reparse_old(db)
    except Exception:
        pass  # pages re-parse for themselves until it works


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


errors.setup()  # errors on beta reach Sentry (app/errors.py); before the app, so Sentry can wrap it
app = FastAPI(title="askdnd", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def not_found_page(request: Request, exc: StarletteHTTPException):
    """A friendly Not found page for people (old bookmarks: every page has one address since 2026-10-23); the API and
    other errors answer as before."""
    if exc.status_code == 404 and not request.url.path.startswith("/api/") and "application/json" not in request.headers.get("accept", ""):
        from app.web import not_found

        return not_found(request, "There's no page at this address. If it's an old bookmark, open the page from the menu and save it again.")
    return await http_exception_handler(request, exc)
from app.usage import Recorder

app.add_middleware(Recorder)  # innermost: it sees the route that ran, and who's asking
app.add_middleware(CampaignPaths)  # inside the session middleware (added last), so it knows who's asking
app.add_middleware(ViewAs)  # between the two: an admin viewing as someone else (app/view_as.py)
app.add_middleware(ReturnAfterSignIn)  # outside both, so it sees the address as asked (app/auth.py)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    session_cookie="askdnd_session",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=config.IS_PRODUCTION,
)
from app.same_site import SameSite
from app.timing import Stopwatch

app.add_middleware(SameSite)  # a change made with the sign-in cookie comes from askdnd's own pages (app/same_site.py)
app.add_middleware(Stopwatch)  # (added after the rest, so it's around them all: the session and the sign-in check count)


# Every answer says these unless its route said otherwise (the outside review's C1, Nov 10): a file is what its type
# says, no other site frames askdnd's pages, and another site sees only askdnd's address, never which page you were on.
# The Content Security Policy (the engineering practices, Nov 13): a page runs only askdnd's own scripts (no inline
# script, no handler written into the page, no text evaluated as code: tests/test_csp.py), loads from askdnd itself and
# only these others: D&D Beyond's pictures (portraits, token and creature art), Google's (your account's picture) and
# fonts, and aidedd.org's Sword Coast map in Campaign › Map. Styles may be inline (style="", set by app.js).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob: https://*.dndbeyond.com https://*.googleusercontent.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com",  # (html-to-image reads the fonts to draw a page)
    "media-src 'self' blob:",
    "frame-src 'self' https://www.aidedd.org",
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])
SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "strict-origin-when-cross-origin",
                "Content-Security-Policy": CSP}


@app.middleware("http")  # (added last, so it runs first)
async def one_address(request: Request, call_next):
    """askdnd.ai, never www.askdnd.ai (Brett, 2026-11-02: askdnd.ai moves to v2): one address, so one sign-in and one
    place Google returns to."""
    if request.headers.get("host", "").lower().startswith("www."):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"https://{request.headers['host'][4:]}{request.url.path}{query}", status_code=308)
    response = await call_next(request)
    for k, v in SAFE_HEADERS.items():
        response.headers.setdefault(k, v)
    return response
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(auth_router)
app.include_router(view_as_router)
app.include_router(admin_router)
app.include_router(item_use_router)
app.include_router(item_creatures_router)  # items that bring a creature (the Beasty Bone)
app.include_router(check_numbers_router)  # Check your numbers (Show the Math, E)
app.include_router(digest_router)  # the Inbox digest email and Your account › Email
app.include_router(usage_router)  # Admin › Features: which features get used
app.include_router(search_router)  # Search, like Spotlight: what the search box can find
app.include_router(trophies_router)  # Trophy Case: Party's Trophies tab and each person's view
app.include_router(casting_router)  # (through the bridge: on_for)
app.include_router(resources_router)  # (through the bridge: on_for)
app.include_router(rests_router)  # (through the bridge: on_for)
app.include_router(level_up_router)
app.include_router(inventory_router)  # (through the bridge: on_for)
app.include_router(preparing_router)  # (through the bridge: on_for)
app.include_router(giving_router)  # (through the bridge: on_for)
app.include_router(item_browser_router)  # (through the bridge: plays)
app.include_router(creature_hp_router)  # (Your creatures: its Hit Points through the bridge)
app.include_router(companions_router)  # (a familiar in play: here, away, gone)
app.include_router(picture_window_router)  # (the one Picture window, and the campaign's art style)
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
app.include_router(readying_router)  # (Ready kept on Battle, app/readying.py)
app.include_router(atlas_router)
app.include_router(manage_router)
app.include_router(notes_router)
app.include_router(history_router)
app.include_router(house_rules_router)
app.include_router(homebrew_router)  # DM Tools: the campaign's homebrew items
app.include_router(campaigns_router)
app.include_router(dice_router)
app.include_router(documents_router)  # Manage › askdnd › Documents: every page made for askdnd (docs/library.json)
app.include_router(narration_router)  # Listen to the recap (Labs): the narration and the motion comic
app.include_router(realtime_router)
app.include_router(errors_router)
app.include_router(ddb_bridge_router)  # only where DDB_BRIDGE=1, per campaign (app/ddb_bridge.py)
app.include_router(hit_points_router)  # (through the bridge: on_for)
app.include_router(death_saves_router)  # (through the bridge: on_for)
app.include_router(table_router)  # askdnd's VTT (app/vtt.py vtt_table)
app.include_router(turn_bar_router)
app.include_router(places_router)  # askdnd's table: places and maps, tokens, the DM's scenes, the fight, creatures
app.include_router(tokens_router)
app.include_router(scene_notes_router)
app.include_router(table_fight_router)
app.include_router(table_creatures_router)
app.include_router(fog_router)
app.include_router(areas_router)
app.include_router(initiative_router)  # the DM changes the fight's order (Labs: Initiative from askdnd)
app.include_router(shifting_router)  # Wild Shape: shifting and leaving
app.include_router(feedback_router)  # notes for Claude from any page, and the queue
app.include_router(your_notes_router)  # Your notes: what each person sent, about the story and about askdnd

LOGIN_ERRORS = {
    "not_allowed": "That Google account isn't on the list for this table.",
    "failed": "Sign-in didn't complete. Please try again.",
    "not_configured": "Google sign-in isn't set up yet.",
}


@app.get("/health")
def health() -> dict:
    """Up, and which commit it runs (Railway's, on beta): scripts/deploy_check.py waits for the new one, and the Mac
    Mini's after-deploy check runs when it changes."""
    return {"status": "ok", "env": config.APP_ENV, "version": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:12]}


@app.get("/login")
def login(request: Request, error: str | None = None, next_: str = Query("", alias="next")):
    """`next`: the page to open after signing in (app/auth.py ReturnAfterSignIn)."""
    back = back_to(next_)
    if current_user(request):
        return RedirectResponse(back, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": LOGIN_ERRORS.get(error or ""), "back": back})
