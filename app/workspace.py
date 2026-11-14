"""The DM's Workspace (Brett chose B, Nov 13, docs/mockups/dm-workspace/): Manage as one place for the DM, its list down
the left grouped by the DM's week (app/manage.py PAGES), and its home a workbench: what needs you, who's at the table,
then a tile per kind of thing the DM makes (the planned kinds as dashed tiles until they're built).

Two pages join The next game here: **Scene notes** (every place's pins, the DM's alone: the `scene_notes` rule, never
an admin as such, never View as; app/scene_notes.py) and **Places and maps** (askdnd's table's places, each opening the
table there). Both need askdnd's table (`vtt_table`); the list leaves them out where it's off.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import homebrew, places, vtt, web
from app.auth import current_user
from app.db import get_db
from app.models import Place, ScenePin
from app.templating import templates

router = APIRouter()


def _places(db: Session, campaign_id: int) -> list[Place]:
    return list(db.scalars(select(Place).where(Place.campaign_id == campaign_id).order_by(Place.position, Place.id)))


def _pins(db: Session, campaign_id: int) -> dict[int | None, list[ScenePin]]:
    out: dict[int | None, list[ScenePin]] = {}
    for p in db.scalars(select(ScenePin).where(ScenePin.campaign_id == campaign_id).order_by(ScenePin.position, ScenePin.id)):
        out.setdefault(p.place_id, []).append(p)
    return out


def workbench(db: Session, request: Request, user: dict, campaign) -> dict:
    """What the home shows below what needs you: the kinds of thing this person may make, each with how many there are."""
    base = web.base(campaign)
    table_on = vtt.on(campaign, "vtt_table")
    tiles = []
    if places.runs(user, campaign) or homebrew.can_make(user, campaign):
        made = [r for r in homebrew.rows_for(db, campaign.id) if not (r.data or {}).get("retired")]
        tiles.append({"key": "items", "name": "Items", "count": len(made),
                      "says": ", ".join(r.name for r in made[:3]) + ("…" if len(made) > 3 else "") if made else "None yet",
                      "open": f"{base}/dm", "new": f"{base}/dm/items/new"})
    if table_on and places.writes_notes(request, user, campaign):
        pins = _pins(db, campaign.id)
        n = sum(len(v) for v in pins.values())
        tiles.append({"key": "scene-notes", "name": "Scene notes", "count": n,
                      "says": f"{n} on {len([k for k in pins if k])} place{'s' if len([k for k in pins if k]) != 1 else ''} · only you see them" if n else "Only you see them",
                      "open": f"{base}/manage/scene-notes"})
    if table_on and places.runs(user, campaign):
        ps = _places(db, campaign.id)
        mapped = sum(1 for p in ps if p.map_key)
        tiles.append({"key": "places", "name": "Places and maps", "count": len(ps),
                      "says": f"{len(ps)} place{'s' if len(ps) != 1 else ''} · {mapped} with a map" if ps else "None yet",
                      "open": f"{base}/manage/places"})
    if homebrew.can_make(user, campaign):
        tiles += [{"key": key, "name": name, "says": what, "planned": True} for key, name, what in homebrew.PLANNED]
    from app import live

    says = {"step": "connected", "via": "through your browser", "closed": "sheet closed"}
    who = []
    for r in live.rows_from(db):
        tone = "step" if r["step"] else "via" if r["via"] else "closed" if r["connects"] else ""
        who.append({"name": r["name"], "portrait": r["portrait"], "tone": tone, "says": says.get(tone, "")})
    return {"tiles": tiles, "who": who}


@router.get("/manage/scene-notes")  # under the campaign: /c/<campaign>/manage/scene-notes
def scene_notes(request: Request, db: Session = Depends(get_db)):
    """Every place's scene notes in one list, each opening its notes or the table at its place. The DM's alone."""
    user = current_user(request)
    campaign = web.campaign(db)
    if not user:
        return web.require(request)[1]
    if not places.writes_notes(request, user, campaign):
        return web.not_found(request)  # (no one else learns a scene exists: app/scene_notes.py)
    rows = []
    pins = _pins(db, campaign.id)
    for p in _places(db, campaign.id):
        rows.append({"place": p, "pins": pins.get(p.id, [])})
    loose = pins.get(None, [])
    return templates.TemplateResponse(request, "manage_scene_notes.html", {
        "rows": rows, "loose": loose, "table_on": vtt.on(campaign, "vtt_table"), "campaign": campaign,
        "count": sum(len(v) for v in pins.values())})


@router.get("/manage/places")  # under the campaign: /c/<campaign>/manage/places
def places_page(request: Request, db: Session = Depends(get_db)):
    """askdnd's table's places, each with its map and pins, opening the table there; Campaign › Map is the story's."""
    user = current_user(request)
    campaign = web.campaign(db)
    if not user:
        return web.require(request)[1]
    if not places.runs(user, campaign):
        return web.forbidden(request, "Places and maps are the DM's (and admins').")
    pins = dict(db.execute(select(ScenePin.place_id, func.count()).where(ScenePin.campaign_id == campaign.id)
                           .group_by(ScenePin.place_id)).all())
    return templates.TemplateResponse(request, "manage_places.html", {
        "places": _places(db, campaign.id), "pins": pins if places.writes_notes(request, user, campaign) else {},
        "table_on": vtt.on(campaign, "vtt_table"), "campaign": campaign})
