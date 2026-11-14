"""DM Tools and the campaign's homebrew items (Brett chose 1B, 2A, 3A, Nov 13; docs/mockups/homebrew-items/).

**DM Tools** (`/c/<campaign>/dm`): the things a DM makes, in a page of its own with its own door in the menu bar
beside Manage, for whoever sets the campaign's house rules (its DM and admins; app/access.py "house_rules"). Items
first; the other kinds (shops, creatures, encounters, loot, handouts) are listed as planned until they're built.

**A homebrew item** is one of the campaign's own magic items (models.CampaignContent, kind "magic_item", source
"Homebrew"; app/rules_data.py reads it with the books): its book fields and its words, then **what it does in play**,
made from what askdnd already plays: a roll (a recipe's `rolls`), a bonus to another roll (`adds`), charges (said, as
D&D Beyond keeps them). It plays for any character who carries an item of that name (a custom item on the D&D Beyond
sheet, as the Beasty Bone is today): Battle's row rolls its plan, the roll card offers its bonus, through the same code
as a book's item (`roll_recipes.item_for`, `rules_book.active`). Giving one to a character from here, onto D&D
Beyond's sheet as a custom item (2A), is the next slice. Players find them only once the DM gives one (3A): they're in
no list players see.
"""

import re
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rules_data, web
from app.auth import can_set_house_rules
from app.db import get_db
from app.models import CampaignContent
from app.templating import templates

router = APIRouter()

KIND = "magic_item"
SOURCE = "Homebrew"
CATEGORIES = rules_data.ITEM_CATEGORIES
RARITIES = ("Common", "Uncommon", "Rare", "Very Rare", "Legendary", "Artifact")
RESOLVE = {"none": "No roll to hit or save", "attack": "An attack roll", "save": "A saving throw"}
EFFECT = {"damage": "Damage", "heal": "Healing", "temp": "Temporary Hit Points", "dice": "Just dice"}
SAVES = ("Str", "Dex", "Con", "Int", "Wis", "Cha")
WHEN = {"before": "Before the roll", "on_hit": "On a hit", "on_damage": "To its damage", "after_fail": "After a failure"}
TO = {"attack": "Attack rolls", "save": "Saving throws", "check": "Ability checks", "damage": "Damage"}
BACK = ("", "dawn", "a Long Rest", "a Short or Long Rest")
MAX_ROLLS, MAX_ADDS = 3, 3
# What else a DM makes (Brett's question on the mockup, Nov 13): listed as planned until each is built
PLANNED = [("shops", "Shops", "What's for sale, at what price"), ("creatures", "Creatures", "A homebrew monster's stat block"),
           ("encounters", "Encounters", "A fight prepared ahead: its creatures, a place, where they stand"),
           ("loot", "Loot", "What a fight or a chest gives, coins included"),
           ("handouts", "Handouts", "A letter, a picture, a map, shown to the table when found")]
CACHE_SECONDS = 10
_cache: dict = {"at": 0.0, "rows": {}}
DICE = re.compile(r"^\s*(\d*d\d+|\d+)(\s*[+-]\s*\d+)?(\s+[a-zA-Z]+)?\s*$")


# ------------------------------------------------------------------ the engine's side


def norm(name: str) -> str:
    return " ".join((name or "").replace("’", "'").lower().split())


def invalidate() -> None:
    _cache["at"] = 0.0


def _load(db: Session) -> dict:
    out: dict = {}
    for row in db.scalars(select(CampaignContent).where(CampaignContent.kind == KIND, CampaignContent.source == SOURCE)):
        data = row.data or {}
        if data.get("retired"):
            continue
        e = book_entry(row.name, data)
        if e:
            out.setdefault(row.campaign_id, {})[norm(row.name)] = e
    return out


def for_campaign(db: Session, campaign_id: int | None) -> dict[str, dict]:
    """{normalized name: the item as a rules-book entry} for the campaign's homebrew items that do something in play."""
    if campaign_id is None:
        return {}
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        try:
            _cache["rows"] = _load(db)
        except Exception:
            pass  # (the database unavailable: the last copy; a book's items still play)
        _cache["at"] = time.monotonic()
    return _cache["rows"].get(campaign_id) or {}


