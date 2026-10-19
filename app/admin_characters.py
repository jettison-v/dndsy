"""Manage › Characters (admins): D&D Beyond links, refreshes, and the regrouping
corrections made from character side panels (sheet_overrides)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app import character_views as views
from app import characters as chars
from app.admin import _guard
from app.db import get_db
from app.models import SheetOverride
from app.templating import templates

router = APIRouter(prefix="/admin/characters")


@router.get("")
def characters_admin(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
    rows = chars.campaign_characters(db, campaign.id) if campaign else []
    overrides = list(db.scalars(select(SheetOverride).order_by(SheetOverride.updated_at.desc())))
    labels = {f: dict(c) for f, c in {**views.OVERRIDE_CHOICES, **views.TERM_CHOICES}.items()}
    return templates.TemplateResponse(request, "admin_characters.html", {
        "rows": rows, "overrides": overrides, "labels": labels, "field_labels": views.FIELD_LABELS,
        "toast": request.session.pop("toast", None),
    })


@router.post("/overrides/{override_id:int}/delete")
def undo_override(request: Request, override_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(SheetOverride, override_id)
    if row:
        db.delete(row)
        db.commit()
        request.session["toast"] = "Back to automatic"
    return RedirectResponse("/admin/characters", status_code=303)
