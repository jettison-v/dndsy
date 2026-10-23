"""Manage › Tool corrections (admins, /manage/tool-corrections): corrections to how askdnd reads D&D Beyond, made
from character side panels (tool_corrections). They apply to every character in every campaign, so they belong to
askdnd as a whole. A DM's rulings for one table are House rules instead."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app.admin import _guard
from app.db import get_db
from app.models import Character, ToolCorrection
from app.templating import templates

router = APIRouter(prefix="/manage/tool-corrections")


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    overrides = list(db.scalars(select(ToolCorrection).order_by(ToolCorrection.updated_at.desc())))
    labels = {f: dict(c) for f, c in {**views.OVERRIDE_CHOICES, **views.TERM_CHOICES}.items()}
    return templates.TemplateResponse(request, "tool_corrections.html", {
        "overrides": overrides, "labels": labels, "field_labels": views.FIELD_LABELS, "names": _names(db, overrides),
        "toast": request.session.pop("toast", None),
    })


KINDS = {"spell": "Spell", "item": "Item", "feature": "Feature", "action": "Action", "attack": "Attack", "creature": "Wild Shape form"}


def _names(db: Session, overrides: list[ToolCorrection]) -> dict[str, dict]:
    """What each correction is about, by name: an item's ref is its D&D Beyond number ("item:992695540"), so look it up
    on the characters' sheets (Brett, 2026-10-23: the bare number meant nothing)."""
    sheets = [sh for sh in (chars.character_summary(c) for c in db.scalars(select(Character))) if sh]
    out = {}
    for o in overrides:
        kind, _, rest = o.ref.partition(":") if ":" in o.ref else ("", "", o.ref)
        found = next((x for sh in sheets if (x := views.find(sh, o.ref))), None)
        out[o.ref] = {"name": (found or {}).get("name") or (rest if not rest.isdigit() else f"Item {rest} (no character has it now)"),
                      "kind": KINDS.get(kind, kind.capitalize())}
    return out


@router.post("/overrides/{override_id:int}/delete")
def undo_override(request: Request, override_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        db.delete(row)
        db.commit()
        request.session["toast"] = "Back to automatic"
    return RedirectResponse("/manage/tool-corrections", status_code=303)


@router.post("/overrides/{override_id:int}/reason")
def override_reason(request: Request, override_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    """Why a tool correction was needed (feedback for fixing the parser)."""
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        row.reason = " ".join(reason.split())[:300]
        db.commit()
        request.session["toast"] = "Saved"
    return RedirectResponse("/manage/tool-corrections", status_code=303)
