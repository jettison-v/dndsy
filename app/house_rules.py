"""House rules: a campaign's own rulings on top of the tool's knowledge (data organization step 3).

The effective value of anything askdnd knows is worked out in three layers, most specific last:

1. tool knowledge, in the code (app/data/roll_recipes.json, rules terms, class rules);
2. tool corrections (tool_corrections): an admin fixing how askdnd reads D&D Beyond, for everyone;
3. house rules (house_rules): the DM's ruling, for their campaign only.

A house rule is a row that points at what it changes (a spell's recipe, by name) and never edits it, so removing
the row brings the tool's value back. What a house rule can change is listed in FIELDS.

Rules are read on every character page, so they're cached in memory for a few seconds and reloaded after any
change on Manage › House rules (like app/access.py). Without a campaign id, the rules of the campaign the person
asking is in apply.
"""

import copy
import re
import time
from collections.abc import Callable

from sqlalchemy import select

from app import roll_recipes as rr

# What a house rule on a spell can change: (field, label on Manage › House rules)
FIELDS = {
    "once": "One roll for all",       # every dart (or other instance) deals the same rolled damage
    "note": "A ruling",               # a short note shown in the roll window
}
CACHE_SECONDS = 10


def _load_from_db() -> dict:
    from app.db import SessionLocal, engine

    if engine is None:
        return {}
    with SessionLocal() as db:
        return rows_from(db)


def rows_from(db) -> dict:
    """{campaign id: {(kind, key): {field: {"value", "reason", "by"}}}}."""
    from app.models import HouseRule

    out: dict = {}
    for r in db.scalars(select(HouseRule)):
        out.setdefault(r.campaign_id, {}).setdefault((r.target_kind, r.target_key), {})[r.field] = {
            "value": r.value, "reason": r.reason, "by": r.set_by}
    return out


loader: Callable[[], dict] = _load_from_db
_cache: dict = {"rows": {}, "at": 0.0}


def invalidate() -> None:
    _cache["at"] = 0.0


def rules(campaign_id: int | None = None) -> dict:
    """The campaign's house rules (the one the person asking is in now if none is given)."""
    if campaign_id is None:
        from app import access

        campaign_id = access.current_campaign_id()
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        try:
            _cache["rows"] = loader()
        except Exception:
            pass  # database unavailable: keep the last rules (none at first); the tool's knowledge still works
        _cache["at"] = time.monotonic()
    return _cache["rows"].get(campaign_id) or {}


def can_roll_once(recipe: dict | None) -> bool:
    """A recipe with several instances rolled on their own and no attack roll (Magic Missile's darts)."""
    return any((e.get("count") or 1) > 1 and e.get("on") != "hit" for e in (recipe or {}).get("events") or [])


def describe(field: str, value: str, recipe: dict | None = None) -> str:
    """A house rule in a few words, as the roll window and Manage › House rules show it."""
    if field == "once":
        each = next((e.get("count_label") for e in (recipe or {}).get("events") or [] if (e.get("count") or 1) > 1), "") or "instance"
        return f"One roll for all {each}s: every {each} deals the same damage"
    return value


def spell(name: str, campaign_id: int | None = None) -> dict | None:
    """The spell's recipe as it works at this table: the audited recipe with the campaign's house rules applied.
    The recipe carries "house_rules": [{"text", "reason", "by"}] so the roll window can say so."""
    base = rr.spell(name)
    if base is None:
        return None
    mine = {f: r for f, r in (rules(campaign_id).get(("spell", rr.spell_key(name))) or {}).items()
            if f in FIELDS and (f != "once" or can_roll_once(base))}
    if not mine:
        return base
    recipe = copy.deepcopy(base)
    if "once" in mine:
        for e in recipe["events"]:
            if (e.get("count") or 1) > 1 and e.get("on") != "hit":
                e["once"] = True
                # The recipe's own note may say the opposite ("Each dart is rolled on its own; aim them…")
                rest = re.sub(r"^Each \w+ is rolled on its own;?\s*", "", e.get("note") or "")
                e["note"] = rest[:1].upper() + rest[1:]
    recipe["house_rules"] = [{"text": describe(f, r["value"], base), "reason": r["reason"], "by": r["by"]} for f, r in mine.items()]
    return recipe


def sheet_overrides(db, campaign_id: int | None = None) -> dict[tuple[str, str], str]:
    """{(ref, field): value} for regrouping sheet items and rules terms: the tool corrections, then the campaign's
    house rules on the same thing (kind "sheet"), which win."""
    from app.models import ToolCorrection

    out = {(o.ref, o.field): o.value for o in db.scalars(select(ToolCorrection))}
    for (kind, key), fields in rules(campaign_id).items():
        if kind == "sheet":
            out.update({(key, f): r["value"] for f, r in fields.items()})
    return out