def book_entry(name: str, data: dict) -> dict | None:
    """A homebrew item as app/data/rules' items are (kind item, its rolls and adds), or None when it does nothing in play."""
    play = data.get("play") or {}
    rolls = [r for r in play.get("rolls") or [] if r.get("dice")]
    adds = [a for a in play.get("adds") or [] if a.get("amount")]
    if not rolls and not adds:
        return None
    return {"kind": "item", "name": name, "homebrew": True, **({"rolls": rolls} if rolls else {}),
            **({"adds": [{**a, "name": a.get("name") or name} for a in adds]} if adds else {})}


# ------------------------------------------------------------------ the form


def _clean(s, n: int = 200) -> str:
    return " ".join(str(s or "").split())[:n]


def from_form(form) -> tuple[dict, list[str]]:
    """The entry a DM Tools item form describes, and what's wrong with it (nothing saved while there's anything)."""
    get = lambda k: _clean(form.get(k))
    errors = []
    name = get("name")[:80]
    if not name:
        errors.append("Give it a name.")
    entry = {"name": name, "category": get("category") if get("category") in CATEGORIES else "Wondrous Item",
             "rarity": get("rarity") if get("rarity") in RARITIES else "Uncommon", "attunement": bool(form.get("attunement")),
             "text": str(form.get("text") or "").strip()[:4000] or "A homebrew item.", "cost": get("cost")[:40], "weight": get("weight")[:40],
             "play": {}}
    rolls, adds = [], []
    for i in range(MAX_ROLLS):
        dice = get(f"roll{i}_dice")[:40]
        if not dice:
            continue
        if not DICE.match(dice):
            errors.append(f"Roll {i + 1}: write its dice like 2d6 force, 1d8+2 or 5.")
            continue
        r = {"name": get(f"roll{i}_name")[:60] or name, "resolve": get(f"roll{i}_resolve") if get(f"roll{i}_resolve") in RESOLVE else "none",
             "effect": get(f"roll{i}_effect") if get(f"roll{i}_effect") in EFFECT else "damage", "dice": [dice]}
        if r["resolve"] == "save":
            dc = get(f"roll{i}_dc")
            if get(f"roll{i}_save") not in SAVES or not dc.isdigit() or not 1 <= int(dc) <= 30:
                errors.append(f"Roll {i + 1}: a saving throw needs its ability and DC.")
                continue
            r |= {"save": get(f"roll{i}_save"), "dc": int(dc), "success": "half" if form.get(f"roll{i}_half") else "none"}
            if r["effect"] not in ("damage",):
                r["effect"] = "damage"
        if r["resolve"] == "attack":
            r["effect"] = "damage"
        if note := get(f"roll{i}_note")[:160]:
            r["note"] = note
        rolls.append(r)
    for i in range(MAX_ADDS):
        amount = get(f"add{i}_amount")[:30]
        if not amount:
            continue
        if not DICE.match(amount.lstrip("+")):
            errors.append(f"Bonus {i + 1}: write it like +1, 1d4 or 2d6 fire.")
            continue
        when, to = get(f"add{i}_when"), get(f"add{i}_to")
        a = {"name": get(f"add{i}_name")[:60] or name, "when": when if when in WHEN else "before", "to": [to if to in TO else "attack"],
             "amount": amount.lstrip("+"), "pressed": False}
        if a["when"] in ("on_hit", "on_damage"):
            a["to"] = ["damage"]
        if form.get(f"add{i}_this"):
            a["with"] = ["this_item"]
        if says := get(f"add{i}_says")[:120]:
            a["says"] = says
        adds.append(a)
    charges = get("charges")
    if charges:
        if not charges.isdigit() or not 1 <= int(charges) <= 50:
            errors.append("Charges: a number from 1 to 50.")
        else:
            entry["play"]["charges"] = {"count": int(charges), "back": get("charges_back") if get("charges_back") in BACK else "",
                                        "regain": get("charges_regain")[:20]}
    if rolls:
        entry["play"]["rolls"] = rolls
    if adds:
        entry["play"]["adds"] = adds
    return entry, errors


