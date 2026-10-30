"""The Character page (Battle, Sheet and Plan modes) and Party, built from D&D Beyond sheets.

- One page per character with three modes: Battle (/characters/{id}/battle: what you can do in
  a fight), Sheet (/characters/{id}: the full sheet in tabs) and Plan (/characters/{id}/plan:
  the player's notes, shortlists and reminders; never the DM). The header is the same in each.
- /battle and /character open on the signed-in person's own character (set on
  Manage › People); /party shows everyone.
- Keeping the copy fresh (Game Mode, Refresh now) lives in the menu bar's Live control
  (app/live.py). A page shows a new copy by fetching itself again and swapping in its main (app.js
  "showInPlace"), whatever brought it.
- Stars and reminders (app/picks.py): only the character's player sets them;
  the DM never sees them. Character notes are never shown here.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app import character_views as views
from app import characters as chars
from app import conditions as cond
from app import ddb, ddb_bridge, hit_points, house_rules, picks
from app import class_rules, player_notes
from app import spellbook as sb
from app import wild_shape as ws
from app import rules_terms as terms
from app.auth import can_run_table, can_set_house_rules, current_user, is_admin, is_reviewer
from app.db import get_db
from app.models import Campaign, Character, HouseRule, TableRoll, ToolCorrection
from app.templating import templates

router = APIRouter()



def _overrides(db: Session) -> dict[tuple[str, str], str]:
    return house_rules.sheet_overrides(db)  # tool corrections, then the campaign's house rules


def _view(db: Session, ch: Character, user: dict) -> dict:
    snap = ch.snapshot
    sheet = views.apply_overrides(ddb_bridge.as_shown(db, ch, chars.character_summary(ch)), _overrides(db))  # with what's on its way
    if sheet:
        sheet["_item_choices"] = ch.item_choices
    mine = picks.picks(db, ch, user)
    druid = ws.druid(sheet)
    return {
        "c": ch,
        "sheet": sheet,
        "fetched_at": snap.fetched_at if snap else None,
        "failed": snap is not None and snap.status == "error",
        "error": snap.error if snap else "",
        "picks": mine,
        "can_pick": picks.can_edit(db, user, ch),
        "can_use": picks.can_edit(db, user, ch) and ddb_bridge.on_for(db, ch),  # an item's button (app/item_use.py)
        "can_play": picks.can_edit(db, user, ch) and ddb_bridge.plays(db, ch),  # Cast, resources, rests (the VTT piece live_state)
        "show_picks": picks.can_see(user, ch),
        "reminders": views.reminders(sheet, mine["remind"], mine["order"].get("forget"), mine["notes"]) if sheet else [],
        "druid": druid,
        "beasts": ws.beasts(db, ch.campaign_id) if druid else ws.beasts(),  # Wild Shape's forms: the SRD's and its campaign's books'
        "reviewer": is_reviewer(user),
        "admin": is_admin(user),
        "item_notes": chars.item_notes(db, ch),
        # what it's under, as badges after the name on every mode (Brett, 2026-10-29); everyone sees them; how long each
        # lasts, by the turns heard from D&D Beyond's VTT (app/fight.py timing)
        "conditions": _timings(db, ch, [{**x, "rules": cond.rules_text(x["name"])} for x in listed(db, ch, sheet)]),
    }


def _timings(db: Session, ch: Character, conditions: list[dict]) -> list[dict]:
    if not any(x.get("lasts") for x in conditions):
        return conditions
    from app import fight

    campaign = db.get(Campaign, ch.campaign_id) if ch.campaign_id else None
    return [{**x, "time": fight.timing(campaign, ch.id, x)} if x.get("lasts") else x for x in conditions]


def _form_label(db: Session, ch: Character, ref: str) -> str:
    """Reminders text for a Wild Shape form that isn't on the sheet (from the character's campaign's Beasts)."""
    return ws.label_for(ref, ws.beasts(db, ch.campaign_id)) if ref.startswith("form:") else ""


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
    return [views.party_row(ch, ddb_bridge.as_shown(db, ch, chars.character_summary(ch)))
            for ch in _mine_first(db, user, chars.campaign_characters(db, campaign.id))]


