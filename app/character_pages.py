"""The Character page (Battle, Sheet and Plan modes) and Party, built from D&D Beyond sheets.

- One page per character with three modes: Battle (/characters/{id}/battle: what you can do in
  a fight), Sheet (/characters/{id}: the full sheet in tabs) and Plan (/characters/{id}/plan:
  the player's notes, shortlists and reminders; never the DM). The header is the same in each.
- /battle and /character open on the signed-in person's own character (set on
  Manage › People); /party shows everyone.
- Keeping the copy fresh (Game Mode, Refresh now) lives in the menu bar's Live control
  (app/live.py). On Battle, Game Mode swaps in the updated body from game_mode_sync.
- Stars and reminders (app/picks.py): only the character's player sets them;
  the DM never sees them. Character notes are never shown here.
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app import character_views as views
from app import characters as chars
from app import conditions as cond
from app import ddb, help_pages, picks
from app import class_rules, live, player_notes
from app import spellbook as sb
from app import wild_shape as ws
from app import rules_terms as terms
from app.auth import current_user, is_admin, is_reviewer
from app.db import get_db
from app.models import Character, SheetOverride, TableRoll
from app.templating import templates

router = APIRouter()

GAME_MODE_SECONDS = live.GAME_MODE_SECONDS


def _overrides(db: Session) -> dict[tuple[str, str], str]:
    return {(o.ref, o.field): o.value for o in db.scalars(select(SheetOverride))}


def _view(db: Session, ch: Character, user: dict) -> dict:
    snap = ch.snapshot
    sheet = views.apply_overrides(chars.character_summary(ch), _overrides(db))
    mine = picks.picks(db, ch, user)
    return {
        "c": ch,
        "sheet": sheet,
        "fetched_at": snap.fetched_at if snap else None,
        "failed": snap is not None and snap.status == "error",
        "error": snap.error if snap else "",
        "picks": mine,
        "can_pick": picks.can_edit(db, user, ch),
        "show_picks": picks.can_see(user),
        "reminders": views.reminders(sheet, mine["remind"], mine["order"].get("forget"), mine["notes"]) if sheet else [],
        "druid": ws.druid(sheet),
        "reviewer": is_reviewer(user),
        "admin": is_admin(user),
        "item_notes": chars.item_notes(db, ch),
        "help_off": help_pages.dismissed(db, user),
    }


_forbidden = web.forbidden


def _not_found(request: Request):
    return web.not_found(request, "That character isn't in the campaign.")


def _mine_first(db: Session, user: dict | None, characters: list[Character]) -> list[Character]:
    """The signed-in player's own character first, then the rest by name."""
    me = picks.user_row(db, user)
    return sorted(characters, key=lambda ch: not (me and ch.owner_id == me.id))


def _party_rows(db: Session, user: dict | None = None) -> list[dict]:
    campaign = web.campaign(db)
    if not campaign:
        return []
    return [views.party_row(ch, chars.character_summary(ch)) for ch in _mine_first(db, user, chars.campaign_characters(db, campaign.id))]


def _page(request: Request, name: str, ctx: dict):
    return templates.TemplateResponse(request, name, {**ctx, "toast": request.session.pop("toast", None)})


# ---------------------------------------------------------------- top-level