def says(data: dict) -> list[str]:
    """What it does in play, in short lines for the list and the form's heading."""
    play, out = data.get("play") or {}, []
    for r in play.get("rolls") or []:
        what = {"attack": "an attack: ", "save": f"{r.get('save')} save DC {r.get('dc')}: "}.get(r.get("resolve"), "")
        out.append(f"{r.get('name')}: {what}{' + '.join(r.get('dice') or [])}" + ({"heal": " healing", "temp": " Temporary Hit Points"}.get(r.get("effect"), "")))
    for a in play.get("adds") or []:
        out.append(f"{a.get('name')}: +{a.get('amount')} {WHEN.get(a.get('when'), '').lower()}" + (" (with this item)" if "this_item" in (a.get("with") or []) else ""))
    if c := play.get("charges"):
        out.append(f"{c['count']} charges" + (f", back at {c['back']}" if c.get("back") else "") + (f" ({c['regain']})" if c.get("regain") else ""))
    return out


# ------------------------------------------------------------------ pages


DENIED = "DM Tools is for the campaign's DM (and admins)."


def _allowed(request: Request, db: Session):
    """(user, campaign, None), or (None, None, the sign-in redirect or the 403 page)."""
    campaign = web.campaign(db)
    user, denied = web.require(request, lambda u: can_make(u, campaign), DENIED)
    return user, campaign, denied


def can_make(user: dict | None, campaign) -> bool:
    """Whoever sets the campaign's house rules makes its homebrew (its DM, admins): `house_rules` in app/access.py."""
    return bool(campaign) and can_set_house_rules(user, campaign.id)


def rows_for(db: Session, campaign_id: int) -> list[CampaignContent]:
    """The campaign's homebrew items, retired ones too (their data says so)."""
    return _rows(db, campaign_id)


def _rows(db: Session, campaign_id: int) -> list[CampaignContent]:
    return list(db.scalars(select(CampaignContent).where(CampaignContent.campaign_id == campaign_id, CampaignContent.kind == KIND,
                                                         CampaignContent.source == SOURCE).order_by(CampaignContent.name)))


def _carried(db: Session, campaign_id: int) -> dict[str, list[str]]:
    """{normalized item name: the characters at the table carrying one} (the list says who has each)."""
    from app import characters as chars
    from app.models import CampaignCharacter, Character

    out: dict[str, list[str]] = {}
    rows = db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                      .where(CampaignCharacter.campaign_id == campaign_id, CampaignCharacter.left_on.is_(None), Character.copy_of_id.is_(None)))
    for ch in rows.unique():
        for it in (chars.character_summary(ch) or {}).get("inventory") or []:
            for n in {norm(it.get("name") or ""), norm(it.get("base_name") or "")} - {""}:
                if ch.name not in out.setdefault(n, []):
                    out[n].append(ch.name)
    return out


def _customs(db: Session, campaign_id: int, made: set[str]) -> list[dict]:
    """Custom items on the table's D&D Beyond sheets that aren't homebrew items yet (the Beasty Bone): a start for one."""
    from app import characters as chars
    from app.models import CampaignCharacter, Character

    out, seen = [], set(made)
    rows = db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                      .where(CampaignCharacter.campaign_id == campaign_id, CampaignCharacter.left_on.is_(None), Character.copy_of_id.is_(None)))
    for ch in rows.unique():
        for it in (chars.character_summary(ch) or {}).get("inventory") or []:
            if it.get("custom") and (n := norm(it.get("name") or "")) and n not in seen:
                seen.add(n)
                out.append({"name": it["name"], "who": ch.name})
    return out


@router.get("/dm", response_class=HTMLResponse)
def dm_tools(request: Request, db: Session = Depends(get_db)):
    user, campaign, denied = _allowed(request, db)
    if denied:
        return denied
    rows = _rows(db, campaign.id)
    carried = _carried(db, campaign.id)
    items = [{"key": r.key, "name": r.name, "data": r.data or {}, "says": says(r.data or {}), "who": carried.get(norm(r.name), []),
              "retired": bool((r.data or {}).get("retired"))} for r in rows]
    return templates.TemplateResponse(request, "dm_tools.html", {
        "user": user, "items": [i for i in items if not i["retired"]], "retired": [i for i in items if i["retired"]],
        "customs": _customs(db, campaign.id, {norm(r.name) for r in rows}), "planned": PLANNED,
        "toast": request.session.pop("toast", None)})