def _page(request: Request, name: str, ctx: dict):
    return templates.TemplateResponse(request, name, {**ctx, "toast": request.session.pop("toast", None)})


# ---------------------------------------------------------------- top-level


@router.get("/party")
def party_page(request: Request, pick: str = "", db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    overrides = _overrides(db)
    rows = [{**r, "sheet": views.apply_overrides(r["sheet"], overrides), "conditions": [{**x, "rules": cond.rules_text(x["name"])} for x in listed(db, r["c"], r["sheet"])]} for r in _party_rows(db, user)]
    return _page(request, "party.html", {
        "rows": rows,
        "spells": views.party_spell_list(rows),
        "items": views.party_item_list(rows),
        "coins": views.party_coins(rows),
        "reviewer": is_reviewer(user),
        "pick": pick if pick in ("battle", "character") else "",
        "oldest": min((r["c"].snapshot.fetched_at for r in rows if r["c"].snapshot and r["c"].snapshot.fetched_at), default=None),
    })


# ---------------------------------------------------------------- one character


def listed(db: Session, ch: Character, sheet: dict | None) -> list[dict]:
    """What this character is under now (cond.shown): D&D Beyond's conditions, from its sheet (as shown, with what's on
    its way: ddb_bridge.as_shown), with askdnd's own. Each says "sync" ("on" on its way, "ending", "failed": given up
    to make by hand) and whether it "counts" (on rolls and the page's edge: not one ending, nor one D&D Beyond didn't take)."""
    sheet = sheet or {}
    now, sync, ending = cond.shown(ch.conditions, sheet.get("conditions"), ddb_bridge.on_for(db, ch)), sheet.get("sync") or {}, sheet.get("ending") or []
    if ch.concentration:  # first, treated like a condition (Brett, 2026-10-29); askdnd's own, as D&D Beyond doesn't keep it
        cn = ch.concentration
        now = [{"name": "Concentration", "spell": cn.get("spell", ""), "round": cn.get("round"), "rounds": cn.get("rounds"),
                "source": cn.get("spell", ""), "due": bool(cn.get("due"))}] + now
    names = {x["name"] for x in now}
    now += [{"name": m[5:], "on_ddb": False} for m, st in sync.items() if st == "failed" and m.startswith("cond:") and m[5:] not in names]
    for x in now:
        x["sync"] = "ending" if x["name"] in ending else sync.get("cond:" + x["name"], "")
        x["counts"] = x["sync"] != "ending" and not (x["sync"] == "failed" and not x.get("on_ddb"))
    return now


def _load(request: Request, db: Session, character_id: int):
    user = current_user(request)
    if not user:
        return None, None, RedirectResponse("/login", status_code=303)
    ch = db.get(Character, character_id)
    if ch is None or not picks.can_view(db, user, ch):
        return user, None, _not_found(request)
    if request.method == "GET" and not request.headers.get("HX-Request") and ddb_bridge.on_for(db, ch):
        ddb_bridge.page_opened(db, ch)  # the D&D Beyond bridge: the page shows D&D Beyond's numbers now
    return user, ch, None


def _battle_ctx(db: Session, ch: Character, user: dict, shape: str | None = None) -> dict:
    """Battle mode's body (also swapped in by Game Mode and the Wild Shape switch). `shape` shows it in that form
    instead of the character's own (the tour's preview: nothing is saved)."""
    ctx = _view(db, ch, user)
    ctx["form"] = None
    ctx["previewing"] = shape is not None
    wild = shape if shape is not None else ch.wild_shape
    if ctx["sheet"]:
        ctx["columns"] = views.battle_columns(ctx["sheet"], ctx["picks"]["star"], ctx["picks"]["order"], pinned_only=ctx["show_picks"])
        ctx["riders"] = class_rules.turn(ctx["sheet"])["riders"]
        ctx["known_forms"] = ws.known_forms(ctx["sheet"], ctx["beasts"]) if ctx["druid"] else []
        beast = ws.beast_for(ctx["sheet"], wild, ctx["beasts"]) if wild and ctx["druid"] else None
        if beast:
            ctx["form"] = ws.shaped(ctx["sheet"], beast, keep=ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep))
            own = ctx["columns"]  # (items stay: what a form's limbs can handle is the DM's to say)
            ctx["columns"] = {k: {**v, "items": own[k]["items"], "item_count": own[k]["item_count"]} for k, v in ctx["form"]["columns"].items()}
            ctx["columns"]["No action"] = own["No action"]
    ctx["spellbar"] = _spellbar(db, ch, ctx)
    now = ctx["conditions"]
    ctx["cond_adv"] = cond.roll_effects([x for x in now if x["counts"]])  # listed in the roll window (app.js specFrom)
    ctx["all_conditions"], ctx["all_effects"] = list(cond.CONDITIONS), list(cond.EFFECTS)
    ctx["active_conditions"] = {x["name"] for x in now if x["sync"] != "ending"}
    ctx["cond_synced"] = ddb_bridge.on_for(db, ch)
    ctx["conc"] = ch.concentration or None  # first in the Status row (_conc_pill.html)
    ctx["con_save"] = sb.concentration_save((ctx["form"] or {}).get("saves") or (ctx["sheet"] or {}).get("saves") or [])
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
        ctx["forms"] = ws.forms(ctx["sheet"], ctx["picks"]["fav"], ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep), ctx["beasts"])
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
            ctx["plan_forms"] = ws.forms(s, fav, ws.chosen_keep(s, ch.wild_shape_keep), ctx["beasts"])  # every form you can learn: Shortlist and All
            ctx["fav_forms"] = [f for f in ctx["plan_forms"] if f["key"] in fav]
    return ctx


