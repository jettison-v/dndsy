"""Machine API for the local Processor (token-protected, no browser session)."""

import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app import admin_sessions, config
from app.db import get_db
from app.extraction import session_label
from app.models import Campaign, GameSession

router = APIRouter(prefix="/api")

MAX_TRANSCRIPT_CHARS = 1_500_000  # ~4 hours of filtered speech is ~200k characters


class TranscriptUpload(BaseModel):
    played_on: date
    text: str = Field(min_length=1, max_length=MAX_TRANSCRIPT_CHARS)
    campaign: str | None = None  # the campaign's slug (its /c/<slug>/ address); none = the first campaign


def _authorized(authorization: str | None) -> bool:
    if not config.UPLOAD_TOKEN or not authorization or not authorization.startswith("Bearer "):
        return False
    return secrets.compare_digest(authorization.removeprefix("Bearer ").strip(), config.UPLOAD_TOKEN)


@router.post("/transcripts")
def upload_transcript(
    body: TranscriptUpload,
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Start drafting a session from a filtered transcript. The text is passed to
    Claude in memory and never stored (CLAUDE.md privacy rule)."""
    if not config.UPLOAD_TOKEN:
        return JSONResponse({"error": "Uploads aren't set up on the server (UPLOAD_TOKEN)."}, status_code=503)
    if not _authorized(authorization):
        return JSONResponse({"error": "Wrong or missing upload token."}, status_code=401)
    campaign = db.scalar(select(Campaign).where(Campaign.slug == body.campaign)) if body.campaign else web.first_campaign(db)
    if campaign is None:
        return JSONResponse({"error": f"No campaign {body.campaign!r}." if body.campaign else "Import the campaign first."},
                            status_code=404 if body.campaign else 409)
    session = db.scalar(
        select(GameSession).where(GameSession.campaign_id == campaign.id, GameSession.played_on == body.played_on)
    )
    if session is None:
        session = GameSession(campaign_id=campaign.id, played_on=body.played_on, source="transcript")
        db.add(session)
        db.commit()
    if not admin_sessions.draft_transcript_in_background(session.id, body.text):
        return JSONResponse({"error": "Claude is busy drafting another session. Try again in a minute."}, status_code=409)
    review_url = str(request.base_url).rstrip("/") + f"/admin/sessions/{session.id}"
    return JSONResponse(
        {"session_id": session.id, "label": session_label(session), "review_url": review_url, "status": "drafting"},
        status_code=202,
    )
