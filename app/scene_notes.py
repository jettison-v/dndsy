"""The DM's scene notes (her request, Nov 6; docs/plans/2026-11-06-dm-scene-notes.md and the table build plan): scenes
with her notes in the sections she sent, pinned on a place's map or not (D&D Beyond's Scene Prep, which she uses).

**The DM's alone** (Brett, Nov 6, a standing rule): only the campaign's DM reads or changes them; not players,
reviewers or admins (Brett included), not View as, and they're never sent to Claude. Every route here asks
`places.writes_notes` and answers Not found to anyone else, so no one learns a scene exists. Read-aloud text reaches
the table only when the DM reads it out (Show to the table comes later, 4.1).

Each section starts with its prompts as faint hints, so a blank scene shows what goes where; every section is
optional. `@` names another scene (Scene links) and is drawn as a link to it.
"""

import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import places, web
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, Place, ScenePin
from app.templating import templates

router = APIRouter()

SECTIONS = [
    ("intro", "Intro", "Read-aloud text first (it's shown boxed, to read to the table), then what you need to get started."),
    ("purpose", "Purpose", "How this place drives the story forward. The big decision or goal here."),
    ("outcomes", "Outcomes", "What the players should get from it. What success brings, and failure."),
    ("location", "Location info", "Setting details, the environment, secrets, traps, lore, treasure."),
    ("activities", "Activities and interactions", "What the players can do here, and what might happen to them."),
    ("summaries", "Scene summaries", "The name and a short description of each scene in this area."),
]
KEYS = {k for k, _, _ in SECTIONS}
MAX_TEXT = 20000


def _guard(request: Request, db: Session) -> Campaign:
    """The campaign, for its DM alone; Not found for everyone else (a scene's existence is hers too)."""
    user = current_user(request)
    campaign = web.campaign(db)
    if not places.writes_notes(request, user, campaign):
        raise HTTPException(404)
    return campaign


def _scene(db: Session, campaign: Campaign, scene_id: int) -> ScenePin:
    s = db.get(ScenePin, scene_id)
    if s is None or s.campaign_id != campaign.id:
        raise HTTPException(404)
    return s


def scenes(db: Session, campaign: Campaign, place: Place | None = None) -> list[ScenePin]:
    q = select(ScenePin).where(ScenePin.campaign_id == campaign.id)
    if place is not None:
        q = q.where(ScenePin.place_id == place.id)
    return list(db.scalars(q.order_by(ScenePin.position, ScenePin.id)))


AT = re.compile(r"@([\w’'\- ]{2,60}?)(?=[.,;:!?)\n]|\s{2}|$)")


def linked(text: str, by_name: dict[str, int]) -> list[dict]:
    """The text as runs for the page: plain words, and @Scene names that are scenes as links to them."""
    out, at = [], 0
    for m in AT.finditer(text or ""):
        sid = by_name.get(m.group(1).strip().lower())
        if sid is None:
            continue
        if m.start() > at:
            out.append({"text": text[at:m.start()]})
        out.append({"text": m.group(1).strip(), "scene": sid})
        at = m.end()
    if at < len(text or ""):
        out.append({"text": text[at:]})
    return out


def _intro(text: str) -> tuple[str, str]:
    """Intro's read-aloud part (its first paragraph) and the rest."""
    parts = (text or "").strip().split("\n\n", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def view(db: Session, campaign: Campaign, s: ScenePin, editing: bool = False) -> dict:
    by_name = {x.name.lower(): x.id for x in scenes(db, campaign)}
    notes = s.notes or {}
    sections = []
    for key, label, hint in SECTIONS:
        text = notes.get(key) or ""
        sec = {"key": key, "label": label, "hint": hint, "text": text, "runs": linked(text, by_name)}
        if key == "intro":
            aloud, rest = _intro(text)
            sec["aloud"], sec["rest"] = linked(aloud, by_name), linked(rest, by_name)
        sections.append(sec)
    place = db.get(Place, s.place_id) if s.place_id else None
    return {"s": s, "sections": sections, "place": place, "editing": editing, "base": web.base(),
            "all": scenes(db, campaign), "places": places.places(db, campaign)}


def _changed(text: str = "") -> dict:
    events = {"tableChanged": True}
    if text:
        events["toast"] = text
    return {"HX-Trigger": json.dumps(events)}


@router.get("/table/scenes/{scene_id:int}")
def scene_panel(request: Request, scene_id: int, edit: int = 0, db: Session = Depends(get_db)):
    """A scene in the side panel: her notes, the read-aloud boxed; Edit turns each section into a box to type in."""
    campaign = _guard(request, db)
    s = _scene(db, campaign, scene_id)
    return templates.TemplateResponse(request, "_scene_panel.html", view(db, campaign, s, bool(edit)))


@router.post("/table/scenes")
def add_scene(request: Request, place: int = Form(0), name: str = Form(""), x: float = Form(-1), y: float = Form(-1),
              db: Session = Depends(get_db)):
    """A new scene, pinned where she clicked on the map (or with no pin), opened to write in."""
    campaign = _guard(request, db)
    p = db.get(Place, place) if place else None
    if p is not None and p.campaign_id != campaign.id:
        raise HTTPException(404)
    last = db.scalar(select(func.max(ScenePin.position)).where(ScenePin.campaign_id == campaign.id)) or 0
    s = ScenePin(campaign_id=campaign.id, place_id=p.id if p else None, name=" ".join(name.split())[:200] or "New scene",
                 position=last + 1, x=x if x >= 0 and p else None, y=y if y >= 0 and p else None, notes={})
    db.add(s)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "openScene": f"{web.base()}/table/scenes/{s.id}?edit=1"})})


@router.post("/table/scenes/{scene_id:int}")
def save_scene(request: Request, scene_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Her edits: the name and each section (any left out stay as they were)."""
    campaign = _guard(request, db)
    s = _scene(db, campaign, scene_id)
    notes = dict(s.notes or {})
    for key in KEYS:
        if key in form:
            notes[key] = str(form[key])[:MAX_TEXT].replace("\r\n", "\n")
    if "name" in form:
        s.name = " ".join(str(form["name"]).split())[:200] or s.name
    s.notes = notes
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "toast": "Saved.",
                                                                        "openScene": f"{web.base()}/table/scenes/{s.id}"})})


@router.post("/table/scenes/{scene_id:int}/pin")
def pin(request: Request, scene_id: int, place: int = Form(0), x: float = Form(-1), y: float = Form(-1),
        db: Session = Depends(get_db)):
    """Pin a scene on a place's map (or take its pin off: x below 0)."""
    campaign = _guard(request, db)
    s = _scene(db, campaign, scene_id)
    if place:
        p = db.get(Place, place)
        if p is None or p.campaign_id != campaign.id:
            raise HTTPException(404)
        s.place_id = p.id
    s.x, s.y = (x, y) if x >= 0 and y >= 0 else (None, None)
    db.commit()
    return Response(status_code=204, headers=_changed())


@router.post("/table/scenes/{scene_id:int}/delete")
def delete(request: Request, scene_id: int, db: Session = Depends(get_db)):
    campaign = _guard(request, db)
    s = _scene(db, campaign, scene_id)
    name = s.name
    db.delete(s)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "closePanel": True,
                                                                        "toast": f"{name} is gone."})})
