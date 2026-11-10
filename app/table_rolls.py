"""Table rolls: dice rolled on the server, shared with the table.

The page's roll buttons carry what to roll (data-roll, data-label, data-mod, data-dmg,
data-adv; app/templates/_char.html). app.js opens a small roll window (Adv / Dis, who
sees it, situational bonuses), then posts the choice here and the server rolls the dice,
so nobody's browser decides a result.

Who sees a roll (Brett, 2026-10-20):
- "table": everyone.
- "dm": the roller and the DM see the number; everyone else only "<character> rolled for
  the DM" (no label, no dice, no total ever leave the server for them).
- "self": the roller only (not even the DM).

A roll can get follow-ups, stored as rows pointing at it (parent_id) and shown with it
as one entry: the damage of an attack (doubled dice on a natural 20), a reroll (Heroic
Inspiration, or Halfling Luck on a 1) and an added die (Bardic Inspiration, Guidance…, named as you say). They share
the roll's character and audience. Only your newest roll offers them.

Only a character's own player rolls for it here (like stars and notes); anyone else's
click stays a private roll in their browser. Anyone signed in can roll plain dice from the
sidebar (the DM's show as "DM").
"""

import json
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import characters as chars
from app import creatures, picks, realtime, web
from app import roll_recipes as rr
from app.auth import current_user, is_dm
from app.db import get_db
from app.models import Character, CharacterSnapshot, TableRoll, User
from app.templating import templates

router = APIRouter()

D20_KINDS = ("save", "check", "attack", "death")
ROOT_KINDS = (*D20_KINDS, "damage", "heal", "temp", "dice", "dc")
# An Unarmed Strike's Grapple or Shove (feedback 26): no dice, the DC the target saves against, for the DM
UNARMED_WAYS = {"Grapple": "Grappled", "Shove": "pushed 5 ft or Prone"}  # (what a failed save means, in the row's 40 characters)
MAX_COUNT = 12  # darts, rays, beams
MODES = ("normal", "adv", "dis")
VISIBILITY = ("table", "dm", "self")
REROLLS = ("Heroic Inspiration", "Luck")
BONUS_DICE = (4, 6, 8, 10, 12)
LOG_SIZE = 30
MAX_MOD = 40
MAX_EXTRAS = 6
TERM = re.compile(r"([+-])(?:(\d{1,2})d(\d{1,3})|(\d{1,3}))")
EXTRA = re.compile(r"^([^:]{1,40}):\s*([+-]\s*(?:\d{1,2}d\d{1,3}|\d{1,2}))$")


def die(sides: int) -> int:
    return secrets.randbelow(sides) + 1


def signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{abs(n)}"


def parse_formula(expr: str) -> tuple[list[tuple[int, int]], int] | None:
    """'2d6+1d8+3' -> ([(2, 6), (1, 8)], 3); a plain '3' -> ([], 3), an Unarmed Strike's damage. At most 40 dice of
    2–100 sides."""
    s = (expr or "").replace(" ", "").replace("−", "-").lower()
    if not s:
        return None
    s = s if s[0] in "+-" else "+" + s
    terms, flat, pos = [], 0, 0
    for m in TERM.finditer(s):
        if m.start() != pos:
            return None
        pos = m.end()
        if m.group(2):
            count, sides = int(m.group(2)), int(m.group(3))
            if m.group(1) == "-" or not (1 <= count <= 20 and 2 <= sides <= 100):
                return None
            terms.append((count, sides))
        else:
            flat += (-1 if m.group(1) == "-" else 1) * int(m.group(4))
    if pos != len(s) or (not terms and flat < 1) or sum(c for c, _ in terms) > 40 or abs(flat) > 60:
        return None
    return terms, flat


def formula_text(terms: list[tuple[int, int]], flat: int) -> str:
    if not terms:
        return str(flat)
    return "+".join(f"{c}d{s}" for c, s in terms) + (signed(flat) if flat else "")


def roll_d20(mod: int, mode: str, roll=None) -> dict:
    """A d20 test: two dice on Advantage or Disadvantage, keeping the higher or lower."""
    roll = roll or die
    dice = [roll(20)] if mode == "normal" else [roll(20), roll(20)]
    kept = max(dice) if mode == "adv" else min(dice) if mode == "dis" else dice[0]
    return {"dice": dice, "kept": kept, "modifier": mod, "total": kept + mod, "formula": f"d20{signed(mod)}"}


def roll_formula(expr: str, crit: bool = False, roll=None, floor: bool = True) -> dict | None:
    """Damage, healing or plain dice. A critical hit rolls the dice twice (not the bonus)."""
    roll = roll or die
    parsed = parse_formula(expr)
    if not parsed:
        return None
    terms, flat = parsed
    terms = [(c * 2, s) for c, s in terms] if crit else terms
    dice = [roll(s) for c, s in terms for _ in range(c)]
    total = sum(dice) + flat
    return {"dice": dice, "kept": None, "modifier": flat, "total": max(total, 0) if floor else total,
            "formula": formula_text(terms, flat)}


