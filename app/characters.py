"""Characters from D&D Beyond: refresh, last good copy, and the parsed summary.

`character_summary` is the seam for character briefings: it returns the parsed
sheet (app/ddb.py's summary shape) for a character, or None if it has never
been fetched. It never contains player notes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import config, ddb
from app.models import NEW_CHARACTER, CampaignCharacter, Character, CharacterItemNote, CharacterSnapshot, Entity, EntityKind

Fetch = Callable[[str], dict]
FETCH: Fetch = ddb.fetch_character  # how a sheet is read from D&D Beyond (tests put a stand-in here)


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


def move(db: Session, character: Character, campaign_id: int | None) -> CampaignCharacter | None:
    """Move a character to another campaign (or out of every campaign): its membership ends today and its story,
    events and recaps stay with the old campaign. In the new one it gets its story page from an earlier stay, or a
    new one; the DM's Wild Shape ruling starts empty there (it's a ruling per campaign)."""
    from datetime import date

    from app.models import Status

    old = character.membership
    if old is not None and old.campaign_id == campaign_id:
        return old
    if old is not None:
        old.left_on = date.today()
        db.flush()
    if campaign_id is None:
        return None
    before = next((m for m in reversed(character.memberships) if m.campaign_id == campaign_id), None)
    entity = before.entity if before else None
    if entity is None:
        entity = Entity(campaign_id=campaign_id, kind=EntityKind.PC, name=character.name, status=Status.PUBLISHED)
        db.add(entity)
        db.flush()
    m = CampaignCharacter(campaign_id=campaign_id, entity=entity)
    character.memberships.append(m)
    db.flush()
    return m


def test_copy(db: Session, original: Character, campaign_id: int, players: set[int] = frozenset()) -> Character:
    """A test copy of a character for a test campaign (VTT 0.1): the same D&D Beyond sheet and its last good copy, with
    its own play state, so trying VTT pieces never touches the real character. Its player's notes, pins and
    reminders stay with the original. It keeps its player only if they're among `players` (in the test campaign)."""
    copy = Character(name=original.name, owner_id=original.owner_id if original.owner_id in players else None, player_name=original.player_name, ddb_id=original.ddb_id,
                     ddb_campaign_id=original.ddb_campaign_id, copy_of_id=original.id)
    db.add(copy)
    db.flush()
    if original.snapshot is not None:
        o = original.snapshot
        db.add(CharacterSnapshot(character_id=copy.id, fetched_at=o.fetched_at, raw=o.raw, summary=o.summary, status=o.status, error=o.error))
    move(db, copy, campaign_id)
    db.flush()
    return copy


def copy_candidates(db: Session, campaign_id: int) -> list[tuple[Character, bool]]:
    """Characters in other campaigns that aren't test ones, each with whether this campaign has a test copy of it."""
    from app.models import Campaign

    copied = {c.copy_of_id for c in campaign_characters(db, campaign_id) if c.copy_of_id}
    rows = db.scalars(select(Character).join(CampaignCharacter).join(Campaign, Campaign.id == CampaignCharacter.campaign_id)
                      .where(CampaignCharacter.left_on.is_(None), CampaignCharacter.campaign_id != campaign_id,
                             Campaign.is_test.is_(False), Character.copy_of_id.is_(None))
                      .order_by(Character.name))
    return [(c, c.id in copied) for c in rows]


def ddb_campaigns(db: Session) -> dict[str, str]:
    """{D&D Beyond campaign id: its name} for the campaigns the characters' D&D Beyond copies say they're in."""
    out = {}
    for ch in db.scalars(select(Character).where(Character.ddb_campaign_id.is_not(None))):
        raw = (ch.snapshot.raw or {}) if ch.snapshot else {}
        out.setdefault(ch.ddb_campaign_id, ((raw.get("campaign") or {}).get("name") or "").strip())
    return out


@dataclass
class Read:
    """One read of a character's D&D Beyond sheet, parsed, made without the database (`read`): `at` when it started,
    and either the sheet (`raw`, `summary`, its item `notes`) or why not (`error`)."""

    at: datetime
    raw: dict | None = None
    summary: dict | None = None
    notes: list = field(default_factory=list)
    error: str = ""


def read(ddb_id: str | None, fetch: Fetch | None = None) -> Read:
    """Read and parse a sheet from D&D Beyond. Touches no database, so call it with none held (`read_released`)."""
    at = datetime.now(UTC)
    try:
        if not ddb_id:
            raise ddb.DdbError("No D&D Beyond link yet.")
        data = (fetch or FETCH)(ddb_id)
        notes = ddb.item_notes(data)
        raw = ddb.sanitize(data)
        return Read(at, raw, ddb.parse_character(raw), notes)
    except ddb.DdbError as e:
        return Read(at, error=str(e))