MODE_CTX = {"battle": _battle_ctx, "sheet": _sheet_ctx, "plan": _plan_ctx}


def _character(request: Request, db: Session, character_id: int, mode: str):
    """One Character page in one mode; the header and the mode switch are the same in each."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if mode == "plan" and not picks.can_see(user, ch):
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


@router.get("/characters/{character_id:int}/all/{cost}")
def see_all(request: Request, character_id: int, cost: str, add: int = 0, items: int = 0, db: Session = Depends(get_db)):
    """Side panel: every option of one kind (actions, bonus actions, reactions). add=1 (the column's
    + Add on Battle): only the ones not pinned yet; items=1 (a column's All items): only its items."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    cost = {"action": "Action", "bonus": "Bonus action", "reaction": "Reaction", "none": "No action"}.get(cost)
    ctx = _view(db, ch, user)
    if not cost or not ctx["sheet"]:
        return HTMLResponse("", status_code=404)
    everything = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"]) if o["cost"] == cost and not (add and o["starred"])
                  and (not items or o["kind"] == "item")]
    return templates.TemplateResponse(request, "_panel_options.html", {**ctx, "title": cost, "opts": everything, "adding": bool(add), "items_only": bool(items),
                                                                      "groups": views.option_groups(everything)})


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
    can_correct = can_set_house_rules(user, ch.campaign_id)
    return templates.TemplateResponse(request, "_panel_detail.html", {**ctx, **d, "ref": ref, "oref": oref, "item_actions": item_actions,
                                      "can_correct": can_correct, "corrections": _corrections(db, ch, oref) if can_correct else {},
                                      "item_kinds": cond.item_options(d["x"]) if d["section"] == "inventory" else None,
                                      "item_kind": ch.item_choices.get(ref.split(":", 1)[1], "") if d["section"] == "inventory" else "",
                                      "cost_from": views.COST_FROM,
                                      "underline": terms.underlined(_overrides(db)),
                                      "choices": views.OVERRIDE_CHOICES, "field_labels": views.FIELD_LABELS,
                                      "fields": views.fields_for(d["section"], d["opt"])})


def _may_correct(user: dict | None, ch: Character | None, scope: str) -> bool:
    return bool(user and ch) and (can_set_house_rules(user, ch.campaign_id) if scope == "campaign" else scope == "everyone" and is_admin(user))


