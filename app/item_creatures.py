"""Items that bring a creature (Brett, Nov 9; docs/mockups/item-creatures/, he chose A and A): Trah's Beasty Bone, a
homebrew item, played like a familiar.

- **Set up once, by the DM** (A): an item's words can't say everything (which beast?), so the campaign's DM (or an admin)
  tells askdnd in the item's side panel, under Correct this: a campaign correction (a house rule of kind "sheet", field
  "brings", listed on Manage › House rules). askdnd fills in what the words do say (`read`); the DM checks it and picks
  the creature from the campaign's books, its own creations and the SRD (app/rules_data.py).
- **askdnd's own creature** (A), like Find Steed's (app/summons.py): kept on the character (`Character.companions`,
  "own", with the item's name), its Hit Points in askdnd, shown by Your creatures (Battle's switch by the name, its own
  Battle, Party's second half, the fight with its own Initiative). D&D Beyond's Extras isn't told.
- **Using it**: the item's row on Battle (its cost, from the setup) opens a window; Bring it keeps the creature, Undo
  takes it back. The item's player or the DM.
- **Commanding it**: a row in its master's column (a Bonus Action for the Beasty Bone), with the range.
- **Ending**: 0 Hit Points or Dismiss on its Battle; then the item is spent until the Long Rest, whose window lists it
  coming back (ticked: the DM may rule otherwise). askdnd never times the hour: its band says "up to 1 hour".

Inform, don't decide: the creature's turn is the DM's to run; askdnd keeps its numbers.
"""

import json
import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import creatures as cr
from app import ddb_bridge, hit_points, house_rules, rules_data, summons, web
from app.auth import can_set_house_rules, current_user
from app.db import get_db
from app.models import Character, HouseRule
from app.templating import templates

router = APIRouter()

FIELD = "brings"
COSTS = ("Action", "Bonus action", "Magic action")
COMMANDS = ("Bonus action", "Action", "")
BACK = ("Long Rest", "Short or Long Rest", "Dawn")
# What makes an item look like one that brings a creature (the side panel offers the setup then, or once it's set up)
LOOKS = re.compile(r"\b(?:creature|beast|animal|undead|figurine|statuette)\b[^.]*\b(?:under your control|you control|obeys?|command|summon|becomes|morphs|transforms)"
                   r"|\bsummons?\b", re.I)


# ------------------------------------------------------------------ the setup

def looks_like(it: dict) -> bool:
    return bool(LOOKS.search(it.get("text") or it.get("summary") or ""))


def read(text: str) -> dict:
    """What the item's own words say, as a setup to check: its cost, range, the creature's type and immunities, how it's
    commanded, its Initiative, how long it lasts and when it comes back. The creature itself is left for the DM."""
    t = " ".join((text or "").split())
    low = t.lower()
    cost = "Bonus action" if re.search(r"\bas a bonus action\b", low) else "Magic action" if "magic action" in low else "Action"
    rng = re.search(r"within (\d+) (?:feet|ft)", low)
    kind = re.search(r"(?:its )?creature type is (\w+)|\bbecomes? an? (\w+) creature|into an? (\w+) creature", low)
    kind_word = next((g for g in (kind.groups() if kind else ()) if g), "")
    immune = []
    m = re.search(r"immunity to ([^.;]+)", low)
    if m:
        for part in re.split(r",\s*|\s+and\s+", m.group(1)):
            part = part.strip().removeprefix("the ").strip()
            if part.endswith(" condition"):
                immune.append(part.removesuffix(" condition").strip().title())
            elif part:
                immune.append(part if "damage" in part else f"{part} damage")
    command = re.search(r"(bonus action|action) to command[^.]*?(?:within (\d+) (?:feet|ft))?", low) or \
        re.search(r"command[^.]*?(bonus action|action)", low)
    cmd_range = re.search(r"command[^.]*?within (\d+) (?:feet|ft)|within (\d+) (?:feet|ft)[^.]*command", low)
    lasts = []
    if (h := re.search(r"(?:lasts|for) (?:for )?(one|1|two|2|eight|8|ten|10|twenty-four|24) hours?", low)):
        lasts.append(f"{ {'one': '1', 'two': '2', 'eight': '8', 'ten': '10', 'twenty-four': '24'}.get(h.group(1), h.group(1))} hour"
                     + ("s" if h.group(1) not in ("one", "1") else ""))
    if re.search(r"(?:falls? to|drops? to|reduced to) 0 hit points", low):
        lasts.append("until 0 Hit Points")
    back = "Dawn" if "dawn" in low else "Short or Long Rest" if "short or long rest" in low else "Long Rest"
    return {"creature": "", "cost": cost, "range": int(rng.group(1)) if rng else 0, "type": kind_word.title(),
            "immune": ", ".join(immune), "init": "own" if "roll initiative" in low or "its own turn" in low else "shares",
            "command": ("Bonus action" if command and command.group(1) == "bonus action" else "Action") if command else "",
            "command_range": int(next((g for g in cmd_range.groups() if g), 0)) if cmd_range else 0,
            "lasts": " or ".join(lasts), "back": back}