@router.get("/battle")
def my_battle(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ch = picks.my_character(db, user)
    return RedirectResponse(f"/characters/{ch.id}/battle" if ch else "/party?pick=battle", status_code=303)


@router.get("/character")
def my_character(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ch = picks.my_character(db, user)
    return RedirectResponse(f"/characters/{ch.id}" if ch else "/party?pick=character", status_code=303)


@router.get("/characters")
def old_list(request: Request):
    return RedirectResponse("/party", status_code=303)


@router.get("/party")
def party_page(request: Request, pick: str = "", db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    rows = [{**r, "sheet": views.apply_overrides(r["sheet"], _overrides(db))} for r in _party_rows(db, user)]
    return _page(request, "party.html", {
        "rows": rows,
        "spells": views.pooled_spells(rows),
        "items": views.pooled_items(rows),
        "coins": views.party_coins(rows),
        "reviewer": is_reviewer(user),
        "pick": pick if pick in ("battle", "character") else "",
        "oldest": min((r["c"].snapshot.fetched_at for r in rows if r["c"].snapshot and r["c"].snapshot.fetched_at), default=None),
    })


# ---------------------------------------------------------------- one character


def _load(request: Request, db: Session, character_id: int):
    user = current_user(request)
    if not user:
        return None, None, RedirectResponse("/login", status_code=303)
    ch = db.get(Character, character_id)
    if ch is None:
        return user, None, _not_found(request)
    return user, ch, None


def _known_forms(sheet: dict | None) -> list[dict]:
    """The forms a druid can shift into right now (known on D&D Beyond), with pictures."""
    out = []
    for c in (sheet or {}).get("creatures") or []:
        if c.get("group") == "Wild Shape form":
            b = ws.catalog_beast(c["kind"]) or {}
            out.append({"name": c["kind"], "cr": c["cr"], "image": b.get("image", "")})
    return out


def _battle_ctx(db: Session, ch: Character, user: dict) -> dict:
    """Battle mode's body (also swapped in by Game Mode and the Wild Shape switch)."""
    ctx = _view(db, ch, user)
    ctx["form"] = None
    if ctx["sheet"]:
        ctx["columns"] = views.battle_columns(ctx["sheet"], ctx["picks"]["star"], ctx["picks"]["order"], pinned_only=ctx["show_picks"])
        ctx["riders"] = class_rules.turn(ctx["sheet"])["riders"]
        ctx["known_forms"] = _known_forms(ctx["sheet"]) if ctx["druid"] else []
        beast = ws.beast_for(ctx["sheet"], ch.wild_shape) if ch.wild_shape and ctx["druid"] else None
        if beast:
            ctx["form"] = ws.shaped(ctx["sheet"], beast, keep=ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep))
            ctx["columns"] = ctx["form"]["columns"]
    ctx["spellbar"] = _spellbar(db, ch, ctx)
    ctx["conditions"] = [{**x, "rules": cond.rules_text(x["name"])} for x in ch.conditions or []]  # everyone sees them
    ctx["cond_adv"] = cond.roll_effects(ch.conditions)  # listed in the roll window (app.js specFrom)
    ctx["all_conditions"], ctx["all_effects"] = list(cond.CONDITIONS), list(cond.EFFECTS)
    ctx["active_conditions"] = {x["name"] for x in ch.conditions or []}
    ctx |= player_notes.page_context(db, ch, user, ctx["sheet"])
    return ctx


def _castable_in_form(ctx: dict) -> set[str]:
    d = ctx.get("druid") or {}
    return set(d.get("moon_spells") or []) | ({sp["name"] for sp in (ctx["sheet"] or {}).get("spells") or []} if d.get("beast_spells") else set())


STARRED_ON_BAR = 4  # starred spells shown on the spell bar, most recently used first (Brett: no wrapping)


def _recent_spells(db: Session, ch: Character, names: set[str]) -> dict[str, int]:
    """When each of these spells was last rolled at the table (Table rolls, newest id = latest),
    plus the one being concentrated on, which counts as just used."""
    seen: dict[str, int] = {}
    if names:
        rows = db.execute(select(TableRoll.label, func.max(TableRoll.id)).where(
            TableRoll.character_id == ch.id, TableRoll.parent_id.is_(None), TableRoll.label.in_(names)).group_by(TableRoll.label))
        seen = {label: last for label, last in rows}
    conc = (ch.concentration or {}).get("spell")
    if conc in names:
        seen[conc] = max(seen.values(), default=0) + 1
    return seen


def _spellbar(db: Session, ch: Character, ctx: dict) -> dict | None:
    """Battle's spell bar: the Spell Book button, slots, starred spells (the most recently used
    few) and Concentration."""
    sheet = ctx["sheet"] or {}
    if not sheet.get("spells"):
        return None
    form = ctx.get("form")
    spells = sb.entries(sheet, _castable_in_form(ctx))
    starred = [e for e in spells if e["key"] in ctx["picks"]["star"] and (not form or e["name"] in form.get("castable", []))]
    recent = _recent_spells(db, ch, {e["name"] for e in starred})
    starred.sort(key=lambda e: -recent.get(e["name"], 0))  # stable: never-used keep their order after the used ones
    return {"slots": sb.slot_levels(sheet), "starred": starred[:STARRED_ON_BAR], "more": max(0, len(starred) - STARRED_ON_BAR),
            "conc": ch.concentration or None, "con_save": sb.concentration_save(form["saves"] if form else sheet.get("saves") or [])}


def _sheet_ctx(db: Session, ch: Character, user: dict) -> dict:
    ctx = _view(db, ch, user)
    if ctx["sheet"]:
        ctx["sheet_spells"] = sb.sheet_entries(ctx["sheet"])  # Spells tab: the shared list
        ctx["spell_groups"] = sb.sheet_filter_groups(ctx["sheet_spells"])
        # Actions tab: everything except leveled spells (those are on the Spells tab), like D&D Beyond
        ctx["options"] = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"])
                          if o["kind"] != "spell" or (o["tags"] and o["tags"][0] == "cantrip" and o["hit"])]
        ctx["feature_rows"] = views.feature_rows(ctx["sheet"], views.options(ctx["sheet"]))  # Features tab: the shared list
        ctx["forms"] = ws.forms(ctx["sheet"], ctx["picks"]["fav"], ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep))
        ctx["ws_other_uses"] = ws.other_uses(ctx["sheet"]) if ctx["druid"] else []
    return ctx


