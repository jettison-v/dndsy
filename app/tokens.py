"""Tokens on a place's map (askdnd's table, slice 6; docs/plans/2026-11-06-table-build-plan.md).

A token is a character's (its portrait, its Hit Points, what it's under), one of a character's creatures (a familiar,
a summon: beside its master), or a creature the DM put there from the campaign's books or the SRD, with its own Hit
Points and conditions (`Token.hp`, `Token.conditions`). Creatures added together share a group, which rolls one
Initiative (Brett, Nov 6) until the DM gives one its own number.

Who sees what: a hidden token reaches only the DM's page (and admins'); a creature's numbers reach players only as the
battle settings say (Healthy, Bloodied or Down by default, app/table_fight.py). Who moves what: the DM any token, a
player their own characters' and their creatures'. A move on your own turn counts toward your movement (your turn's
bar) in feet as app/measure.py counts them (the campaign's diagonal rule, the DM's Difficult Terrain), and leaving a
creature's reach says an Opportunity Attack is possible.
"""

import json
import re
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import characters as chars
from app import picks, places, rules_data, web
from app.db import get_db
from app.models import Campaign, CampaignCharacter, Character, Place, Token

router = APIRouter()

SIZES = {"tiny": 0.5, "small": 1, "medium": 1, "large": 2, "huge": 3, "gargantuan": 4}
MOST_AT_ONCE = 12


def size_of(text: str | None) -> float:
    """Squares across for a stat block's size ("Medium or Small": the first)."""
    word = (text or "medium").split()[0].lower()
    return SIZES.get(word, 1)


def status(hp: dict | None) -> str:
    """Healthy, Bloodied (half or less) or Down (0), as players see a creature by default."""
    if not hp or not hp.get("max"):
        return ""
    cur = int(hp.get("current") or 0)
    return "Down" if cur <= 0 else "Bloodied" if cur * 2 <= int(hp["max"]) else "Healthy"


def _changed(text: str = "", kind: str = "ok") -> Response:
    events = {"tableChanged": True}
    if text:
        events["toast"] = web.notice(text, kind)
    return Response(status_code=204, headers={"HX-Trigger": json.dumps(events)})


def _token(db: Session, campaign: Campaign, token_id: int) -> Token:
    t = db.get(Token, token_id)
    if t is None or t.campaign_id != campaign.id:
        raise HTTPException(404)
    return t


def party(db: Session, campaign: Campaign) -> list[Character]:
    """The characters at this campaign's table now."""
    return list(db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                           .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None))
                           .order_by(Character.id)))


def visible(place: Place | None, t: Token, dm: bool) -> bool:
    """Whether this person sees the token at all: the DM every one; a player not a hidden one, nor a creature under fog
    (the one rule for the map, areas, the side panel and reach reminders: a creature they can't see is as if not there)."""
    from app import fog

    return dm or not (t.hidden or (t.kind == "monster" and fog.covered(place, t.x, t.y, t.size)))


def may_move(db: Session, user: dict | None, campaign: Campaign, t: Token, dm: bool) -> bool:
    if dm:
        return True
    if t.kind in ("character", "creature") and t.character_id:
        ch = db.get(Character, t.character_id)
        return ch is not None and picks.can_edit(db, user, ch)
    return False


