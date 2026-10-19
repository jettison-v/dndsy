"""Load a campaign bundle (JSON) into the database. Safe to run repeatedly:
existing records are matched and updated, never duplicated.

Renames: an entity whose alias equals an existing entity's name (same kind)
renames that entity; the old name is kept as an alias ("former name").
Relationship types are listed in app/relations.py.

Bundle shape (all sections optional except campaign):
{
  "campaign": {"slug": "...", "name": "..."},
  "members": [{"email": "...", "name": "...", "role": "dm|player", "is_admin": false}],
  "entities": [{"kind": "npc", "name": "...", "summary": "...", "aliases": ["..."],
                "quest_open": null,
                "character": {"owner_email": "...", "ddb_id": "..."}}],   # PCs only
  "relationships": [{"from": "name or alias", "type": "parent_of", "to": "...", "note": ""}],
  "glossary": [{"term": "...", "description": "...", "misheard_as": ["..."]}],
  "sessions": [{"number": 17, "played_on": "2025-03-22", "title": "...", "source": "notes"}],
  "player_notes": [{"character": "Cole", "kind": "combo|leveling|quest|general", "title": "...",
                    "status": "", "data": {...}}],                 # see app/player_notes.py; matched on title
  "form_notes": [{"character": "Cole", "form": "Polar Bear", "note": "..."}]   # Wild Shape shortlist notes
}
Player notes hold a player's own writing: keep such bundles out of git (private/).
"""

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import relations
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


def _alias_text(alias) -> str:
    return alias if isinstance(alias, str) else alias["alias"]


def _renamed(existing: dict, kind: EntityKind, item: dict) -> Entity | None:
    """An existing entity of the same kind whose name is one of the item's aliases."""
    for alias in item.get("aliases", []):
        entity = existing.get((kind, _norm(_alias_text(alias))))
        if entity is not None:
            return entity
    return None


def _import_relationships(db: Session, campaign: Campaign, items: list, counts: Counter) -> None:
    entities = list(db.scalars(select(Entity).where(Entity.campaign_id == campaign.id)))
    index = {_norm(e.name): e for e in entities}
    for e in entities:
        for a in e.aliases:
            index.setdefault(_norm(a.alias), e)
    for r in items:
        try:
            a, type_, b = r["from"], r["type"], r["to"]
        except (KeyError, TypeError) as e:
            raise BundleError("each relationship needs from, type and to") from e
        if type_ not in relations.TYPES:
            raise BundleError(f"unknown relationship type {type_!r} (use one of: {', '.join(relations.TYPES)})")
        ends = []
        for name in (a, b):
            entity = index.get(_norm(name))
            if entity is None:
                raise BundleError(f"relationship {a} {type_} {b}: no entity named {name!r}")
            ends.append(entity)
        try:
            _, created = relations.add(db, ends[0], type_, ends[1], r.get("note", ""))
        except relations.RelationError as e:
            raise BundleError(f"relationship {a} {type_} {b}: {e}") from e
        if created:
            counts["relationships added"] += 1


def import_bundle(db: Session, bundle: dict, keep_text: bool = False, batch: str | None = None) -> Counter:
    """Apply `bundle`, with every change it makes recorded in version history as one
    import (`batch`), so the whole import can be undone (app/history.py)."""
    from app import history

    with history.source("import", batch=batch or history.new_batch()):
        return _import_bundle(db, bundle, keep_text)


