"""Manage › Campaigns (admins): every campaign, creating one, and moving characters between them
(data organization step 4). People's roles in a campaign are set on Manage › People while in it."""

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, ddb, web
from app import characters as chars
from app.auth import is_admin
from app.db import get_db
from app.models import Campaign, CampaignMember, Character, Role, User
from app.templating import templates

router = APIRouter(prefix="/manage/campaigns")
DENIED = "Campaigns are set up by admins."
BACK = "/manage/campaigns"


def slug_for(db: Session, name: str) -> str:
    """A short address for the campaign ("Curse of Strahd" -> "curse-of-strahd"), unique."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "campaign"
    slug, n = base, 2
    while db.scalar(select(Campaign.id).where(Campaign.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def overview(db: Session) -> dict:
    campaigns = list(db.scalars(select(Campaign).order_by(Campaign.id)))
    dms: dict[int, list[str]] = {}
    people = dict(db.execute(select(CampaignMember.campaign_id, func.count()).where(CampaignMember.left_on.is_(None))
                             .group_by(CampaignMember.campaign_id)).all())
    for m, u in db.execute(select(CampaignMember, User).join(User).where(CampaignMember.left_on.is_(None), CampaignMember.role == Role.DM)):
        dms.setdefault(m.campaign_id, []).append(u.name)
    everyone = list(db.scalars(select(Character).order_by(Character.name)))
    by_ddb = {c.ddb_campaign_id: c for c in campaigns if c.ddb_campaign_id}
    seen = chars.ddb_campaigns(db)
    rows = []
    for ch in everyone:
        here = next((c for c in campaigns if c.id == ch.campaign_id), None)
        # D&D Beyond says it's in another campaign: offer the matching askdnd campaign (never moved automatically)
        theirs = ch.ddb_campaign_id
        mismatch = bool(theirs and here and here.ddb_campaign_id and theirs != here.ddb_campaign_id) or bool(theirs and not here)
        rows.append({"c": ch, "here": here, "mismatch": mismatch, "ddb_name": seen.get(theirs or "", ""),
                     "suggest": by_ddb.get(theirs) if mismatch else None})
    return {"campaigns": [{"c": c, "dms": dms.get(c.id, []), "people": people.get(c.id, 0),
                           "characters": [r["c"] for r in rows if r["here"] is c], "ddb_name": seen.get(c.ddb_campaign_id or "", "")}
                          for c in campaigns],
            "characters": rows,
            "unmatched": [(i, n) for i, n in seen.items() if i not in by_ddb]}


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    return templates.TemplateResponse(request, "manage_campaigns.html", {**overview(db), "toast": request.session.pop("toast", None)})


@router.post("")
def create(request: Request, name: str = Form(""), dm_name: str = Form(""), ddb_campaign_id: str = Form(""),
           db: Session = Depends(get_db)):
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    name = " ".join(name.split())[:200]
    if not name:
        request.session["toast"] = "Give the campaign a name."
        return RedirectResponse(BACK, status_code=303)
    c = Campaign(name=name, slug=slug_for(db, name), dm_name=" ".join(dm_name.split())[:200],
                 ddb_campaign_id=ddb_campaign_id.strip()[:40] or None)
    db.add(c)
    db.commit()
    access.invalidate()
    request.session["toast"] = f"Created {name}. Switch to it to add people (Manage › People) and characters."
    return RedirectResponse(BACK, status_code=303)


@router.post("/{campaign_id:int}")
def edit(request: Request, campaign_id: int, name: str = Form(""), dm_name: str = Form(""), ddb_campaign_id: str = Form(""),
         db: Session = Depends(get_db)):
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    c = db.get(Campaign, campaign_id)
    if c is not None and " ".join(name.split()):
        c.name = " ".join(name.split())[:200]
        c.dm_name = " ".join(dm_name.split())[:200]
        c.ddb_campaign_id = ddb_campaign_id.strip()[:40] or None
        db.commit()
        access.invalidate()
        request.session["toast"] = f"Saved {c.name}"
    return RedirectResponse(BACK, status_code=303)


@router.post("/characters/{character_id:int}/move")
def move(request: Request, character_id: int, campaign_id: str = Form(""), db: Session = Depends(get_db)):
    """Move a character: its time in the old campaign ends today and stays in that campaign's story."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    ch = db.get(Character, character_id)
    target = db.get(Campaign, int(campaign_id)) if campaign_id.isdigit() else None
    if ch is not None:
        chars.move(db, ch, target.id if target else None)
        db.commit()
        request.session["toast"] = f"{ch.name} is now in {target.name}" if target else f"{ch.name} is in no campaign now"
    return RedirectResponse(BACK, status_code=303)


@router.post("/{campaign_id:int}/characters")
def add_character(request: Request, campaign_id: int, name: str = Form(""), player_name: str = Form(""),
                  ddb_link: str = Form(""), db: Session = Depends(get_db)):
    """A new character, straight into this campaign (its D&D Beyond copy is fetched if a link is given)."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    target = db.get(Campaign, campaign_id)
    name = " ".join(name.split())[:200]
    if target is None or not name:
        request.session["toast"] = "Give the character a name."
        return RedirectResponse(BACK, status_code=303)
    ch = Character(name=name, player_name=" ".join(player_name.split())[:200])
    db.add(ch)
    db.flush()
    chars.move(db, ch, target.id)
    note = ""
    if ddb_link.strip():
        try:
            chars.set_ddb_link(db, ch, ddb_link)
            snap = chars.refresh(db, ch)
            note = "" if snap.status == "ok" else f" ({snap.error})"
        except ddb.DdbError as e:
            note = f" ({e})"
    db.commit()
    request.session["toast"] = f"Added {name} to {target.name}{note}"
    return RedirectResponse(BACK, status_code=303)


