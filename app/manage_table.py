"""Manage › Table (/c/<campaign>/manage/table): who's at the table, in one list (Brett, 2026-10-30,
docs/mockups/the-table.html). A person and their character are one row; the campaign's DM and admins change it.

- **Add to the table** does a person, a character, or both in one step. Someone with an account can be added by the DM;
  a brand-new email, which lets someone sign in to askdnd, stays an admin's.
- **A row** holds everything about that seat: role, what they play, the D&D Beyond link, refresh, View as, Move to
  (admins) and Remove.
- **Remove never deletes.** A person's membership or a character's stay in the campaign ends today; their story, rolls
  and notes stay, and Left the table has Bring back.
- What each role can do: the chart from app/access.py.

Who may sign in at all, and who's an admin, is askdnd-wide: Manage › Accounts (app/manage_accounts.py).
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import view_as
from app import access, config, ddb, entities, web
from app import characters as chars
from app.auth import can_run_table, can_see_table, is_admin, is_reviewer
from app.db import get_db
from app.models import NEW_CHARACTER, Campaign, CampaignCharacter, CampaignMember, Character, Role, User
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


def _left(db: Session, campaign_id: int, here: set[str]) -> list[dict]:
    """Who left this campaign and isn't back: people, and characters that aren't in another campaign now (a character
    moved elsewhere didn't leave the table, it's playing there)."""
    out, seen = [], set()
    rows = db.execute(select(CampaignMember, User).join(User, User.id == CampaignMember.user_id)
                      .where(CampaignMember.campaign_id == campaign_id, CampaignMember.left_on.is_not(None)).order_by(CampaignMember.left_on.desc()))
    for m, u in rows:
        if u.email.lower() not in here and u.id not in seen:
            seen.add(u.id)
            out.append({"kind": "person", "name": u.name if u.name and u.name != u.email else u.email, "email": u.email, "on": m.left_on, "role": m.role})
    seen = set()
    for m in db.scalars(select(CampaignCharacter).where(CampaignCharacter.campaign_id == campaign_id, CampaignCharacter.left_on.is_not(None))
                        .order_by(CampaignCharacter.left_on.desc())):
        if m.character_id not in seen and m.character.membership is None:
            seen.add(m.character_id)
            out.append({"kind": "character", "name": m.character.name, "id": m.character_id, "on": m.left_on})
    return out


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
    played = {c.id for p in everyone for c in p["plays"]}
    seats = [{"person": p, "character": c} for p in everyone for c in (p["plays"] or [None])]
    return templates.TemplateResponse(request, "manage_table.html", {
        "campaign": campaign, "characters": characters, "people": everyone, "names": names,
        "running": [s for s in seats if s["person"]["role"] != access.PLAYER], "playing": [s for s in seats if s["person"]["role"] == access.PLAYER],
        "free": [c for c in characters if c.id not in played], "left": _left(db, campaign.id, in_campaign),
        "others": [c for c in db.scalars(select(Campaign).order_by(Campaign.name)) if c.id != campaign.id] if is_admin(user) else [],
        "can_add_new": is_admin(user),
        "classes": {c.id: _classes(c) for c in characters},
        # A test campaign (VTT 0.1) can add test copies of the table's characters
        "copyable": chars.copy_candidates(db, campaign.id) if campaign.is_test else [],
        "originals": {c.copy_of_id: _original(db, c.copy_of_id) for c in characters if c.copy_of_id},
        "accounts": [u for u in db.scalars(select(User).order_by(User.name))
                     if u.email.lower() not in in_campaign and access.level(u.email) is not None],
        "can_change": can_run_table(user, campaign.id), "can_refresh": is_reviewer(user), "roles": access.ROLES, "role_labels": access.ROLE_LABELS,
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
    """Someone's role in this campaign, or none: Remove from the table. Their characters here are then nobody's, and
    Left the table brings them back."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    email = email.strip().lower()
    if campaign is None or "@" not in email:
        return _back()
    if _role(role) is None and email == user["email"].lower() and not is_admin(user):
        request.session["toast"] = web.notice("You can't remove yourself: ask an admin.", "warn")
        return _back()
    u = account(db, email)
    set_role(db, u, campaign.id, _role(role))
    if _role(role) is None:
        for ch in chars.campaign_characters(db, campaign.id):
            if ch.owner_id == u.id:
                ch.owner_id = None
    db.commit()
    request.session["toast"] = "Saved" if _role(role) else f"{u.name or email} left {campaign.name}"
    return _back()


@router.post("/people/back")
def bring_person_back(request: Request, email: str = Form(""), role: str = Form(access.PLAYER), db: Session = Depends(get_db)):
    """Left the table › Bring back: in their old role, with no character until they're given one."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    u = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if campaign is not None and u is not None:
        set_role(db, u, campaign.id, _role(role) or access.PLAYER)
        db.commit()
        request.session["toast"] = f"{u.name or u.email} is back in {campaign.name}"
    return _back()


@router.post("/plays")
def save_plays(request: Request, email: str = Form(""), character_id: str = Form(""), db: Session = Depends(get_db)):
    """What someone plays here, from their row: one character per person in a campaign."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    u = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if campaign is None or u is None:
        return _back()
    here = chars.campaign_characters(db, campaign.id)
    ch = next((c for c in here if str(c.id) == character_id), None)
    for other in here:
        if other.owner_id == u.id and other is not ch:
            other.owner_id = None
    if ch is not None:
        ch.owner_id = u.id
    db.commit()
    request.session["toast"] = f"{u.name or u.email} plays {ch.name}" if ch else f"{u.name or u.email} has no character"
    return _back()