def _plan_ctx(db: Session, ch: Character, user: dict) -> dict:
    """Plan mode: the player's notes, Reminders, and the spell and Wild Shape shortlists."""
    ctx = _view(db, ch, user)
    s, fav = ctx["sheet"], ctx["picks"]["fav"]
    ctx["fav_spells"], ctx["fav_forms"], ctx["plan_spells"], ctx["plan_spell_groups"], ctx["plan_forms"] = [], [], [], [], []
    if s:
        ctx["plan_spells"] = sb.sheet_entries(s)  # every spell: Shortlist to compare, All to pick from
        ctx["plan_spell_groups"] = sb.sheet_filter_groups(ctx["plan_spells"])
        ctx["fav_spells"] = [e for e in ctx["plan_spells"] if e["key"] in fav]  # the tab's count
        if ctx["druid"]:
            ctx["plan_forms"] = ws.forms(s, fav, ws.chosen_keep(s, ch.wild_shape_keep))  # every form you can learn: Shortlist and All
            ctx["fav_forms"] = [f for f in ctx["plan_forms"] if f["key"] in fav]
    return ctx


MODE_CTX = {"battle": _battle_ctx, "sheet": _sheet_ctx, "plan": _plan_ctx}


def _character(request: Request, db: Session, character_id: int, mode: str):
    """One Character page in one mode; the header and the mode switch are the same in each."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if mode == "plan" and not picks.can_see(user):
        return RedirectResponse(f"/characters/{ch.id}", status_code=303)  # Plan is the players' (never the DM)
    ctx = MODE_CTX[mode](db, ch, user)
    if mode != "battle":
        ctx |= player_notes.page_context(db, ch, user, ctx["sheet"])
    return _page(request, "character.html", {**ctx, "mode": mode})


@router.get("/characters/{character_id:int}")
def character_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    return _character(request, db, character_id, "sheet")


@router.get("/characters/{character_id:int}/battle")
def battle_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    return _character(request, db, character_id, "battle")


@router.get("/characters/{character_id:int}/plan")
def plan_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    return _character(request, db, character_id, "plan")


@router.post("/characters/{character_id:int}/sync")
def game_mode_sync(request: Request, character_id: int, now: str = Form(""), db: Session = Depends(get_db)):
    """Game Mode on Battle: refresh from D&D Beyond (at most every ~2 minutes per character,
    whoever is watching) and return the updated Battle body, with the menu bar's Live pill."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    live.maybe_refresh(db, ch, live.MANUAL_MIN_AGE if now else live.AUTO_MIN_AGE)
    tn = live.table(user, "", live.rows_from(db), ch.id)
    return templates.TemplateResponse(request, "_battle_sync.html", {**_battle_ctx(db, ch, user), "tn": tn, "oob": True})


