"""Settings read from environment variables (see .env.example)."""

import os
import secrets


def parse_allowlist(raw: str | None) -> frozenset[str]:
    """Comma-separated emails -> normalized set. Blank entries are ignored."""
    if not raw:
        return frozenset()
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


def is_allowed(email: str | None, allowlist: frozenset[str]) -> bool:
    return bool(email) and email.strip().lower() in allowlist


APP_ENV = os.getenv("APP_ENV", "development")
IS_PRODUCTION = APP_ENV == "production"

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAILS = parse_allowlist(os.getenv("ALLOWED_EMAILS"))

SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError("SESSION_SECRET must be set in production")
    # Local dev without .env: sessions just won't survive a restart.
    SESSION_SECRET = secrets.token_urlsafe(32)

GOOGLE_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