def setup(sheet: dict | None, it: dict) -> dict | None:
    """The DM's setup for this item in this campaign, or None (not set up)."""
    raw = ((sheet or {}).get("_overrides") or {}).get(f"item:{it.get('base_name') or it['name']}|{FIELD}")
    try:
        cfg = json.loads(raw) if raw else None
    except ValueError:
        return None
    return cfg if isinstance(cfg, dict) and cfg.get("creature") else None


def until(cfg: dict | None) -> str:
    """When it comes back, in words: "a Long Rest", "a Short or Long Rest", "dawn"."""
    back = (cfg or {}).get("back") or "Long Rest"
    return "dawn" if back == "Dawn" else f"a {back}"


def describe(value: str) -> str:
    """The setup in a few words (Manage › House rules)."""
    try:
        cfg = json.loads(value)
    except ValueError:
        return value
    what = " ".join(x for x in (cfg.get("type"), cfg.get("creature")) if x) or "a creature"
    return f"Brings {what}" + (f", immune to {cfg['immune']}" if cfg.get("immune") else "") + f"; back after {until(cfg)}"


# ------------------------------------------------------------------ the creature

def _block(e: dict) -> dict:
    """A stat block from the rules data (app/rules_data.py monsters) in the shape Battle draws a creature's."""
    scores = e.get("abilities") or {}
    saves = [k for k, v in (e.get("saves") or {}).items() if v != (scores.get(k, 10) - 10) // 2]
    return {"name": e["name"], "size": e.get("size") or "", "ac": e.get("ac") or 10, "hp": e.get("hp") or 1, "hit_dice": e.get("hit_dice") or "",
            "speed": dict(e.get("speed") or {}), "abilities": dict(scores), "block_saves": saves, "block_skills": dict(e.get("skills") or {}),
            "condition_immunities": list(e.get("condition_immunities") or []), "saves": {}, "skills": {},
            "senses": dict(e.get("senses") or {}), "passive_perception": e.get("passive_perception") or 10,
            "traits": [dict(x) for x in e.get("traits") or []], "actions": [dict(x) for x in e.get("actions") or []],
            "bonus_actions": [dict(x) for x in e.get("bonus_actions") or []], "reactions": [dict(x) for x in e.get("reactions") or []],
            "source": e.get("source") or "", "cr": e.get("cr") or 0, "cr_label": e.get("cr_label") or ""}


def creature_id(it: dict) -> int:
    return summons.own_id(f"item:{it['key']}")


def creature(it: dict, cfg: dict, entry: dict, name: str = "") -> dict:
    """The creature this item brings, as askdnd keeps its own (the shape of one on a sheet's Extras)."""
    b = _block(entry)
    immune = [x.strip() for x in (cfg.get("immune") or "").split(",") if x.strip()]
    b["condition_immunities"] = sorted(set(b["condition_immunities"]) | {x for x in immune if "damage" not in x.lower()})
    changed = " ".join(x for x in (cfg.get("type") and f"{cfg['type']}", immune and f"immune to {', '.join(immune)}") if x)
    if changed:
        b["traits"] = [{"name": f"Changed by the {it['name']}", "text": (f"Its creature type is {cfg['type']}" if cfg.get("type") else "It keeps its creature type")
                        + (f"; it has immunity to {', '.join(immune)}" if immune else "") + "."}] + b["traits"]
    own_init = cfg.get("init") == "own"
    cmd = cfg.get("command") or ""
    turn = ("Its own turn: it rolls its own Initiative. " if own_init else "Right after its master's turn, sharing their Initiative. ") \
        + (f"Its master commands it with a {cmd.replace('action', 'Action')}" + (f" within {cfg['command_range']} feet" if cfg.get("command_range") else "")
           + "; it follows the command until it's done or told otherwise, and with none it defends itself." if cmd else "")
    kind = f"{cfg['type']} {entry['name']}" if cfg.get("type") and cfg["type"].lower() not in (entry.get("type") or "").lower() else entry["name"]
    return {"key": f"item:{it['key']}", "name": (name or "").strip()[:60] or entry["name"], "kind": entry["name"], "own": True,
            "spell": it["name"], "item": it["name"], "item_key": it["key"], "id": creature_id(it), "group_id": cr.SUMMONED,
            "group": "Summoned", "group_name": "Summoned", "level": None, "choice": "", "look": "", "concentration": False,
            "turn_text": turn, "own_initiative": own_init, "lasts": cfg.get("lasts") or "", "goes": "", "cr": "",
            "armor_class": b["ac"], "hit_points": b["hp"], "speed": b["speed"], "block": b, "removed": 0, "temp": 0, "active": True,
            "max_set": None, "picture": entry.get("picture") or "",
            "about": " · ".join(x for x in (kind, f"from the {it['name']}", entry.get("source") or "") if x)}


def state(ch: Character, it: dict) -> str:
    """"ready", "here" (the creature is here), or "spent" (it came and went: back after the item's rest)."""
    kept = (ch.companions or {}).get(str(creature_id(it))) or {}
    w = kept.get("state")
    return "ready" if not w else "here" if w == "here" else "spent"


# ------------------------------------------------------------------ on Battle

def options(ch: Character, sheet: dict) -> list[dict]:
    """The rows on Battle: each set-up item (its cost from the setup; Use opens the window) and, while its creature is
    here, Command it in its master's column."""
    out = []
    for it in sheet.get("inventory") or []:
        cfg = setup(sheet, it)
        if not cfg:
            continue
        st = state(ch, it)
        kept = ((ch.companions or {}).get(str(creature_id(it))) or {}).get("c") or {}
        name = kept.get("name") or cfg["creature"]
        cost = cfg.get("cost") if cfg.get("cost") in COSTS else "Action"
        col = "Action" if cost == "Magic action" else cost
        says = {"ready": f"Brings {' '.join(x for x in (cfg.get('type'), cfg['creature']) if x)}" + (f" within {cfg['range']} ft" if cfg.get("range") else "")
                + f" · back after {until(cfg)}",
                "here": f"{name} is here" + (f" · up to {cfg['lasts']}" if cfg.get("lasts") else ""),
                "spent": f"Spent · back after {until(cfg)}"}[st]
        out.append({"key": f"bring:{it['key']}", "kind": "item", "cost": col, "name": it["name"], "meta": says,
                    "text": it.get("text") or "", "summary": it.get("summary") or "", "common": True, "tags": [],
                    "bring": {"id": it["key"], "state": st, "verb": "Use"}})
        cmd = cfg.get("command") or ""
        if st == "here" and cmd:
            out.append({"key": f"bring:{it['key']}:command", "kind": "feature", "cost": cmd, "name": f"Command {name}",
                        "tags": [it["name"]], "common": True,
                        "meta": (f"Within {cfg['command_range']} ft · " if cfg.get("command_range") else "") + "it acts on its own turn",
                        "text": f"{name} does what you command (it moves and takes an action from its stat block) on its turn, and keeps at "
                                f"it until it's done or you command something else; with no command it defends itself ({it['name']})."})
    return out


def ready_again(ch: Character, sheet: dict, kind: str) -> list[str]:
    """The items a rest brings back (the Long Rest window lists them, ticked)."""
    out = []
    for it in sheet.get("inventory") or []:
        cfg = setup(sheet, it)
        back = (cfg or {}).get("back") or "Long Rest"
        if cfg and state(ch, it) != "ready" and (back == "Short or Long Rest" or (kind == "long" and back == "Long Rest")):
            out.append(it["name"])
    return out


def rest(ch: Character, sheet: dict, kind: str) -> list[str]:
    """A rest: each item it brings back is ready again (its creature, if still here, goes: the item's magic resets)."""
    names, now = ready_again(ch, sheet, kind), dict(ch.companions or {})
    for it in sheet.get("inventory") or []:
        if it["name"] in names:
            now.pop(str(creature_id(it)), None)
    if names:
        ch.companions = now
    return names


# ------------------------------------------------------------------ routes

KEY = re.compile(r"(?:item|custom):\d+")


def _load(db: Session, request: Request, character_id: int, key: str) -> tuple[Character, dict, dict, dict | None, dict]:
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or not ch or not hit_points.can_apply(db, user, ch):  # (its player, the DM, an admin)
        raise HTTPException(404)
    sheet = views.apply_overrides(ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}, house_rules.sheet_overrides(db, ch.campaign_id)) or {}
    it = next((x for x in sheet.get("inventory") or [] if x["key"] == key), None) if KEY.fullmatch(key) else None
    if it is None:
        raise HTTPException(404)
    return ch, user, sheet, setup(sheet, it), it