def _correction(db: Session, ch: Character, oref: str, field: str, scope: str) -> HouseRule | ToolCorrection | None:
    if scope == "campaign":
        return db.scalar(select(HouseRule).where(HouseRule.campaign_id == ch.campaign_id, HouseRule.target_kind == "sheet",
                                                 HouseRule.target_key == oref[:200], HouseRule.field == field))
    return db.scalar(select(ToolCorrection).where(ToolCorrection.ref == oref[:300], ToolCorrection.field == field))


def _corrections(db: Session, ch: Character, oref: str) -> dict:
    """What Correct this shows now: each scope's values by field, and why."""
    ours = list(db.scalars(select(HouseRule).where(HouseRule.campaign_id == ch.campaign_id, HouseRule.target_kind == "sheet", HouseRule.target_key == oref[:200])))
    all_ = list(db.scalars(select(ToolCorrection).where(ToolCorrection.ref == oref[:300])))
    return {"campaign": {r.field: r.value for r in ours}, "everyone": {r.field: r.value for r in all_},
            "campaign_why": next((r.reason for r in ours if r.reason), ""), "everyone_why": next((r.reason for r in all_ if r.reason), "")}


@router.post("/characters/{character_id:int}/override/why")
def set_correction_why(request: Request, character_id: int, oref: str = Form(...), scope: str = Form(...), reason: str = Form(""), db: Session = Depends(get_db)):
    """Why, in a few words, on what's corrected for this thing in that scope."""
    user, ch = current_user(request), db.get(Character, character_id)
    if not _may_correct(user, ch, scope):
        return _forbidden(request, "Only the DM or an admin can correct this.")
    q = (select(HouseRule).where(HouseRule.campaign_id == ch.campaign_id, HouseRule.target_kind == "sheet", HouseRule.target_key == oref[:200])
         if scope == "campaign" else select(ToolCorrection).where(ToolCorrection.ref == oref[:300]))
    for row in db.scalars(q):
        row.reason = " ".join(reason.split())[:300]
    db.commit()
    house_rules.invalidate()
    return HTMLResponse("", status_code=204)


@router.post("/characters/{character_id:int}/override")
def set_override(request: Request, character_id: int, ref: str = Form(...), oref: str = Form(...), field: str = Form(...),
                 value: str = Form(...), scope: str = Form("everyone"), reason: str = Form(""), db: Session = Depends(get_db)):
    """Correct this (an item's side panel; docs/mockups/correction-flow.html): for this campaign (its DM or an admin, a
    house rule of kind "sheet") or for everyone (an admin, a tool correction). Returns just that setting's row, so the
    side panel doesn't jump or lose the other choices."""
    user, ch = current_user(request), db.get(Character, character_id)
    if not _may_correct(user, ch, scope):
        return _forbidden(request, "Only the DM or an admin can correct this for the campaign." if scope == "campaign" else "Only an admin can correct this for everyone.")
    if field not in views.OVERRIDE_CHOICES or value not in [v for v, _ in views.OVERRIDE_CHOICES[field]] + ["default"]:
        return HTMLResponse("", status_code=400)
    reason = " ".join(reason.split())[:300]
    row = _correction(db, ch, oref, field, scope)
    if value == "default":
        if row:
            db.delete(row)
    elif row:
        row.value = value
        if reason:
            row.reason = reason
    elif scope == "campaign":
        db.add(HouseRule(campaign_id=ch.campaign_id, target_kind="sheet", target_key=oref[:200], field=field, value=value, reason=reason, set_by=web.person_name(user)))
    else:
        db.add(ToolCorrection(ref=oref[:300], field=field, value=value, reason=reason, set_by=user["email"]))
    db.commit()
    house_rules.invalidate()
    resp = templates.TemplateResponse(request, "_override_field.html", {
        "c": {"id": character_id}, "ref": ref, "oref": oref, "field": field, "current": None if value == "default" else value, "scope": scope,
        "choices": views.OVERRIDE_CHOICES, "field_labels": views.FIELD_LABELS, "saved": True})
    resp.headers["HX-Trigger"] = json.dumps({"toast": "Saved for this campaign" if scope == "campaign" else "Saved for every character"})
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
        "hp_change": kind == "hp" and ddb_bridge.on_for(db, ch) and hit_points.can_apply(db, user, ch),
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
        on = picks.toggle(db, ch, kind, ref, views.label_for(sheet, ref) or _form_label(db, ch, ref))
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    if marks:
        shown = [m for m in marks.split(",") if m in picks.KINDS]
        resp = templates.TemplateResponse(request, "_detail_marks.html", {"c": ch, "ref": ref, "can_pick": True, "marks": shown,
                                                                          "picks": picks.picks(db, ch, user)})
    else:
        resp = templates.TemplateResponse(request, "_pick.html", {"c": ch, "kind": kind, "ref": ref, "on": on, "can_pick": True})
    resp.headers["HX-Trigger"] = web.changed(ch)  # the page and its open panels show it (pinning also shortlists)
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
        picks.add_text_reminder(db, ch, text)
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, toast="Reminder added")})


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
        picks.set_note(db, ch, ref, note, views.label_for(sheet, ref) or _form_label(db, ch, ref))
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    return HTMLResponse('<span class="note">Saved</span>', headers={"HX-Trigger": web.changed(ch)})


