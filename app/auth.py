"""Google sign-in limited to an email allowlist."""

from authlib.integrations.starlette_client import OAuth, OAuthError
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, config
from app.db import get_db

oauth = OAuth()
oauth.register(
    name="google",
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
)

router = APIRouter()


def current_user(request: Request) -> dict | None:
    user = request.session.get("user")
    # Re-check on every request so removing someone (Manage › Accounts or ALLOWED_EMAILS) locks them out.
    if user and access.level(user.get("email")):
        from app.history import set_actor

        set_actor(user.get("email", ""))  # version history records who changed what
        return user
    return None


def _allows(user: dict | None, rule: str, campaign_id: int | None = None) -> bool:
    """Ask the shared rules in app/access.py (the chart on Manage › Table is drawn from them). Campaign roles are
    about one campaign: the first one unless another is given."""
    if not user:
        return False
    email = user.get("email")
    return access.allows(rule, access.level(email), access.role(email, campaign_id))


def is_admin(user: dict | None) -> bool:
    return _allows(user, "admin")


def is_reviewer(user: dict | None, campaign_id: int | None = None) -> bool:
    """Reviewers, the DM and admins (see app/access.py)."""
    return _allows(user, "review", campaign_id)


def is_dm(user: dict | None, campaign_id: int | None = None) -> bool:
    """The DM controls the story: their corrections and additions don't wait for a reviewer."""
    return bool(user) and access.is_dm(user.get("email"), campaign_id)


def can_moderate(user: dict | None, campaign_id: int | None = None) -> bool:
    """Who gets the table's suggestions: admins, reviewers and the DM."""
    return _allows(user, "moderate", campaign_id)


def can_edit_entries(user: dict | None, campaign_id: int | None = None) -> bool:
    """Who edits campaign entries directly (names, descriptions, relationships): reviewers, admins and the DM."""
    return _allows(user, "edit_entries", campaign_id)


def can_set_house_rules(user: dict | None, campaign_id: int | None = None) -> bool:
    """House rules are the DM's rulings: the campaign's DM and admins."""
    return _allows(user, "house_rules", campaign_id)


def can_run_table(user: dict | None, campaign_id: int | None = None) -> bool:
    """Manage › Table's changes: the campaign's DM and admins (a brand-new email stays an admin's)."""
    return _allows(user, "table", campaign_id)


def can_see_table(user: dict | None, campaign_id: int | None = None) -> bool:
    """Manage › Table (who plays which character): the campaign's DM sees it; admins also change it."""
    return _allows(user, "see_table", campaign_id)


def can_edit_settings(user: dict | None, campaign_id: int | None = None) -> bool:
    """Manage › Settings (the campaign's name, DM's name, D&D Beyond id): the campaign's DM and admins."""
    return _allows(user, "settings", campaign_id)


def can_see_character_notes(user: dict | None, character=None) -> bool:
    """Character notes are visible to players but never to the DM of the campaign the character is in now
    (CLAUDE.md; data organization decision 3). Without a character: the first campaign."""
    return _allows(user, "player_notes", character.campaign_id if character is not None else None)


def back_to(path: str | None) -> str:
    """Where to go after signing in: a page on this site only (never another site's address, nor the sign-in itself)."""
    path = path or "/"
    if any(ord(c) < 32 or c == "\x7f" for c in path):  # (a browser drops tabs and newlines: "/\t/evil" would be "//evil")
        return "/"
    return path if path.startswith("/") and not path.startswith(("//", "/\\", "/login", "/auth/")) else "/"


