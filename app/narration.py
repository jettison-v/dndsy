"""Listen to the recap (a Labs feature, `recap_listen`; Brett, Nov 6): Previously on… read aloud by a narrator, over a
"motion comic" of the pictures of who and what each paragraph names, panning slowly, the paragraph on screen.

The narration is made the first time anyone presses Listen on a published recap (OpenAI's text to speech, a voice told
to sound like a dark fantasy series' "previously on"), kept in file storage like a picture (`Recap.narration_key`) and
counted on Manage › Usage (an ExtractionRun of source "narration", at an estimated cost, under the monthly limit). Only
the published recap's words are sent, and the campaign's name. A recap published again gets its own narration.

The comic is the recap's paragraphs, each shown for its share of the narration's length (a narrator keeps an even
pace, so a paragraph's share of the words is close to its share of the time), with the pictures of World entries whose
names or other names it mentions. Needs OPENAI_API_KEY (scripts/set-secret.sh); OPENAI_TTS_MODEL and OPENAI_TTS_VOICE
name the model and voice (OpenAI's names change often).
"""

import html
import json
import os
import re
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import files, mentions, pictures, spending, vtt, web
from app.auth import current_user, is_admin
from app.db import get_db
from app.extraction import session_label
from app.models import Entity, EntityKind, ExtractionRun, GameSession, Recap, Status
from app.render import markdown_to_html

router = APIRouter()

API = "https://api.openai.com/v1/audio/speech"
MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")
COST_PER_1K = float(os.getenv("OPENAI_TTS_COST_PER_1K_CHARS", "0.015"))  # an estimate, for Usage and the monthly limit
STYLE = ("You are the narrator of a dark fantasy series reading its 'previously on'. Speak low, slow and ominous, with "
         "weight on names and dramatic pauses between sentences; never cheerful, never rushed.")
CHUNK = 3800  # OpenAI reads at most 4096 characters at a time; longer recaps are read in parts, joined
PIECE = "recap_listen"
FETCH = None  # tests replace it: (text) -> mp3 bytes


class NarrationError(Exception):
    """Why the narration can't be made now, said plainly."""


def published(db: Session, session: GameSession) -> Recap | None:
    return next((r for r in reversed(session.recaps) if r.status == Status.PUBLISHED), None)


def paragraphs(body: str) -> list[str]:
    """The recap's paragraphs as plain words: what's read aloud and what's on screen."""
    text = re.sub(r"<[^>]+>", " ", markdown_to_html(body or "", lambda _n: None).replace("</p>", "\n\n").replace("<br>", "\n"))
    return [p for p in (" ".join(html.unescape(x).split()) for x in text.split("\n\n")) if p]


def opening(campaign_name: str) -> str:
    return f"Previously, on {campaign_name}…"


def _speak(text: str) -> bytes:
    if FETCH is not None:
        return FETCH(text)
    key = os.getenv("OPENAI_API_KEY", "")
    body = json.dumps({"model": MODEL, "voice": VOICE, "input": text, "instructions": STYLE, "response_format": "mp3"}).encode()
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read()).get("error", {}).get("message", "")
        except ValueError:
            said = ""
        raise NarrationError(f"OpenAI didn't read it ({e.code}{': ' + said[:200] if said else ''}).") from None
    except (urllib.error.URLError, TimeoutError):
        raise NarrationError("OpenAI couldn't be reached. Try again in a moment.") from None


def _parts(lines: list[str]) -> list[str]:
    """The words to read, in parts OpenAI takes (paragraphs kept whole where they fit)."""
    out, cur = [], ""
    for line in lines:
        if len(line) > CHUNK and cur:  # (what's waiting is read first: the order is the recap's)
            out.append(cur)
            cur = ""
        while len(line) > CHUNK:  # (a paragraph longer than a part: at a sentence's end where there is one)
            cut = line.rfind(". ", 0, CHUNK) + 1 or CHUNK
            out.append(line[:cut].strip())
            line = line[cut:].strip()
        if cur and len(cur) + len(line) + 2 > CHUNK:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{line}" if cur else line
    return out + ([cur] if cur else [])


def narrate(db: Session, session: GameSession, recap: Recap, campaign_name: str, again: bool = False) -> str:
    """The recap's narration, made now if it hasn't been: its key in file storage. The caller lets go of the database
    first (reading takes OpenAI a little while). `again`: an admin's Re-record the voice, a new narration in its place."""
    if recap.narration_key and not again:
        return recap.narration_key
    if not os.getenv("OPENAI_API_KEY") and FETCH is None:
        raise NarrationError("Listen isn't set up yet: askdnd needs an OpenAI key (an admin's step).")
    stop = spending.reached(db)
    if stop:
        raise NarrationError(stop)
    lines = [opening(campaign_name)] + paragraphs(recap.body)
    run = ExtractionRun(source="narration", model=MODEL, status="running", session_id=session.id)
    db.add(run)
    db.commit()  # (counted before the call; the database isn't held while OpenAI reads)
    try:
        audio = b"".join(_speak(part) for part in _parts(lines))  # (MP3 parts play joined)
        if not audio:
            raise NarrationError("OpenAI sent nothing back. Try again.")
        key = files.put(db, session.campaign_id, audio, "audio/mpeg")
    except (NarrationError, files.FileError, files.StorageNotReady) as e:
        run.status, run.error = "error", str(e)[:500]
        db.commit()
        raise NarrationError(str(e)) from None
    recap = db.get(Recap, recap.id)
    recap.narration_key = key
    run.status, run.cost_usd = "done", round(COST_PER_1K * sum(len(x) for x in lines) / 1000, 4)
    db.commit()
    return key


