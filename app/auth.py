"""Google sign-in limited to an email allowlist."""

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app import config

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
    # Re-check on every request so removing someone from ALLOWED_EMAILS locks them out.
    if user and config.is_allowed(user.get("email"), config.ALLOWED_EMAILS):
        return user
    return None


def is_admin(user: dict | None) -> bool:
    return bool(user) and config.is_allowed(user.get("email"), config.ADMIN_EMAILS)


def is_reviewer(user: dict | None) -> bool:
    """Admins plus anyone in REVIEWER_EMAILS (the DM)."""
    return is_admin(user) or (bool(user) and config.is_allowed(user.get("email"), config.REVIEWER_EMAILS))


@router.get("/auth/google")
async def login_with_google(request: Request):
    if not config.GOOGLE_CONFIGURED:
        return RedirectResponse("/login?error=not_configured", status_code=303)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/login?error=failed", status_code=303)

    info = token.get("userinfo") or {}
    email = info.get("email")
    if not info.get("email_verified") or not config.is_allowed(email, config.ALLOWED_EMAILS):
        request.session.clear()
        return RedirectResponse("/login?error=not_allowed", status_code=303)

    request.session["user"] = {
        "email": email.lower(),
        "name": info.get("name") or email,
        "picture": info.get("picture"),
    }
    return RedirectResponse("/", status_code=303)


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
