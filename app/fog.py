"""Fog and Difficult Terrain on askdnd's table (slices 9 and 8; docs/plans/2026-11-06-table-build-plan.md): each place keeps its own, drawn by the
DM by hand, the way D&D Beyond's Maps does it (its users like that it's simple; they asked that fog stays with its map
when the DM switches maps, which a place's own fog does).

`Place.fog` is {"on": bool, "shown": ["x,y", …]}: with fog on, players see only the squares the DM showed; with it off,
the whole map. The DM shows or hides a rectangle of squares, a whole room (a Universal VTT file's walls and doors
bound it: app/places.py keeps them in squares), or everything. A creature's token under fog never reaches a player's
page (app/tokens.py `shown`); the party's own tokens always do. The map's picture itself reaches every player's
browser whole, as in every VTT: fog is what the page shows, not a secret kept from someone reading the page's files.

The DM paints Difficult Terrain the same way, squares as "x,y" in `Place.terrain`, and moves count it (app/measure.py).
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app import places, web
from app.db import get_db
from app.models import Place

router = APIRouter()
ROOM_MOST = 6000  # squares a room may hold before it's taken as no room at all (a map without walls around it)


def on(p: Place | None) -> bool:
    return bool(p and (p.fog or {}).get("on"))


def shown(p: Place) -> set[str]:
    return set((p.fog or {}).get("shown") or [])


def covered(p: Place | None, x: float, y: float, size: float = 1) -> bool:
    """Whether a token there is all under fog (fog on, and not one of its squares shown)."""
    if not on(p):
        return False
    seen, span = shown(p), max(1, int(round(size)))
    return not any(f"{int(x) + i},{int(y) + j}" in seen for i in range(span) for j in range(span))


def runs(squares: set[str]) -> list[tuple[int, int, int]]:
    """Squares as row runs (x, y, how many across), to draw one shape for many squares."""
    rows: dict[int, list[int]] = {}
    for s in squares:
        x, y = (int(v) for v in s.split(","))
        rows.setdefault(y, []).append(x)
    out = []
    for y, xs in rows.items():
        xs.sort()
        start = prev = xs[0]
        for x in xs[1:] + [None]:
            if x is not None and x == prev + 1:
                prev = x
                continue
            out.append((start, y, prev - start + 1))
            if x is not None:
                start = prev = x
    return sorted(out, key=lambda r: (r[1], r[0]))


def hidden(p: Place, cols: int, rows: int) -> list[tuple[int, int, int]]:
    """The fogged squares as row runs, for drawing (everything not shown)."""
    if not on(p):
        return []
    seen = shown(p)
    return runs({f"{x},{y}" for y in range(rows) for x in range(cols) if f"{x},{y}" not in seen})


# ------------------------------------------------------------------ a room, bounded by walls and doors
def _crosses(a, b, c, d) -> bool:
    """Whether segment ab crosses segment cd (touching counts)."""
    def side(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    s1, s2, s3, s4 = side(a, b, c), side(a, b, d), side(c, d, a), side(c, d, b)
    return s1 != s2 and s3 != s4


def room(walls: list, start: tuple[int, int], cols: int, rows: int) -> set[str] | None:
    """The squares reachable from `start` without crossing a wall or door: a room. None when there are no walls or it
    runs past ROOM_MOST squares (no room to speak of)."""
    if not walls:
        return None
    cells: dict[tuple[int, int], list] = {}
    for w in walls:
        x1, y1, x2, y2 = w
        for cx in range(int(min(x1, x2)) - 1, int(max(x1, x2)) + 1):
            for cy in range(int(min(y1, y2)) - 1, int(max(y1, y2)) + 1):
                cells.setdefault((cx, cy), []).append(((x1, y1), (x2, y2)))
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in seen or not (0 <= nx < cols and 0 <= ny < rows):
                continue
            a, b = (x + 0.5, y + 0.5), (nx + 0.5, ny + 0.5)
            near = cells.get((x, y), []) + cells.get((nx, ny), [])
            if any(_crosses(a, b, c, d) for c, d in near):
                continue
            seen.add((nx, ny))
            todo.append((nx, ny))
            if len(seen) > ROOM_MOST:
                return None
    return {f"{x},{y}" for x, y in seen}


def _squares(text: str, cols: int, rows: int) -> set[str]:
    """ "x1,y1,x2,y2": the rectangle between two squares, inside the map."""
    try:
        x1, y1, x2, y2 = (int(float(v)) for v in text.split(","))
    except ValueError:
        raise HTTPException(400, "Which squares?") from None
    xs = range(max(0, min(x1, x2)), min(cols - 1, max(x1, x2)) + 1)
    ys = range(max(0, min(y1, y2)), min(rows - 1, max(y1, y2)) + 1)
    return {f"{x},{y}" for x in xs for y in ys}


@router.post("/table/places/{place_id:int}/fog")
def change(request: Request, place_id: int, do: str = Form(...), rect: str = Form(""), x: int = Form(0), y: int = Form(0),
           db: Session = Depends(get_db)):
    """The DM's fog: do = on, off, show or hide (a rectangle, `rect`), room or hide_room (from square x, y), all (show
    everything) or none (hide everything)."""
    _, campaign = places.here(request, db)
    p = places._place(db, campaign, place_id)
    g = places.drawn(p) or {}
    cols, rows = g.get("cols") or 0, g.get("rows") or 0
    fog = {"on": on(p), "shown": sorted(shown(p))}
    seen = set(fog["shown"])
    said = ""
    if do in ("on", "off"):
        fog["on"] = do == "on"
        said = "Fog is on: players see only what you show." if do == "on" else "Fog is off: players see the whole map."
    elif do in ("show", "hide"):
        sq = _squares(rect, cols, rows)
        seen = seen | sq if do == "show" else seen - sq
    elif do in ("room", "hide_room"):
        r = room(p.walls or [], (x, y), cols, rows)
        if r is None:
            return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": web.notice(
                "No room there: this map has no walls around it (a Dungeon Alchemist file brings them). Drag a rectangle instead.", "warn")})})
        seen = seen | r if do == "room" else seen - r
    elif do == "all":
        seen = {f"{i},{j}" for i in range(cols) for j in range(rows)}
    elif do == "none":
        seen = set()
    else:
        raise HTTPException(400, "What to do with the fog?")
    fog["shown"] = sorted(seen)
    p.fog = fog
    flag_modified(p, "fog")
    db.commit()
    events = {"tableChanged": True}
    if said:
        events["toast"] = web.notice(said)
    return Response(status_code=204, headers={"HX-Trigger": json.dumps(events)})


@router.post("/table/places/{place_id:int}/terrain")
def terrain(request: Request, place_id: int, do: str = Form(...), rect: str = Form(""), db: Session = Depends(get_db)):
    """The DM's Difficult Terrain (app/measure.py counts it): do = add or clear (a rectangle, `rect`), or none."""
    _, campaign = places.here(request, db)
    p = places._place(db, campaign, place_id)
    g = places.drawn(p) or {}
    have = set(p.terrain or [])
    if do == "none":
        have = set()
    elif do in ("add", "clear"):
        sq = _squares(rect, g.get("cols") or 0, g.get("rows") or 0)
        have = have | sq if do == "add" else have - sq
    else:
        raise HTTPException(400, "What to do with the terrain?")
    p.terrain = sorted(have)
    flag_modified(p, "terrain")
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True})})