def roll_damage(expr: str, crit: bool = False, roll=None) -> dict | None:
    return roll_formula(expr, crit, roll)


def check_parts(parts: list[str], count: int = 1) -> bool:
    """Parts like "1d6+2 piercing" (from a stored recipe, app/roll_recipes.py): sensible dice only."""
    parsed = [rr.parse_part(p) for p in parts]
    if not parts or len(parts) > 8 or not (1 <= count <= MAX_COUNT) or any(p is None for p in parsed):
        return False
    if any((n and not 2 <= s <= 100) or n > 40 or abs(f) > 60 or len(k) > 60 for n, s, f, k in parsed):
        return False
    return sum(n for n, *_ in parsed) * count <= 120


def roll_parts(parts: list[str], count: int = 1, crits: list[bool] | None = None, each: str = "", roll=None,
               floor: bool = True, once: bool = False) -> dict:
    """Roll each part, once per instance (3 darts: 3 × 1d4+1), keeping each roll's own line. A
    critical instance rolls its dice twice. `crits` (one per instance) also says how many there are.
    `once` (a house rule, app/house_rules.py): the first instance's dice count for every instance."""
    roll = roll or die
    crits = crits if crits is not None else [False] * count
    lines, first = [], {}
    for i, crit in enumerate(crits):
        for j, (n, sides, flat, kind) in enumerate(rr.parse_part(p) for p in parts):
            k = n * 2 if crit else n
            dice = list(first[j]) if once and i else [roll(sides) for _ in range(k)]
            first.setdefault(j, dice)
            lines.append({"label": f"{each.title()} {i + 1}" if len(crits) > 1 and each else "", "kind": kind, "crit": crit,
                          "formula": (f"{k}d{sides}" + (f"{flat:+d}" if flat else "")) if k else str(flat), "dice": dice,
                          "total": sum(dice) + flat})
    total = sum(x["total"] for x in lines)
    return {"dice": [d for x in lines for d in x["dice"]], "kept": None, "modifier": sum(rr.parse_part(p)[2] for p in parts) * len(crits),
            "total": max(total, 0) if floor else total, "formula": " + ".join(parts), "parts": lines}


def parse_extras(values: list[str]) -> list[tuple[str, int, int, int]] | None:
    """Situational bonuses as 'Bless:+1d4', 'Bane:-1d4', 'Other:+2' -> (label, sign, count, sides);
    a flat bonus has sides 0. None if any doesn't make sense."""
    out = []
    for v in values:
        if not v:
            continue
        m = EXTRA.match(v.replace("−", "-").strip())
        if not m:
            return None
        label, term = " ".join(m.group(1).split()), m.group(2).replace(" ", "")
        sign, body = (-1 if term[0] == "-" else 1), term[1:]
        if "d" in body:
            count, sides = (int(x) for x in body.split("d"))
            if not (1 <= count <= 10 and 2 <= sides <= 100):
                return None
        else:
            count, sides = int(body), 0
        out.append((label, sign, count, sides))
    return out if len(out) <= MAX_EXTRAS else None


def roll_extras(extras, crit: bool = False, roll=None) -> list[dict]:
    roll = roll or die
    out = []
    for label, sign, count, sides in extras:
        if sides:
            n = count * 2 if crit else count
            dice = [roll(sides) for _ in range(n)]
            out.append({"label": label, "formula": f"{'+' if sign > 0 else '-'}{n}d{sides}", "dice": dice, "total": sign * sum(dice)})
        else:
            out.append({"label": label, "formula": signed(sign * count), "dice": [], "total": sign * count})
    return out


def _int(s: str) -> int | None:
    try:
        return int(str(s or "0").replace("−", "-").strip() or 0)
    except ValueError:
        return None


# ------------------------------------------------------------------ what the page knows about a character

def roll_context(sheet: dict | None) -> dict:
    """For the roll window: Heroic Inspiration, Luck Points (Lucky feat), Halfling Luck, the
    spellcasting modifier (most healing spells add it) and the Constitution modifier with
    the hit dice (Short Rest)."""
    s = sheet or {}
    luck = next((a.get("uses") for a in s.get("actions") or [] if a.get("name") == "Luck Points" and a.get("uses")), None)
    sc = (s.get("spellcasting") or [{}])[0]
    spell_mod = next((v for k, v in sc.get("dc_parts") or [] if k.endswith(" modifier")), None)
    con = next((a.get("modifier") for a in s.get("abilities") or [] if a.get("short") == "Con"), 0)
    dice = sorted({h["die"] for h in (s.get("hit_points") or {}).get("hit_dice") or [] if h.get("total", 0) > h.get("used", 0)})
    slots = (s.get("spell_slots") or {})
    have = sorted({x["level"] for x in slots.get("slots") or [] if x.get("max", 0) > x.get("used", 0)}
                  | ({slots["pact"]["level"]} if slots.get("pact") and slots["pact"].get("max", 0) > slots["pact"].get("used", 0) else set()))
    return {"inspiration": bool(s.get("inspiration")), "luck": luck["left"] if luck else None,
            "halfling": "halfling" in (s.get("species") or "").lower(), "spell_mod": spell_mod, "con": con, "hit_dice": dice,
            "level": s.get("level") or 1, "slots": have,
            # (the roll card's pills on a check or a save: this character's own modifiers, app/roll_plan.py)
            "mods": {k: _modifiers(s, k) for k in ("check", "save")}}