@router.get("/characters/{character_id:int}/all/{cost}")
def see_all(request: Request, character_id: int, cost: str, add: int = 0, db: Session = Depends(get_db)):
    """Side panel: every option of one kind (actions, bonus actions, reactions). add=1 (the column's
    + Add on Battle): only the ones not pinned yet."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    cost = {"action": "Action", "bonus": "Bonus action", "reaction": "Reaction"}.get(cost)
    ctx = _view(db, ch, user)
    if not cost or not ctx["sheet"]:
        return HTMLResponse("", status_code=404)
    everything = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"]) if o["cost"] == cost and not (add and o["starred"])]
    return templates.TemplateResponse(request, "_panel_options.html", {**ctx, "title": cost, "opts": everything, "adding": bool(add)})


@router.get("/characters/{character_id:int}/detail")
@router.get("/characters/{character_id:int}/option")
def detail_panel(request: Request, character_id: int, ref: str, db: Session = Depends(get_db)):
    """Side panel: everything about one thing on the sheet (spell, action, item, feature…)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    d = views.detail(ctx["sheet"] or {}, ref, ctx["picks"]["star"])
    if d is None:
        return HTMLResponse("", status_code=404)
    oref = d["opt"]["oref"] if d["opt"] else views.override_ref({**d["x"], "key": ref}, d["section"])
    item_actions = cond.item_actions(d["x"]) if d["section"] == "inventory" else []  # its Battle actions, to pin
    return templates.TemplateResponse(request, "_panel_detail.html", {**ctx, **d, "ref": ref, "oref": oref, "item_actions": item_actions,
                                      "underline": terms.underlined(_overrides(db)),
                                      "choices": views.OVERRIDE_CHOICES, "field_labels": views.FIELD_LABELS,
                                      "fields": views.fields_for(d["section"], d["opt"])})


@router.post("/characters/{character_id:int}/override")
def set_override(request: Request, character_id: int, ref: str = Form(...), oref: str = Form(...),
                 field: str = Form(...), value: str = Form(...), db: Session = Depends(get_db)):
    """Admin: regroup something (for every character). Returns just that setting's
    row, so the side panel doesn't jump or lose the admin's other choices."""
    user = current_user(request)
    if not is_admin(user):
        return _forbidden(request, "Only an admin can regroup things.")
    if field not in views.OVERRIDE_CHOICES or value not in [v for v, _ in views.OVERRIDE_CHOICES[field]] + ["default"]:
        return HTMLResponse("", status_code=400)
    row = db.scalar(select(SheetOverride).where(SheetOverride.ref == oref[:300], SheetOverride.field == field))
    if value == "default":
        if row:
            db.delete(row)
    elif row:
        row.value, row.set_by = value, user["email"]
    else:
        db.add(SheetOverride(ref=oref[:300], field=field, value=value, set_by=user["email"]))
    db.commit()
    resp = templates.TemplateResponse(request, "_override_field.html", {
        "c": {"id": character_id}, "ref": ref, "oref": oref, "field": field, "current": None if value == "default" else value,
        "choices": views.OVERRIDE_CHOICES, "field_labels": views.FIELD_LABELS, "saved": True})
    resp.headers["HX-Trigger"] = json.dumps({"toast": "Saved for every character"})
    return resp


