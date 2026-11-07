"""Places on askdnd's table (slice 5; docs/plans/2026-11-06-table-build-plan.md, D&D Beyond's Locations): one map or
none, its tokens (app/tokens.py), its own fog, and the DM's scenes pinned on it (app/scene_notes.py).

A map is a picture with its grid set by hand (how many squares across), or a Universal VTT file (.dd2vtt from Dungeon
Alchemist, .uvtt) whose grid and walls come with it. The picture is kept in askdnd's file storage as WebP, made smaller
when it's bigger than a phone can hold (`MAX_PIXELS`), its grid scaled with it. Players see the place the DM shows
(`Campaign.shown_place_id`) and no other; the DM (and admins) can open any. Each place keeps its tokens and fog when
the DM moves to another.
"""

import base64
import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, files, vtt, web
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, Place, Token
from app.view_as import viewing

router = APIRouter()

MAX_UPLOAD = 80 * 1024 * 1024  # a Universal VTT file carries its picture as text, so it's larger than the picture
MAX_PIXELS = 24_000_000  # a map bigger than this is made smaller (an iPhone can't hold much more in a page)
MAX_SIDE = 8192
MIN_SQUARE = 12  # pixels per square, at the least
UVTT = (".dd2vtt", ".uvtt", ".df2vtt")


class MapError(Exception):
    """Why a map couldn't be taken, said plainly."""


# ------------------------------------------------------------------ who may do what
def runs(user: dict | None, campaign: Campaign | None) -> bool:
    """The campaign's DM or an admin: places, maps, creatures, fog, the fight."""
    email = (user or {}).get("email")
    return bool(email and campaign) and access.allows("run_table", access.level(email), access.role(email, campaign.id))


def writes_notes(request: Request, user: dict | None, campaign: Campaign | None) -> bool:
    """The DM's scene notes: the campaign's DM alone, and never while an admin views askdnd as someone (View as)."""
    email = (user or {}).get("email")
    if not email or campaign is None or viewing(request.session):
        return False
    return access.allows("scene_notes", access.level(email), access.role(email, campaign.id))


def here(request: Request, db: Session, need_runs: bool = True) -> tuple[dict, Campaign]:
    """The signed-in person and their campaign with askdnd's VTT on; refuses anyone else (or a player, `need_runs`)."""
    user = current_user(request)
    campaign = web.campaign(db)
    if not user or campaign is None or not vtt.on(campaign, "vtt_table"):
        raise HTTPException(404)
    if need_runs and not runs(user, campaign):
        raise HTTPException(403, "Only the DM can do that.")
    return user, campaign


def _place(db: Session, campaign: Campaign, place_id: int) -> Place:
    p = db.get(Place, place_id)
    if p is None or p.campaign_id != campaign.id:
        raise HTTPException(404)
    return p


def places(db: Session, campaign: Campaign) -> list[Place]:
    return list(db.scalars(select(Place).where(Place.campaign_id == campaign.id).order_by(Place.position, Place.id)))


def chosen(db: Session, campaign: Campaign, dm: bool, place_id: int = 0) -> Place | None:
    """The place this person sees: players the shown one; the DM the one asked for, else the shown one, else the first."""
    if not dm:
        return db.get(Place, campaign.shown_place_id) if campaign.shown_place_id else None
    if place_id:
        p = db.get(Place, place_id)
        if p is not None and p.campaign_id == campaign.id:
            return p
    if campaign.shown_place_id:
        return db.get(Place, campaign.shown_place_id)
    return db.scalar(select(Place).where(Place.campaign_id == campaign.id).order_by(Place.position, Place.id))


