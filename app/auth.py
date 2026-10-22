"""Google sign-in limited to an email allowlist."""

from authlib.integrations.starlette_client import OAuth, OAuthError
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
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
    # Re-check on every request so removing someone (People page or ALLOWED_EMAILS) locks them out.
    if user and access.level(user.get("email")):
        from app.history import set_actor

        set_actor(user.get("email", ""))  # version history records who changed what
        return user
    return None


def _allows(user: dict | None, rule: str, campaign_id: int | None = None) -> bool:
    """Ask the shared rules in app/access.py (the People page's chart is drawn from them). Campaign roles are
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


def can_see_character_notes(user: dict | None, character=None) -> bool:
    """Character notes are visible to players but never to the DM of the campaign the character is in now
    (CLAUDE.md; data organization decision 3). Without a character: the first campaign."""
    return _allows(user, "player_notes", character.campaign_id if character is not None else None)


@router.get("/auth/google")
async def login_with_google(request: Request):
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
    _record_sign_in(db, email.lower(), info.get("name") or "")
    return RedirectResponse("/", status_code=303)


def _record_sign_in(db: Session, email: str, name: str) -> None:
    """Remember the person's Google name and when they last signed in (People page)."""
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
def dev_login(request: Request, as_: str = Query("", alias="as")):
    """Local-only shortcut for previewing pages without Google (see DEV_LOGIN_EMAIL).
    `?as=<email>` previews as someone else who can sign in (two people at once: one tab on
    localhost, another on 127.0.0.1, since each keeps its own cookie)."""
    local = request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")
    if config.IS_PRODUCTION or not config.DEV_LOGIN_EMAIL or not local:
        return RedirectResponse("/login", status_code=303)
    email = as_.strip().lower() or config.DEV_LOGIN_EMAIL
    if not access.level(email):
        return RedirectResponse("/login", status_code=303)
    request.session["user"] = {"email": email, "name": "Dev preview", "picture": None}
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