def _modifiers(sheet: dict, kind: str) -> list[dict]:
    from app.roll_plan import modifiers_for

    try:
        return modifiers_for(sheet, kind)
    except Exception:  # noqa: BLE001 - a sheet the plan can't read: no pills, the roll still works
        return []


templates.env.globals["roll_context"] = lambda sheet: json.dumps(roll_context(sheet))


# ------------------------------------------------------------------ who sees what

def shown(roll: TableRoll, viewer_id: int | None, viewer_is_dm: bool) -> str | None:
    """'full' (the number), 'hidden' (only that a roll happened) or None (not at all)."""
    mine = viewer_id is not None and roll.user_id == viewer_id
    if roll.visibility == "table" or mine:
        return "full"
    if roll.visibility == "dm":
        return "full" if viewer_is_dm else "hidden"
    return None  # "self": the roller only


def _visible_roots(campaign_id: int, viewer_id: int | None):
    """Rolls anyone could be shown something about: others' just-me rolls never leave the database."""
    mine = TableRoll.user_id == viewer_id if viewer_id is not None else False
    return select(TableRoll).where(TableRoll.campaign_id == campaign_id, TableRoll.parent_id.is_(None),
                                   or_(TableRoll.visibility.in_(("table", "dm")), mine))


def _ago(when: datetime | None) -> str:
    if not when:
        return ""
    s = max((datetime.now(UTC) - when).total_seconds(), 0)
    if s < 10:
        return "now"
    if s < 60:
        return f"{int(s)} s"
    if s < 3600:
        return f"{int(s // 60)} min"
    if s < 86400:
        return f"{int(s // 3600)} h"
    return when.strftime("%b %-d")


def _part(r: TableRoll) -> dict:
    """One roll's dice for display."""
    many = r.kept is not None and len(r.dice) > 1
    return {"dice": list(r.dice), "kept_at": r.dice.index(r.kept) if many and r.kept in r.dice else -1, "modifier": r.modifier,
            "mode": r.mode, "formula": r.formula, "extras": list(r.extras or []), "total": r.total, "crit": r.crit,
            "parts": [{**x, "kept_at": x["dice"].index(x["kept"]) if x.get("kept") in x.get("dice", []) and len(x["dice"]) > 1 else -1}
                      for x in r.parts or []]}


def detail_of(level: int = 0, why=(), riders=(), hidden="", via="", own="") -> dict:
    """What else the roll card or window knew, checked and kept short (TableRoll.detail; Brett's round 2 note, Nov 10)."""
    clean = lambda xs, n: [" ".join(str(x).split())[:n] for x in xs if str(x).strip()][:6]  # noqa: E731
    out = {"level": level if 1 <= (level or 0) <= 9 else None, "why": clean(why, 120), "riders": clean(riders, 80),
           "hidden": bool(hidden), "via": via if via in ("card", "window", "search") else None, "self": bool(own)}
    return {k: v for k, v in out.items() if v}


def _death(total: int, nat: int | None) -> str:
    if nat == 20:
        return "natural 20: you regain 1 Hit Point"
    if nat == 1:
        return "natural 1: two failures"
    return "success" if total >= 10 else "failure"