# ------------------------------------------------------------------ what a page draws
def shown(db: Session, place: Place, user: dict | None, campaign: Campaign, dm: bool, rows: list[dict]) -> list[dict]:
    """The place's tokens as this person may see them, each {"id", "name", "kind", "x", "y", "size", "hidden",
    "picture", "moves", "panel", "hp" (pct or None), "status", "conds" (names), "character", "mine", "foe", "reach" (feet),
    "down", "fogged" (the DM's: under fog, players don't see it)}. A creature under fog never reaches a player. `rows`: Party's
    rows (character_pages.party_rows), for each character's portrait, Hit Points and what it's under."""
    from app import table_fight

    by_char = {r["c"].id: r for r in rows}
    settings = table_fight.settings(campaign)
    me = picks.user_row(db, user)
    out = []
    from app import fog

    for t in db.scalars(select(Token).where(Token.place_id == place.id).order_by(Token.id)):
        if not visible(place, t, dm):
            continue  # (hidden, or under fog: as if it weren't there)
        r = by_char.get(t.character_id) if t.character_id else None
        d = {"id": t.id, "name": t.name, "kind": t.kind, "x": t.x, "y": t.y, "size": t.size, "hidden": t.hidden, "picture": "",
             "panel": f"{web.base()}/table/tokens/{t.id}", "hp": None, "status": "", "conds": [], "character": t.character_id,
             "mine": bool(me and r and r["c"].owner_id == me.id), "foe": t.kind == "monster", "reach": reach(db, campaign, t),
             "fogged": dm and t.kind == "monster" and fog.covered(place, t.x, t.y, t.size)}
        d["moves"] = dm or d["mine"]
        if t.kind == "character" and r:
            s = r["sheet"] or {}
            hp = s.get("hit_points") or {}
            d["picture"] = (r.get("form") or {}).get("image") or s.get("portrait") or ""
            d["hp"] = round(100 * max(0, hp.get("current") or 0) / hp["max"]) if hp.get("max") else None
            d["conds"] = [x["name"] for x in r.get("conditions") or []]
            d["panel"] = f"/characters/{t.character_id}/brief"
            d["status"] = "Down" if hp.get("max") and not hp.get("current") else ""
        elif t.kind == "creature" and r:
            k = next((c for c in r.get("creatures") or [] if str(c["id"]) == str(t.creature)), None)
            if k:
                d["picture"] = k.get("picture") or ""
                d["hp"] = round(100 * max(0, k["hp"]["current"]) / k["hp"]["max"]) if k["hp"].get("max") else None
            d["panel"] = f"/characters/{t.character_id}/brief"
        else:
            m = t.monster or {}
            d["picture"] = m.get("image") or ""
            d["status"] = status(t.hp)
            if dm or settings["enemy_hp"] == "numbers":
                d["hp"] = round(100 * max(0, (t.hp or {}).get("current", 0)) / t.hp["max"]) if (t.hp or {}).get("max") else None
            elif settings["enemy_hp"] == "none":
                d["status"] = ""
            d["conds"] = [x.get("name", "") for x in t.conditions or []]
        d["down"] = d["status"] == "Down" or (t.kind == "monster" and status(t.hp) == "Down")
        out.append(d)
    return out


# ------------------------------------------------------------------ changes
@router.post("/table/tokens/{token_id:int}/move")
def move(request: Request, token_id: int, x: float = Form(...), y: float = Form(...), db: Session = Depends(get_db)):
    """A token dragged to a square (in squares, its top-left corner). On its character's turn, counts toward its movement."""
    user, campaign = places.here(request, db, need_runs=False)
    t = _token(db, campaign, token_id)
    dm = places.runs(user, campaign)
    if not may_move(db, user, campaign, t, dm):
        raise HTTPException(403, "That isn't your token to move.")
    p = db.get(Place, t.place_id)
    cols, rows = (places.drawn(p) or {}).get("cols") or 200, (places.drawn(p) or {}).get("rows") or 200
    step = 0.5 if t.size < 1 else 1
    nx = max(0.0, min(cols - max(t.size, step), round(x / step) * step))
    ny = max(0.0, min(rows - max(t.size, step), round(y / step) * step))
    from app import measure, table_fight

    steps = measure.path((t.x, t.y), (nx, ny))
    feet = measure.cost(steps, table_fight.settings(campaign)["diagonal"], set(p.terrain or []), t.size)["feet"]
    if t.kind == "character" and t.character_id and feet:
        from app import fight

        f = fight.shown(campaign, True)
        ch = db.get(Character, t.character_id)
        if f and f.get("now") and f["now"].get("character") == t.character_id and ch is not None:
            turn = dict(ch.turn or {})
            turn["moved"] = int(turn.get("moved") or 0) + feet
            ch.turn = turn
    # (players are told: only creatures they can see count, and a creature they can't see moving tells them nothing)
    left = measure.leaves({"size": t.size}, (t.x, t.y), (nx, ny), threats(db, campaign, t)) if visible(p, t, False) else []
    t.x, t.y = nx, ny
    if left:
        _left_reach(db, campaign, t, left)
    db.commit()
    return _changed()


def _left_reach(db: Session, campaign: Campaign, t: Token, left: list[dict]) -> None:
    """In a fight, leaving a creature's reach is a reminder for the DM and the player whose character it concerns (the
    mover's, or each character whose reach a creature left): an Opportunity Attack is possible. Out of a fight, nothing."""
    import copy

    from sqlalchemy.orm.attributes import flag_modified

    from app import fight, measure

    now = fight.shown(campaign, True) if campaign.fight else None
    if not now or now.get("waiting"):  # (before Round 1 begins, no one's turn: nothing to remind)
        return
    f = copy.deepcopy(campaign.fight)
    if t.character_id:
        ch = db.get(Character, t.character_id)
        if ch is not None:
            fight.remind(f, ch, "reach", t.name, measure.says(t.name, left))
    else:
        for x in left:
            o = db.get(Token, x["id"])
            ch = db.get(Character, o.character_id) if o is not None and o.character_id else None
            if ch is not None:
                fight.remind(f, ch, "reach", t.name, measure.says(t.name, [x]))
    campaign.fight = f
    flag_modified(campaign, "fight")


