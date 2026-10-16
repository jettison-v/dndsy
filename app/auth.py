"""Google sign-in limited to an email allowlist."""

from authlib.integrations.starlette_client import OAuth, OAuthError
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
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
        return user
    return None


def is_admin(user: dict | None) -> bool:
    return bool(user) and access.level(user.get("email")) == access.ADMIN


def is_reviewer(user: dict | None) -> bool:
    """Reviewers and admins (see app/access.py)."""
    return bool(user) and access.level(user.get("email")) in (access.REVIEWER, access.ADMIN)


def is_dm(user: dict | None) -> bool:
    """The DM controls the story: their corrections and additions don't wait for a reviewer."""
    return bool(user) and access.is_dm(user.get("email"))


def can_moderate(user: dict | None) -> bool:
    """Who gets the table's suggestions: admins, reviewers and the DM."""
    return is_reviewer(user) or is_dm(user)


def can_see_character_notes(user: dict | None) -> bool:
    """Character notes are context for the whole table, the DM included (Brett, 2026-10-17)."""
    return bool(user)


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
def dev_login(request: Request):
    """Local-only shortcut for previewing pages without Google (see DEV_LOGIN_EMAIL)."""
    local = request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")
    if config.IS_PRODUCTION or not config.DEV_LOGIN_EMAIL or not local:
        return RedirectResponse("/login", status_code=303)
    request.session["user"] = {"email": config.DEV_LOGIN_EMAIL, "name": "Dev preview", "picture": None}
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