@router.get("/characters/{character_id:int}/brief")
def brief(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Modal on the Party page: a short version of the character."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    return templates.TemplateResponse(request, "_brief.html", _view(db, ch, user))


VITALS = {"hp": "Hit Points", "ac": "Armor Class", "speed": "Speed", "initiative": "Initiative", "spell": "Spell save DC and attack",
          "inspiration": "Heroic Inspiration", "proficiency": "Proficiency Bonus", "perception": "Passive Perception"}


@router.get("/characters/{character_id:int}/vital/{kind}")
def vital_panel(request: Request, character_id: int, kind: str, db: Session = Depends(get_db)):
    """Side panel for one number at the top (HP, AC, Speed…): what it means and how it adds up."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    s = ctx["sheet"]
    skill = next((k for k in (s or {}).get("skills") or [] if kind == "skill-" + k["name"].lower().replace(" ", "-")), None)
    if (kind not in VITALS and not skill) or not s:
        return HTMLResponse("", status_code=404)
    gives = [f for f in s.get("features") or [] if "Heroic Inspiration" in (f.get("text") or "")] if kind == "inspiration" else []
    perception = next((k for k in s.get("skills") or [] if k["name"] == "Perception"), None)
    return templates.TemplateResponse(request, "_panel_vital.html", {
        **ctx, "kind": "skill" if skill else kind, "title": f"{skill['name']} ({skill['ability']})" if skill else VITALS[kind],
        "skill": skill, "gives": gives, "perception": perception,
        "underline": terms.underlined(_overrides(db))})


@router.post("/characters/{character_id:int}/pick")
def toggle_pick(request: Request, character_id: int, kind: str = Form(...), ref: str = Form(...), marks: str = Form(""),
                db: Session = Depends(get_db)):
    """Pin, shortlist or remind, from the character's own player only. Returns the button, or with
    `marks` (the side panel) the whole marks block, since pinning also shortlists."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    sheet = chars.character_summary(ch) or {}
    try:
        on = picks.toggle(db, ch, kind, ref, views.label_for(sheet, ref) or ws.label_for(ref))
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    if marks:
        shown = [m for m in marks.split(",") if m in picks.KINDS]
        resp = templates.TemplateResponse(request, "_detail_marks.html", {"c": ch, "ref": ref, "can_pick": True, "marks": shown,
                                                                          "picks": picks.picks(db, ch, user)})
    else:
        resp = templates.TemplateResponse(request, "_pick.html", {"c": ch, "kind": kind, "ref": ref, "on": on, "can_pick": True})
    # Tell the page behind (Battle, Sheet's rows) so it shows the change without a refresh (roadmap step 5).
    # Pinning also shortlists; unpinning leaves the shortlist as it was (fav: None).
    fav = on if kind == "fav" else (True if kind == "star" and on else None)
    resp.headers["HX-Trigger"] = json.dumps({"marksChanged": {"character": ch.id, "kind": kind, "ref": ref, "on": on, "fav": fav}})
    return resp


@router.post("/characters/{character_id:int}/reminders")
def add_reminder(request: Request, character_id: int, text: str = Form(""), db: Session = Depends(get_db)):
    """A free-text reminder from the Reminders box (Battle and Plan), from the character's own player only."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    try:
        ref = picks.add_text_reminder(db, ch, text)
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({
        "toast": "Reminder added", "marksChanged": {"character": ch.id, "kind": "remind", "ref": ref, "on": True, "fav": None}})})


@router.get("/characters/{character_id:int}/battle/body")
def battle_body(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Battle's body on its own, for a live update after a pin or reminder changes (no D&D Beyond refresh)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    return templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))


@router.post("/characters/{character_id:int}/pick/note")
def save_pick_note(request: Request, character_id: int, ref: str = Form(...), note: str = Form(""),
                   db: Session = Depends(get_db)):
    """The player's one note on a thing (saved as they type)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    sheet = chars.character_summary(ch) or {}
    try:
        picks.set_note(db, ch, ref, note, views.label_for(sheet, ref) or ws.label_for(ref))
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    # Tell the page behind so the note line under the row shows it without a refresh (roadmap step 5b)
    note = (picks.picks(db, ch, user)["notes"].get(ref) or "")
    return HTMLResponse('<span class="note">Saved</span>', headers={
        "HX-Trigger": json.dumps({"noteChanged": {"character": ch.id, "ref": ref, "note": note}})})


@router.get("/characters/{character_id:int}/form")
def form_panel(request: Request, character_id: int, name: str, db: Session = Depends(get_db)):
    """Side panel: a Wild Shape form with this druid's stats carried over, as battle cards."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    beast = ws.beast_for(ctx["sheet"] or {}, name) if ctx["druid"] else None
    if beast is None:
        return HTMLResponse("", status_code=404)
    known = any(f["name"].lower() == beast["name"].lower() for f in _known_forms(ctx["sheet"]))
    return templates.TemplateResponse(request, "_panel_form.html", {
        **ctx, "f": ws.shaped(ctx["sheet"], beast, keep=ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep)), "ref": f"form:{beast['name']}", "known": known,
        "keep_options": ws.options_for(ctx["sheet"] or {}, ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep)), "beast_name": beast["name"],
        "why_not": ws.why_not(ctx["druid"], beast), "credit": ws.credit() if beast.get("source") == "SRD 5.2" else "",
        "current": (ch.wild_shape or "").lower() == beast["name"].lower()})


@router.post("/characters/{character_id:int}/wild-shape/keep")
async def set_wild_shape_keep(request: Request, character_id: int, db: Session = Depends(get_db)):
    """The character's player records what the DM lets them keep in Wild Shape (items, class
    features). Saved on the character, so it applies to every form until changed. Returns
    the form's modal again with the new numbers."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    form = await request.form()
    sheet = chars.character_summary(ch) or {}
    allowed = {o["key"] for o in ws.options_for(sheet, [])}
    ch.wild_shape_keep = sorted(k for k in form.getlist("keep") if k in allowed)
    db.commit()
    return form_panel(request, character_id, str(form.get("name", "")), db)