def reach(db: Session, campaign: Campaign, t: Token) -> int:
    """How far a token reaches (feet): a creature's from its stat block (kept on the token when it's added; looked up
    for one added before), anyone else 5 feet."""
    from app import measure

    m = t.monster or {}
    if t.kind != "monster" or not m.get("key"):
        return measure.DEFAULT_REACH
    if isinstance(m.get("reach"), int):
        return m["reach"]
    return measure.reach_of(rules_data.find("monster", m["key"], db, campaign.id))


def threats(db: Session, campaign: Campaign, t: Token) -> list[dict]:
    """The tokens that could make an Opportunity Attack on this one as it moves: the other side (the party's against
    the DM's creatures), not Down, and only creatures the players can see (the reminder reaches a player, whoever
    moved the token)."""
    foe = t.kind != "monster"
    p = db.get(Place, t.place_id)
    out = []
    for o in db.scalars(select(Token).where(Token.place_id == t.place_id, Token.id != t.id)):
        if (o.kind == "monster") != foe or not visible(p, o, False):
            continue
        if o.kind == "monster" and status(o.hp) == "Down":
            continue
        out.append({"id": o.id, "name": o.name, "x": o.x, "y": o.y, "size": o.size, "reach": reach(db, campaign, o)})
    return out


@router.post("/table/places/{place_id:int}/party")
def place_party(request: Request, place_id: int, x: float = Form(-1), y: float = Form(-1), db: Session = Depends(get_db)):
    """The party's tokens on this map, with their creatures that are here: each character's once (one already on the map
    stays where it is), side by side from the square given (else the middle)."""
    from app.character_pages import party_rows

    user, campaign = places.here(request, db)
    p = places._place(db, campaign, place_id)
    g = places.drawn(p)
    if not g["url"]:
        return _changed("Add a map first.", "warn")
    x = x if x >= 0 else max(0, g["cols"] // 2 - 2)
    y = y if y >= 0 else max(0, g["rows"] // 2)
    have = {(t.character_id, t.creature) for t in db.scalars(select(Token).where(Token.place_id == p.id))}
    n = 0
    for r in party_rows(db, user):
        ch = r["c"]
        if ch.campaign_id != campaign.id:
            continue
        if (ch.id, None) not in have:
            db.add(Token(campaign_id=campaign.id, place_id=p.id, kind="character", character_id=ch.id, name=ch.name,
                         x=x + n % 6, y=y + n // 6, size=1))
            n += 1
        for k in r.get("creatures") or []:
            if (ch.id, str(k["id"])) not in have:
                db.add(Token(campaign_id=campaign.id, place_id=p.id, kind="creature", character_id=ch.id, creature=str(k["id"]),
                             name=k["name"], x=x + n % 6, y=y + n // 6, size=size_of(k.get("size")) if size_of(k.get("size")) > 1 else 0.5))
                n += 1
    db.commit()
    return _changed(f"The party is on the map ({n} token{'s' if n != 1 else ''})." if n else "The party is on the map already.")


@router.post("/table/places/{place_id:int}/creatures")
def add_creatures(request: Request, place_id: int, key: str = Form(...), count: int = Form(1), name: str = Form(""),
                  hidden: str = Form(""), x: float = Form(-1), y: float = Form(-1), db: Session = Depends(get_db)):
    """Creatures from the campaign's books or the SRD onto the map: `count` of one kind, numbered when more than one, one
    group for Initiative. Hidden ones only the DM sees until shown."""
    user, campaign = places.here(request, db)
    p = places._place(db, campaign, place_id)
    from app import measure

    entry = rules_data.find("monster", key, db, campaign.id)
    if entry is None:
        return _changed("That creature isn't in your books or the SRD.", "warn")
    g = places.drawn(p)
    count = max(1, min(MOST_AT_ONCE, count))
    base = " ".join(name.split())[:180] or entry["name"]
    size = size_of(entry.get("size"))
    x = x if x >= 0 else max(0, (g["cols"] or 20) // 2 + 2)
    y = y if y >= 0 else max(0, (g["rows"] or 20) // 2 - 2)
    taken = {t.name for t in db.scalars(select(Token).where(Token.place_id == p.id))}
    group = secrets.token_hex(4) if count > 1 else None
    hide = hidden == "1"  # (+ Creatures ticks Hidden when the battle settings start new creatures hidden)
    pic = (rules_data.pictures().get(entry.get("key", "")) or {}).get("image") or entry.get("image") or ""
    n, made = 1, 0
    while made < count:
        label = f"{base} {n}" if count > 1 or base in taken else base
        n += 1
        if label in taken:
            continue
        taken.add(label)
        db.add(Token(campaign_id=campaign.id, place_id=p.id, kind="monster", name=label, group=group, hidden=hide,
                     monster={"key": entry["key"], "name": entry["name"], "source": entry.get("source", ""), "image": pic,
                              "reach": measure.reach_of(entry)},
                     hp={"current": int(entry.get("hp") or 1), "max": int(entry.get("hp") or 1), "temp": 0},
                     x=x + (made % 4) * size, y=y + (made // 4) * size, size=size))
        made += 1
    db.flush()
    from app import table_fight

    new = list(db.scalars(select(Token).where(Token.place_id == p.id, Token.name.in_(list(taken)))
                          .order_by(Token.id.desc()).limit(count)))
    table_fight.joined(db, campaign, new, (picks.user_row(db, user).id if picks.user_row(db, user) else None))
    db.commit()
    hid = " (hidden from the players)" if hide else ""
    return _changed(f"{count} {entry['name']} on the map{hid}." if count > 1 else f"{base} is on the map{hid}.")


@router.post("/table/tokens/{token_id:int}/hidden")
def set_hidden(request: Request, token_id: int, on: int = Form(...), db: Session = Depends(get_db)):
    _, campaign = places.here(request, db)
    t = _token(db, campaign, token_id)
    t.hidden = bool(on)
    from app import table_fight

    table_fight.renamed(db, campaign, t)
    db.commit()
    return _changed(f"{t.name} is hidden from the players." if on else f"Players see {t.name} now.")


@router.post("/table/tokens/{token_id:int}/remove")
def remove(request: Request, token_id: int, db: Session = Depends(get_db)):
    _, campaign = places.here(request, db)
    t = _token(db, campaign, token_id)
    name = t.name
    from app import table_fight

    table_fight.left(db, campaign, t.id)
    db.delete(t)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "closePanel": True,
                                                                        "toast": f"{name} is off the map."})})


@router.post("/table/tokens/{token_id:int}/rename")
def rename(request: Request, token_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    _, campaign = places.here(request, db)
    t = _token(db, campaign, token_id)
    if t.kind != "monster":
        raise HTTPException(422)
    t.name = " ".join(name.split())[:200] or t.name
    from app import table_fight

    table_fight.renamed(db, campaign, t)
    db.commit()
    return _changed(f"Renamed to {t.name}.")


HP_TERM = re.compile(r"^[+−-]?\d{1,4}$")


@router.post("/table/tokens/{token_id:int}/hp")
def change_hp(request: Request, token_id: int, change: str = Form(...), db: Session = Depends(get_db)):
    """A creature's Hit Points, by the DM: −7 takes 7, +5 heals 5, 20 sets it to 20 (Temporary Hit Points first)."""
    _, campaign = places.here(request, db)
    t = _token(db, campaign, token_id)
    if t.kind != "monster" or not HP_TERM.match(change.strip()):
        return _changed("Type −7 for damage, +5 for healing, or a number.", "warn")
    hp = dict(t.hp or {"current": 0, "max": 0, "temp": 0})
    c = change.strip().replace("−", "-")
    n = int(c)
    if c[0] == "-":
        temp = int(hp.get("temp") or 0)
        used = min(temp, -n)
        hp["temp"], hp["current"] = temp - used, max(0, int(hp["current"]) - (-n - used))
    elif c[0] == "+":
        hp["current"] = min(int(hp["max"]), int(hp["current"]) + n)
    else:
        hp["current"] = max(0, min(int(hp["max"]), n))
    t.hp = hp
    db.commit()
    return _changed(f"{t.name}: {hp['current']} / {hp['max']}{' (' + status(hp) + ')' if status(hp) != 'Healthy' else ''}.")


def sheet_hp(ch: Character) -> dict:
    return (chars.character_summary(ch) or {}).get("hit_points") or {}
