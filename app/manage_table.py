"""Manage › Table (/c/<campaign>/manage/table): who plays in the campaign and with which character, in one place
(Manage layout, 2026-10-23). The campaign's DM sees it; only admins change it.

- Characters: who plays each one, its D&D Beyond link and refresh (refreshing is for the DM and reviewers too, as
  before), and adding a new one. Moving a character to another campaign stays on Manage › Campaigns.
- People: each person's role in this campaign; adding someone (an account askdnd has, or a new email).
- What each role can do: the chart from app/access.py.

Who may sign in at all, and who's an admin, is askdnd-wide: Manage › Accounts (app/manage_accounts.py).
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import view_as
from app import access, config, ddb, web
from app import characters as chars
from app.auth import can_see_table, is_admin, is_reviewer
from app.db import get_db
from app.models import Campaign, CampaignMember, Character, Role, User
from app.templating import templates

router = APIRouter(prefix="/manage/table")
DENIED_SEE = "The Table is for the campaign's DM and admins."
DENIED = "Only admins change who plays in a campaign."
ROLE_ORDER = {access.DM: 0, access.REVIEWER: 1, access.PLAYER: 2}


def _back() -> RedirectResponse:
    return RedirectResponse(f"{web.base()}/manage/table", status_code=303)


def people(db: Session, campaign_id: int) -> list[dict]:
    """Everyone with a role in this campaign (DM, reviewers, players), with what they can do and the character they
    play here. Reviewers on the Railway list count in every campaign."""
    rows = access.rows_from(db)
    users = {u.email.lower(): u for u in db.scalars(select(User))}
    here = {c.id: c for c in chars.campaign_characters(db, campaign_id)}
    out = []
    for email in set(users) | config.ALLOWED_EMAILS | config.REVIEWER_EMAILS | config.ADMIN_EMAILS:
        lvl, role = access.level(email, rows), access.role(email, campaign_id, rows)
        if lvl is None or role is None:
            continue
        u = users.get(email)
        out.append({"user": u, "email": email, "name": u.name if u and u.name != email else "", "role": role, "level": lvl,
                    "plays": [c for c in here.values() if u and c.owner_id == u.id],
                    "summary": access.summary(lvl, role),
                    "from_railway": role != ((rows.get(email) or {}).get("roles") or {}).get(campaign_id)})
    return sorted(out, key=lambda p: (ROLE_ORDER[p["role"]], (p["name"] or p["email"]).lower()))


def _classes(ch: Character) -> str:
    """"Druid 5 / Monk 2", from the last D&D Beyond copy (empty if there's none)."""
    summary = (ch.snapshot.summary if ch.snapshot else None) or {}
    return " / ".join(f"{k.get('name')} {k.get('level')}" for k in summary.get("classes") or [] if isinstance(k, dict) and k.get("name"))


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = web.require(request, can_see_table, DENIED_SEE)
    if denied:
        return denied
    campaign = web.campaign(db)
    if campaign is None:
        return web.not_found(request, "Pick a campaign first.")
    everyone = people(db, campaign.id)
    names = {u.id: (u.name if u.name and u.name != u.email else u.email) for u in db.scalars(select(User))}
    in_campaign = {p["email"] for p in everyone}
    characters = chars.campaign_characters(db, campaign.id)
    return templates.TemplateResponse(request, "manage_table.html", {
        "campaign": campaign, "characters": characters, "people": everyone, "names": names,
        "classes": {c.id: _classes(c) for c in characters},
        # A test campaign (VTT 0.1) can add test copies of the table's characters
        "copyable": chars.copy_candidates(db, campaign.id) if campaign.is_test else [],
        "originals": {c.copy_of_id: _original(db, c.copy_of_id) for c in characters if c.copy_of_id},
        "accounts": [u for u in db.scalars(select(User).order_by(User.name))
                     if u.email.lower() not in in_campaign and access.level(u.email) is not None],
        "can_change": is_admin(user), "can_refresh": is_reviewer(user), "roles": access.ROLES, "role_labels": access.ROLE_LABELS,
        "chart": access.chart(), "toast": request.session.pop("toast", None),
        "can_view": {p["email"] for p in everyone if not view_as.refusal(user["email"], p["email"])}})


def _original(db: Session, character_id: int) -> str:
    """What a test copy is a copy of: "copy of Cole in The Adventure Begins"."""
    o = db.get(Character, character_id)
    there = db.get(Campaign, o.campaign_id) if o is not None and o.campaign_id else None
    return f"copy of {o.name}" + (f" in {there.name}" if there else "") if o is not None else "test copy"


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


def account(db: Session, email: str, name: str = "") -> User:
    """The person's account, made (as a member) if askdnd doesn't have one yet."""
    u = db.scalar(select(User).where(User.email == email))
    if u is None:
        u = User(email=email, name=name or email, access=access.MEMBER)
        db.add(u)
        db.flush()
        access.invalidate()
    elif u.access is None and access.level(email) is None:
        u.access = access.MEMBER  # imported, never invited: adding them to a campaign invites them (removed people stay removed)
        db.flush()
        access.invalidate()
    return u


def _role(value: str) -> str | None:
    return value if value in access.ROLES else None


@router.post("/people")
def save_person(request: Request, email: str = Form(...), role: str = Form(""), db: Session = Depends(get_db)):
    """An admin changes someone's role in this campaign (No role takes them out of it; their characters here are
    then nobody's)."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    email = email.strip().lower()
    if campaign is None or "@" not in email:
        return _back()
    u = account(db, email)
    set_role(db, u, campaign.id, _role(role))
    if _role(role) is None:
        for ch in chars.campaign_characters(db, campaign.id):
            if ch.owner_id == u.id:
                ch.owner_id = None
    db.commit()
    request.session["toast"] = "Saved" if _role(role) else f"{u.name or email} is no longer in {campaign.name}"
    return _back()


@router.post("/people/add")
def add_person(request: Request, email: str = Form(""), new_email: str = Form(""), name: str = Form(""),
               role: str = Form(access.PLAYER), db: Session = Depends(get_db)):
    """Add someone to this campaign: an account askdnd has, or a new email (which can then sign in)."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    email = (new_email or email).strip().lower()
    if campaign is None or "@" not in email:
        request.session["toast"] = "Pick someone, or enter an email address."
        return _back()
    new = db.scalar(select(User).where(User.email == email)) is None
    u = account(db, email, " ".join(name.split())[:200])
    if access.level(email) is None:
        request.session["toast"] = f"{email}'s account was removed. Bring it back on Manage › Accounts first."
        return _back()
    set_role(db, u, campaign.id, _role(role) or access.PLAYER)
    db.commit()
    request.session["toast"] = f"Added {u.name or email} to {campaign.name}" + (
        ". Add them as a Google test user too (Manage › Accounts says how)." if new else "")
    return _back()


@router.post("/characters/{character_id:int}")
def save_player(request: Request, character_id: int, user_id: str = Form(""), db: Session = Depends(get_db)):
    """Who plays this character (their notes, pins and reminders are theirs to set). One character per person in a
    campaign; their characters in other campaigns stay theirs."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    ch = db.get(Character, character_id)
    if campaign is None or ch is None or ch.campaign_id != campaign.id:
        return _back()
    player = db.get(User, int(user_id)) if user_id.isdigit() else None
    if player is not None:
        for other in chars.campaign_characters(db, campaign.id):
            if other.owner_id == player.id and other.id != ch.id:
                other.owner_id = None
    ch.owner_id = player.id if player else None
    db.commit()
    request.session["toast"] = f"{ch.name}: played by {player.name or player.email}" if player else f"{ch.name}: nobody plays it now"
    return _back()


@router.post("/test-copies")
def add_test_copies(request: Request, character_ids: list[int] = Form([]), db: Session = Depends(get_db)):
    """Test copies of the table's characters, into this test campaign (VTT 0.1). Admins only."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    if campaign is None or not campaign.is_test:
        request.session["toast"] = "Test copies are only for a test campaign (Settings › Virtual tabletop)."
        return _back()
    can = {c.id: c for c, copied in chars.copy_candidates(db, campaign.id) if not copied}
    # A copy keeps its player if they're in the test campaign, or are the admin making it (they play their own copy)
    players = {m.user_id for m in db.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign.id,
                                                                            CampaignMember.left_on.is_(None)))}
    me = db.scalar(select(User.id).where(func.lower(User.email) == user["email"].lower()))
    made = [chars.test_copy(db, can[i], campaign.id, players | {me}).name for i in character_ids if i in can]
    db.commit()
    request.session["toast"] = (f"Added test copies of {', '.join(made)}." if made else "Pick at least one character.")
    return _back()


@router.post("/characters")
def add_character(request: Request, name: str = Form(""), user_id: str = Form(""), ddb_link: str = Form(""),
                  db: Session = Depends(get_db)):
    """A new character, straight into this campaign (its D&D Beyond copy is fetched if a link is given)."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    name = " ".join(name.split())[:200]
    if campaign is None or not name:
        request.session["toast"] = "Give the character a name."
        return _back()
    player = db.get(User, int(user_id)) if user_id.isdigit() else None
    ch = Character(name=name, player_name=(player.name if player else "")[:200], owner_id=player.id if player else None)
    db.add(ch)
    db.flush()
    chars.move(db, ch, campaign.id)
    note = ""
    if ddb_link.strip():
        try:
            chars.set_ddb_link(db, ch, ddb_link)
            snap = chars.refresh(db, ch)
            note = "" if snap.status == "ok" else f" ({snap.error})"
        except ddb.DdbError as e:
            note = f" ({e})"
    db.commit()
    request.session["toast"] = f"Added {name} to {campaign.name}{note}"
    return _back()
