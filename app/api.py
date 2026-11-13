"""Machine API for the local Processor (token-protected, no browser session)."""

import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import admin_sessions, config, files, session_story, web
from app.db import get_db
from app.extraction import session_label
from app.models import Campaign, GameSession

router = APIRouter(prefix="/api")

MAX_TRANSCRIPT_CHARS = 1_500_000  # ~4 hours of filtered speech is ~200k characters


class TranscriptUpload(BaseModel):
    played_on: date
    text: str = Field(min_length=1, max_length=MAX_TRANSCRIPT_CHARS)
    campaign: str | None = None  # the campaign's slug (its /c/<slug>/ address); none = the first campaign
    # Who talked, counted on Brett's Mac: {"speakers": {recording's name: seconds}, "length": seconds} (app/session_story.py)
    talk: dict | None = None


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
    """Keep a session's cleaned transcript and who talked, and start its first read (questions and suggestions; the
    recap is drafted once they're settled). The transcript goes to file storage, never the database (Session Story,
    Brett Nov 7: the raw recording stays on his Mac)."""
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
    if admin_sessions.busy():
        return JSONResponse({"error": "Claude is busy drafting another session. Try again in a minute."}, status_code=409)
    try:
        session_story.keep(db, session, body.text, session_story.clean_talk(body.talk))
        db.commit()
    except (files.FileError, files.StorageNotReady) as e:
        db.rollback()
        return JSONResponse({"error": f"askdnd couldn't keep the transcript: {e}"}, status_code=503)
    if not admin_sessions.read_transcript_in_background(session.id, body.text):
        return JSONResponse({"error": "Claude is busy drafting another session. Try again in a minute."}, status_code=409)
    review_url = str(request.base_url).rstrip("/") + f"/c/{campaign.slug}/manage/sessions/{session.id}"
    return JSONResponse(
        {"session_id": session.id, "label": session_label(session), "review_url": review_url, "status": "reading"},
        status_code=202,
    )


class TalkUpload(BaseModel):
    played_on: date
    campaign: str | None = None
    talk: dict


@router.post("/transcripts/talk")
def upload_talk(body: TalkUpload, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Who talked, for a session already sent (Brett, Nov 13: Terra in the Observatory went from a Processor that was
    opened before it counted speaking times). Only the numbers: the transcript, its read and the drafts stay as they are."""
    if not config.UPLOAD_TOKEN:
        return JSONResponse({"error": "Uploads aren't set up on the server (UPLOAD_TOKEN)."}, status_code=503)
    if not _authorized(authorization):
        return JSONResponse({"error": "Wrong or missing upload token."}, status_code=401)
    campaign = db.scalar(select(Campaign).where(Campaign.slug == body.campaign)) if body.campaign else web.first_campaign(db)
    session = campaign and db.scalar(select(GameSession).where(GameSession.campaign_id == campaign.id, GameSession.played_on == body.played_on))
    if not session:
        return JSONResponse({"error": "No session from that day: send the transcript first."}, status_code=404)
    talk = session_story.clean_talk(body.talk)
    if not talk.get("speakers"):
        return JSONResponse({"error": "No speaking times in what was sent."}, status_code=422)
    session.talk = {**(session.talk or {}), **talk}  # (a start set on the review page stays unless this one has its own)
    db.commit()
    return JSONResponse({"session_id": session.id, "label": session_label(session), "speakers": len(talk["speakers"])})
