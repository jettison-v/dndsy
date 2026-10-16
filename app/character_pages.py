"""Battle, Character and Party pages, built from D&D Beyond sheets.

- /battle and /character open on the signed-in person's own character (set on
  Manage › People); /party shows everyone.
- Reviewers link characters to D&D Beyond and refresh them. Anyone can turn on
  Game Mode on a Battle page, which re-fetches that character every 2–3 minutes
  while the page is open (throttled per character on the server).
- Stars and reminders (app/picks.py): only the character's player sets them;
  the DM never sees them. Character notes are never shown here.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import ddb, picks
from app.auth import current_user, is_reviewer
from app.db import get_db
from app.models import Campaign, Character
from app.templating import templates

router = APIRouter()

GAME_MODE_SECONDS = 150  # the page asks every 2.5 minutes…
AUTO_MIN_AGE = timedelta(seconds=110)  # …and the server fetches at most this often per character
MANUAL_MIN_AGE = timedelta(seconds=20)  # "Refresh now"


def _campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


def _view(db: Session, ch: Character, user: dict) -> dict:
    snap = ch.snapshot
    sheet = chars.character_summary(ch)
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
        "reminders": views.reminders(sheet, mine["remind"]) if sheet else [],
        "reviewer": is_reviewer(user),
    }


def _forbidden(request: Request, message: str = "Only the admin and the DM can do that."):
    return templates.TemplateResponse(request, "message.html", {"title": "Not available", "message": message}, status_code=403)


def _not_found(request: Request):
    return templates.TemplateResponse(
        request, "message.html", {"title": "Not found", "message": "That character isn't in the campaign."}, status_code=404
    )


def _party_rows(db: Session) -> list[dict]:
    campaign = _campaign(db)
    return [views.party_row(ch, chars.character_summary(ch)) for ch in chars.campaign_characters(db, campaign.id)] if campaign else []


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
    rows = _party_rows(db)
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
        # Actions tab: everything except leveled spells (those are on the Spells tab), like D&D Beyond
        ctx["options"] = [o for o in views.options(ctx["sheet"], ctx["picks"]["star"])
                          if o["kind"] != "spell" or (o["tags"] and o["tags"][0] == "cantrip" and o["hit"])]
    return _page(request, "character.html", {**ctx, "others": chars.campaign_characters(db, ch.entity.campaign_id)})


def _battle_ctx(db: Session, ch: Character, user: dict) -> dict:
    ctx = _view(db, ch, user)
    if ctx["sheet"]:
        ctx["columns"] = views.battle_columns(ctx["sheet"], ctx["picks"]["star"])
    ctx["party"] = _party_rows(db)
    ctx["game_mode_seconds"] = GAME_MODE_SECONDS
    return ctx


@router.get("/characters/{character_id:int}/battle")
def battle_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    return _page(request, "battle.html", {**_battle_ctx(db, ch, user), "others": chars.campaign_characters(db, ch.entity.campaign_id)})


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


@router.get("/characters/{character_id:int}/option")
def option_detail(request: Request, character_id: int, ref: str, db: Session = Depends(get_db)):
    """Side panel: one option's details."""
    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    found = [o for o in views.options(ctx["sheet"] or {}, ctx["picks"]["star"]) if o["key"] == ref]
    if not found:
        return HTMLResponse("", status_code=404)
    return templates.TemplateResponse(request, "_panel_options.html", {**ctx, "title": found[0]["name"], "opts": found, "open": True})


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
    """Save the D&D Beyond link, then fetch the character straight away."""
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/party", status_code=303)
    try:
        chars.set_ddb_link(db, ch, ddb_link)
    except ddb.DdbError as e:
        request.session["toast"] = str(e)
        return RedirectResponse(f"/characters/{ch.id}", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = "Linked and updated from D&D Beyond" if snap.status == "ok" else "Linked, but couldn't fetch it yet"
    return RedirectResponse(f"/characters/{ch.id}", status_code=303)
