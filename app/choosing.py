"""Changing spells and Wild Shape forms (Brett, Nov 16: the wide window, D on docs/mockups/changing-spells/): one
immersive window for every list a character changes on D&D Beyond (cantrips, prepared or learned spells, a Wizard's
spellbook, Wild Shape's known forms), built on the same list as Sheet › Spells and Sheet › Wild Shape, so every column,
filter and the search are there to decide with. Edit mode puts one button where the bookmark's neighbours are: Prepare
or Unprepare, Learn or Let go, Copy in.

What it keeps, by Brett's picks (docs/DECISIONS.md, Nov 16):
- **A tab per class** for two spellcasting classes, each with its own lists and rules; Make takes every class's changes.
- **Why you're changing** (after a Long Rest, a level in a class, just looking), set from where the window opened; each
  list's rule says Now or Not now for it.
- **Counts held, as D&D Beyond holds them**: no more prepared, known or learned than the number at your level (let one go
  first), here and on the server. **Swaps are never limited**: one past its 2024 rule (how many, or when) is warned
  about, never blocked; the DM rules.

The changes go through the bridge with D&D Beyond's own requests: `ddb_fields` "prep" (PUT spell/prepared), "learn"
(POST and DELETE spell, a cantrip, a learned spell, a spell copied into a spellbook) and "wildshape" (a creature in
group 13). One Make sends them together, letting go before adding (so the sheet never holds more than its number), and
one sealed Undo puts them all back.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import components, ddb_bridge, picks, rules_data, web
from app import spellbook as sb
from app import wild_shape as ws
from app.db import get_db
from app.inventory import _guard
from app.item_use import _sheet
from app.templating import templates

router = APIRouter()
LOOK = "look"

# When each list may change, by the 2024 Player's Handbook (checked against its text, Nov 15; board 1 of the mockup):
# (when: "rest" or "level", one at a time?, what you may do, and when: the rule line says them as one plain sentence,
# "Swap 1 when you gain a Druid level"; Brett, Nov 16: "one, when you gain a Druid level" was confusing). Said, never
# enforced.
CANTRIPS = {"Wizard": ("rest", True, "swap 1", "after a Long Rest")}
CANTRIPS_DEFAULT = ("level", True, "swap 1", "when you gain a {cls} level")
SPELLS = {"Cleric": ("rest", False, "change any", "after a Long Rest"), "Druid": ("rest", False, "change any", "after a Long Rest"),
          "Wizard": ("rest", False, "change any", "from your spellbook after a Long Rest"),
          "Paladin": ("rest", True, "swap 1", "after a Long Rest"), "Ranger": ("rest", True, "swap 1", "after a Long Rest")}
SPELLS_DEFAULT = ("level", True, "swap 1", "when you gain a {cls} level")
BOOK = ("level", False, "copy in 2 free", "on each Wizard level; a spell you find takes 2 hours and 50 GP a level (not taken from your purse)")
FORMS = ("rest", True, "swap 1", "after a Long Rest")


def _rule(table: dict, default: tuple, cls: str) -> tuple[str, bool, str, str]:
    when, one, may, words = table.get(cls, default)
    return when, one, may, words.format(cls=cls)


def _list(lid: str, cls: str, title: str, label: str, kind: str, rule: tuple, cap: int | None, add: str, drop: str) -> dict:
    when, one, may, words = rule
    return {"id": lid, "cls": cls, "title": title, "label": label, "kind": kind, "cap": cap or 0, "one": one, "may": may, "when": f"{may} {words}",
            "k": when, "occ": ["rest"] if when == "rest" else [f"level-{cls.lower()}"], "add": add, "drop": drop, "rows": [],
            "first": "let one go first" if drop == "Let go" else f"{drop.lower()} one first",  # (what a full count asks)
            "full": f"{'let one go' if drop == 'Let go' else drop.lower() + ' one'} to {add.lower()} another"}


def spell_lists(sheet: dict) -> list[dict]:
    """Each class with something to change: {"cls", "level", "lists"}, each list with its rows ({"sp", "on", "always"})."""
    tabs = []
    for b in sheet.get("spellbook") or []:
        cls, spells = b["class"], b.get("spells") or []
        lists = []
        cant = _list(f"{cls}:cantrips", cls, "Cantrips", f"{cls} cantrips", "learn", _rule(CANTRIPS, CANTRIPS_DEFAULT, cls),
                     b.get("cantrips_max"), "Learn", "Let go")
        for sp in spells:
            if not sp["level"] and (sp.get("learn") or sp["state"] == "always"):
                cant["rows"].append({"sp": sp, "on": sp["state"] in ("known", "always"), "always": sp["state"] == "always"})
        if any(not r["always"] for r in cant["rows"]):
            lists.append(cant)
        leveled = [sp for sp in spells if sp["level"]]
        if any(sp.get("prep") for sp in leveled):  # (a class that prepares from a list, or a Wizard from the book)
            prep = _list(f"{cls}:spells", cls, "Prepared", f"{cls} prepared spells", "prep", _rule(SPELLS, SPELLS_DEFAULT, cls),
                         b.get("prepared_max"), "Prepare", "Unprepare")
            prep["rows"] = [{"sp": sp, "on": sp["state"] in ("prepared", "always"), "always": sp["state"] == "always"}
                            for sp in leveled if sp.get("prep") or sp["state"] == "always"]
            lists.append(prep)
            if b.get("spellbook"):
                book = _list(f"{cls}:book", cls, "Spellbook", f"{cls} spellbook", "learn", BOOK, None, "Copy in", "Take out")
                book["rows"] = [{"sp": sp, "on": False, "always": False} for sp in leveled if sp.get("learn") and sp["state"] == "available"]
                if book["rows"]:
                    lists.append(book)
        elif b.get("learns") and any(sp.get("learn") for sp in leveled):  # (D&D Beyond has the class learning its spells)
            lrn = _list(f"{cls}:spells", cls, "Prepared", f"{cls} prepared spells", "learn", _rule(SPELLS, SPELLS_DEFAULT, cls),
                        b.get("prepared_max"), "Prepare", "Unprepare")
            lrn["rows"] = [{"sp": sp, "on": sp["state"] in ("prepared", "known", "always"), "always": sp["state"] == "always"}
                           for sp in leveled if sp.get("learn") or sp["state"] == "always"]
            lists.append(lrn)
        for L in lists:
            L["count"] = sum(1 for r in L["rows"] if r["on"] and not r["always"])
        if lists:
            tabs.append({"cls": cls, "level": b.get("level"), "lists": lists})
    return tabs


def _ids() -> dict[str, str]:
    """D&D Beyond's monster id for each Beast askdnd knows, by its key ("dire-wolf")."""
    return {k: str(v["ddb_id"]) for k, v in rules_data.pictures().items() if v.get("ddb_id")}