class ReturnAfterSignIn:
    """A page opened signed out opens again after signing in (Brett, 2026-11-05: askdnd.ai/twin landed on the Story page
    instead): wherever a page visit (a GET asking for a page, not HTMX or a fetch) is sent to /login, the address says
    where it came from (`/login?next=`), the sign-in button carries it to Google, and Google's return goes there. Outside
    CampaignPaths, so it sees the address as asked (/c/<campaign>/…)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers") or []) if scope["type"] == "http" else {}
        if scope["type"] != "http" or scope["method"] != "GET" or b"hx-request" in headers or b"text/html" not in headers.get(b"accept", b""):
            return await self.app(scope, receive, send)
        query = scope.get("query_string") or b""
        here = back_to(scope["path"] + (f"?{query.decode('latin-1')}" if query else ""))

        async def sending(message):
            if message["type"] == "http.response.start" and here != "/":
                message = {**message, "headers": [(k, f"/login?next={quote(here, safe='')}".encode() if k.lower() == b"location" and v == b"/login" else v)
                                                  for k, v in message.get("headers", [])]}
            await send(message)

        await self.app(scope, receive, sending)


@router.get("/auth/google")
async def login_with_google(request: Request, next_: str = Query("", alias="next")):
    if next_:
        request.session["next"] = back_to(next_)  # (Google's return, auth_callback, goes there)
    if not config.GOOGLE_CONFIGURED:
        return RedirectResponse("/login?error=not_configured", status_code=303)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/login?error=failed", status_code=303)

    info = token.get("userinfo") or {}
    email = info.get("email")
    if not info.get("email_verified") or not access.level(email):
        request.session.clear()
        return RedirectResponse("/login?error=not_allowed", status_code=303)

    request.session["user"] = {
        "email": email.lower(),
        "name": info.get("name") or email,
        "picture": info.get("picture"),
    }
    await run_in_threadpool(_record_sign_in, db, email.lower(), info.get("name") or "")  # (never the database on the event loop)
    return RedirectResponse(back_to(request.session.pop("next", "/")), status_code=303)


def _record_sign_in(db: Session, email: str, name: str) -> None:
    """Remember the person's Google name and when they last signed in (Manage › Accounts)."""
    from app.models import User

    try:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, name=name or email)
            db.add(u)
        elif name and u.name in ("", u.email):
            u.name = name
        u.last_seen_at = datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()  # never block sign-in over this


@router.get("/dev/login")
def dev_login(request: Request, as_: str = Query("", alias="as"), next_: str = Query("/", alias="next"),
              db: Session = Depends(get_db)):
    """Local-only shortcut for previewing pages without Google (see DEV_LOGIN_EMAIL).
    `?as=<email>` previews as someone else who can sign in (two people at once: one tab on
    localhost, another on 127.0.0.1, since each keeps its own cookie); `?as=dm` or `?as=player` is that campaign's DM,
    or one of its players other than you (the campaign in `next`, else the first), so a link needs no one's email.
    `?next=/a/page` opens that page after (a path on this site only), so a link Claude gives Brett to try a change lands
    on it."""
    local = request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")
    if config.IS_PRODUCTION or not config.DEV_LOGIN_EMAIL or not local:
        return RedirectResponse("/login", status_code=303)
    email = _dev_person(db, as_.strip().lower(), next_) or config.DEV_LOGIN_EMAIL
    if not access.level(email):
        return RedirectResponse("/login", status_code=303)
    request.session["user"] = {"email": email, "name": "Dev preview", "picture": None}
    here = back_to(next_)
    return RedirectResponse(here, status_code=303)


def _dev_person(db: Session, who: str, next_: str) -> str:
    """The email `?as=` names: an email as it is, or "dm" / "player" in the campaign the next page is in."""
    if who not in ("dm", "player"):
        return who
    from app.models import Campaign, CampaignMember, Role, User

    slug = next_.split("/")[2] if next_.startswith("/c/") and next_.count("/") >= 2 else None
    campaign = db.scalar(select(Campaign).where(Campaign.slug == slug)) if slug else db.scalar(select(Campaign).order_by(Campaign.id))
    roles = (Role.DM,) if who == "dm" else (Role.PLAYER, Role.REVIEWER)
    emails = db.scalars(select(User.email).join(CampaignMember, CampaignMember.user_id == User.id)
                        .where(CampaignMember.campaign_id == (campaign.id if campaign else None), CampaignMember.left_on.is_(None),
                               CampaignMember.role.in_(roles), User.email != config.DEV_LOGIN_EMAIL)
                        .order_by(User.id)).all()
    return next((e for e in emails if access.level(e)), "x@invalid")  # (nobody with that role: no sign-in)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
