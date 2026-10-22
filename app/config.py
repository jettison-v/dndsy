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
# Publishing a session drafts the next one with Claude (real cost). On in production; off locally unless
# AUTO_DRAFT=1, so testing with a copy of beta's data (scripts/pull_beta.sh) doesn't spend money by surprise.
AUTO_DRAFT = os.getenv("AUTO_DRAFT", "1" if IS_PRODUCTION else "0").strip().lower() in ("1", "true", "yes", "on")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAILS = parse_allowlist(os.getenv("ALLOWED_EMAILS"))
# Admins can import data and review/publish recaps. Must also be in ALLOWED_EMAILS.
ADMIN_EMAILS = parse_allowlist(os.getenv("ADMIN_EMAILS"))
# Reviewers (e.g. the DM) can draft, review and publish recaps, but not open
# People, Characters, Usage, Data or the campaign doc.
REVIEWER_EMAILS = parse_allowlist(os.getenv("REVIEWER_EMAILS"))

SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError("SESSION_SECRET must be set in production")
    # Local dev without .env: sessions just won't survive a restart.
    SESSION_SECRET = secrets.token_urlsafe(32)

GOOGLE_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Shared secret the local Processor uses to send filtered transcripts to askdnd.
UPLOAD_TOKEN = os.getenv("UPLOAD_TOKEN", "").strip()

# Local development only: /dev/login signs in as this email without Google.
# Ignored in production and for requests that don't come from this machine.
DEV_LOGIN_EMAIL = "" if IS_PRODUCTION else os.getenv("DEV_LOGIN_EMAIL", "").strip().lower()


def sqlalchemy_url(raw: str | None) -> str:
    """Railway gives postgresql://...; SQLAlchemy needs the psycopg (v3) driver named."""
    if not raw:
        return ""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix) :]
    return raw


DATABASE_URL = sqlalchemy_url(os.getenv("DATABASE_URL")) or (
    "" if IS_PRODUCTION else "postgresql+psycopg://localhost/askdnd_dev"
)
