"""Creatures in the side panel (askdnd's table, slice 3; docs/plans/2026-11-06-table-build-plan.md, docs/mockups/
table-slices/ Creatures): pressing a creature's token opens its stat block from the campaign's books or the SRD, the
first thing D&D Beyond's users ask for (the stat block beside the order, its Hit Points, its rolls).

For the DM: its Hit Points with − and + and a box to type in, Bloodied at half, what players see of it, its abilities,
saves and senses, and each action as a row with its roll (to hit, then damage; a save's DC), rolled in askdnd's Table
rolls as the creature (only the DM sees it unless she picks otherwise), damage offering Apply to as today. Hide, Show,
Rename and Take off the map. Players get only its name, size, kind and what the battle settings let them see.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import creatures, places, rules_data, table_fight, tokens
from app import wild_shape as ws
from app.db import get_db
from app.models import Place, Token
from app.templating import templates

router = APIRouter()

COSTS = (("Action", "actions"), ("Bonus action", "bonus_actions"), ("Reaction", "reactions"), ("Legendary", "legendary_actions"))


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{-n}"


def card(entry: dict) -> dict:
    """A stat block as the side panel draws it: its numbers, and each action as a row with its roll."""
    scores = entry.get("abilities") or {}
    saves = entry.get("saves") or {}
    abilities = [{"short": short, "score": scores.get(k, 10), "mod": _signed((scores.get(k, 10) - 10) // 2),
                  "save": _signed(saves.get(k, (scores.get(k, 10) - 10) // 2))} for k, _, short in ws.ABILITIES]
    cols = []
    for cost, key in COSTS:
        rows = [ws._entry({**e, "text": creatures.modern(e["text"])}, cost, {}) for e in entry.get(key) or []]
        if rows:
            cols.append({"cost": cost, "rows": rows, "intro": entry.get("legendary_uses") if key == "legendary_actions" else ""})
    return {"name": entry["name"], "size": entry.get("size") or "", "type": entry.get("type") or "", "ac": entry.get("ac"),
            "hp": entry.get("hp"), "hit_dice": entry.get("hit_dice") or "", "speed": ws.speed_text(entry.get("speed") or {}),
            "initiative": _signed(entry["initiative"]) if isinstance(entry.get("initiative"), int) else "",
            "abilities": abilities, "skills": ", ".join(f"{k} {_signed(v)}" for k, v in (entry.get("skills") or {}).items()),
            "senses": ws.senses_text(entry), "passive": entry.get("passive_perception"), "languages": entry.get("languages") or "",
            "resist": ", ".join(entry.get("resistances") or []), "immune": ", ".join(entry.get("immunities") or []),
            "vulnerable": ", ".join(entry.get("vulnerabilities") or []),
            "cond_immune": ", ".join(entry.get("condition_immunities") or []), "cr": entry.get("cr_label") or "",
            "source": entry.get("source") or "", "traits": entry.get("traits") or [], "columns": cols}


@router.get("/table/tokens/{token_id:int}")
def token_panel(request: Request, token_id: int, db: Session = Depends(get_db)):
    """A creature's token in the side panel: the DM's stat block, or what players may see of it."""
    user, campaign = places.here(request, db, need_runs=False)
    t = db.get(Token, token_id)
    dm = places.runs(user, campaign)
    if t is None or t.campaign_id != campaign.id or (not dm and (t.place_id != campaign.shown_place_id
                                                                  or not tokens.visible(db.get(Place, t.place_id), t, False))):
        raise HTTPException(404)  # (a player: only a creature they can see, on the place the DM shows)
    entry = rules_data.find("monster", (t.monster or {}).get("key", ""), db, campaign.id) if t.kind == "monster" else None
    s = table_fight.settings(campaign)
    f = table_fight.ours(campaign) and campaign.fight
    now = bool(f) and any(x.get("token") == t.id and x.get("active") for x in f.get("order") or [])
    return templates.TemplateResponse(request, "_token_panel.html", {
        "t": t, "dm": dm, "k": card(entry) if entry and dm else None, "entry": entry, "status": tokens.status(t.hp),
        "players_see": s["enemy_hp"], "its_turn": now,
        "seen": None if dm else ({"numbers": t.hp, "status": tokens.status(t.hp), "none": None}[s["enemy_hp"]])})