def read_released(db: Session, character: Character, fetch: Fetch | None = None) -> Read:
    """Read the sheet with this request's database let go: what it did so far is committed (its connection goes back to
    the pool and its locks are released), then D&D Beyond is asked. D&D Beyond can take 15 seconds; holding a
    connection and a character's lock through that ran beta out of connections (Sentry ASKDND-V2-7, architecture review
    2026-11-02). A caller that held a lock takes it again before `store` and checks what changed meanwhile."""
    ddb_id = character.ddb_id  # (before the commit: reading it after could load the row again, opening a transaction)
    db.commit()
    return read(ddb_id, fetch)


def store(db: Session, character: Character, got: Read) -> CharacterSnapshot:
    """Keep a read as the character's copy. On success the snapshot is replaced; on any failure only its status and
    error change, so the last good copy stays. A read older than the copy already kept (another request stored a newer
    one while this one waited for D&D Beyond) changes nothing."""
    snap = character.snapshot
    if snap is None:
        snap = CharacterSnapshot(character=character, status="ok", error="")
        db.add(snap)
    elif snap in db and not db.is_modified(snap):
        db.refresh(snap)  # (as it is now: another request may have stored a newer copy)
    if snap.fetched_at is not None and snap.fetched_at > got.at:
        return snap
    snap.attempted_at = got.at
    if got.raw is None:
        snap.status, snap.error = "error", got.error
    else:
        raw, summary = got.raw, got.summary
        if config.DDB_BRIDGE:  # the bridge's log of what changed on D&D Beyond, whichever read saw it
            from app import ddb_bridge  # (it builds on this module)
            if ddb_bridge.on_for(db, character):
                ddb_bridge.seen(db, character, snap.raw, raw, summary)
                from app import creature_hp  # (its routes read characters)

                creature_hp.keep_max(db, character, summary)
                from app import companions  # (a familiar form askdnd added: tied to its new creature)

                companions.adopt(db, character, summary, raw)
        from app import level_up  # (its route reads characters through item_use)

        if (news := level_up.changes(snap.summary, summary)):
            character.level_up = level_up.merged(character.level_up, news)
        snap.raw, snap.summary, snap.fetched_at = raw, summary, got.at
        character.ddb_campaign_id = ddb.campaign_id(raw)
        snap.status, snap.error = "ok", ""
        _store_item_notes(db, character, got.notes)
        if character.name == NEW_CHARACTER and summary.get("name"):  # only then: a table can name a character its own way
            character.name = summary["name"][:200]
            if character.membership is not None:
                character.membership.entity.name = character.name
    db.flush()
    return snap


def refresh(db: Session, character: Character, fetch: Fetch | None = None) -> CharacterSnapshot:
    """Read the character from D&D Beyond and keep it, in this request's transaction (an admin's button, adding a
    character). Anything that runs often or holds a lock reads with `read_released` and then `store`s."""
    return store(db, character, read(character.ddb_id, fetch))


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


def refresh_all(db: Session, campaign_id: int, fetch: Fetch | None = None) -> tuple[int, list[str]]:
    """Refresh every linked character. Returns (how many worked, names that failed)."""
    ok, failed = 0, []
    for ch in campaign_characters(db, campaign_id):
        if not ch.ddb_id:
            continue
        if store(db, ch, read_released(db, ch, fetch)).status == "ok":  # (one at a time, the database let go while each is read)
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


def reparse_old(db: Session) -> None:
    """Store a new parser's summaries (once, at startup: app/main.py), so a page doesn't parse each whole sheet on every
    load until its next refresh. Quietly: nothing changed on anyone's sheet. A refresh meanwhile already holds a new
    summary, so it's left alone."""
    old = CharacterSnapshot.summary["parser_version"].as_integer().is_distinct_from(ddb.PARSER_VERSION)
    for sid in db.scalars(select(CharacterSnapshot.id).where(CharacterSnapshot.summary.is_not(None), CharacterSnapshot.raw.is_not(None), old)).all():
        try:
            summary = ddb.parse_character(db.scalar(select(CharacterSnapshot.raw).where(CharacterSnapshot.id == sid)))
        except ddb.DdbError:
            continue  # (character_summary keeps using the stored one)
        db.execute(update(CharacterSnapshot).where(CharacterSnapshot.id == sid, old).values(summary=summary))
        db.commit()
