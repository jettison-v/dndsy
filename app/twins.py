"""A test copy of your character (temporary; Brett, 2026-11-05): `/twin`, step by step, for each player at a real table,
how to copy their character on D&D Beyond into VTT test, where a test account claims it as its twin for the live test
(docs/testing-setup.md; the twins step on the roadmap). Every link is the player's own: their sheet, their account's My
Characters, VTT test's invite and campaign page.

Steps tick themselves where askdnd can see them: the extension in this browser (app.js "a test copy"), and what VTT test
lists on D&D Beyond (every VTT test sheet askdnd reads names the campaign's characters and who owns each: the copy shows
up under its player's account once it joins, unassigned once they let it go, under a test account once Brett claims it).
An admin also sees where everyone's copy stands. Delete this module, twin.html and tests/test_twins.py once the twins are
claimed.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, web
from app.auth import current_user, is_admin
from app.db import get_db
from app.models import Campaign, CampaignCharacter, Character, CharacterSnapshot, User
from app.templating import templates

router = APIRouter()
FRESH = timedelta(minutes=1)  # (reading VTT test again for the page at most this often)


def test_table(db: Session) -> Campaign | None:
    """VTT test: the test campaign linked to a D&D Beyond campaign."""
    return db.scalar(select(Campaign).where(Campaign.is_test.is_(True), Campaign.ddb_campaign_id.is_not(None)).order_by(Campaign.id))


def listed(db: Session, test: Campaign, refresh: bool = False) -> tuple[list[dict], datetime | None]:
    """VTT test's characters as D&D Beyond lists them, from the newest copy of any of its sheets, read again first when
    `refresh` (at most every FRESH). ([{characterId, characterName, userId, username, isAssigned}], when it was read)."""
    rows = db.execute(select(Character, CharacterSnapshot).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                      .join(CharacterSnapshot, CharacterSnapshot.character_id == Character.id)
                      .where(CampaignCharacter.campaign_id == test.id, CampaignCharacter.left_on.is_(None), Character.ddb_id.is_not(None),
                             Character.copy_of_id.is_(None))).all()
    ours = [(ch, s) for ch, s in rows if str(((s.raw or {}).get("campaign") or {}).get("id")) == str(test.ddb_campaign_id)]
    if not ours:
        return [], None
    ch, snap = max(ours, key=lambda x: x[1].fetched_at or datetime.min.replace(tzinfo=UTC))
    if refresh:
        from app.live import maybe_refresh

        maybe_refresh(db, ch, FRESH)
        db.refresh(snap)
    return list(((snap.raw or {}).get("campaign") or {}).get("characters") or []), snap.fetched_at


COPY = "Copy of "  # (D&D Beyond names a copy "Copy of Cole Lockhard": Brett, Nov 5)


def bare(name: str | None) -> str:
    """A character's name as D&D Beyond lists it, without the "Copy of " a copy starts with, for comparing."""
    name = (name or "").strip()
    return (name[len(COPY):] if name.lower().startswith(COPY.lower()) else name).strip().lower()


def where(real: Character, entries: list[dict]) -> dict:
    """Where a character's copy stands in VTT test: {"joined", "unassigned", "claimed"} (each the D&D Beyond entry, or
    None). A copy carries its character's name ("Copy of …" until Brett renames it) and, until claimed, its player's
    account."""
    raw = (real.snapshot.raw if real.snapshot else None) or {}
    owner = raw.get("userId")
    names = tuple(n.strip().lower() for n in (raw.get("name"), real.name) if n and n.strip())  # (D&D Beyond's, askdnd's: "Cole (twin)")
    copies = [e for e in entries if names and str(e.get("characterId")) != str(real.ddb_id) and bare(e.get("characterName")).startswith(names)]
    mine = next((e for e in copies if e.get("userId") == owner), None)
    claimed = next((e for e in copies if e.get("userId") != owner), None)
    return {"joined": mine or claimed, "unassigned": claimed or (mine if mine and mine.get("isAssigned") is False else None), "claimed": claimed}


def playing(db: Session, user_id: int | None = None) -> list[Character]:
    """The characters played at real tables (not test campaigns) that have a D&D Beyond sheet: one person's, or everyone's."""
    q = (select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id).join(Campaign, Campaign.id == CampaignCharacter.campaign_id)
         .where(CampaignCharacter.left_on.is_(None), Campaign.is_test.is_(False), Character.ddb_id.is_not(None), Character.copy_of_id.is_(None))
         .order_by(Character.name))
    if user_id is not None:
        q = q.where(Character.owner_id == user_id)
    return list(db.scalars(q))


@router.get("/twin")
def twin_page(request: Request, db: Session = Depends(get_db)):
    user, refused = web.require(request)
    if refused:
        return refused
    me = db.scalar(select(User).where(User.email == user["email"].lower()))
    test = test_table(db)
    entries, read_at = listed(db, test, refresh=True) if test else ([], None)

    def card(ch: Character) -> dict:
        raw = (ch.snapshot.raw if ch.snapshot else None) or {}
        return {"c": ch, "account": raw.get("username") or "", "sheet": f"https://www.dndbeyond.com/characters/{ch.ddb_id}",
                "ddb_name": raw.get("name") or ch.name, "at": where(ch, entries)}

    mine = [card(c) for c in playing(db, me.id)] if me else []
    everyone = [card(c) | {"player": c.owner.name if c.owner else ""} for c in playing(db)] if is_admin(current_user(request)) else []
    return templates.TemplateResponse(request, "twin.html", {
        "mine": mine, "everyone": everyone, "test": test, "read_at": read_at, "invite": config.VTT_TEST_INVITE_URL,
        "extension": config.BRIDGE_EXTENSION_URL,
        "campaign_url": f"https://www.dndbeyond.com/campaigns/{test.ddb_campaign_id}" if test else ""})
