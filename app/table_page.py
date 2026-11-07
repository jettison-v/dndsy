"""askdnd's table (docs/plans/2026-11-06-table-build-plan.md; the walkthrough, docs/mockups/table-slices/): one page per
campaign at /c/<campaign>/table. The fight band across the top is the turn bar; Table rolls on the left and the side
panel on the right are every page's own; the middle is the place the DM shows, its map with its tokens (app/places.py,
app/tokens.py), or the fight's rows when there's no map; your turn's bar sits under it (app/turn_bar.py).

The DM (and admins) see every place and what's hidden, with her tools: places and their maps, the party and creatures
on the map, her scene pins (only the campaign's DM: app/scene_notes.py), and the fight (app/table_fight.py). Players
see the place the DM shows and only what they may. Only where askdnd's VTT is on (app/vtt.py `vtt_table`); refused
everywhere else, so no one stumbles on it.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import areas, fight, fog, picks, places, rules_data, scene_notes, table_fight, tokens, turn_bar, vtt, web
from app.auth import current_user
from app.character_pages import party_rows
from app.db import get_db
from app.templating import templates

router = APIRouter()
FOUND = 40  # creatures listed at once in + Creatures


@router.get("/table")
def table_page(request: Request, place: int = 0, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = web.campaign(db)
    if not vtt.on(campaign, "vtt_table"):
        return web.not_found(request, "There's no page at this address.")
    dm = places.runs(user, campaign)
    notes = places.writes_notes(request, user, campaign)
    p = places.chosen(db, campaign, dm, place)
    f = fight.for_person(db, campaign, user.get("email"))
    rows = party_rows(db, user)
    tb = turn_bar.context(db, user, campaign, f)
    if tb is not None:
        tb["ends_here"] = bool(f and f.get("source") == "askdnd")
    toks = tokens.shown(db, p, user, campaign, dm, rows) if p else []
    active = next((x for x in (f or {}).get("order") or [] if x.get("active")), None) if f and not f.get("waiting") else None
    for t in toks:  # whose turn it is, ringed on the map
        t["now"] = bool(active) and (active.get("token") == t["id"] or (t["kind"] == "character" and active.get("character") == t["character"]))
    pins = [s for s in scene_notes.scenes(db, campaign, p) if s.x is not None] if notes and p else []
    g = places.drawn(p)
    me = picks.user_row(db, user)
    layers = {"terrain": fog.runs(set(p.terrain or [])) if p else [], "fog": fog.hidden(p, g["cols"], g["rows"]) if p and g else [],
              "fog_on": fog.on(p), "areas": areas.shown(p, areas.tokens_for(db, p, dm), me.id if me else None, dm) if p else [],
              "rule": table_fight.settings(campaign)["diagonal"], "terrain_keys": sorted(p.terrain or []) if p else []}
    if tb and tb.get("on_turn"):  # (your feet left this turn, for the ruler while you drag)
        layers["turn"] = {"character": tb["c"].id, "left": tb["turn"]["left"]}
    return templates.TemplateResponse(request, "table.html", {
        "campaign": campaign, "rows": rows, "tb": tb, "dm": dm, "notes": notes, "place": p, "g": g, "layers": layers,
        "tokens": toks, "pins": pins,
        "scenes": scene_notes.scenes(db, campaign) if notes else [], "places": places.places(db, campaign) if dm else [],
        "shown_id": campaign.shown_place_id, "ours": table_fight.ours(campaign), "fight_here": table_fight.in_fight(campaign, p),
        "settings": table_fight.settings(campaign), "f": f, "toast": request.session.pop("toast", None)})


@router.get("/table/creatures")
def find_creatures(request: Request, q: str = "", place: int = 0, db: Session = Depends(get_db)):
    """+ Creatures' list: the campaign's books and the SRD, by name (and kind), best matches first."""
    _, campaign = places.here(request, db)
    words = q.lower().split()
    found = []
    for e in rules_data.catalog("monster", db, campaign.id):
        hay = f"{e['name']} {e.get('type', '')}".lower()
        if all(w in hay for w in words):
            found.append(e)
    found.sort(key=lambda e: (not e["name"].lower().startswith(q.lower().strip()), e["name"]))
    pics = rules_data.pictures()
    return templates.TemplateResponse(request, "_creature_find.html", {
        "found": [{**e, "image": (pics.get(e["key"]) or {}).get("image") or e.get("image") or ""} for e in found[:FOUND]],
        "more": max(0, len(found) - FOUND), "q": q, "place": place, "settings": table_fight.settings(campaign)})

