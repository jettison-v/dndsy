"""Characters pages: a card per character and the full D&D Beyond sheet.

Reviewers (admin and DM) can link a character to D&D Beyond and refresh it.
Fetching happens only when someone clicks Refresh; there's no background job.
Character notes are never shown here (they're hidden from the DM; CLAUDE.md).
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import characters as chars
from app import ddb
from app.auth import current_user, is_reviewer
from app.db import get_db
from app.models import Campaign, Character
from app.templating import templates

router = APIRouter(prefix="/characters")


def _campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


def _view(ch: Character) -> dict:
    snap = ch.snapshot
    return {
        "c": ch,
        "sheet": chars.character_summary(ch),
        "fetched_at": snap.fetched_at if snap else None,
        "failed": snap is not None and snap.status == "error",
        "error": snap.error if snap else "",
    }


def _forbidden(request: Request):
    return templates.TemplateResponse(
        request, "message.html", {"title": "Not available", "message": "Only the admin and the DM can do that."}, status_code=403
    )


@router.get("")
def characters_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = _campaign(db)
    rows = [_view(ch) for ch in chars.campaign_characters(db, campaign.id)] if campaign else []
    return templates.TemplateResponse(
        request, "characters.html",
        {"rows": rows, "reviewer": is_reviewer(user), "toast": request.session.pop("toast", None)},
    )


@router.get("/{character_id:int}")
def character_page(request: Request, character_id: int, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ch = db.get(Character, character_id)
    if ch is None:
        return templates.TemplateResponse(
            request, "message.html", {"title": "Not found", "message": "That character isn't in the campaign."}, status_code=404
        )
    return templates.TemplateResponse(
        request, "character.html",
        {**_view(ch), "reviewer": is_reviewer(user), "toast": request.session.pop("toast", None)},
    )


@router.post("/refresh")
def refresh_all(request: Request, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    campaign = _campaign(db)
    ok, failed = chars.refresh_all(db, campaign.id) if campaign else (0, [])
    db.commit()
    msg = f"Updated {ok} from D&D Beyond"
    request.session["toast"] = msg + (f"; couldn't update {', '.join(failed)}" if failed else "")
    return RedirectResponse("/characters", status_code=303)


@router.post("/{character_id:int}/refresh")
def refresh_one(request: Request, character_id: int, db: Session = Depends(get_db)):
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/characters", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = "Updated from D&D Beyond" if snap.status == "ok" else "Couldn't update; showing the last good copy"
    return RedirectResponse(f"/characters/{ch.id}", status_code=303)


@router.post("/{character_id:int}/link")
def link(request: Request, character_id: int, ddb_link: str = Form(""), db: Session = Depends(get_db)):
    """Save the D&D Beyond link, then fetch the character straight away."""
    if not is_reviewer(current_user(request)):
        return _forbidden(request)
    ch = db.get(Character, character_id)
    if ch is None:
        return RedirectResponse("/characters", status_code=303)
    try:
        chars.set_ddb_link(db, ch, ddb_link)
    except ddb.DdbError as e:
        request.session["toast"] = str(e)
        return RedirectResponse(f"/characters/{ch.id}", status_code=303)
    snap = chars.refresh(db, ch)
    db.commit()
    request.session["toast"] = "Linked and updated from D&D Beyond" if snap.status == "ok" else "Linked, but couldn't fetch it yet"
    return RedirectResponse(f"/characters/{ch.id}", status_code=303)