@router.post("/characters/{character_id:int}/wild-shape")
def set_wild_shape(request: Request, character_id: int, form: str = Form(""), db: Session = Depends(get_db)):
    """Battle's Wild Shape switch (the character's player): show a known form's
    battle cards, or go back to normal. Everyone at the table sees it."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    known = {f["name"].lower(): f["name"] for f in _known_forms(chars.character_summary(ch))}
    if form and form.lower() not in known:
        return HTMLResponse("", status_code=400)
    ch.wild_shape = known[form.lower()] if form else None
    db.commit()
    if request.headers.get("HX-Request"):
        resp = templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))
        resp.headers["HX-Trigger"] = json.dumps({"toast": f"Wild Shape: {ch.wild_shape}" if ch.wild_shape else "Back to normal form"})
        return resp
    return RedirectResponse(f"/characters/{ch.id}/battle", status_code=303)


@router.get("/characters/{character_id:int}/spellbook")
def spellbook_modal(request: Request, character_id: int, db: Session = Depends(get_db)):
    """The Spell Book (a large modal from Battle's spell bar): every spell the character can cast now,
    on the shared list pattern (filters, search, sort), with averages at each slot level."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    sheet = ctx["sheet"] or {}
    spells = sb.entries(sheet, _castable_in_form(ctx))
    moon = bool(ctx["druid"] and ctx["druid"].get("moon_spells"))
    return templates.TemplateResponse(request, "_spellbook.html", {
        **ctx, "spells": spells, "slots": sb.slot_levels(sheet), "groups": sb.filter_groups(spells, wild_shape=moon),
        "in_form": bool(ch.wild_shape and moon), "sc": (sheet.get("spellcasting") or [{}])[0], "conc": ch.concentration})


def _concentration_reply(request: Request, db: Session, ch: Character, user: dict, toast: str):
    if request.headers.get("HX-Request"):
        resp = templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))
        resp.headers["HX-Trigger"] = json.dumps({"toast": toast})
        return resp
    return RedirectResponse(f"/characters/{ch.id}/battle", status_code=303)


def _concentration_guard(request: Request, db: Session, character_id: int):
    user, ch, stop = _load(request, db, character_id)
    if not stop and not picks.can_edit(db, user, ch):
        stop = _forbidden(request, "Only this character's player can do that.")
    return user, ch, stop


