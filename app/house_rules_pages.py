"""Manage › House rules: the DM's rulings on how askdnd rolls things at this table (app/house_rules.py)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import house_rules, web
from app import roll_recipes as rr
from app.auth import can_set_house_rules
from app.db import get_db
from app.models import HouseRule
from app.templating import templates

router = APIRouter(prefix="/manage/house-rules")
DENIED = "House rules are for the DM and admins."


def _rows(db: Session, campaign_id: int) -> list[dict]:
    rows = db.scalars(select(HouseRule).where(HouseRule.campaign_id == campaign_id)
                      .order_by(HouseRule.target_key, HouseRule.field))
    return [{"r": r, "text": house_rules.describe(r.field, r.value, rr.spell(r.target_key))} for r in rows]


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = web.require(request, can_set_house_rules, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    spells = sorted((rr.recipes().get("spells") or {}).items())
    return templates.TemplateResponse(request, "house_rules.html", {
        "campaign": campaign, "rules": _rows(db, campaign.id) if campaign else [],
        "spells": [name for name, _ in spells], "once_spells": [name for name, r in spells if house_rules.can_roll_once(r)],
        "toast": request.session.pop("toast", None)})


@router.post("")
def add(request: Request, spell: str = Form(""), field: str = Form(""), value: str = Form(""), reason: str = Form(""),
        db: Session = Depends(get_db)):
    user, denied = web.require(request, can_set_house_rules, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    key = rr.spell_key(spell)
    value, reason = " ".join(value.split())[:500], " ".join(reason.split())[:500]
    if not campaign or key is None or field not in house_rules.FIELDS:
        request.session["toast"] = "Pick a spell."
    elif field == "once" and not house_rules.can_roll_once(rr.spell(key)):
        request.session["toast"] = f"{key} has nothing that's rolled more than once."
    elif field == "note" and not value:
        request.session["toast"] = "Write the ruling."
    else:
        row = db.scalar(select(HouseRule).where(HouseRule.campaign_id == campaign.id, HouseRule.target_kind == "spell",
                                                HouseRule.target_key == key, HouseRule.field == field))
        if row is None:
            row = HouseRule(campaign_id=campaign.id, target_kind="spell", target_key=key, field=field)
            db.add(row)
        row.value, row.reason, row.set_by = ("1" if field == "once" else value), reason, web.person_name(user)
        db.commit()
        house_rules.invalidate()
        request.session["toast"] = f"House rule saved for {key}"
    return RedirectResponse(f"{web.base()}/manage/house-rules", status_code=303)


@router.post("/{rule_id:int}/delete")
def remove(request: Request, rule_id: int, db: Session = Depends(get_db)):
    user, denied = web.require(request, can_set_house_rules, DENIED)
    if denied:
        return denied
    row = db.get(HouseRule, rule_id)
    campaign = web.campaign(db)
    if row and campaign and row.campaign_id == campaign.id:
        key = row.target_key
        db.delete(row)
        db.commit()
        house_rules.invalidate()
        request.session["toast"] = f"Removed. {key} works as the rules say again (History can bring it back)."
    return RedirectResponse(f"{web.base()}/manage/house-rules", status_code=303)