@router.get("/characters/{character_id:int}/form")
def form_panel(request: Request, character_id: int, name: str, db: Session = Depends(get_db)):
    """Side panel: a Wild Shape form with this druid's stats carried over, as battle cards."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    beast = ws.beast_for(ctx["sheet"] or {}, name, ctx["beasts"]) if ctx["druid"] else None
    if beast is None:
        return HTMLResponse("", status_code=404)
    known = any(f["name"].lower() == beast["name"].lower() for f in ws.known_forms(ctx["sheet"], ctx["beasts"]))
    return templates.TemplateResponse(request, "_panel_form.html", {
        **ctx, "f": ws.shaped(ctx["sheet"], beast, keep=ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep)), "ref": f"form:{beast['name']}", "known": known,
        "keep_options": ws.options_for(ctx["sheet"] or {}, ws.chosen_keep(ctx["sheet"], ch.wild_shape_keep)), "beast_name": beast["name"],
        "why_not": ws.why_not(ctx["druid"], beast), "credit": ws.credit(beast), "book": ws.book_label(beast),
        "current": (ch.wild_shape or "").lower() == beast["name"].lower()})


@router.post("/characters/{character_id:int}/wild-shape/keep")
def set_wild_shape_keep(request: Request, character_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """The character's player records what the DM lets them keep in Wild Shape (items, class
    features). Saved on the character, so it applies to every form until changed. Returns
    the form's modal again with the new numbers."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
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
    known = {f["name"].lower(): f["name"] for f in ws.known_forms(chars.character_summary(ch))}
    if form and form.lower() not in known:
        return HTMLResponse("", status_code=400)
    ch.wild_shape = known[form.lower()] if form else None
    db.commit()
    if request.headers.get("HX-Request"):
        resp = templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))
        resp.headers["HX-Trigger"] = json.dumps({"toast": f"Wild Shape: {ch.wild_shape}" if ch.wild_shape else "Back to normal form"})
        return resp
    return RedirectResponse(f"/characters/{ch.id}/battle", status_code=303)