def _form_page(request: Request, user, item: dict, key: str = "", errors: list[str] | None = None, status: int = 200):
    play = item.get("play") or {}
    return templates.TemplateResponse(request, "dm_item.html", {
        "user": user, "item": item, "key": key, "errors": errors or [], "rolls": (play.get("rolls") or []) + [{}] * (MAX_ROLLS - len(play.get("rolls") or [])),
        "adds": (play.get("adds") or []) + [{}] * (MAX_ADDS - len(play.get("adds") or [])), "charges": play.get("charges") or {},
        "categories": CATEGORIES, "rarities": RARITIES, "resolve": RESOLVE, "effect": EFFECT, "saves": SAVES, "when": WHEN, "to": TO,
        "back": BACK}, status_code=status)


@router.get("/dm/items/new", response_class=HTMLResponse)
def new_item(request: Request, name: str = "", db: Session = Depends(get_db)):
    user, campaign, denied = _allowed(request, db)
    if denied:
        return denied
    return _form_page(request, user, {"name": _clean(name)[:80], "category": "Wondrous Item", "rarity": "Uncommon"})


@router.get("/dm/items/{key}", response_class=HTMLResponse)
def edit_item(request: Request, key: str, db: Session = Depends(get_db)):
    user, campaign, denied = _allowed(request, db)
    if denied:
        return denied
    row = _row(db, campaign.id, key)
    if row is None:
        return web.not_found(request, "There's no homebrew item by that name.")
    return _form_page(request, user, {"name": row.name, **(row.data or {})}, key=row.key)


def _row(db: Session, campaign_id: int, key: str) -> CampaignContent | None:
    return db.scalar(select(CampaignContent).where(CampaignContent.campaign_id == campaign_id, CampaignContent.kind == KIND,
                                                   CampaignContent.source == SOURCE, CampaignContent.key == key))


@router.post("/dm/items")
def save_item(request: Request, form=web.FormBody, db: Session = Depends(get_db)):
    """Make or change a homebrew item (`key`: the one being changed; renaming keeps it the same item)."""
    user, campaign, denied = _allowed(request, db)
    if denied:
        return denied
    entry, errors = from_form(form)
    key = _clean(form.get("key"))[:120]
    old = _row(db, campaign.id, key) if key else None
    if key and old is None:
        return web.not_found(request, "There's no homebrew item by that name.")
    clash = _row(db, campaign.id, rules_data.slug(entry["name"]))
    if clash is not None and clash is not old:
        errors.append(f"There's already a homebrew item called {clash.name}.")
    if errors:
        return _form_page(request, user, entry, key=key, errors=errors, status=422)
    if old is not None and old.key != rules_data.slug(entry["name"]):
        db.delete(old)  # (renamed: saved again under its new name)
        db.flush()
    from app import picks

    me = picks.user_row(db, user)
    try:
        rules_data.save(db, campaign.id, KIND, {**entry, "retired": False}, source=SOURCE, user_id=me.id if me else None)
    except ValueError as e:
        return _form_page(request, user, entry, key=key, errors=[f"askdnd couldn't keep it: {e}"], status=422)
    db.commit()
    invalidate()
    request.session["toast"] = web.notice(f"Saved: {entry['name']}")
    return RedirectResponse(web.base() + "/dm", status_code=303)


@router.post("/dm/items/{key}/retire")
def retire_item(request: Request, key: str, db: Session = Depends(get_db)):
    """Retire a homebrew item (it stops playing; kept, with Bring back), or bring a retired one back."""
    user, campaign, denied = _allowed(request, db)
    if denied:
        return denied
    row = _row(db, campaign.id, key)
    if row is None:
        return web.not_found(request, "There's no homebrew item by that name.")
    row.data = {**(row.data or {}), "retired": not (row.data or {}).get("retired")}
    db.commit()
    invalidate()
    request.session["toast"] = web.notice(f"{'Retired' if row.data['retired'] else 'Back in play'}: {row.name}")
    return RedirectResponse(web.base() + "/dm", status_code=303)