@router.post("/characters/{character_id:int}/concentration")
def start_concentration(request: Request, character_id: int, key: str = Form(...), level: int = Form(0), db: Session = Depends(get_db)):
    """Start tracking Concentration on a spell (the character's player). A new one replaces the
    old, as at the table. Slots are spent on D&D Beyond; askdnd only keeps track."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    sp = next((e for e in sb.entries(chars.character_summary(ch) or {}) if e["key"] == key and e["conc"]), None)
    if sp is None:
        return HTMLResponse("", status_code=400)
    ch.concentration = {"spell": sp["name"], "key": sp["key"], "level": max(level, sp["level"]), "round": 1, "rounds": sp["rounds"]}
    db.commit()
    return _concentration_reply(request, db, ch, user, f"Concentrating on {sp['name']}")


@router.post("/characters/{character_id:int}/conditions")
def start_condition(request: Request, character_id: int, name: str = Form(...), source: str = Form(""), note: str = Form(""),
                    level: int = Form(0), db: Session = Depends(get_db)):
    """A condition or effect (from a magic item's action, or picked: Poisoned, Exhaustion 2…), from the character's own player only."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    try:
        ch.conditions = cond.add(ch.conditions, name, source, note, level)
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    return _concentration_reply(request, db, ch, user, f"{name}" + (f" {level}" if name == "Exhaustion" else "") + (f" ({source})" if source else ""))


@router.post("/characters/{character_id:int}/conditions/end")
def end_condition(request: Request, character_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    ch.conditions = cond.end(ch.conditions, name) or None
    db.commit()
    return _concentration_reply(request, db, ch, user, f"No longer {name}")


@router.post("/characters/{character_id:int}/concentration/round")
def next_concentration_round(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    if ch.concentration:
        c = dict(ch.concentration)
        c["round"] = min(c.get("round", 1) + 1, c.get("rounds") or 9999)
        ch.concentration = c
        db.commit()
    return _concentration_reply(request, db, ch, user, f"Round {ch.concentration['round']}" if ch.concentration else "Not concentrating")


@router.post("/characters/{character_id:int}/concentration/end")
def end_concentration(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    name = (ch.concentration or {}).get("spell", "")
    ch.concentration = None
    db.commit()
    return _concentration_reply(request, db, ch, user, f"Concentration on {name} ended" if name else "Not concentrating")


@router.post("/characters/{character_id:int}/order")
async def save_order(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Drag and drop on Battle: the player's own order for one column."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    form = await request.form()
    column = form.get("column", "")
    if column not in ("Action", "Bonus action", "Reaction", "forget"):
        return HTMLResponse("", status_code=400)
    picks.set_order(db, ch, column, [str(k) for k in form.getlist("keys")])
    db.commit()
    return HTMLResponse("", status_code=204)


# ---------------------------------------------------------------- reviewers


@router.post("/characters/refresh")
def refresh_all(request: Request, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    campaign = web.campaign(db)
    ok, failed = chars.refresh_all(db, campaign.id) if campaign else (0, [])
    db.commit()
    msg = f"Updated {ok} from D&D Beyond"
    request.session["toast"] = msg + (f"; couldn't update {', '.join(failed)}" if failed else "")
    return RedirectResponse("/party", status_code=303)


@router.post("/characters/{character_id:int}/refresh")
def refresh_one(request: Request, character_id: int, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/party", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = "Updated from D&D Beyond" if snap.status == "ok" else "Couldn't update; showing the last good copy"
    return RedirectResponse(f"/characters/{ch.id}", status_code=303)


@router.post("/characters/{character_id:int}/link")
def link(request: Request, character_id: int, ddb_link: str = Form(""), db: Session = Depends(get_db)):
    """Admin (Manage › Characters): save the D&D Beyond link, then fetch the character."""
    if not is_admin(current_user(request)):
        return _forbidden(request, "Only an admin can change D&D Beyond links.")
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/admin/characters", status_code=303)
    try:
        chars.set_ddb_link(db, ch, ddb_link)
    except ddb.DdbError as e:
        request.session["toast"] = str(e)
        return RedirectResponse("/admin/characters", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = (f"{ch.entity.name}: linked and updated from D&D Beyond" if snap.status == "ok"
                                else f"{ch.entity.name}: linked, but couldn't fetch it yet")
    return RedirectResponse("/admin/characters", status_code=303)


@router.get("/rules/terms.json")
def rule_terms(request: Request, db: Session = Depends(get_db)):
    """Definitions for the underlined rule terms in side panels (loaded once, on first hover)."""
    user = current_user(request)
    if not user:
        return JSONResponse({}, status_code=401)
    return JSONResponse({"terms": terms.as_json(), "on": sorted(terms.underlined(_overrides(db))), "admin": is_admin(user)})


@router.post("/rules/terms/{slug}/underline")
def set_term_underline(request: Request, slug: str, value: str = Form(...), db: Session = Depends(get_db)):
    """Admin: underline a rule term in every description, or stop underlining it.
    "default" goes back to the built-in choice (terms everyone knows aren't underlined)."""
    user = current_user(request)
    if not is_admin(user):
        return JSONResponse({"error": "Only an admin can change this."}, status_code=403)
    t = terms.BY_SLUG.get(slug)
    if t is None or value not in ("on", "off", "default"):
        return JSONResponse({"error": "Unknown term or setting."}, status_code=400)
    ref = f"term:{t.name}"
    row = db.scalar(select(SheetOverride).where(SheetOverride.ref == ref, SheetOverride.field == "underline"))
    if value == "default" or (value == "on") == (not t.basic):
        if row:
            db.delete(row)  # same as the built-in choice: nothing to store
    elif row:
        row.value, row.set_by = value, user["email"]
    else:
        db.add(SheetOverride(ref=ref, field="underline", value=value, set_by=user["email"]))
    db.commit()
    return JSONResponse({"on": t.slug in terms.underlined(_overrides(db))})