@router.get("/characters/{character_id:int}/battle/preview")
def battle_preview(request: Request, character_id: int, form: str = "", db: Session = Depends(get_db)):
    """Battle's body as if in a Wild Shape form (one the druid knows), or in the character's own state with no
    form given: for the tour, which shows a transformation and then puts the real one back. Nothing is saved or
    announced (app/tour.py)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _battle_ctx(db, ch, user, shape=form or None)
    if form and form.lower() not in {f["name"].lower() for f in ctx.get("known_forms", [])}:
        return HTMLResponse("", status_code=400)
    return templates.TemplateResponse(request, "_battle_body.html", ctx)


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


def _concentration_reply(request: Request, db: Session, ch: Character, user: dict, toast: str, deliver: bool = False):
    if request.headers.get("HX-Request"):
        resp = templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))
        # (and every open window shows its new copy at once: the Spell Book's Concentrate, Brett 2026-10-29)
        resp.headers["HX-Trigger"] = json.dumps({"toast": toast, "characterChanged": {"character": ch.id},
                                                 **({"bridgeDeliver": web.deliver_now(ch)} if deliver else {})})
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
    old, as at the table. No slot is spent here: Cast does that (app/casting.py), this is for one cast elsewhere."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    sp = next((e for e in sb.entries(chars.character_summary(ch) or {}) if e["key"] == key and e["conc"]), None)
    if sp is None:
        return HTMLResponse("", status_code=400)
    ch.concentration = sb.concentrating(sp, level)
    db.commit()
    return _concentration_reply(request, db, ch, user, f"Concentrating on {sp['name']}")


@router.post("/characters/{character_id:int}/conditions")
def start_condition(request: Request, character_id: int, name: str = Form(...), source: str = Form(""), note: str = Form(""),
                    level: int = Form(0), lasts: str = Form(""), n: int = Form(0), time: str = Form(""), ability: str = Form(""),
                    dc: int = Form(0), whose: str = Form(""), db: Session = Depends(get_db)):
    """A condition or effect (from a magic item's action, or picked: Poisoned, Exhaustion 2…), from the character's own
    player only. One D&D Beyond holds goes to the sheet where the bridge works (only while it can be reached), and
    shows once D&D Beyond has it; askdnd keeps where it came from."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    try:
        own = cond.add(ch.conditions, name, source, note, level)
    except ValueError:
        return HTMLResponse("", status_code=400)
    own[-1] = _timed(db, ch, own[-1], lasts, n, time, ability, dc, whose)
    label = f"{name}" + (f" {level}" if name == "Exhaustion" else "") + (f" ({source})" if source else "")
    synced = ddb_bridge.on_for(db, ch) and name in cond.ON_DDB
    if synced:
        ddb_bridge.reach(ch)
        ddb_bridge.add(db, ch, "set", {"field": cond.ddb_field(name), "value": own[-1].get("level", True)}, f"{ch.name}: {label}")
    ch.conditions = own
    db.commit()
    return _concentration_reply(request, db, ch, user, label + (": on its way to D&D Beyond" if synced else ""), deliver=synced)


def _timed(db: Session, ch: Character, entry: dict, lasts: str, n: int, time: str, ability: str, dc: int, whose: str) -> dict:
    """+ Condition's Lasts on the new entry (app/conditions.py), begun on whose turn it is now in the heard fight."""
    from app import fight

    campaign = db.get(Campaign, ch.campaign_id) if ch.campaign_id else None
    f = fight.shown(campaign, dm=True)
    names = {x["key"]: x["name"] for x in (f or {}).get("order", [])}
    la = cond.lasts_from(lasts, n, time, ability, dc, whose if whose in names else "self", names.get(whose, ""))
    if not la:
        return entry
    entry = {**entry, "lasts": la}
    began = fight.active_key(campaign.fight) if f else None
    if la["kind"] == "rounds" and began:
        entry["began"], entry["left"] = began, la["n"]
    return entry


@router.post("/characters/{character_id:int}/conditions/keep")
def keep_condition(request: Request, character_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    """Keep: its time ran out, and the DM says it lasts. From then on it lasts until it's ended."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    ch.conditions = [({k: v for k, v in c.items() if k not in ("lasts", "due", "armed", "began", "left")} if c.get("name") == name else c)
                     for c in ch.conditions or []]
    if name == "Concentration" and ch.concentration:
        ch.concentration = {k: v for k, v in ch.concentration.items() if k != "due"} | {"rounds": None}
    db.commit()
    return _concentration_reply(request, db, ch, user, f"{name}: kept")


@router.post("/characters/{character_id:int}/conditions/end")
def end_condition(request: Request, character_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    """Ends one: on D&D Beyond where the bridge works and the sheet has it. Without the bridge, one ticked on D&D
    Beyond is ended there (askdnd only reads the sheet)."""
    user, ch, stop = _concentration_guard(request, db, character_id)
    if stop:
        return stop
    # as shown, with what's on its way: one still on its way to D&D Beyond is ended there too (review, 2026-10-29: it
    # landed after it was ended)
    now = next((c for c in listed(db, ch, ddb_bridge.as_shown(db, ch, chars.character_summary(ch))) if c["name"] == name), None)
    synced = bool(now and now.get("on_ddb")) and ddb_bridge.on_for(db, ch)
    if now and now.get("on_ddb") and not synced:
        raise HTTPException(409, f"{name} is ticked on {ch.name}'s D&D Beyond sheet: end it there, and askdnd shows it when it next reads the sheet.")
    if synced:
        ddb_bridge.reach(ch)
        ddb_bridge.add(db, ch, "set", {"field": cond.ddb_field(name), "value": 0 if name == "Exhaustion" else False}, f"{ch.name}: no longer {name}")
    ch.conditions = cond.end(ch.conditions, name) or None
    db.commit()
    return _concentration_reply(request, db, ch, user, f"No longer {name}" + (": on its way to D&D Beyond" if synced else ""), deliver=synced)


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
def save_order(request: Request, character_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Drag and drop on Battle: the player's own order for one column."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    column = form.get("column", "")
    if column not in ("Action", "Bonus action", "Reaction", "forget", "Action items", "Bonus action items", "Reaction items", "No action items"):
        return HTMLResponse("", status_code=400)
    picks.set_order(db, ch, column, [str(k) for k in form.getlist("keys")])
    db.commit()
    return HTMLResponse("", status_code=204)


# ---------------------------------------------------------------- reviewers


def _table() -> str:
    return f"{web.base()}/manage/table"


def _back(request: Request, default: str) -> str:
    """Where a refresh sends you back to: Manage › Table when it was pressed there, else `default`."""
    return _table() if request.query_params.get("from") == "table" else default


@router.post("/characters/refresh")
def refresh_all(request: Request, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    campaign = web.campaign(db)
    ok, failed = chars.refresh_all(db, campaign.id) if campaign else (0, [])
    db.commit()
    msg = f"Updated {ok} from D&D Beyond"
    request.session["toast"] = web.notice(msg + f"; couldn't update {', '.join(failed)}", "warn") if failed else msg
    return RedirectResponse(_back(request, "/party"), status_code=303)


@router.post("/characters/{character_id:int}/refresh")
def refresh_one(request: Request, character_id: int, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/party", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = "Updated from D&D Beyond" if snap.status == "ok" else web.notice("Couldn't update; showing the last good copy", "warn")
    return RedirectResponse(_back(request, f"/characters/{ch.id}"), status_code=303)


@router.post("/characters/{character_id:int}/link")
def link(request: Request, character_id: int, ddb_link: str = Form(""), db: Session = Depends(get_db)):
    """Admin (Manage › Table): save the D&D Beyond link, then fetch the character."""
    ch = db.get(Character, character_id)
    if not ch or not can_run_table(current_user(request), ch.campaign_id):
        return _forbidden(request, "Only the DM or an admin can change D&D Beyond links.")
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse(_table(), status_code=303)
    try:
        chars.set_ddb_link(db, ch, ddb_link)
    except ddb.DdbError as e:
        request.session["toast"] = web.notice(str(e), "warn")
        return RedirectResponse(_table(), status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = (f"{ch.name}: linked and updated from D&D Beyond" if snap.status == "ok"
                                else f"{ch.name}: linked, but couldn't fetch it yet")
    return RedirectResponse(_table(), status_code=303)


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
    row = db.scalar(select(ToolCorrection).where(ToolCorrection.ref == ref, ToolCorrection.field == "underline"))
    if value == "default" or (value == "on") == (not t.basic):
        if row:
            db.delete(row)  # same as the built-in choice: nothing to store
    elif row:
        row.value, row.set_by = value, user["email"]
    else:
        db.add(ToolCorrection(ref=ref, field="underline", value=value, set_by=user["email"]))
    db.commit()
    return JSONResponse({"on": t.slug in terms.underlined(_overrides(db))})