def entries(db: Session, roots: list[TableRoll], kids: list[TableRoll], viewer_id: int | None, viewer_is_dm: bool,
            mine_ctx: dict | None = None) -> list[dict]:
    """What a viewer's browser gets for each roll and its follow-ups, newest activity first.
    A hidden roll carries only who and when. Your newest roll offers its follow-ups."""
    by_root: dict[int, list[TableRoll]] = {}
    for k in kids:
        by_root.setdefault(k.parent_id, []).append(k)
    ids = {r.character_id for r in roots if r.character_id}
    names, pics = {}, {}
    if ids:
        for ch in db.scalars(select(Character).where(Character.id.in_(ids))):
            names[ch.id] = ch.name
        pics = dict(db.execute(select(CharacterSnapshot.character_id, CharacterSnapshot.summary["portrait"].astext)
                               .where(CharacterSnapshot.character_id.in_(ids))).all())
    from app.dice import prefs

    rollers = {r.user_id for r in roots if r.user_id}
    dice = {u.id: prefs(u) for u in db.scalars(select(User).where(User.id.in_(rollers)))} if rollers else {}
    seq = {r.id: max([r.id] + [k.id for k in by_root.get(r.id, [])]) for r in roots}
    out, newest_mine = [], True
    for r in sorted(roots, key=lambda r: seq[r.id], reverse=True):
        how = shown(r, viewer_id, viewer_is_dm)
        if how is None:
            continue
        mine = viewer_id is not None and r.user_id == viewer_id
        name = (f"{names[r.character_id]} ({r.who})" if r.who else names[r.character_id]) if r.character_id in names else (r.who or "Someone")
        e = {"id": r.id, "seq": seq[r.id], "character_id": r.character_id or 0, "name": name, "initial": name[:1].upper(),
             "portrait": pics.get(r.character_id) or "", "hue": (r.character_id or 0) % 6 if r.character_id else 6,
             "mine": mine, "to": r.visibility, "hidden": how == "hidden", "dice": dice.get(r.user_id) or prefs(None), "ddb": bool(r.ddb_roll_id),
             "at": r.created_at.isoformat() if r.created_at else "", "ago": _ago(r.created_at),
             "hidden_text": "Rolled for the DM" if r.character_id else "Rolled behind the screen",
             "by_dm": bool(r.ddb_roll_id and not r.character_id)}  # (a monster's, heard from D&D Beyond's game log)
        if how == "full":
            k = {x.kind: x for x in by_root.get(r.id, [])}
            rr, dmg, bonus = k.get("reroll"), k.get("damage"), k.get("bonus")
            eff = rr or r
            nat = eff.kept if r.kind in D20_KINDS and eff.kept in (1, 20) else None
            total = eff.total + (bonus.total if bonus else 0)
            e |= {"label": r.label, "kind": r.kind, "total": total, "nat": nat, "main": _part(eff),
                  "rerolled": {**_part(r), "reason": rr.label} if rr else None,
                  "bonus": {"label": bonus.label, "formula": bonus.formula, "dice": list(bonus.dice), "total": bonus.total} if bonus else None,
                  "damage": _part(dmg) if dmg else None,
                  "outcome": _death(total, nat) if r.kind == "death" else "",
                  "detail": dict(r.detail or {}) | ({"outcome": "hit"} if dmg and r.kind == "attack" else {}),
                  "short": {"death": "Death", "heal": "Heal", "damage": "Dmg", "dice": "Dice"}.get(r.kind) or r.label.split()[0][:5],
                  "can": {"damage": "", "reroll": "", "bonus": False}}
            if mine and newest_mine and not r.ddb_roll_id:  # (a roll made on D&D Beyond is only shown: its dice are D&D Beyond's)
                ctx = mine_ctx or {}
                e["can"] = {
                    "damage": _damage_label(r) if r.kind == "attack" and (r.damage or r.spec) and not dmg and (nat != 1 or r.parts)
                    and (r.detail or {}).get("outcome") != "miss" else "",  # (marked missed: no damage to roll)
                    "reroll": "" if rr or damage_rolled(dmg) or r.kind not in D20_KINDS else
                              "Luck" if ctx.get("halfling") and eff.kept == 1 else
                              "Heroic Inspiration" if ctx.get("inspiration") else "",
                    "bonus": r.kind in D20_KINDS and not bonus and not damage_rolled(dmg),
                }
        if mine:
            newest_mine = False
        out.append(e)
    return out


def damage_rolled(damage: TableRoll | None) -> bool:
    """Damage with dice was rolled: the attack's done. Flat damage (an Unarmed Strike's 3) comes with the attack roll
    itself (feedback 25), so a reroll or an added die on the attack is still yours to make."""
    return bool(damage and damage.dice)


def flat_damage(expr: str) -> dict | None:
    """'3' or '0' (Vi's Unarmed Strike: 1 + Strength −1): damage with no dice, as its roll; None for dice."""
    parsed = parse_formula(expr) if expr != "0" else ([], 0)
    return {"dice": [], "kept": None, "modifier": parsed[1], "total": parsed[1], "formula": str(parsed[1])} if parsed and not parsed[0] else None


def _damage_label(r: TableRoll) -> str:
    """What an attack's damage button rolls: '1d6+3', or '2d6 fire, per ray'."""
    if r.spec and r.spec.get("parts"):
        return " + ".join(r.spec["parts"]) + (f", per {r.spec.get('each') or 'hit'}" if len(r.parts or []) > 1 else "")
    return r.damage


def _viewer(db: Session, user: dict) -> tuple[int | None, bool]:
    me = picks.user_row(db, user)
    return (me.id if me else None), is_dm(user)


def _ctx(db: Session, viewer_id: int | None) -> dict:
    """The viewer's own character's roll context (for the follow-ups their newest roll offers)."""
    if viewer_id is None:
        return {}
    summary = db.scalar(select(CharacterSnapshot.summary).join(Character, Character.id == CharacterSnapshot.character_id)
                        .where(Character.owner_id == viewer_id).order_by(Character.id))
    return roll_context(summary) if summary else {}


def _kids(db: Session, roots: list[TableRoll]) -> list[TableRoll]:
    ids = [r.id for r in roots]
    return list(db.scalars(select(TableRoll).where(TableRoll.parent_id.in_(ids)).order_by(TableRoll.id))) if ids else []


def render(request: Request, items: list[dict]) -> str:
    return templates.get_template("_roll_items.html").render(rolls=items, request=request)


# ------------------------------------------------------------------ routes