def _entry(db: Session, ch: Character, name: str) -> dict | None:
    return rules_data.find("monster", name, db, ch.campaign_id) if name else None


@router.get("/characters/{character_id:int}/bring/{key}")
def window(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """What the item's Use opens, in the roll window."""
    ch, _, sheet, cfg, it = _load(db, request, character_id, key)
    entry = _entry(db, ch, (cfg or {}).get("creature", ""))
    return templates.TemplateResponse(request, "_bring_window.html", {"c": ch, "it": it, "cfg": cfg, "state": state(ch, it), "until": until,
                                                                      "k": creature(it, cfg, entry) if cfg and entry else None})


@router.post("/characters/{character_id:int}/bring/{key}")
def bring(request: Request, character_id: int, key: str, name: str = Form(""), db: Session = Depends(get_db)):
    """Use it: the creature is here (askdnd's own), and the item is in use until it's spent."""
    ch, _, sheet, cfg, it = _load(db, request, character_id, key)
    if not cfg:
        raise HTTPException(409, f"The DM hasn't set up what the {it['name']} brings yet.")
    if state(ch, it) != "ready":
        raise HTTPException(409, f"The {it['name']} is " + ("in use." if state(ch, it) == "here" else f"spent until {until(cfg)}."))
    entry = _entry(db, ch, cfg["creature"])
    if entry is None:
        raise HTTPException(409, f"askdnd can't find a {cfg['creature']} in this campaign's books: the DM can pick another in the item's setup.")
    c = creature(it, cfg, entry, name)
    was = (ch.companions or {}).get(str(c["id"]))
    ch.companions = {**(ch.companions or {}), str(c["id"]): {"own": True, "state": "here", "c": {k: v for k, v in c.items() if k not in ("removed", "temp")},
                                                             "removed": 0, "temp": 0}}
    db.commit()
    said = f"{c['name']} is here (the {it['name']})" + (": it rolls its own Initiative" if c["own_initiative"] else "")
    return JSONResponse({"text": said, "undo": {"was": json.dumps(was) if was else ""}, "undoUrl": f"/characters/{ch.id}/bring/{key}/undo"})


@router.post("/characters/{character_id:int}/bring/{key}/undo")
def undo(request: Request, character_id: int, key: str, was: str = Form(""), db: Session = Depends(get_db)):
    """The corner card's Undo: as it was before."""
    ch, _, _, _, it = _load(db, request, character_id, key)
    now = dict(ch.companions or {})
    try:
        before = json.loads(was) if was else None
    except ValueError:
        before = None
    if isinstance(before, dict):
        now[str(creature_id(it))] = before
    else:
        now.pop(str(creature_id(it)), None)
    ch.companions = now
    db.commit()
    return JSONResponse({"text": f"{it['name']}: undone"})


@router.post("/characters/{character_id:int}/bring/{key}/dismiss")
def dismiss(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """Its master ends it early (or the hour is up): it goes, and the item is spent until its rest."""
    ch, _, _, cfg, it = _load(db, request, character_id, key)
    kept = (ch.companions or {}).get(str(creature_id(it))) or {}
    if kept.get("state") != "here":
        raise HTTPException(409, "It isn't here.")
    ch.companions = {**(ch.companions or {}), str(creature_id(it)): {**kept, "state": "gone", "why": "dismissed"}}
    db.commit()
    name = (kept.get("c") or {}).get("name") or "It"
    return HTMLResponse("", status_code=204, headers={"HX-Trigger": web.changed(ch, f"{name} goes: the {it['name']} is spent until {until(cfg)}")})


@router.post("/characters/{character_id:int}/bring/{key}/setup")
def save_setup(request: Request, character_id: int, key: str, form=web.FormBody, db: Session = Depends(get_db)):
    """The DM's setup (Correct this): a campaign correction on everything named like this item. An empty creature
    removes it."""
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or not ch or not can_set_house_rules(user, ch.campaign_id):
        raise HTTPException(403, "Only the DM or an admin can set up what an item brings.")
    sheet = chars.character_summary(ch) or {}
    it = next((x for x in sheet.get("inventory") or [] if x["key"] == key), None) if KEY.fullmatch(key) else None
    if it is None:
        raise HTTPException(404)
    oref = f"item:{it.get('base_name') or it['name']}"[:200]
    row = db.scalar(select(HouseRule).where(HouseRule.campaign_id == ch.campaign_id, HouseRule.target_kind == "sheet",
                                            HouseRule.target_key == oref, HouseRule.field == FIELD))
    name = " ".join(str(form.get("creature") or "").split())[:100]
    if not name:
        if row:
            db.delete(row)
        db.commit()
        house_rules.invalidate()
        return HTMLResponse("", status_code=204, headers={"HX-Trigger": web.changed(ch, f"{it['name']}: no longer set up")})
    entry = _entry(db, ch, name)
    if entry is None:
        raise HTTPException(409, f"No creature named {name} in this campaign's books or the SRD.")

    def num(k):
        v = str(form.get(k) or "").strip()
        return int(v) if v.isdigit() else 0
    cfg = {"creature": entry["name"], "cost": form.get("cost") if form.get("cost") in COSTS else "Action", "range": num("range"),
           "type": " ".join(str(form.get("type") or "").split())[:40], "immune": " ".join(str(form.get("immune") or "").split())[:200],
           "init": "own" if form.get("init") == "own" else "shares", "command": form.get("command") if form.get("command") in COMMANDS else "",
           "command_range": num("command_range"), "lasts": " ".join(str(form.get("lasts") or "").split())[:80],
           "back": form.get("back") if form.get("back") in BACK else "Long Rest"}
    value = json.dumps(cfg)
    if row:
        row.value = value
    else:
        db.add(HouseRule(campaign_id=ch.campaign_id, target_kind="sheet", target_key=oref, field=FIELD, value=value,
                         reason="What it brings", set_by=web.person_name(user)))
    db.commit()
    house_rules.invalidate()
    return HTMLResponse("", status_code=204, headers={"HX-Trigger": web.changed(ch, f"Saved for this campaign: the {it['name']} brings {describe(value)[7:]}")})