def _import_bundle(db: Session, bundle: dict, keep_text: bool = False) -> Counter:
    """Apply `bundle` inside the caller's transaction. Returns created/updated counts.

    keep_text: leave existing entries' description, quest status and published state
    as they are here (new entries, names, aliases and everything else still import)."""
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
            entity = _renamed(existing, kind, item)
            if entity is not None:  # an alias names an existing entity: it was renamed
                old_name = entity.name
                del existing[(kind, _norm(old_name))]
                entity.name = item["name"].strip()
                existing[key] = entity
                for a in list(entity.aliases):
                    if _norm(a.alias) == _norm(entity.name):
                        entity.aliases.remove(a)
                if _norm(old_name) not in {_norm(a.alias) for a in entity.aliases}:
                    entity.aliases.append(EntityAlias(alias=old_name, note="former name"))
                counts["entities renamed"] += 1
        is_new = entity is None
        if is_new:
            entity = Entity(campaign_id=campaign.id, kind=kind, name=item["name"].strip())
            db.add(entity)
            existing[key] = entity
            counts["entities created"] += 1
        else:
            counts["entities updated"] += 1
        if is_new or not keep_text:
            entity.status = Status.PUBLISHED  # an admin import is a deliberate, reviewed change
            if "summary" in item:
                entity.summary = item["summary"]
            if "quest_open" in item:
                entity.quest_open = item["quest_open"]
        have = {_norm(a.alias): a for a in entity.aliases}
        for alias in item.get("aliases", []):
            text, note = (alias, "") if isinstance(alias, str) else (alias["alias"], alias.get("note", ""))
            misspelling = isinstance(alias, dict) and bool(alias.get("misspelling"))
            if _norm(text) in have:
                if isinstance(alias, dict) and "misspelling" in alias and have[_norm(text)].misspelling != misspelling:
                    have[_norm(text)].misspelling = misspelling
                    counts["aliases updated"] += 1
            elif _norm(text) != _norm(entity.name):
                new = EntityAlias(alias=text.strip(), note=note, misspelling=misspelling)
                entity.aliases.append(new)
                have[_norm(text)] = new
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

    if bundle.get("relationships"):
        db.flush()
        _import_relationships(db, campaign, bundle["relationships"], counts)

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
    if bundle.get("player_notes") or bundle.get("form_notes"):
        _import_notes(db, campaign, bundle, counts)
    db.flush()  # inside the import's history source, so its changes are recorded as this import
    return counts


def _character(db: Session, campaign: Campaign, name: str) -> Character:
    ch = db.scalar(select(Character).join(Entity).where(Entity.campaign_id == campaign.id, Entity.name == name))
    if ch is None:
        raise BundleError(f"no character named {name!r}")
    return ch


def _import_notes(db: Session, campaign: Campaign, bundle: dict, counts: Counter) -> None:
    from app.models import CharacterPick, PlayerNote
    from app.player_notes import KINDS, QUEST_STATUS
    from app.wild_shape import label_for

    for item in bundle.get("player_notes") or []:
        kind, title = item.get("kind"), (item.get("title") or "").strip()[:200]
        if kind not in KINDS or not title or not isinstance(item.get("data"), dict):
            raise BundleError("each player note needs a kind (combo, leveling, quest, general), a title and data")
        ch = _character(db, campaign, item.get("character", ""))
        note = db.scalar(select(PlayerNote).where(PlayerNote.character_id == ch.id, PlayerNote.kind == kind, PlayerNote.title == title))
        if note is None:
            position = len(list(db.scalars(select(PlayerNote.id).where(PlayerNote.character_id == ch.id)))) + 1
            note = PlayerNote(character_id=ch.id, kind=kind, title=title, position=position)
            db.add(note)
            counts["player notes created"] += 1
        else:
            counts["player notes updated"] += 1
        note.data = item["data"]
        note.status = item.get("status") if item.get("status") in QUEST_STATUS else ("open" if kind == "quest" else "")
    for item in bundle.get("form_notes") or []:
        ch = _character(db, campaign, item.get("character", ""))
        ref = f"form:{item.get('form', '').strip()}"
        pick = db.scalar(select(CharacterPick).where(CharacterPick.character_id == ch.id, CharacterPick.kind == "fav", CharacterPick.ref == ref))
        if pick is None:
            pick = CharacterPick(character_id=ch.id, kind="fav", ref=ref, label=label_for(ref))
            db.add(pick)
            counts["shortlisted forms added"] += 1
        pick.note = (item.get("note") or "").strip()[:500]
        counts["form notes set"] += 1
    db.flush()