@router.get("/rolls")
def roll_log(request: Request, since: int = -1, also: int = 0, db: Session = Depends(get_db)):
    """The table's rolls this viewer may see, newest activity first: the last LOG_SIZE (with a
    line when there are none), or only rolls with something new after `since` (pages poll
    every few seconds; nothing new is a 204, which htmx skips). A roll whose damage, reroll or
    added die is new comes again, whole: the page replaces its old copy. `also`: a roll that changed without a new row
    (its outcome, the card's Missed), announced with its id, so every page shows it again."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    campaign = web.campaign(db)
    if not campaign:
        return Response(status_code=204)
    viewer_id, dm = _viewer(db, user)
    q = _visible_roots(campaign.id, viewer_id)
    if since >= 0:
        touched = {pid or rid for rid, pid in db.execute(select(TableRoll.id, TableRoll.parent_id)
                                                          .where(TableRoll.campaign_id == campaign.id, TableRoll.id > since))}
        if also:
            touched.add(also)
        if not touched:
            return Response(status_code=204)
        q = q.where(TableRoll.id.in_(touched))
    roots = list(db.scalars(q.order_by(TableRoll.id.desc()).limit(LOG_SIZE)))
    if not roots and since >= 0:
        return Response(status_code=204)
    return HTMLResponse(render(request, _entries(db, user, roots, viewer_id, dm)))


def _error(text: str, status: int = 400):
    return JSONResponse({"error": text}, status_code=status)


def _entries(db: Session, user: dict, roots: list[TableRoll], viewer_id: int | None, dm: bool) -> list[dict]:
    """entries() with what each damage or healing roll offers this viewer: Apply to whom, who it was applied to, and
    the Concentration save a hit asks of their own character (app/hit_points.py)."""
    from app import hit_points

    kids = _kids(db, roots)
    items = entries(db, roots, kids, viewer_id, dm, _ctx(db, viewer_id))
    info = hit_points.apply_info(db, user, roots, kids)
    for e in items:
        e["apply"] = info.get(e["id"])
    return items


LIVE_FIELDS = ("id", "seq", "name", "label", "kind", "main", "damage", "bonus", "dice", "total", "nat")


def _live(db: Session, root: TableRoll) -> dict:
    """A roll the whole table sees, in the live message itself (Brett, 2026-10-29: every screen starts the dice at once,
    as D&D Beyond's do; an exception to "a live message says what changed, never the change"): what throwing it takes,
    as anyone else at the table sees it. Each page still fetches its own row (Apply, who sees what). A roll for fewer
    people (the DM, just you) sends nothing more than that the rolls changed, so only the server decides who sees it."""
    if root.visibility != "table":
        return {}
    e = entries(db, [root], _kids(db, [root]), None, False)[0]
    if e.get("hidden"):
        return {}
    roll = {k: e.get(k) for k in LIVE_FIELDS} | {"by": root.user_id}
    return {"roll": roll} if len(json.dumps(roll, default=str)) < 5000 else {}  # (Postgres's NOTIFY holds 8000 bytes)


def death_mark(db: Session, root: TableRoll) -> dict | None:
    """A death save marks itself on the sheet (app/death_saves.py; Brett, 2026-10-29): the result as the roll counts it
    now, moving its earlier mark after a reroll or an added die. What the page does next ({"text", "character",
    "deliver"}), or None."""
    from app import death_saves

    ch = root.character
    if root.kind != "death" or not ch:
        return None
    kids = {k.kind: k for k in _kids(db, [root])}
    eff = kids.get("reroll") or root
    result = death_saves.outcome(eff.total + (kids["bonus"].total if "bonus" in kids else 0), eff.kept if eff.kept in (1, 20) else None)
    said = death_saves.roll(db, ch, result, replaces=(root.spec or {}).get("death", ""))
    if not said:
        return None
    root.spec = {**(root.spec or {}), "death": result}
    return {"text": said, "character": ch.id, "deliver": web.deliver_now(ch)}


def reply_body(request: Request, db: Session, root: TableRoll, me_id: int, dm: bool, new: TableRoll | None = None,
               death: dict | None = None) -> dict:
    """The roll's entry and its HTML for the log, and what the extension sends to D&D Beyond's Game Log for the roll
    just made (`new`: a follow-up, else the roll itself; app/gamelog.py); `death`: what a death save marked."""
    from app import gamelog  # (it reads this module's kinds)

    entry = _entries(db, current_user(request), [root], me_id, dm)[0]
    made = new or root
    out = {"roll": entry, "html": render(request, [entry]), **({"death": death} if death else {})}
    if (msgs := gamelog.messages(db, made, made.character)):
        out["gamelog"] = {"ddbId": str(made.character.ddb_id), "messages": msgs}
    return out


def _reply(request: Request, db: Session, root: TableRoll, me_id: int, dm: bool, new: TableRoll | None = None,
           death: dict | None = None):
    return JSONResponse(reply_body(request, db, root, me_id, dm, new, death))


def add_roll(db: Session, ch: Character, me_id: int, label: str, dice: str) -> TableRoll | None:
    """A healing roll the whole table sees, made for another route (a potion: app/item_use.py). None: not dice."""
    result = roll_formula(dice, floor=True)
    if result is None:
        return None
    row = TableRoll(campaign_id=ch.campaign_id, character_id=ch.id, user_id=me_id, label=label[:120], kind="heal", mode="normal",
                    visibility="table", damage="", spec=None, extras=[], who="", **result)
    db.add(row)
    db.flush()
    realtime.announce(db, ch.campaign_id, "rolls", **_live(db, row))
    return row


KIND_USES = {"attack": "attacks", "save": "saves", "check": "checks", "damage": "damage", "heal": "healing", "temp": "healing",
             "death": "death saves", "dc": "Grapple and Shove"}


def usage_name(kind: str, action: str, via: str) -> str:
    """A roll's use, as Admin › Features counts it: "Rolls: attacks", "Roll card: damage", "Rolls: rerolls"."""
    what = {"reroll": "rerolls", "bonus": "added dice", "damage": "damage"}.get(action) or KIND_USES.get(kind, "other")
    return f"{'Roll card' if via == 'card' else 'Rolls'}: {what}"


@router.post("/rolls")
def make_roll(request: Request, character: int = Form(0), kind: str = Form(""), label: str = Form(""),
              mod: str = Form(""), dmg: str = Form(""), adv: str = Form(""), mode: str = Form("normal"),
              to: str = Form("table"), extra: list[str] = Form([]), parent: int = Form(0), action: str = Form(""),
              die_size: int = Form(0, alias="die"), part: list[str] = Form([]), dmg_part: list[str] = Form([]),
              count: int = Form(1), each: str = Form(""), once: str = Form(""), who: str = Form(""), token: int = Form(0),
              via: str = Form(""), level: int = Form(0), why: list[str] = Form([]), rider: list[str] = Form([]),
              hidden: str = Form(""), own: str = Form("", alias="self"), db: Session = Depends(get_db)):
    """Roll on the server and return the result (the entry and its HTML for the log).

    A new roll: `kind` with its data, for the player's own character (plain `dice` may have
    none). A follow-up: `parent` (your roll) and `action` = damage | reroll | bonus."""
    request.state.usage = usage_name(kind, action, via)  # (which features get used: app/usage.py)
    user = current_user(request)
    if not user:
        return _error("Sign in to roll.", 401)
    campaign = web.campaign(db)
    me = picks.user_row(db, user)
    if not campaign or not me:
        return _error("Sign in to roll.", 401)
    extras = parse_extras(extra)
    if extras is None:
        return _error("A bonus doesn't look right.")
    if parent:
        return _follow_up(request, db, campaign.id, me.id, is_dm(user), parent, action, label, extras, die_size)

    ch = db.get(Character, character) if character else None
    if character and (not ch or ch.campaign_id != campaign.id):
        return _error("That character isn't in the campaign.", 404)
    tok = None
    if token and not ch:  # a creature on askdnd's table, rolled by the DM as it (app/table_creatures.py)
        from app import places
        from app.models import Token

        tok = db.get(Token, token)
        if tok is None or tok.campaign_id != campaign.id or not places.runs(user, campaign):
            return _error("Only the DM rolls for the creatures on the map.", 403)
    if kind != "dice" and not ch and not tok:
        return _error("That character isn't in the campaign.", 404)
    if ch and not picks.can_edit(db, user, ch):
        return _error(f"Only {ch.name}'s player rolls for {ch.name} at the table.", 403)
    label = " ".join(label.split())[:120] or ("Dice" if kind == "dice" else "")
    if kind not in ROOT_KINDS or not label or mode not in MODES or to not in VISIBILITY:
        return _error("That roll is missing something.")
    damage, spec, each = "", None, " ".join(each.split())[:20].lower()
    if (part and not check_parts(part, count)) or (dmg_part and not check_parts(dmg_part, count)) or not 1 <= count <= MAX_COUNT:
        return _error("Those dice don't look right.")
    if kind == "dc":
        from app.character_views import unarmed_choices

        u = unarmed_choices(chars.character_summary(ch) or {}, {"name": "Unarmed Strike"})
        if label not in UNARMED_WAYS or not u:
            return _error("That roll is missing something.")
        result = {"dice": [], "kept": None, "modifier": 0, "total": u["dc"], "parts": [],
                  "formula": f"Str or Dex save, or {UNARMED_WAYS[label]}"}
        rolled, mode = [], "normal"
    elif kind in D20_KINDS:
        m = 0 if kind == "death" else _int(mod)
        if m is None or abs(m) > MAX_MOD:
            return _error("That bonus doesn't look right.")
        if mode == "normal" and adv:
            mode = "adv"  # Advantage that always applies (data-adv)
        rays = []
        for i in range(count if kind == "attack" else 1):  # several rays or beams: an attack roll each
            r = roll_d20(m, mode)
            x = roll_extras(extras)
            r["total"] += sum(e["total"] for e in x)
            rays.append({**r, "extras": x, "label": f"{(each or 'attack').title()} {i + 1}"})
        result = {k: rays[0][k] for k in ("dice", "kept", "modifier", "total", "formula")}
        rolled = rays[0]["extras"]
        result["parts"] = rays if count > 1 else []
        if kind == "attack" and dmg_part:
            spec = {"parts": dmg_part, "each": each}
        elif kind == "attack" and (parse_formula(dmg) or dmg.strip() == "0"):
            damage = dmg.replace(" ", "").replace("−", "-")
    else:
        if part:
            result = roll_parts(part, count, each=each, floor=kind != "dice", once=bool(once))
        else:
            result = roll_formula(dmg, floor=kind != "dice")
            if result is None:
                return _error("Those dice don't look right.")
        rolled = roll_extras(extras)
        result["total"] = result["total"] + sum(x["total"] for x in rolled)
        result["total"] = max(result["total"], 0) if kind != "dice" else result["total"]
        mode = "normal"
    # With a character, `who` is the Wild Shape form it rolled in, kept with the roll (Table rolls says "Cole (Polar Bear)"),
    # or one of its creatures it rolled for (Your creatures: "Vi (Homunculus Servant)"), only a creature on its sheet
    mine = {x["name"] for x in creatures.yours(chars.character_summary(ch))} if ch and who else set()
    who = (who if who in mine else ch.wild_shape or "")[:80] if ch else tok.name[:80] if tok else ("DM" if is_dm(user) else (me.name or "Someone").split()[0])
    row = TableRoll(campaign_id=campaign.id, character_id=ch.id if ch else None, user_id=me.id, label=label, kind=kind,
                    mode=mode, visibility=to, damage=damage, spec=spec, extras=rolled, who=who,
                    detail=detail_of(level, why if mode != "normal" else [], rider, hidden, via, own), **result)
    db.add(row)
    db.flush()
    if kind == "attack" and (flat := flat_damage(damage)) and row.kept != 1:  # (flat: on a hit it's just this, feedback 25)
        db.add(TableRoll(campaign_id=campaign.id, character_id=row.character_id, user_id=me.id, parent_id=row.id, kind="damage",
                         label=label, mode="normal", visibility=to, who=who, crit=row.kept == 20, extras=[], **flat))
        db.flush()
    from app import hiding

    death = death_mark(db, row) or hiding.mark(db, row)  # (a death save marks itself; a Hide roll of 15+ starts Hidden)
    realtime.announce(db, campaign.id, "rolls", **_live(db, row))  # every page at the table (app/realtime.py)
    if ch and kind == "check" and label == "Initiative":  # (askdnd runs the fight: the number lands in it, app/table_fight.py)
        from app import table_fight

        table_fight.rolled(db, campaign, ch, row.who if row.who and row.who != (ch.wild_shape or "") else "", row.total)
    also = _initiative(db, campaign, ch, me.id, row) if ch and kind == "check" and label == "Initiative" else []
    db.commit()
    db.refresh(row)
    out = reply_body(request, db, row, me.id, is_dm(user), death=death)
    if also:
        out["also"] = [reply_body(request, db, x, me.id, is_dm(user)) | {"who": x.who} for x in also]
    return JSONResponse(out)


def _initiative(db: Session, campaign, ch: Character, me_id: int, row: TableRoll) -> list[TableRoll]:
    """An Initiative roll, with Initiative from askdnd on (app/initiative.py): before Start Combat its number goes to
    the token in D&D Beyond's VTT, and a character's own also rolls for each of its familiars that are here (Brett,
    Nov 4: one press; each its own roll, as the rules have a familiar roll its own). Those rolls, made here."""
    from app import initiative

    creature = row.who if row.who and row.who != (ch.wild_shape or "") else ""
    initiative.rolled(db, campaign, ch, creature, row.total)
    if creature:
        return []
    made = []
    for name, mod in initiative.familiars(db, campaign, ch):
        r = roll_d20(mod, "normal")
        x = TableRoll(campaign_id=campaign.id, character_id=ch.id, user_id=me_id, label="Initiative", kind="check", mode="normal",
                      visibility=row.visibility, damage="", spec=None, extras=[], who=name[:80], parts=[],
                      **{k: r[k] for k in ("dice", "kept", "modifier", "total", "formula")})
        db.add(x)
        db.flush()
        realtime.announce(db, campaign.id, "rolls", **_live(db, x))
        initiative.rolled(db, campaign, ch, name, x.total)
        made.append(x)
    return made


def _follow_up(request, db, campaign_id, me_id, dm, parent_id, action, label, extras, die_size):
    root = db.get(TableRoll, parent_id)
    if not root or root.campaign_id != campaign_id or root.user_id != me_id or root.parent_id is not None:
        return _error("That roll isn't yours to follow up.", 403)
    kids = {k.kind: k for k in _kids(db, [root])}
    eff = kids.get("reroll") or root
    base = {"campaign_id": campaign_id, "character_id": root.character_id, "user_id": me_id, "parent_id": root.id,
            "visibility": root.visibility, "who": root.who}
    if action == "damage":
        rays = [x for x in root.parts or [] if x.get("kept") is not None]
        if root.kind != "attack" or not (root.damage or root.spec) or "damage" in kids or (eff.kept == 1 and not rays):
            return _error("That attack has no damage to roll.", 409)
        if rays:  # a damage roll for each ray that isn't a natural 1, doubled where it was a 20
            hits = [x for x in rays if x["kept"] != 1]
            if not hits:
                return _error("Every attack rolled a 1: no damage.", 409)
            result = roll_parts(root.spec["parts"], crits=[x["kept"] == 20 for x in hits])
            for line, ray in zip(result["parts"], [r for r in hits for _ in root.spec["parts"]]):
                line["label"] = ray["label"]
            crit = any(x["kept"] == 20 for x in hits)
            rolled = []
            for ray in hits:  # extra dice (Hunter's Mark…) on each hit
                rolled += [{**x, "label": f"{ray['label']} · {x['label']}"} for x in roll_extras(extras, ray["kept"] == 20)]
        else:
            crit = eff.kept == 20
            result = roll_parts(root.spec["parts"], crits=[crit]) if root.spec else roll_formula(root.damage, crit)
            rolled = roll_extras(extras, crit)
        result["total"] = max(result["total"] + sum(x["total"] for x in rolled), 0)
        row = TableRoll(**base, kind="damage", label=root.label, mode="normal", crit=crit, extras=rolled, **result)
        root.detail = {**(root.detail or {}), "outcome": "hit"}  # (its damage rolled: it hit)
    elif action == "reroll":
        if root.kind not in D20_KINDS or "reroll" in kids or damage_rolled(kids.get("damage")) or label not in REROLLS or root.parts:
            return _error("That roll can't be rerolled now.", 409)
        dice = list(root.dice)
        dice[dice.index(root.kept)] = die(20)  # the die that counted
        kept = max(dice) if root.mode == "adv" else min(dice) if root.mode == "dis" else dice[0]
        total = kept + root.modifier + sum(x["total"] for x in root.extras or [])
        row = TableRoll(**base, kind="reroll", label=label, mode=root.mode, dice=dice, kept=kept, modifier=root.modifier,
                        total=total, formula=root.formula, extras=list(root.extras or []))
    elif action == "bonus":
        # One die (die_size), or dice a feature adds after the roll (`extra`: Favored by the Gods' 2d4; the roll card, Nov 9)
        if root.kind not in D20_KINDS or "bonus" in kids or damage_rolled(kids.get("damage")) or (die_size not in BONUS_DICE and not extras):
            return _error("That die can't be added now.", 409)
        if extras:
            got = roll_extras(extras)
            dice, n, formula = [d for x in got for d in x["dice"]], sum(x["total"] for x in got), " ".join(x["formula"] for x in got).lstrip("+")
            label = label or extras[0][0]
        else:
            n = die(die_size)
            dice, formula = [n], f"1d{die_size}"
        row = TableRoll(**base, kind="bonus", label=(" ".join(label.split())[:40] or "Added die"), mode="normal",
                        dice=dice, kept=None, modifier=0, total=n, formula=formula, extras=[])
    else:
        return _error("That roll is missing something.")
    db.add(row)
    db.flush()
    death = death_mark(db, root) if action != "damage" else None
    realtime.announce(db, campaign_id, "rolls", **_live(db, root))
    db.commit()
    db.refresh(root)
    return _reply(request, db, root, me_id, dm, new=row, death=death)


@router.post("/rolls/{roll_id:int}/outcome")
def roll_outcome(request: Request, roll_id: int, outcome: str = Form(""), db: Session = Depends(get_db)):
    """An attack's outcome when no damage follows (the roll card's Missed): kept with the roll, by whoever rolled it."""
    user = current_user(request)
    me = picks.user_row(db, user) if user else None
    row = db.get(TableRoll, roll_id)
    if me is None or row is None or row.user_id != me.id or row.parent_id is not None or row.kind != "attack":
        return _error("That roll isn't yours.", 404)
    if outcome not in ("hit", "miss"):
        return _error("Hit or miss.")
    row.detail = {**(row.detail or {}), "outcome": outcome}
    realtime.announce(db, row.campaign_id, "rolls", changed=row.id)  # (no new row: every page asks for this one again)
    db.commit()
    return Response(status_code=204)


@router.get("/rolls/checks")
def checks(request: Request, db: Session = Depends(get_db)):
    """Table rolls' Roll window (Brett chose A, Nov 10, docs/mockups/roll-kinds/): your own character's ability checks,
    saves and skills by ability, Initiative, a Death save, a Hit Die, and Any dice; for anyone without a character (the
    DM), Any dice alone; and a Your dice tab (Brett, Nov 10)."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    from app import dice  # (Your dice, the window's second tab)

    ch = picks.my_character(db, user)
    sheet = chars.character_summary(ch) if ch else None
    return templates.TemplateResponse(request, "_roll_checks.html", {"c": ch, "s": sheet, "ctx": roll_context(sheet), "dm": is_dm(user),
                                                                     "d": dice.prefs(picks.user_row(db, user)), "sets": dice.SETS, "materials": dice.MATERIALS})
