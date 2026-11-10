"""Search, like Spotlight (Brett chose A and A, Nov 9; docs/mockups/search/): one search for anything about your
character, from any page. The Search button in the menu bar, ⌘F or Ctrl+F (taking over the browser's find, which ⌘F
again gives back) or ⌘K opens a box in the middle; results come as you type, grouped by kind, the best highlighted.

`/search/index` is everything this person can find, once per page (app.js "Search" matches it as they type):

- **Your character**: Battle's own rows (`character_views.options`, as Battle draws them, with their roll plans and
  recipes), each with what Enter does (A): roll it (the roll card or window), Cast, Use, else its side panel. ⌘ Enter
  opens its side panel instead.
- **Checks, saves, skills**: what Table rolls' Roll finds (Enter rolls).
- **Rules**: the rule terms (app/rules_terms.py), their words shown in the box.
- **The story** (A: what everyone shares, not the party's characters): the World's entries a person may see (the
  Campaign page's own rule: published, or any for the DM, reviewers and admins, those marked hidden), and the
  published sessions.
- **Pages**: Story, Campaign, Party, Your notes, Help and the Manage pages this person can open.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import picks, web
from app.auth import can_edit_entries, current_user
from app.db import get_db
from app.models import Entity, Status

router = APIRouter()

KINDS = {"pc": "a character", "npc": "a person", "place": "a place", "faction": "a faction", "item": "an item", "quest": "a quest",
         "creature": "a creature", "event": "an event", "lore": "lore"}


def _words(*parts) -> str:
    return " ".join(str(p or "") for p in parts).lower()


ABILITY = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}


def character_rows(db: Session, user: dict) -> tuple[int | None, list[dict], dict]:
    """The person's own character's rows as Battle shows them now (in a Wild Shape form, the form's: its columns, saves,
    skills and Initiative), then its checks, saves and skills, with the roll context Battle's rows carry (the conditions'
    reasons and Hidden too, so a roll from Search on any page is the roll Battle makes)."""
    from app import table_rolls
    from app.character_pages import _view, form_now
    from app.conditions import roll_effects

    ch = picks.my_character(db, user)
    if ch is None:
        return None, [], {}
    ctx = _view(db, ch, user)
    sheet = ctx.get("sheet") or {}
    if not sheet:
        return ch.id, [], {}
    from app import character_views as views

    form = form_now(ctx, ch)
    mine = views.options(sheet, ctx["picks"]["star"])
    if form:  # (items stay, and what takes no action: Battle in a form, character_pages._battle_ctx)
        mine = [o for col in form["columns"].values() for o in col["all"]] + [o for o in mine if o["kind"] == "item" or o["cost"] == "No action"]
    out = []
    for o in mine:
        hit = str(o.get("hit") or "").replace("−", "-")
        panel = f"/characters/{ch.id}/detail?ref={quote(o['key'])}"
        row = {"g": "Your character", "n": o["name"], "s": " · ".join(x for x in (o.get("cost") or "", hit, o.get("meta") or "") if x)[:140],
               "find": _words(o["name"], o.get("cost"), " ".join(o.get("tags") or []), o.get("kind")), "panel": panel}
        first = next((p for p in views.option_rolls(o) if p["button"]), None)  # (Battle's own roll button: its first)
        if o.get("cast") and ctx.get("can_play"):
            row |= {"a": "Cast", "use": f"/characters/{ch.id}/cast?key={quote(o['key'])}"}
        elif (o.get("use") or {}).get("id") and ctx.get("can_use"):
            row |= {"a": o["use"].get("verb") or "Use", "use": f"/characters/{ch.id}/use/{o['use']['id']}"}
        elif (o.get("bring") or {}).get("state") == "ready" and ctx.get("can_bring"):
            row |= {"a": "Use", "use": f"/characters/{ch.id}/bring/{o['bring']['id']}"}
        elif first:
            row |= {"a": first["text"] if first["text"] == "Heal" else "Roll", "roll": first["attrs"]}
        else:
            row |= {"a": "Open", "go": panel, "panel_only": True}
        out.append(row)

    def roll(kind, label, mod, find, sub, advs=()):  # (as the Sheet's and Table rolls' buttons: their Advantage too)
        return {"g": "Checks, saves, skills", "n": label, "s": sub, "a": "Roll", "find": find, "roll": views.roll_data(kind, label, mod, advs=advs)}
    now = form or sheet
    for sk in now.get("skills") or []:
        ab = sk.get("ability") or next((x.get("ability") for x in sheet.get("skills") or [] if x["name"] == sk["name"]), "") or ""
        out.append(roll("check", f"{sk['name']} check", sk["label"], _words(sk["name"], ab, "skill check"), f"skill · {sk['label']}" + (f" ({ab})" if ab else ""), sk.get("adv")))
    for sv in now.get("saves") or []:
        out.append(roll("save", f"{sv['short']} save", sv["label"], _words(sv["short"], ABILITY.get(sv["short"].lower()[:3]), "save saving throw"), sv["label"], sv.get("adv")))
    for a in now.get("abilities") or []:
        name = a.get("name") or ABILITY.get(str(a.get("key") or a.get("short") or "").lower()[:3], a.get("short"))
        out.append(roll("check", f"{name} check", a["label"], _words(name, a.get("short"), "check"), a["label"]))
    if now.get("initiative"):
        out.append(roll("check", "Initiative", now["initiative"], "initiative", now["initiative"], now.get("initiative_adv")))
    hidden = next((x["find"] for x in ctx.get("conditions") or [] if x.get("find")), None)
    return ch.id, out, table_rolls.roll_context(sheet) | {
        "condAdv": roll_effects([x for x in ctx.get("conditions") or [] if x["counts"]]), "hidden": hidden}


def story_rows(db: Session, user: dict) -> list[dict]:
    """The World's entries this person may see (the Campaign page's rule) and the published sessions."""
    from app.extraction import session_label, timeline

    campaign = web.campaign(db)
    if campaign is None:
        return []
    editor = can_edit_entries(user)
    out = []
    for e in db.scalars(select(Entity).options(selectinload(Entity.aliases)).where(Entity.campaign_id == campaign.id).order_by(Entity.name)):
        hidden = e.status != Status.PUBLISHED
        if hidden and not editor:
            continue  # (hidden is as if it didn't exist: CLAUDE.md › Privacy)
        kind = getattr(e.kind, "value", e.kind)
        out.append({"g": "The story", "n": e.name, "s": KINDS.get(kind, kind) + (" · hidden" if hidden else ""), "a": "Open",
                    "find": _words(e.name, " ".join(a.alias for a in e.aliases or []), kind), "go": f"{web.base()}/campaign?open={e.id}"})
    for s in timeline(db, campaign.id):
        if any(r.status == Status.PUBLISHED for r in s.recaps):
            out.append({"g": "The story", "n": s.title or session_label(s), "s": f"{session_label(s)} · the full tale and stats", "a": "Open",
                        "find": _words(s.title, session_label(s), "session recap tale"), "go": f"{web.base()}/sessions/{s.id}"})
    return out


def page_rows(user: dict, path: str) -> list[dict]:
    from app import access
    from app.manage import pages_for
    from app.templating import table_url

    base = web.base()
    out = [{"g": "Pages", "n": n, "s": s, "a": "Go", "find": _words(n, s), "go": h} for n, s, h in (
        ("Story", "Previously on… and every session", f"{base}/"), ("Campaign", "the World, quests, relationships, the map", f"{base}/campaign"),
        ("Party", "everyone at the table", "/party"), ("Your notes", "what happened to what you sent", "/your-notes"),
        ("Help", "the FAQ and About askdnd", "/help"))]
    table = table_url(access.current_campaign())
    if table:  # (the menu bar's Table: askdnd's own, else D&D Beyond's VTT in a tab of its own)
        out.insert(2, {"g": "Pages", "n": "Table", "s": "where the table plays" + ("" if table.startswith("/") else " (D&D Beyond ↗)"), "a": "Go",
                       "find": _words("table vtt map play"), "go": table})
    out += [{"g": "Pages", "n": p["label"], "s": p.get("about") or "", "a": "Go", "find": _words(p["label"], p.get("about"), "manage"), "go": p["href"]}
            for p in pages_for(user, path)]
    return out


@router.get("/search/index")
def index(request: Request, db: Session = Depends(get_db)):
    """Everything this person can find, for the search box (matched in the browser as they type)."""
    user = current_user(request)
    if not user:
        return JSONResponse({}, status_code=401)
    from app import rules_terms

    cid, mine, ctx = character_rows(db, user)
    rules = [{"g": "Rules", "n": t["name"], "s": t.get("kind") or "rule", "a": "Read it", "find": _words(t["name"], t.get("kind")), "text": t.get("text") or ""}
             for t in rules_terms.as_json().values()]
    return JSONResponse({"character": cid, "ctx": ctx, "rows": mine + rules + story_rows(db, user) + page_rows(user, request.url.path)})