PLACES = (EntityKind.PLACE,)
PEOPLE = (EntityKind.PC, EntityKind.NPC, EntityKind.CREATURE)
MOST_PEOPLE = 2  # portraits in front of the place, for one paragraph


def _names(db: Session, campaign_id: int) -> tuple[dict[int, Entity], object]:
    """The campaign's published people and places, and a finder for their names (app/mentions.py)."""
    entries = {e.id: e for e in db.scalars(select(Entity).where(Entity.campaign_id == campaign_id, Entity.status == Status.PUBLISHED,
                                                              Entity.kind.in_(PLACES + PEOPLE)).options(selectinload(Entity.aliases)))}
    return entries, mentions.finder((n, e.id) for e in entries.values() for n in [e.name] + [a.alias for a in e.display_aliases])


def tale(db: Session, session: GameSession, recap: Recap, campaign_name: str) -> dict:
    """What the motion comic shows (Brett, Nov 6: the place as the backdrop): the session's label and title, then each
    paragraph over a place, the one it names, else the last one named, else the recap's most named place, with the
    portraits of up to two people it names in front (a paragraph naming no one shows just its place), and its share
    of the narration's length."""
    lines = paragraphs(recap.body)
    entries, find = _names(db, session.campaign_id)
    named = [[entries[i] for i in find(line)] for line in lines]
    shown = pictures.urls(db, {e.id for es in named for e in es})
    pic = lambda e: {"src": shown[e.id]["full"], "pos": shown[e.id].get("pos") or "50% 30%", "name": e.name}  # noqa: E731
    counts = {}
    for es in named:
        for e in es:
            if e.kind in PLACES and e.id in shown:
                counts[e.id] = counts.get(e.id, 0) + 1
    home = next((e for es in named for e in es if e.id == max(counts, key=counts.get)), None) if counts else None
    slides, place = [], None
    for line, es in zip(lines, named):
        place = next((e for e in es if e.kind in PLACES and e.id in shown), place)
        people = [pic(e) for e in es if e.kind in PEOPLE and e.id in shown][:MOST_PEOPLE]
        backdrop = place or home
        slides.append({"text": line, "place": pic(backdrop) if backdrop else None, "people": people, "weight": len(line)})
    intro = opening(campaign_name)
    first = slides[0]["place"] if slides else (pic(home) if home else None)
    return {"label": session_label(session), "title": session.title or "", "intro": intro,
            "slides": [{"text": "", "place": first, "people": [], "weight": len(intro), "intro": True}] + slides}


def _here(request: Request, db: Session, session_id: int) -> tuple[dict | None, GameSession | None, Recap | None, Response | None]:
    """Who's asking and the session's published recap, in their campaign, with Listen switched on; else the answer."""
    user = current_user(request)
    if not user:
        return None, None, None, JSONResponse({"error": "Sign in first."}, status_code=401)
    campaign = web.campaign(db)
    s = db.get(GameSession, session_id)
    recap = published(db, s) if s is not None else None
    if campaign is None or s is None or s.campaign_id != campaign.id or recap is None or not vtt.on(campaign, PIECE):
        return user, None, None, JSONResponse({"error": "That recap isn't here."}, status_code=404)
    return user, s, recap, None


@router.get("/sessions/{session_id:int}/tale")
def tale_route(request: Request, session_id: int, db: Session = Depends(get_db)):
    """The motion comic's pictures and words, and the narration's address when it's been made."""
    user, s, recap, stop = _here(request, db, session_id)
    if stop:
        return stop
    out = tale(db, s, recap, web.campaign(db).name)
    out["can_redo"] = is_admin(user)  # (Re-record the voice, in the player)
    out["audio"] = f"{web.base()}/sessions/{s.id}/narration?v={files.version(recap.narration_key)}" if recap.narration_key else ""
    return JSONResponse(out)


@router.post("/sessions/{session_id:int}/narrate")
def narrate_route(request: Request, session_id: int, again: int = 0, db: Session = Depends(get_db)):
    """Make the narration if it hasn't been made (the first Listen), and say where it is; `again=1`, an admin's
    Re-record the voice, makes a new one in its place (Brett, Nov 6)."""
    user, s, recap, stop = _here(request, db, session_id)
    if stop:
        return stop
    if again and not is_admin(user):
        return JSONResponse({"error": "Only an admin can have the voice recorded again."}, status_code=403)
    try:
        key = narrate(db, s, recap, web.campaign(db).name, again=bool(again))
    except NarrationError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    return JSONResponse({"audio": f"{web.base()}/sessions/{s.id}/narration?v={files.version(key)}"})


@router.get("/sessions/{session_id:int}/narration")
def narration_file(request: Request, session_id: int, db: Session = Depends(get_db)):
    """The narration itself, for the people at its table."""
    _, s, recap, stop = _here(request, db, session_id)
    if stop:
        return stop
    data = files.read(recap.narration_key)
    if data is None:
        return JSONResponse({"error": "The narration isn't there. Press Listen again."}, status_code=404)
    return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})
