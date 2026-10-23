"""Manage › Tool corrections (admins, /manage/tool-corrections): corrections to how askdnd reads D&D Beyond, made
from character side panels (tool_corrections). They apply to every character in every campaign, so they belong to
askdnd as a whole. A DM's rulings for one table are House rules instead."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app import rules_terms as terms
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
        **_split(db, overrides),
        "toast": request.session.pop("toast", None),
    })


KINDS = {"spell": "Spell", "item": "Item", "feature": "Feature", "action": "Action", "attack": "Attack", "creature": "Wild Shape form"}


def automatic(sheets: list[dict], ref: str, field: str) -> str | None:
    """What askdnd chooses on its own for this thing, without any correction: the value the correction would set
    if askdnd got it right. None when no character has the thing (or for "hide", which askdnd never chooses).
    When a code fix makes this equal a correction's value, the correction is built in (Brett, 2026-10-23)."""
    if field == "underline":
        term = next((t for t in terms.TERMS if f"term:{t.name}" == ref), None)
        return None if term is None else ("off" if term.basic else "on")
    for raw in sheets:
        sheet = views.apply_overrides(raw, {})
        if ref.split(":", 1)[-1].isdigit() and (x := views.find(sheet, ref)):  # an older correction, stored by D&D Beyond number
            ref = views.override_ref(x, x["section"])
        if field in ("cost", "battle"):
            o = next((o for o in views.options(sheet) if o["oref"] == ref), None)
            if o:
                return o["cost"] if field == "cost" else ("common" if o.get("common") else "normal")
        section, key = {"feature_group": ("features", "use"), "situ_group": ("situational", "in_numbers"),
                        "item_group": ("inventory", "group")}.get(field, (None, None))
        if section:
            x = next((x for x in sheet.get(section) or [] if views.override_ref(x, section) == ref), None)
            if x is not None:
                if field == "feature_group":
                    return "use" if x["use"] else "passive"
                if field == "situ_group":
                    return "in_numbers" if x["in_numbers"] else "situational"
                return x["group"]
    return None


def _status(db: Session, overrides: list[ToolCorrection]) -> dict[int, str]:
    """Each correction: "open" (askdnd still gets it wrong), "built_in" (askdnd now chooses the same on its own,
    so the correction can go) or "unseen" (no character has the thing now)."""
    sheets = [sh for sh in (chars.character_summary(c) for c in db.scalars(select(Character))) if sh]
    out = {}
    for o in overrides:
        auto = automatic(sheets, o.ref, o.field)
        out[o.id] = "open" if o.field == "hide" or (auto is not None and auto != o.value) else ("built_in" if auto == o.value else "unseen")
    return out


def _split(db: Session, overrides: list[ToolCorrection]) -> dict:
    status = _status(db, overrides)
    return {"open": [o for o in overrides if status[o.id] != "built_in"], "built": [o for o in overrides if status[o.id] == "built_in"],
            "unseen": {o.id for o in overrides if status[o.id] == "unseen"}}


def open_count(db: Session) -> int:
    """For Needs you: corrections askdnd still needs a code fix for."""
    rows = list(db.scalars(select(ToolCorrection).where(ToolCorrection.field != "hide")))
    return sum(1 for v in _status(db, rows).values() if v == "open") if rows else 0


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
