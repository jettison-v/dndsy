"""Manage › People (admins): who can sign in and what they can do (app/access.py)."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, config, web
from app.admin import _guard
from app.db import get_db
from app.models import CampaignMember, Character, Role, User
from app.templating import templates

router = APIRouter(prefix="/admin/people")


def people(db: Session, campaign_id: int | None) -> list[dict]:
    """Everyone with a user row, plus emails only in the Railway lists, with their role in this campaign."""
    rows = access.rows_from(db)
    users = {u.email.lower(): u for u in db.scalars(select(User))}
    emails = set(users) | config.ALLOWED_EMAILS | config.REVIEWER_EMAILS | config.ADMIN_EMAILS
    out = []
    for email in emails:
        u = users.get(email)
        lvl = access.level(email, rows)
        stored = u.access if u else None
        out.append({
            "user": u,
            "email": email,
            "name": u.name if u and u.name != email else "",
            "level": lvl,
            "role": access.role(email, campaign_id, rows),
            "stored": stored,
            "owner": access.is_owner(email),
            "from_railway": stored is None and lvl is not None,
            "removed": stored == access.REMOVED,
            "invited": lvl is not None,
            "last_seen": u.last_seen_at if u else None,
        })
    owned = {}
    for ch in db.scalars(select(Character).where(Character.owner_id.is_not(None))):
        owned.setdefault(ch.owner_id, ch.id)
    for p in out:
        p["character_id"] = owned.get(p["user"].id) if p["user"] else None
    return sorted(out, key=lambda p: (p["name"].lower() or p["email"]))


def groups(everyone: list[dict]) -> list[tuple[str, list[dict]]]:
    """People by their role in the campaign (DM, Reviewers, Players, then no role); removed people last."""
    here = [p for p in everyone if p["invited"]]
    out = [("DM", [p for p in here if p["role"] == access.DM]),
           ("Reviewers", [p for p in here if p["role"] == access.REVIEWER]),
           ("Players", [p for p in here if p["role"] == access.PLAYER]),
           ("No role in this campaign", [p for p in here if p["role"] is None])]
    return [(title, ps) for title, ps in out if ps]


@router.get("")
def people_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
    everyone = people(db, campaign.id if campaign else None)
    return templates.TemplateResponse(
        request, "admin_people.html",
        {"groups": groups(everyone), "away": [p for p in everyone if not p["invited"]], "campaign": campaign,
         "characters": list(db.scalars(select(Character).order_by(Character.name))),
         "roles": access.ROLES, "role_labels": access.ROLE_LABELS, "me": user["email"], "chart": access.chart(),
         "summaries": {f"{t}|{r or ''}": access.summary(t, r) for t in access.TOOL_ROLES for r in [*access.ROLES, None]},
         "toast": request.session.pop("toast", None)},
    )


def assign_character(db: Session, email: str, character_id: int | None) -> None:
    """Who plays which character: their pins and reminders are theirs to set."""
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=email)
        db.add(u)
        db.flush()
    for ch in db.scalars(select(Character).where(Character.owner_id == u.id)):
        if ch.id != character_id:
            ch.owner_id = None
    if character_id:
        ch = db.get(Character, character_id)
        if ch:
            ch.owner_id = u.id
    db.flush()


def set_role(db: Session, user: User, campaign_id: int, role: str | None) -> None:
    """Their role in the campaign. Changing it keeps the membership; no role ends it (the row stays, with the date)."""
    m = db.scalar(select(CampaignMember).where(CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user.id,
                                               CampaignMember.left_on.is_(None)))
    if role is None:
        if m is not None:
            m.left_on = date.today()
    elif m is None:
        db.add(CampaignMember(campaign_id=campaign_id, user_id=user.id, role=Role(role)))
    elif m.role != role:
        m.role = Role(role)
    db.flush()
    access.invalidate()


def _save(db: Session, email: str, tool: str, role: str | None, campaign_id: int | None, name: str = "",
          keep_role: bool = False) -> User:
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name or email)
        db.add(u)
    elif name:
        u.name = name
    u.access = tool
    db.flush()
    if campaign_id and not keep_role:
        set_role(db, u, campaign_id, role)
    access.invalidate()
    return u


def _role(value: str) -> str | None:
    return value if value in access.ROLES else None


@router.post("")
def add_person(request: Request, email: str = Form(...), name: str = Form(""), role: str = Form(access.PLAYER),
               admin: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    email = email.strip().lower()
    campaign = web.campaign(db)
    if "@" not in email:
        request.session["toast"] = "Enter an email address."
    else:
        _save(db, email, access.ADMIN if admin else access.MEMBER, _role(role), campaign.id if campaign else None, name.strip())
        db.commit()
        request.session["toast"] = f"Added {email}. Add them as a Google test user too (see below)."
    return RedirectResponse("/admin/people", status_code=303)


@router.post("/update")
def update_person(request: Request, email: str = Form(...), role: str = Form("keep"), admin: str = Form(""),
                  remove: str = Form(""), character_id: str = Form("keep"), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    email = email.strip().lower()
    campaign = web.campaign(db)
    if character_id != "keep" and not remove:
        assign_character(db, email, int(character_id) if character_id.isdigit() else None)
        db.commit()
    mine = access.is_owner(email) or email == user["email"].lower()
    tool = access.REMOVED if remove else access.ADMIN if (admin or mine) else access.MEMBER
    if access.is_owner(email) and tool != access.ADMIN:
        request.session["toast"] = "Owners are set on Railway (ADMIN_EMAILS) and are always admins."
    elif email == user["email"].lower() and tool != access.ADMIN:
        request.session["toast"] = "You can't lower your own access."
    else:
        _save(db, email, tool, _role(role), campaign.id if campaign else None, keep_role=role == "keep" or bool(remove))
        db.commit()
        request.session["toast"] = "Removed" if tool == access.REMOVED else "Saved"
    return RedirectResponse("/admin/people", status_code=303)
