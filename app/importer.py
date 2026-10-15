"""Load a campaign bundle (JSON) into the database. Safe to run repeatedly:
existing records are matched and updated, never duplicated.

Bundle shape (all sections optional except campaign):
{
  "campaign": {"slug": "...", "name": "..."},
  "members": [{"email": "...", "name": "...", "role": "dm|player", "is_admin": false}],
  "entities": [{"kind": "npc", "name": "...", "summary": "...", "aliases": ["..."],
                "quest_open": null,
                "character": {"owner_email": "...", "ddb_id": "..."}}],   # PCs only
  "glossary": [{"term": "...", "description": "...", "misheard_as": ["..."]}],
  "sessions": [{"number": 17, "played_on": "2025-03-22", "title": "...", "source": "notes"}]
}
"""

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignMember,
    Character,
    Entity,
    EntityAlias,
    EntityKind,
    GameSession,
    GlossaryTerm,
    Role,
    Status,
    User,
)


class BundleError(ValueError):
    pass


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def import_bundle(db: Session, bundle: dict) -> Counter:
    """Apply `bundle` inside the caller's transaction. Returns created/updated counts."""
    counts: Counter = Counter()
    try:
        c = bundle["campaign"]
        slug, name = c["slug"].strip(), c["name"].strip()
    except (KeyError, AttributeError, TypeError) as e:
        raise BundleError("bundle needs campaign.slug and campaign.name") from e

    campaign = db.scalar(select(Campaign).where(Campaign.slug == slug))
    if campaign is None:
        campaign = Campaign(slug=slug, name=name)
        db.add(campaign)
        counts["campaigns created"] += 1
    else:
        campaign.name = name
    if c.get("dm_name"):
        campaign.dm_name = c["dm_name"]
    db.flush()

    users: dict[str, User] = {}
    for m in bundle.get("members", []):
        email = m["email"].strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, name=m.get("name") or email)
            db.add(user)
            db.flush()
            counts["users created"] += 1
        if "name" in m:
            user.name = m["name"]
        if "is_admin" in m:
            user.is_admin = bool(m["is_admin"])
        users[email] = user
        role = Role(m["role"])
        member = db.scalar(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign.id, CampaignMember.user_id == user.id
            )
        )
        if member is None:
            db.add(CampaignMember(campaign_id=campaign.id, user_id=user.id, role=role))
            counts["members created"] += 1
        else:
            member.role = role

    existing = {
        (e.kind, _norm(e.name)): e
        for e in db.scalars(select(Entity).where(Entity.campaign_id == campaign.id))
    }
    for item in bundle.get("entities", []):
        kind = EntityKind(item["kind"])
        key = (kind, _norm(item["name"]))
        entity = existing.get(key)
        if entity is None:
            entity = Entity(campaign_id=campaign.id, kind=kind, name=item["name"].strip())
            db.add(entity)
            existing[key] = entity
            counts["entities created"] += 1
        else:
            counts["entities updated"] += 1
        entity.status = Status.PUBLISHED  # an admin import is a deliberate, reviewed change
        if "summary" in item:
            entity.summary = item["summary"]
        if "quest_open" in item:
            entity.quest_open = item["quest_open"]
        have = {_norm(a.alias) for a in entity.aliases}
        for alias in item.get("aliases", []):
            text, note = (alias, "") if isinstance(alias, str) else (alias["alias"], alias.get("note", ""))
            if _norm(text) not in have and _norm(text) != _norm(entity.name):
                entity.aliases.append(EntityAlias(alias=text.strip(), note=note))
                have.add(_norm(text))
                counts["aliases added"] += 1
        db.flush()
        if "character" in item:
            if kind != EntityKind.PC:
                raise BundleError(f"{item['name']}: only pc entities can have character details")
            ch = db.scalar(select(Character).where(Character.entity_id == entity.id))
            if ch is None:
                ch = Character(entity_id=entity.id)
                db.add(ch)
                counts["characters created"] += 1
            details = item["character"]
            if details.get("player_name"):
                ch.player_name = details["player_name"]
            if details.get("ddb_id"):
                ch.ddb_id = str(details["ddb_id"])
            owner_email = (details.get("owner_email") or "").strip().lower()
            if owner_email:
                owner = users.get(owner_email) or db.scalar(select(User).where(User.email == owner_email))
                if owner is None:
                    raise BundleError(f"{item['name']}: owner {owner_email} is not a member")
                ch.owner_id = owner.id

    for g in bundle.get("glossary", []):
        term = db.scalar(
            select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign.id, GlossaryTerm.term == g["term"])
        )
        if term is None:
            term = GlossaryTerm(campaign_id=campaign.id, term=g["term"], misheard_as=[])
            db.add(term)
            counts["glossary terms created"] += 1
        if "description" in g:
            term.description = g["description"]
        merged = list(dict.fromkeys([*(term.misheard_as or []), *g.get("misheard_as", [])]))
        term.misheard_as = merged

    for s in bundle.get("sessions", []):
        played_on = date.fromisoformat(s["played_on"]) if s.get("played_on") else None
        number = s.get("number")
        if number is None and played_on is None:
            raise BundleError("each session needs a number or a played_on date")
        q = select(GameSession).where(GameSession.campaign_id == campaign.id)
        q = q.where(GameSession.number == number) if number is not None else q.where(GameSession.played_on == played_on)
        gs = db.scalar(q)
        if gs is None:
            gs = GameSession(campaign_id=campaign.id, number=number, source=s.get("source", "notes"))
            db.add(gs)
            counts["sessions created"] += 1
        gs.played_on = played_on or gs.played_on
        gs.title = s.get("title", gs.title or "")

    db.flush()
    return counts