def drawn(p: Place | None) -> dict | None:
    """What the page needs to draw a place's map: {"id", "name", "url", "w", "h", "size", "x", "y", "cols", "rows"}."""
    if p is None:
        return None
    g = p.grid or {}
    size = float(g.get("size") or 0)
    out = {"id": p.id, "name": p.name, "url": "", "w": p.map_w, "h": p.map_h, "size": size, "x": float(g.get("x") or 0),
           "y": float(g.get("y") or 0), "cols": 0, "rows": 0, "walls": p.walls or []}
    if p.map_key:
        out["url"] = f"{web.base()}/table/places/{p.id}/map?v={files.version(p.map_key)}"
    if size:
        out["cols"], out["rows"] = int((p.map_w - out["x"]) // size), int((p.map_h - out["y"]) // size)
    return out


# ------------------------------------------------------------------ reading a map
def _webp(img, factor: float = 1.0) -> tuple[bytes, int, int]:
    from PIL import Image

    if factor < 1:
        img = img.resize((max(1, int(img.width * factor)), max(1, int(img.height * factor))), Image.LANCZOS)
    img = img.convert("RGB")
    for quality in (82, 70, 55):
        out = io.BytesIO()
        img.save(out, "WEBP", quality=quality, method=4)
        if out.tell() <= files.TYPES["image/webp"][1]:
            return out.getvalue(), img.width, img.height
    raise MapError("That map is too large even made smaller. Export it at a lower resolution.")


def _factor(w: int, h: int) -> float:
    return min(1.0, (MAX_PIXELS / (w * h)) ** 0.5, MAX_SIDE / max(w, h))


def _points(line, scale: float) -> list[list[float]]:
    """A Universal VTT polyline as wall segments in squares: [[x1, y1, x2, y2], …]."""
    pts = [(float(q.get("x", 0)) * scale, float(q.get("y", 0)) * scale) for q in line or [] if isinstance(q, dict)]
    return [[round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3)] for a, b in zip(pts, pts[1:])]


def read_map(raw: bytes, filename: str) -> dict:
    """A picture or a Universal VTT file as {"data" (WebP), "w", "h", "grid" (or None: set by hand), "walls"}."""
    from PIL import Image, UnidentifiedImageError

    name = (filename or "").lower()
    if not raw:
        raise MapError("That file is empty.")
    if len(raw) > MAX_UPLOAD:
        raise MapError(f"That file is over {MAX_UPLOAD // (1024 * 1024)} MB.")
    Image.MAX_IMAGE_PIXELS = 400_000_000
    if name.endswith(UVTT) or raw[:1] == b"{":
        try:
            j = json.loads(raw)
            res = j["resolution"]
            ppg = float(res["pixels_per_grid"])
            img = Image.open(io.BytesIO(base64.b64decode(j["image"])))
            img.load()
        except (ValueError, KeyError, TypeError, UnidentifiedImageError, OSError):
            raise MapError("That doesn't look like a Universal VTT file (.dd2vtt or .uvtt).") from None
        if ppg < 1:
            raise MapError("That file doesn't say how big its squares are.")
        f = _factor(img.width, img.height)
        data, w, h = _webp(img, f)
        origin = res.get("map_origin") or {}
        walls = []
        for line in (j.get("line_of_sight") or []) + (j.get("objects_line_of_sight") or []):
            walls += _points(line, 1.0)
        doors = [_points(d.get("bounds"), 1.0) for d in j.get("portals") or [] if isinstance(d, dict)]
        size = ppg * f
        return {"data": data, "w": w, "h": h, "walls": walls + [s for d in doors for s in d],
                "grid": {"size": round(size, 4), "x": round(-float(origin.get("x") or 0) * size, 2),
                         "y": round(-float(origin.get("y") or 0) * size, 2)}}
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise MapError("askdnd can't read that picture. A .jpg, .png or .webp, or a Universal VTT file.") from None
    data, w, h = _webp(img, _factor(img.width, img.height))
    return {"data": data, "w": w, "h": h, "grid": None, "walls": []}


# ------------------------------------------------------------------ the DM's changes
def _done(text: str, kind: str = "ok") -> Response:
    """The answer to a table change: the page shows its new copy (every page there hears it: app/realtime.py)."""
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "toast": web.notice(text, kind)})})


