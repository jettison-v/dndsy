"""Spell areas on askdnd's table (slice 10; docs/plans/2026-11-06-table-build-plan.md).

An area is drawn on a place's map for everyone at the table to see (`Place.areas`): a Cone, Cube, Cylinder, Emanation,
Line or Sphere, its size in feet, where it starts and which way it points. Anyone at the table places one (the area
tool, or Cast on the table page starts it already sized from the spell's own words, `from_spell`); its maker or the DM
takes it away. Who's in it is worked out here (`inside`), listed on the area, and offered to Apply to.

The 2024 rules (PHB, Areas of Effect; on a grid, DMG): a Sphere's or Cylinder's point of origin is a corner of a
square, its size a radius; a Cone's width at any point equals its distance from its origin; a Line has its length and
a width (5 feet unless the spell says); an Emanation spreads from a creature's edges and moves with it; a Cube's
origin lies on one of its faces. A square is in an area when the area covers its middle (the DMG's "at least half a
square", without drawing it by hand); a creature is in it when any of its squares is. The DM rules on the edge cases.
"""

import json
import math
import re
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app import picks, places
from app.db import get_db
from app.models import Place, Token

router = APIRouter()
SHAPES = ("cone", "cube", "cylinder", "emanation", "line", "sphere")
MOST = 30  # areas on a place at once
STEP = 5

# "20-foot-radius Sphere", "15-foot Cone", "100-foot-long, 5-foot-wide Line", "10-foot-radius, 40-foot-high Cylinder"
_AREA = re.compile(r"(\d+)-foot(?:-radius|-long)?(?:,? (\d+)-foot-(?:wide|high|tall))? (Cone|Cube|Cylinder|Emanation|Line|Sphere)\b", re.I)


def from_spell(entry: dict | None) -> dict | None:
    """A spell's area from its own words: {"shape", "feet", "wide"} (wide: a Line's width), or None."""
    m = _AREA.search((entry or {}).get("text") or "")
    if not m:
        return None
    shape = m.group(3).lower()
    wide = int(m.group(2)) if shape == "line" and m.group(2) else STEP
    return {"shape": shape, "feet": int(m.group(1)), "wide": wide}


def covers(a: dict, px: float, py: float) -> bool:
    """Whether the area covers the point (px, py), in squares (a square's middle is x + 0.5)."""
    r = (a.get("feet") or 0) / STEP
    ox, oy = a["x"], a["y"]
    dx, dy = px - ox, py - oy
    ang = math.radians(a.get("angle") or 0)
    along = dx * math.cos(ang) + dy * math.sin(ang)  # (along its direction, and across it)
    across = -dx * math.sin(ang) + dy * math.cos(ang)
    shape = a["shape"]
    if shape in ("sphere", "cylinder"):
        return math.hypot(dx, dy) <= r + 1e-9
    if shape == "cone":
        return 0 < along <= r + 1e-9 and abs(across) <= along / 2 + 1e-9
    if shape == "line":
        return 0 <= along <= r + 1e-9 and abs(across) <= (a.get("wide") or STEP) / STEP / 2 + 1e-9
    if shape == "cube":
        return 0 <= along <= r + 1e-9 and abs(across) <= r / 2 + 1e-9
    if shape == "emanation":  # from a creature's edges: its footprint, grown by the size in every direction
        size = a.get("size") or 1
        return ox - r <= px <= ox + size + r and oy - r <= py <= oy + size + r
    return False


def outline(a: dict) -> dict:
    """How to draw it, in squares: {"circle": (cx, cy, r)} or {"points": "x,y x,y …"} or {"rect": (x, y, w, h, rx)},
    and where its label goes ("lx", "ly")."""
    r = (a.get("feet") or 0) / STEP
    ox, oy, ang = a["x"], a["y"], math.radians(a.get("angle") or 0)
    shape = a["shape"]

    def at(along, across):
        return (ox + along * math.cos(ang) - across * math.sin(ang), oy + along * math.sin(ang) + across * math.cos(ang))

    if shape in ("sphere", "cylinder"):  # (its label sits on its top edge, clear of the tokens in it)
        return {"circle": (ox, oy, r), "lx": ox, "ly": oy - r}
    if shape == "emanation":
        size = a.get("size") or 1
        return {"rect": (ox - r, oy - r, size + 2 * r, size + 2 * r, r), "lx": ox + size / 2, "ly": oy - r}
    half = {"cone": r / 2, "line": (a.get("wide") or STEP) / STEP / 2, "cube": r / 2}.get(shape, 0)
    pts = [at(0, 0), at(r, -half), at(r, half)] if shape == "cone" else [at(0, -half), at(r, -half), at(r, half), at(0, half)]
    return {"points": " ".join(f"{x:.3f},{y:.3f}" for x, y in pts), "lx": sum(x for x, _ in pts) / len(pts), "ly": min(y for _, y in pts)}