def form_lists(db: Session, ch, sheet: dict, fav: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Wild Shape's known forms as one list (a tab of its own), and the forms list's rows: every Beast Sheet › Wild Shape
    shows (with `fav`, the Shortlist: a Beast shortlisted but not yet allowed is listed, locked), each with what its
    button does (`pick`), or why it has none."""
    d = ws.druid(sheet)
    if not d:
        return [], []
    beasts = ws.beasts(db, ch.campaign_id)
    ids = _ids()
    known = {c["kind"].lower(): str(c["monster_id"]) for c in sheet.get("creatures") or []
             if c.get("group") == "Wild Shape form" and c.get("monster_id")}
    L = _list("Druid:forms", "Druid", "Known forms", "Known forms", "wildshape", FORMS, d["known"], "Learn", "Let go")
    forms = ws.forms(sheet, fav or set(), None, beasts)
    for f in forms:
        mid = known.get(f["name"].lower()) if f["known"] else ids.get((ws.catalog_beast(f["name"], beasts) or {}).get("key", ""))
        lock = "" if mid else ("Let it go on D&D Beyond" if f["known"] else "Learn it on D&D Beyond")
        if not f["known"] and f.get("why_not"):
            lock = f["why_not"]
        f["pick"] = {"id": f"{L['id']}|{mid or f['name']}", "list": L["id"], "on": bool(f["known"]), "always": False, "lock": lock, "cls": "Druid"}
        f["going"] = bool(mid) and (sheet.get("sync") or {}).get(f"wildshape:{mid}") in ("on", "failed")
        L["rows"].append({"mid": mid, "name": f["name"], "on": bool(f["known"]), "lock": lock})
    L["count"] = sum(1 for f in forms if f["known"])
    return [{"cls": "Druid", "level": d["level"], "lists": [L]}], forms


def occasions(tabs: list[dict]) -> list[tuple[str, str, str]]:
    """The reasons offered: (key, the chip's words, the words for a rule broken)."""
    return ([("rest", "After a Long Rest", "after a Long Rest")]
            + [(f"level-{t['cls'].lower()}", f"I gained a {t['cls']} level", f"on a {t['cls']} level") for t in tabs]
            + [(LOOK, "Just looking", "")])


def allows(tabs: list[dict], key: str) -> str:
    """What a reason lets this character change, in the words of each list's rule (the ask step's tiles; Brett chose B,
    Nov 16, docs/mockups/why-changing/): "Paladin prepared spells: swap 1" for After a Long Rest."""
    if key == LOOK:
        return "See the lists; nothing is marked Now."
    said = [f"{L['label']}: {L['may']}" for t in tabs for L in t["lists"] if key in L["occ"]]
    return " · ".join(said) if said else "Nothing changes now by the rules; you can still look."


def _meta(tabs: list[dict]) -> dict:
    return {L["id"]: {k: L[k] for k in ("cls", "label", "cap", "one", "when", "occ", "add", "drop", "first")} for t in tabs for L in t["lists"]}


def _spell_rows(sheet: dict, tabs: list[dict], ch) -> list[dict]:
    """The spell list's rows (Sheet's own entries), one per spell per list, each with its button (`pick`)."""
    rules = components.rules_for(ch.campaign_id)
    sync = sheet.get("sync") or {}
    out = []
    for t in tabs:
        for L in t["lists"]:
            for r in L["rows"]:
                sp = r["sp"]
                e = sb._entry(sp, sheet, 0) | {"state": sp["state"], "from": "", "source": t["cls"], "core": sp.get("core"), "book": sp.get("book") or ""}
                e["ready"] = r["on"]
                e["need"] = components.need(sp, sheet, rules)
                e["pick"] = {"id": f"{L['id']}|{sp['key']}", "list": L["id"], "on": r["on"], "always": r["always"], "lock": "", "cls": t["cls"]}
                ids = sp.get("prep") if L["kind"] == "prep" else sp.get("learn")
                e["going"] = bool(ids) and sync.get(f"{'prep' if L['kind'] == 'prep' else 'learn'}:{ids.get('cls')}:{ids.get('entry')}") in ("on", "failed")
                out.append(e)
    return sorted(out, key=lambda e: (e["level"], e["name"]))


def _window(request: Request, db: Session, character_id: int, what: str, cls: str, why: str):
    ch, user = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    noting = picks.can_see(user, ch)
    mine = picks.picks(db, ch, user) if noting else {"fav": [], "star": [], "remind": [], "notes": {}}
    if what == "forms":
        tabs, rows = form_lists(db, ch, sheet, set(mine.get("fav") or []))
    else:
        tabs = spell_lists(sheet)
        rows = _spell_rows(sheet, tabs, ch) if tabs else []
    if not tabs:
        raise HTTPException(404)
    occ = occasions(tabs)
    # No reason given (opened from Sheet): the window asks first (Brett chose B, Nov 16, docs/mockups/why-changing/);
    # from the Long Rest window or a level-up card the reason comes with it, and the list opens at once
    ask = why not in {k for k, _, _ in occ}
    why = LOOK if ask else why
    cls = cls if cls in {t["cls"] for t in tabs} else tabs[0]["cls"]
    groups = [g for g in sb.sheet_filter_groups(rows) if g["key"] not in ("prep", "from")] if what == "spells" else []
    url = f"/characters/{ch.id}/{'wild-shape/forms' if what == 'forms' else 'spells/prepare'}"
    return templates.TemplateResponse(request, "_change_window.html", {
        "c": ch, "what": what, "tabs": tabs, "cls": cls, "occasions": occ, "occ": why, "ask": ask, "rows": rows, "groups": groups,
        "allows": {k: allows(tabs, k) for k, _, _ in occ},
        "picks": {"fav": set(mine.get("fav") or []), "star": set(mine.get("star") or []), "remind": set(mine.get("remind") or []), "notes": mine.get("notes") or {}},
        "can_pick": noting, "meta": _meta(tabs), "url": url, "reachable": ddb_bridge.reachable(ch)})


@router.get("/characters/{character_id:int}/spells/prepare")
def spells_window(request: Request, character_id: int, cls: str = "", why: str = "", db: Session = Depends(get_db)):
    """Change spells: from Sheet › Spells, the Spell Book, the Long Rest window and the level-up card."""
    return _window(request, db, character_id, "spells", cls, why)


@router.get("/characters/{character_id:int}/wild-shape/forms")
def forms_window(request: Request, character_id: int, why: str = "", db: Session = Depends(get_db)):
    """Change forms: from Sheet › Wild Shape and the Long Rest window."""
    return _window(request, db, character_id, "forms", "", why)


def _send(db: Session, ch, kind: str, data: dict, name: str, on: bool) -> str:
    """One change through the bridge; what the corner card says of it."""
    if kind == "wildshape":
        ddb_bridge.add(db, ch, "set", {"field": f"wildshape:{data['mid']}", "value": 1 if on else 0},
                       f"{ch.name}: Wild Shape form {name} {'learned' if on else 'let go'}")
        return f"{name} {'learned' if on else 'let go'}"
    body = {**data, "value": on, "name": name}
    ddb_bridge.add(db, ch, "prepare" if kind == "prep" else "learn", body, f"{ch.name}: {ddb_bridge.describe('prepare' if kind == 'prep' else 'learn', body, {})}")
    if kind == "prep":
        return f"{name} {'prepared' if on else 'unprepared'}"
    return f"{name} {'learned' if on else 'let go'}"


def _said(ch, made: list[str]) -> str:
    return f"{ch.name}: {', '.join(made)}, on {'their' if len(made) > 1 else 'its'} way to D&D Beyond"


@router.post("/characters/{character_id:int}/spells/prepare")
@router.post("/characters/{character_id:int}/wild-shape/forms")
def make(request: Request, character_id: int, body=web.JsonBody, db: Session = Depends(get_db)):
    """Make the window's changes ({"changes": [{"id", "on"}]}), or Undo them ({"undo": what askdnd handed back})."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    body = body if isinstance(body, dict) else {}
    forms = request.url.path.endswith("/wild-shape/forms")
    if "undo" in body:
        return _undo(db, ch, body["undo"], request.url.path)
    wanted = body.get("changes")
    if not isinstance(wanted, list) or not wanted or len(wanted) > 80:
        raise HTTPException(409, "Nothing to change.")
    sheet = _sheet(db, ch)
    if forms:
        tabs, _ = form_lists(db, ch, sheet)
    else:
        tabs = spell_lists(sheet)
    lists = {L["id"]: L for t in tabs for L in t["lists"]}
    todo, gone = [], 0  # (list, kind, data, name, on); what's no longer there to change
    for w in wanted:
        if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not isinstance(w.get("on"), bool) or "|" not in w["id"]:
            raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
        lid, key = w["id"].split("|", 1)
        L = lists.get(lid)
        one = _one(L, key, w["on"]) if L else "gone"
        if one == "gone":
            gone += 1  # (changed on D&D Beyond meanwhile: one spell no longer fails the lot; review, Nov 2)
        elif one:
            todo.append(one)
    left = f"; {gone} can't be changed from askdnd now, left as {'they are' if gone > 1 else 'it is'}" if gone else ""
    if not todo:
        return {"text": "Nothing to change: D&D Beyond has it already" + left, "deliver": web.deliver_now(ch)}
    # Counts are held, as D&D Beyond holds them: never more than the list's number at this level
    for L in lists.values():
        if L["cap"]:
            after = L["count"] + sum(1 if t[4] else -1 for t in todo if t[0] is L)
            if after > L["cap"] and any(t[0] is L and t[4] for t in todo):
                raise HTTPException(409, f"{L['label']}: {after} of {L['cap']}; {L['first']}.")
    todo.sort(key=lambda t: t[4])  # (letting go first: the sheet never holds more than its number)
    made = [_send(db, ch, t[1], t[2], t[3], t[4]) for t in todo]
    db.commit()
    back = {"made": json.dumps([[t[1], t[2], t[3], not t[4]] for t in todo], sort_keys=True)}
    back["sig"] = web.seal(back, f"change:{ch.id}")
    return JSONResponse({"text": _said(ch, made) + left, "undo": back, "undoUrl": request.url.path, "deliver": web.deliver_now(ch)})


def _one(L: dict, key: str, on: bool):
    """(list, kind, what the bridge names, name, on) for one row of a list; None when it's so already; "gone" when it
    isn't a row that can change (changed on D&D Beyond meanwhile, always prepared, a locked form)."""
    if L["kind"] == "wildshape":
        row = next((r for r in L["rows"] if r["mid"] == key), None)
        if row is None or row["lock"]:
            return "gone"
        return None if row["on"] == on else (L, "wildshape", {"mid": row["mid"]}, row["name"], on)
    row = next((r for r in L["rows"] if r["sp"]["key"] == key), None)
    if row is None or row["always"]:
        return "gone"
    if row["on"] == on:
        return None
    sp = row["sp"]
    if L["kind"] == "prep":
        return (L, "prep", dict(sp["prep"]), sp["name"], on)
    return (L, "learn", dict(sp["learn"]), sp["name"], on)


def _undo(db: Session, ch, undo, path: str):
    """Put back exactly what a Make sent, from what askdnd sealed (a spell let go of isn't listed until D&D Beyond has it
    back, so the ids come from the seal, not the sheet)."""
    if not isinstance(undo, dict) or not web.sealed({"made": undo.get("made", "")}, f"change:{ch.id}", str(undo.get("sig", ""))):
        raise HTTPException(409, "That Undo isn't one askdnd gave.")
    try:
        made = json.loads(undo["made"])
    except (ValueError, TypeError):
        raise HTTPException(409, "That Undo isn't one askdnd gave.") from None
    made.sort(key=lambda m: m[3])
    said = [_send(db, ch, kind, data, name, on) for kind, data, name, on in made]
    db.commit()
    return JSONResponse({"text": _said(ch, said), "deliver": web.deliver_now(ch)})