@router.post("/table/places")
def add_place(request: Request, name: str = Form(""), db: Session = Depends(get_db)):
    _, campaign = here(request, db)
    name = " ".join(name.split())[:200] or "New place"
    last = db.scalar(select(func.max(Place.position)).where(Place.campaign_id == campaign.id)) or 0
    p = Place(campaign_id=campaign.id, name=name, position=last + 1, fog={"on": False, "shown": []})
    db.add(p)
    db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"{web.base()}/table?place={p.id}"})


@router.post("/table/places/{place_id:int}/map")
def set_map(request: Request, place_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """A map for a place: a picture (its grid set next) or a Universal VTT file (its grid and walls come with it)."""
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    raw = file.file.read(MAX_UPLOAD + 1)
    try:
        got = read_map(raw, file.filename or "")
        key = files.put(db, campaign.id, got["data"], "image/webp")
    except (MapError, files.FileError, files.StorageNotReady) as e:
        return _done(str(e), "warn")
    p.map_key, p.map_w, p.map_h, p.walls = key, got["w"], got["h"], got["walls"]
    if got["grid"]:
        p.grid = got["grid"]
    elif not (p.grid or {}).get("size"):
        p.grid = {"size": round(got["w"] / 30, 3), "x": 0, "y": 0}  # (a guess: 30 squares across, until the DM sets it)
    db.commit()
    said = "The map is in, with its grid and walls." if got["grid"] else "The map is in. Set its grid: how many squares across."
    return _done(said)


@router.post("/table/places/{place_id:int}/grid")
def set_grid(request: Request, place_id: int, across: float = Form(0), x: float = Form(0), y: float = Form(0),
             db: Session = Depends(get_db)):
    """A picture's grid: how many squares across (each 5 feet), and where the first square starts, in pixels."""
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    if not p.map_w or across < 1:
        return _done("Say how many squares across the map is.", "warn")
    size = (p.map_w - x) / across
    if size < MIN_SQUARE:
        return _done("That's more squares than the map has room for.", "warn")
    p.grid = {"size": round(size, 4), "x": round(x, 2), "y": round(y, 2)}
    db.commit()
    return _done(f"The grid is {int(across)} squares across.")


@router.post("/table/places/{place_id:int}/rename")
def rename(request: Request, place_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    p.name = " ".join(name.split())[:200] or p.name
    db.commit()
    return _done(f"Renamed to {p.name}.")


@router.post("/table/places/{place_id:int}/show")
def show(request: Request, place_id: int, db: Session = Depends(get_db)):
    """Players see this place now (and no other)."""
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    campaign.shown_place_id = p.id
    db.commit()
    return _done(f"Players see {p.name}.")


@router.post("/table/places/{place_id:int}/hide")
def hide(request: Request, place_id: int, db: Session = Depends(get_db)):
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    if campaign.shown_place_id == p.id:
        campaign.shown_place_id = None
    db.commit()
    return _done("Players see no place now.")


@router.post("/table/places/{place_id:int}/delete")
def delete(request: Request, place_id: int, db: Session = Depends(get_db)):
    """A place goes with its tokens and scene pins (its notes go too: there's no undo, so the page asks first)."""
    _, campaign = here(request, db)
    p = _place(db, campaign, place_id)
    if campaign.shown_place_id == p.id:
        campaign.shown_place_id = None
    name = p.name
    db.delete(p)
    db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"{web.base()}/table",
                                              "HX-Trigger": json.dumps({"toast": web.notice(f"{name} is gone.")})})


@router.get("/table/places/{place_id:int}/map")
def map_file(request: Request, place_id: int, db: Session = Depends(get_db)):
    """A place's map picture: the DM's for any place, a player's only for the shown one."""
    user, campaign = here(request, db, need_runs=False)
    p = _place(db, campaign, place_id)
    if not runs(user, campaign) and campaign.shown_place_id != p.id:
        raise HTTPException(404)
    return files.serve(p.map_key, "image/webp", release=db)


def token_count(db: Session, place: Place) -> int:
    return db.scalar(select(func.count(Token.id)).where(Token.place_id == place.id)) or 0
