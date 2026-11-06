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
# Staging (docs/SETUP_LOG.md › A staging copy): Railway names the environment; STAGING=1 shows its look locally. Every
# page says so (the Staging label and an amber menu bar), so no one mistakes it for the table's askdnd.
STAGING = os.getenv("RAILWAY_ENVIRONMENT_NAME") == "staging" or os.getenv("STAGING", "").strip() == "1"
# Publishing a session drafts the next one with Claude (real cost). On in production; off locally unless
# AUTO_DRAFT=1, so testing with a copy of beta's data (scripts/pull_beta.sh) doesn't spend money by surprise.
AUTO_DRAFT = os.getenv("AUTO_DRAFT", "1" if IS_PRODUCTION else "0").strip().lower() in ("1", "true", "yes", "on")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAILS = parse_allowlist(os.getenv("ALLOWED_EMAILS"))
# Admins can import data and review/publish recaps. Must also be in ALLOWED_EMAILS.
ADMIN_EMAILS = parse_allowlist(os.getenv("ADMIN_EMAILS"))
# At least reviewers in every campaign (draft, review and publish recaps), without
# People, Characters, Usage, Data or the campaign doc. Roles are normally set on Manage › People.
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
# The D&D Beyond bridge (app/ddb_bridge.py, extension/askdnd-bridge) may run where DDB_BRIDGE=1 (beta since 2026-10-28,
# roadmap step 4); each campaign still has it only once switched on (the VTT piece "ddb_bridge", app/vtt.py)
DDB_BRIDGE = os.getenv("DDB_BRIDGE", "").strip() == "1"
# Claude's key to the feedback queue (app/feedback.py `/api/feedback`, scripts/feedback.py): set with scripts/set-secret.sh;
# unset, the API answers nothing
FEEDBACK_KEY = os.getenv("FEEDBACK_KEY", "").strip()
# Where the table adds the extension: its Chrome Web Store listing (unlisted: only people with this link find it)
BRIDGE_EXTENSION_URL = "https://chromewebstore.google.com/detail/askdnd-bridge/obpgemimnhngpcckodjkcihiahoaefpl"
# VTT test's invite link on D&D Beyond, for "A test copy of your character" (app/twins.py, temporary): anyone with it can
# join the test campaign, so it's kept out of git (scripts/set-secret.sh VTT_TEST_INVITE_URL)
VTT_TEST_INVITE_URL = os.getenv("VTT_TEST_INVITE_URL", "").strip()


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

# File storage (app/files.py): "s3" keeps files in S3 under v2/files/ (the default on beta; it needs the bucket and
# an AWS key that may use v2/files/), anything else is a folder, relative to the repo (private/files locally).
FILE_STORAGE = os.getenv("FILE_STORAGE", "").strip() or ("s3" if IS_PRODUCTION else "private/files")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "").strip()
