"""Characters from D&D Beyond: refresh, last good copy, and the parsed summary.

`character_summary` is the seam for character briefings: it returns the parsed
sheet (app/ddb.py's summary shape) for a character, or None if it has never
been fetched. It never contains player notes.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ddb
from app.models import CampaignCharacter, Character, CharacterItemNote, CharacterSnapshot, Entity

Fetch = Callable[[str], dict]


def campaign_characters(db: Session, campaign_id: int) -> list[Character]:
    """The characters in this campaign now, by name."""
    return list(db.scalars(select(Character).join(CampaignCharacter)
                           .where(CampaignCharacter.campaign_id == campaign_id, CampaignCharacter.left_on.is_(None))
                           .order_by(Character.name)))


def for_entity(db: Session, entity_id: int) -> Character | None:
    """The character whose story page this is (in any campaign, now or before)."""
    return db.scalar(select(Character).join(CampaignCharacter).where(CampaignCharacter.entity_id == entity_id))


def join(db: Session, character: Character, entity: Entity) -> CampaignCharacter:
    """Put a character in its story page's campaign (it can be in one campaign at a time)."""
    if character.membership is not None:
        raise ValueError(f"{character.name} is already in a campaign.")
    m = CampaignCharacter(campaign_id=entity.campaign_id, entity=entity)
    character.memberships.append(m)
    character.name = character.name or entity.name
    db.flush()
    return m


def set_ddb_link(db: Session, character: Character, value: str) -> None:
    """Save the character's D&D Beyond id from a pasted link or id. Raises DdbError."""
    ddb_id = ddb.ddb_id_from(value)
    if not ddb_id:
        raise ddb.DdbError("Paste the character's D&D Beyond link, like https://www.dndbeyond.com/characters/12345678.")
    if ddb_id != character.ddb_id and character.snapshot is not None:
        db.delete(character.snapshot)  # a different character: the old copy no longer applies
        character.snapshot = None
    character.ddb_id = ddb_id
    db.flush()


def refresh(db: Session, character: Character, fetch: Fetch = ddb.fetch_character) -> CharacterSnapshot:
    """Fetch and parse the character. On success the snapshot is replaced; on any
    failure only its status and error change, so the last good copy stays."""
    snap = character.snapshot
    if snap is None:
        snap = CharacterSnapshot(character=character, status="ok", error="")
        db.add(snap)
    now = datetime.now(UTC)
    snap.attempted_at = now
    try:
        if not character.ddb_id:
            raise ddb.DdbError("No D&D Beyond link yet.")
        data = fetch(character.ddb_id)
        notes = ddb.item_notes(data)
        raw = ddb.sanitize(data)
        summary = ddb.parse_character(raw)
    except ddb.DdbError as e:
        snap.status, snap.error = "error", str(e)
    else:
        snap.raw, snap.summary, snap.fetched_at = raw, summary, now
        character.ddb_campaign_id = ddb.campaign_id(raw)
        snap.status, snap.error = "ok", ""
        _store_item_notes(db, character, notes)
    db.flush()
    return snap


def _store_item_notes(db: Session, character: Character, notes: list[dict]) -> None:
    """Make the stored item notes match D&D Beyond's (added, changed and deleted)."""
    have = {n.item_ref: n for n in db.scalars(select(CharacterItemNote).where(CharacterItemNote.character_id == character.id))}
    for n in notes:
        row = have.pop(n["ref"], None) or CharacterItemNote(character_id=character.id, item_ref=n["ref"][:80])
        row.item_name, row.note = n["name"][:200], n["note"]
        db.add(row)
    for gone in have.values():
        db.delete(gone)


def item_notes(db: Session, character: Character) -> dict[str, str]:
    """{item key: note}: players' notes on their items (everyone at the table sees them)."""
    return {n.item_ref: n.note for n in db.scalars(select(CharacterItemNote).where(CharacterItemNote.character_id == character.id))}


def refresh_all(db: Session, campaign_id: int, fetch: Fetch = ddb.fetch_character) -> tuple[int, list[str]]:
    """Refresh every linked character. Returns (how many worked, names that failed)."""
    ok, failed = 0, []
    for ch in campaign_characters(db, campaign_id):
        if not ch.ddb_id:
            continue
        if refresh(db, ch, fetch).status == "ok":
            ok += 1
        else:
            failed.append(ch.name)
    return ok, failed


def character_summary(character: Character) -> dict | None:
    """The parsed D&D Beyond sheet for this character (last good copy), or None.

    Summaries made by an older parser are re-parsed from the stored copy, so
    parser improvements apply without a refresh; if re-parsing fails, the
    stored summary is used as it is.
    """
    snap = character.snapshot
    if snap is None or snap.summary is None:
        return None
    if snap.summary.get("parser_version") != ddb.PARSER_VERSION and snap.raw:
        try:
            return ddb.parse_character(snap.raw)
        except ddb.DdbError:
            pass
    return snap.summary
