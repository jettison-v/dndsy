"""Battle, Character and Party pages, built from D&D Beyond sheets.

- /battle and /character open on the signed-in person's own character (set on
  Manage › People); /party shows everyone.
- Reviewers link characters to D&D Beyond and refresh them. Anyone can turn on
  Game Mode on a Battle page, which re-fetches that character every 2–3 minutes
  while the page is open (throttled per character on the server).
- Stars and reminders (app/picks.py): only the character's player sets them;
  the DM never sees them.
"""

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import ddb, picks
from app import rules_terms as terms
from app.auth import current_user, is_admin, is_reviewer
from app.db import get_db
from app.models import Campaign, Character, SheetOverride
from app.templating import templates

router = APIRouter()

GAME_MODE_SECONDS = 150  # the page asks every 2.5 minutes…
AUTO_MIN_AGE = timedelta(seconds=110)  # …and the server fetches at most this often per character
MANUAL_MIN_AGE = timedelta(seconds=20)  # "Refresh now"


def _campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


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
        "reminders": views.reminders(sheet, mine["remind"], mine["order"].get("forget")) if sheet else [],
        "reviewer": is_reviewer(user),
        "admin": is_admin(user),
        "item_notes": chars.item_notes(db, ch),
    }


def _forbidden(request: Request, message: str = "Only the admin and the DM can do that."):
    return templates.TemplateResponse(request, "message.html", {"title": "Not available", "message": message}, status_code=403)


def _not_found(request: Request):
    return templates.TemplateResponse(
        request, "message.html", {"title": "Not found", "message": "That character isn't in the campaign."}, status_code=404
    )


def _mine_first(db: Session, user: dict | None, characters: list[Character]) -> list[Character]:
    """The signed-in player's own character first, then the rest by name."""
    me = picks.user_row(db, user)
    return sorted(characters, key=lambda ch: not (me and ch.owner_id == me.id))


def _party_rows(db: Session, user: dict | None = None) -> list[dict]:
    campaign = _campaign(db)
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


@router.get("/characters/{character_id:int}")
def character_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    if ctx["sheet"]:
        ctx["granted_spells"] = views.granted_spells(ctx["sheet"])
        # Actions tab: everything except leveled spells (those are on the Spells tab), like D&D Beyond
        ctx["options"] = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"])
                          if o["kind"] != "spell" or (o["tags"] and o["tags"][0] == "cantrip" and o["hit"])]
    return _page(request, "character.html", {**ctx, "others": _mine_first(db, user, chars.campaign_characters(db, ch.entity.campaign_id))})


def _battle_ctx(db: Session, ch: Character, user: dict) -> dict:
    ctx = _view(db, ch, user)
    if ctx["sheet"]:
        ctx["columns"] = views.battle_columns(ctx["sheet"], ctx["picks"]["star"], ctx["picks"]["order"])
    ctx["party"] = _party_rows(db, user)
    ctx["game_mode_seconds"] = GAME_MODE_SECONDS
    return ctx


@router.get("/characters/{character_id:int}/battle")
def battle_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    return _page(request, "battle.html", {**_battle_ctx(db, ch, user), "others": _mine_first(db, user, chars.campaign_characters(db, ch.entity.campaign_id))})


@router.post("/characters/{character_id:int}/sync")
def game_mode_sync(request: Request, character_id: int, now: str = Form(""), db: Session = Depends(get_db)):
    """Game Mode: refresh from D&D Beyond (at most every ~2 minutes per character,
    whoever is watching) and return the updated Battle body."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if ch.ddb_id:
        snap = ch.snapshot
        min_age = MANUAL_MIN_AGE if now else AUTO_MIN_AGE
        last = snap.attempted_at if snap else None
        if last is None or datetime.now(UTC) - last >= min_age:
            chars.refresh(db, ch)
            db.commit()
    return templates.TemplateResponse(request, "_battle_body.html", _battle_ctx(db, ch, user))


@router.get("/characters/{character_id:int}/all/{cost}")
def see_all(request: Request, character_id: int, cost: str, db: Session = Depends(get_db)):
    """Side panel: every option of one kind (actions, bonus actions, reactions)."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    cost = {"action": "Action", "bonus": "Bonus action", "reaction": "Reaction"}.get(cost)
    ctx = _view(db, ch, user)
    if not cost or not ctx["sheet"]:
        return HTMLResponse("", status_code=404)
    everything = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"]) if o["cost"] == cost]
    return templates.TemplateResponse(request, "_panel_options.html", {**ctx, "title": cost, "opts": everything})


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
    return templates.TemplateResponse(request, "_panel_detail.html", {**ctx, **d, "ref": ref, "oref": oref,
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


@router.post("/characters/{character_id:int}/pick")
def toggle_pick(request: Request, character_id: int, kind: str = Form(...), ref: str = Form(...),
                db: Session = Depends(get_db)):
    """Star or remind, from the character's own player only. Returns the button."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    if not picks.can_edit(db, user, ch):
        return _forbidden(request, "Only this character's player can do that.")
    sheet = chars.character_summary(ch) or {}
    try:
        on = picks.toggle(db, ch, kind, ref, views.label_for(sheet, ref))
    except ValueError:
        return HTMLResponse("", status_code=400)
    db.commit()
    return templates.TemplateResponse(request, "_pick.html", {"c": ch, "kind": kind, "ref": ref, "on": on, "can_pick": True})


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
    campaign = _campaign(db)
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