@router.post("/add")
def add(request: Request, email: str = Form(""), new_email: str = Form(""), name: str = Form(""), role: str = Form(access.PLAYER),
        ddb_link: str = Form(""), char_name: str = Form(""), db: Session = Depends(get_db)):
    """Add to the table: a person (an account askdnd has, or a new email), a character (a D&D Beyond link, or a name), or
    both, in one step."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    email = (new_email or email).strip().lower()
    char_name, ddb_link = " ".join(char_name.split())[:200], ddb_link.strip()
    if campaign is None or not (email or ddb_link or char_name) or (email and "@" not in email):
        request.session["toast"] = web.notice("Pick someone, enter an email address, or paste a character's link.", "warn")
        return _back()
    u, new = None, False
    if email:
        new = db.scalar(select(User).where(User.email == email)) is None
        if new and not is_admin(user):
            request.session["toast"] = web.notice("Only an admin can add someone new to askdnd. Pick someone who has an account.", "warn")
            return _back()
        u = account(db, email, " ".join(name.split())[:200])
        if access.level(email) is None:
            request.session["toast"] = web.notice(f"{email}'s account was removed. Bring it back on Manage › Accounts first.", "warn")
            return _back()
        set_role(db, u, campaign.id, _role(role) or access.PLAYER)
    note, added = "", (u.name or email) if u else ""
    if ddb_link or char_name:
        ch = Character(name=char_name or NEW_CHARACTER, player_name=(u.name if u else "")[:200], owner_id=u.id if u else None)
        db.add(ch)
        db.flush()
        chars.move(db, ch, campaign.id)
        if u is not None:
            for other in chars.campaign_characters(db, campaign.id):
                if other.owner_id == u.id and other.id != ch.id:
                    other.owner_id = None
        if ddb_link:
            try:
                chars.set_ddb_link(db, ch, ddb_link)
                snap = chars.refresh(db, ch)
                note = "" if snap.status == "ok" else f" ({snap.error})"
            except ddb.DdbError as e:
                note = f" ({e})"
        added = f"{added} with {ch.name}" if added else ch.name
    db.commit()
    request.session["toast"] = f"Added {added} to {campaign.name}{note}" + (". Add them as a Google test user too (Manage › Accounts says how)." if new else "")
    return _back()


@router.post("/characters/{character_id:int}/remove")
def remove_character(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Remove from the table: it leaves this campaign and the fight; its story, rolls and notes stay, and nobody plays
    it. Left the table brings it back."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    ch = db.get(Character, character_id)
    if campaign is not None and ch is not None and ch.campaign_id == campaign.id:
        name = ch.name
        ch.owner_id = None
        chars.move(db, ch, None)
        db.commit()
        request.session["toast"] = f"{name} left {campaign.name}"
    return _back()


@router.post("/characters/{character_id:int}/back")
def bring_character_back(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Left the table › Bring back: at the table again with its story page, and nobody playing it yet."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    ch = db.get(Character, character_id)
    if campaign is not None and ch is not None and ch.membership is None:
        chars.move(db, ch, campaign.id)
        db.commit()
        request.session["toast"] = f"{ch.name} is back in {campaign.name}"
    return _back()


@router.post("/characters/{character_id:int}")
def save_player(request: Request, character_id: int, user_id: str = Form(""), db: Session = Depends(get_db)):
    """Who plays this character (their notes, pins and reminders are theirs to set). One character per person in a
    campaign; their characters in other campaigns stay theirs."""
    user, denied = web.require(request, can_run_table, DENIED)
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


@router.post("/characters/{character_id:int}/name")
def save_name(request: Request, character_id: int, name: str = Form(""), db: Session = Depends(get_db)):
    """A character's name: until now only its story page could change it."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    ch = db.get(Character, character_id)
    if campaign is None or ch is None or ch.campaign_id != campaign.id:
        return _back()
    try:
        entities.rename(ch.membership.entity, name)
    except entities.EntityError as e:
        request.session["toast"] = web.notice(str(e), "warn")
        return _back()
    db.commit()
    request.session["toast"] = f"Renamed {ch.name}"
    return _back()


@router.post("/test-copies")
def add_test_copies(request: Request, character_ids: list[int] = Form([]), db: Session = Depends(get_db)):
    """Test copies of the table's characters, into this test campaign (VTT 0.1). Admins only."""
    user, denied = web.require(request, can_run_table, DENIED)
    if denied:
        return denied
    campaign = web.campaign(db)
    if campaign is None or not campaign.is_test:
        request.session["toast"] = web.notice("Test copies are only for a test campaign (Manage › Settings › Test campaign).", "warn")
        return _back()
    can = {c.id: c for c, copied in chars.copy_candidates(db, campaign.id) if not copied}
    # A copy keeps its player if they're in the test campaign, or are the admin making it (they play their own copy)
    players = {m.user_id for m in db.scalars(select(CampaignMember).where(CampaignMember.campaign_id == campaign.id,
                                                                            CampaignMember.left_on.is_(None)))}
    me = db.scalar(select(User.id).where(func.lower(User.email) == user["email"].lower()))
    left = {c.copy_of_id: c for c in db.scalars(select(Character).join(CampaignCharacter).where(CampaignCharacter.campaign_id == campaign.id, Character.copy_of_id.is_not(None)))
            if c.membership is None}  # (one that left comes back, not a second copy)
    made = []
    for i in character_ids:
        if i in can and i in left:
            chars.move(db, left[i], campaign.id)
            made.append(left[i].name)
        elif i in can:
            made.append(chars.test_copy(db, can[i], campaign.id, players | {me}).name)
    db.commit()
    request.session["toast"] = (f"Added test copies of {', '.join(made)}." if made else web.notice("Pick at least one character.", "warn"))
    return _back()
