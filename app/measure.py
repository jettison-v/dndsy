"""Moving and measuring on askdnd's table (slice 8; docs/plans/2026-11-06-table-build-plan.md).

One place for the numbers a move has, so the page (app.js "askdnd's table map", while dragging) and the server (a move
counted toward your turn) agree: the squares a straight move enters, what they cost in feet by the campaign's diagonal
rule and the DM's Difficult Terrain, and whose reach the mover leaves.

The 2024 rules: each square is 5 feet, a diagonal too (PHB, Movement; the DMG's optional rule, 5 then 10 alternating,
is the battle setting "alternate"); Difficult Terrain costs 1 extra foot for every foot (a square's 5 becomes 10); an
Opportunity Attack is possible when a creature you can see leaves your reach (PHB, Opportunity Attacks). askdnd counts
and says; it never stops a move or decides an attack (the DM rules: inform, don't advise).
"""

import re

STEP = 5  # feet, one square
DEFAULT_REACH = 5


def key(x: float, y: float) -> str:
    return f"{int(x)},{int(y)}"


def path(a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float, bool]]:
    """The squares a straight move from a to b enters, in order, each (x, y, diagonal): as many steps as the longer
    side, each one square along it (and one across, while there's any left), so a move is never cheaper than the
    rules' count."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    n = round(max(abs(dx), abs(dy)))
    out, px, py = [], x0, y0
    for i in range(1, n + 1):
        x, y = round(x0 + dx * i / n), round(y0 + dy * i / n)
        out.append((x, y, x != px and y != py))
        px, py = x, y
    return out


def cost(steps: list[tuple[float, float, bool]], rule: str = "5", terrain: set[str] | None = None, size: float = 1) -> dict:
    """{"feet", "squares", "rough" (squares of Difficult Terrain entered)} for the steps of a move. A Large creature is
    slowed where any square it enters is Difficult Terrain."""
    terrain = terrain or set()
    feet = rough = diagonals = 0
    span = max(1, round(size))
    for x, y, diag in steps:
        base = STEP
        if diag:
            diagonals += 1
            if rule == "alternate" and diagonals % 2 == 0:
                base = 2 * STEP
        if terrain and any(key(x + i, y + j) in terrain for i in range(span) for j in range(span)):
            rough += 1
            base += STEP
        feet += base
    return {"feet": feet, "squares": len(steps), "rough": rough}


def apart(a: dict, b: dict) -> int:
    """Feet between two tokens ({"x", "y", "size"} in squares), edge to edge as the grid counts it (5 when they
    touch, diagonals included)."""
    def gap(p, ps, q, qs):
        return max(0.0, q - (p + ps), p - (q + qs))
    sa, sb = max(a.get("size") or 1, 0.5), max(b.get("size") or 1, 0.5)
    squares = max(gap(a["x"], sa, b["x"], sb), gap(a["y"], sa, b["y"], sb))
    return round(squares) * STEP + STEP


REACH = re.compile(r"\breach (\d+) ?(?:ft|feet)", re.I)


def reach_of(entry: dict | None) -> int:
    """A stat block's longest reach (its actions', "reach 10 ft."), else 5 feet."""
    best = DEFAULT_REACH
    for group in ("actions", "bonus_actions", "reactions", "legendary_actions"):
        for a in (entry or {}).get(group) or []:
            for n in REACH.findall(a.get("text") or ""):
                best = max(best, int(n))
    return best


def leaves(mover: dict, start: tuple[float, float], end: tuple[float, float], others: list[dict]) -> list[dict]:
    """The others whose reach the mover is in at the start and not at the end: [{"id", "name", "reach"}]. `others`
    are the tokens that could make an Opportunity Attack ({"id", "name", "x", "y", "size", "reach"}): the caller
    leaves out allies, anyone who's Down and anyone the mover's player can't see."""
    a = {**mover, "x": start[0], "y": start[1]}
    b = {**mover, "x": end[0], "y": end[1]}
    out = []
    for o in others:
        r = o.get("reach") or DEFAULT_REACH
        if apart(a, o) <= r < apart(b, o):
            out.append({"id": o["id"], "name": o["name"], "reach": r})
    return out


def says(mover: str, left: list[dict]) -> str:
    """A move's note: "Cole left the reach of Goblin 2: an Opportunity Attack is possible, unless Cole took the
    Disengage action"."""
    if not left:
        return ""
    names = [x["name"] for x in left]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{mover} left the reach of {who}: an Opportunity Attack is possible, unless {mover} took the Disengage action"