def named(a: dict) -> str:
    """ "20-ft Sphere", "100-ft Line (5 ft wide)"."""
    words = f"{a.get('feet')}-ft {a['shape'].title()}"
    if a["shape"] == "line" and (a.get("wide") or STEP) != STEP:
        words += f" ({a['wide']} ft wide)"
    return words


def inside(a: dict, tokens: list[dict]) -> list[dict]:
    """The tokens with any square in the area ({"id", "name", "x", "y", "size"}); an Emanation's own creature isn't."""
    out = []
    for t in tokens:
        if a["shape"] == "emanation" and a.get("token") == t["id"]:
            continue
        span = max(1, int(round(t.get("size") or 1)))
        if any(covers(a, t["x"] + i + 0.5, t["y"] + j + 0.5) for i in range(span) for j in range(span)):
            out.append(t)
    return out


def shown(p: Place, tokens: list[dict], me_id: int | None, dm: bool) -> list[dict]:
    """The place's areas for the page, each with who's in it (from the tokens this person sees) and whether they may
    take it away."""
    out = []
    for a in p.areas or []:
        if a.get("token"):  # an Emanation moves with its creature
            t = next((x for x in tokens if x["id"] == a["token"]), None)
            if t is None:
                continue
            a = {**a, "x": t["x"], "y": t["y"], "size": t["size"]}
        out.append({**a, **outline(a), "named": named(a), "in": [t["name"] for t in inside(a, tokens)],
                    "mine": dm or (me_id is not None and a.get("by") == me_id)})
    return out


def _who(db: Session, user: dict | None) -> tuple[int | None, str]:
    me = picks.user_row(db, user)
    return (me.id, me.name or "") if me else (None, "")


@router.post("/table/places/{place_id:int}/areas")
def add(request: Request, place_id: int, shape: str = Form(...), feet: int = Form(...), wide: int = Form(STEP),
        x: float = Form(...), y: float = Form(...), angle: float = Form(0), label: str = Form(""), token: int = Form(0),
        db: Session = Depends(get_db)):
    """An area on the map, seen by everyone at the table: anyone who sees the place may place one."""
    user, campaign = places.here(request, db, need_runs=False)
    dm = places.runs(user, campaign)
    p = places._place(db, campaign, place_id)
    if not dm and campaign.shown_place_id != p.id:
        raise HTTPException(404)
    if shape not in SHAPES or not 0 < feet <= 500 or not 0 < wide <= 100:
        raise HTTPException(400, "That isn't an area askdnd can draw.")
    area = {"id": secrets.token_hex(4), "shape": shape, "feet": int(feet), "wide": int(wide), "x": round(x, 2), "y": round(y, 2),
            "angle": round(angle % 360, 1), "label": label.strip()[:80]}
    if shape == "emanation":
        from app.tokens import visible

        t = db.get(Token, token) if token else None
        if t is None or t.place_id != p.id or not visible(p, t, dm):
            raise HTTPException(400, "An Emanation spreads from a creature: pick its token.")
        area["token"] = t.id
    area["by"], area["by_name"] = _who(db, user)
    p.areas = (list(p.areas or []) + [area])[-MOST:]
    flag_modified(p, "areas")
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True})})


@router.post("/table/places/{place_id:int}/areas/{area_id}/remove")
def remove(request: Request, place_id: int, area_id: str, db: Session = Depends(get_db)):
    """Takes an area away: its maker's, or any for the DM. area_id "all" takes every one (the DM)."""
    user, campaign = places.here(request, db, need_runs=False)
    dm = places.runs(user, campaign)
    p = places._place(db, campaign, place_id)
    me, _ = _who(db, user)
    keep = []
    for a in p.areas or []:
        if (area_id == "all" and dm) or (a.get("id") == area_id and (dm or (me is not None and a.get("by") == me))):
            continue
        keep.append(a)
    if len(keep) == len(p.areas or []):
        raise HTTPException(403 if area_id != "all" else 404, "That area isn't yours to take away.")
    p.areas = keep
    flag_modified(p, "areas")
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True})})


def tokens_for(db: Session, p: Place, dm: bool) -> list[dict]:
    """Every token on the place as areas need them, as this person may see them (no hidden ones, none under fog, for a
    player)."""
    out = []
    from app.tokens import visible

    for t in db.scalars(select(Token).where(Token.place_id == p.id)):
        if not visible(p, t, dm):
            continue
        out.append({"id": t.id, "name": t.name, "x": t.x, "y": t.y, "size": t.size})
    return out

