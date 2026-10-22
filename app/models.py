"""Campaign data model. See docs/ARCHITECTURE.md ("Data").

Privacy: there is deliberately no table for transcripts. Only the extracted
story (recaps, events, entities) is stored.
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(cls):
    return Enum(cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class Role(StrEnum):
    """A person's role in one campaign (app/access.py)."""

    DM = "dm"  # includes Reviewer; never sees the notes of the campaign's characters
    REVIEWER = "reviewer"
    PLAYER = "player"


class EntityKind(StrEnum):
    PC = "pc"  # player character (details in `characters`)
    NPC = "npc"
    PLACE = "place"
    FACTION = "faction"
    QUEST = "quest"
    ITEM = "item"
    CREATURE = "creature"
    OTHER = "other"


class Status(StrEnum):
    DRAFT = "draft"  # AI output, not yet reviewed
    PUBLISHED = "published"  # reviewed by Brett, visible to the table


class EventKind(StrEnum):
    EVENT = "event"
    REVEAL = "reveal"  # new lore or information learned
    DECISION = "decision"
    LOOT = "loot"
    THEORY = "theory"  # speculation; recaps list these as open threads, not facts


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Timestamped, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercase
    name: Mapped[str] = mapped_column(String(200))
    # Their tool role, set on Manage › People: member | admin, or "removed" (can't sign in). None = not set in the
    # app (people imported but never invited); the Railway lists decide. Roles at a table are in campaign_members.
    access: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_help: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # help lines they pressed "Got it" on (help_pages.HELP)


class Campaign(Timestamped, Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    dm_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    monthly_limit_usd: Mapped[float | None] = mapped_column(nullable=True)  # Claude spending cap (app/spending.py); blank = none
    ddb_campaign_id: Mapped[str | None] = mapped_column(String(40))  # the matching campaign on D&D Beyond, if known
    members: Mapped[list["CampaignMember"]] = relationship(back_populates="campaign")


class CampaignMember(Base):
    """A person's role in one campaign (the DM of one campaign may play in another). Leaving keeps the row with
    left_on set, so who was at the table stays answerable; one current row per person and campaign."""

    __tablename__ = "campaign_members"
    __table_args__ = (
        Index("campaign_members_one_current", "campaign_id", "user_id", unique=True, postgresql_where=sql("left_on IS NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(_enum(Role))
    joined_on: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    left_on: Mapped[date | None] = mapped_column(Date)
    campaign: Mapped[Campaign] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Entity(Timestamped, Base):
    """Anything with a name in the story: PCs, NPCs, places, factions, quests, items."""

    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    kind: Mapped[EntityKind] = mapped_column(_enum(EntityKind))
    name: Mapped[str] = mapped_column(String(200))  # current canonical name
    summary: Mapped[str] = mapped_column(Text, default="")
    quest_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # quests only
    status: Mapped[Status] = mapped_column(_enum(Status), default=Status.DRAFT)
    # "Regenerate description": Claude's proposed rewrite awaiting a reviewer, and
    # the summary it replaced once accepted (for Undo).
    draft_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_fact_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # facts Claude worked into draft_summary
    # Who wrote the description last: "claude", a person's name, or "" (not known). A person's words are kept: Claude's
    # later updates arrive as marked-up edits of them (content workflows step 3).
    summary_by: Mapped[str] = mapped_column(String(200), default="", server_default="")
    aliases: Mapped[list["EntityAlias"]] = relationship(cascade="all, delete-orphan")

    @property
    def written_by_person(self) -> str:
        """The person who wrote the description last ("" when Claude did, or it isn't known)."""
        return "" if self.summary_by in ("", "claude") else self.summary_by

    @property
    def display_aliases(self) -> list["EntityAlias"]:
        """Real other names only (nicknames, former names); misspellings hidden."""
        return [a for a in self.aliases if not a.misspelling]


class EntityPicture(Timestamped, Base):
    """A picture on an entity page (portrait, map, banner), added by the DM or a reviewer.
    Stored resized (app/pictures.py) in the database, like note images."""

    __tablename__ = "entity_pictures"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), unique=True)
    content_type: Mapped[str] = mapped_column(String(100), default="image/webp", server_default="image/webp")
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)  # up to 1200 px
    thumb: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)  # 320 px square crop
    added_by: Mapped[str] = mapped_column(String(320), default="", server_default="")


class EntityAlias(Base):
    """Other names: renames (Sarkas -> No Name), nicknames, common mis-transcriptions."""

    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("entity_id", "alias"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(300), default="")  # e.g. "former name"
    # A misspelling (e.g. how a transcript mishears a name) is used for matching
    # and linking but never shown as "also known as".
    misspelling: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Fact(Timestamped, Base):
    """Something anyone at the table adds to an entity page. A reviewer merges it
    (shown on the page as written; the summary is not rewritten) or rejects it."""

    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    author_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    # pending | merged | rejected | done (worked into the description, or marked Done by the DM or an editor)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    # "addition" (something new) or "correction" (something on the page is wrong)
    kind: Mapped[str] = mapped_column(String(20), default="addition", server_default="addition")

    @property
    def labeled_text(self) -> str:
        return f"Correction: {self.text}" if self.kind == "correction" else self.text


class Suggestion(Timestamped, Base):
    """A correction or addition from someone at the table about a session or the
    glossary (entity suggestions are Facts). Reviewers act on these from Review."""

    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(20))  # "session" or "glossary"
    target_id: Mapped[int | None] = mapped_column(Integer)  # session or glossary term id; None = new glossary term
    kind: Mapped[str] = mapped_column(String(20), default="correction")  # correction | addition
    text: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    author_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")  # pending | used | done | dismissed
    # From the DM: skipped review, went straight into the session's answers, and shows
    # under the recap until the session is redrafted and published again.
    from_dm: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class EntityRelation(Timestamped, Base):
    """A typed link between two entities: "Aldric parent_of Kieran". Types and
    their wording (incl. inverses) are in app/relations.py."""

    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("from_entity_id", "type", "to_entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    from_entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    to_entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    from_entity: Mapped[Entity] = relationship(foreign_keys=[from_entity_id])
    to_entity: Mapped[Entity] = relationship(foreign_keys=[to_entity_id])


class Character(Timestamped, Base):
    """A player character. It belongs to its player, not to a campaign: its D&D Beyond copy, notes, pins and
    reminders travel with it. Which campaign it's in (and its story page there) is a CampaignCharacter."""

    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")  # one name, shown in every campaign
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ddb_id: Mapped[str | None] = mapped_column(String(40))  # D&D Beyond character id
    ddb_campaign_id: Mapped[str | None] = mapped_column(String(40))  # the D&D Beyond campaign its sheet says it's in
    player_name: Mapped[str] = mapped_column(String(200), default="", server_default="")  # who plays it, before they have an account
    wild_shape: Mapped[str | None] = mapped_column(String(200), nullable=True)  # the form they're in on Battle (app/wild_shape.py), set by their player
    # What they're concentrating on (app/spellbook.py), set by their player: {"spell", "key", "level", "round", "rounds"}
    concentration: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    conditions: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [{"name": "Invisible", "source": "Ring of Invisibility"}] (app/conditions.py)
    owner: Mapped[User | None] = relationship()
    snapshot: Mapped["CharacterSnapshot | None"] = relationship(back_populates="character", uselist=False, passive_deletes=True)
    memberships: Mapped[list["CampaignCharacter"]] = relationship(
        back_populates="character", order_by="CampaignCharacter.id", cascade="all, delete-orphan", passive_deletes=True,
        lazy="selectin")

    @property
    def membership(self) -> "CampaignCharacter | None":
        """The campaign it's in now (at most one, like on D&D Beyond)."""
        return next((m for m in self.memberships if m.left_on is None), None)

    @property
    def campaign_id(self) -> int | None:
        m = self.membership
        return m.campaign_id if m else None

    @property
    def entity(self) -> "Entity | None":
        """Its story page in the campaign it's in now."""
        m = self.membership
        return m.entity if m else None

    @property
    def wild_shape_keep(self) -> list | None:
        """What its current campaign's DM lets it keep in Wild Shape (a ruling, so per campaign)."""
        m = self.membership
        return m.wild_shape_keep if m else None

    @wild_shape_keep.setter
    def wild_shape_keep(self, value: list | None) -> None:
        if (m := self.membership) is not None:
            m.wild_shape_keep = value


class CampaignCharacter(Base):
    """A character in a campaign: its story page there, when it joined and left. Leaving keeps the row (and the
    story page, events and recaps), so who was at the table in a session stays answerable."""

    __tablename__ = "campaign_characters"
    __table_args__ = (
        Index("campaign_characters_one_current", "character_id", unique=True, postgresql_where=sql("left_on IS NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), unique=True)  # its story page
    joined_on: Mapped[date] = mapped_column(Date, server_default=func.current_date())
    left_on: Mapped[date | None] = mapped_column(Date)
    # What the DM lets it keep in Wild Shape (item and feature keys from the sheet's form_options), set by its player
    wild_shape_keep: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    character: Mapped[Character] = relationship(back_populates="memberships")
    entity: Mapped[Entity] = relationship()


class CharacterSnapshot(Timestamped, Base):
    """The last good copy of a character from D&D Beyond (unofficial data; see app/ddb.py).

    A failed refresh only updates status/error/attempted_at: raw, summary and
    fetched_at always hold the last copy that worked, so the app keeps working
    when D&D Beyond is down or changes its format. Player notes are stripped
    before storing (ddb.sanitize).
    """

    __tablename__ = "character_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), unique=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the good copy was fetched
    raw: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[dict | None] = mapped_column(JSONB)  # ddb.parse_character(raw)
    status: Mapped[str] = mapped_column(String(20), default="ok", server_default="ok")  # result of the latest attempt
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    character: Mapped[Character] = relationship(back_populates="snapshot")


class CharacterPick(Timestamped, Base):
    """A player's own marks on their character: a pin (kind "star": show it on Battle),
    the shortlist ("fav"), a reminder ("remind") or their one note on a thing ("note").
    Only the character's player can set them; like character notes, the DM never sees
    them (app/picks.py)."""

    __tablename__ = "character_picks"
    __table_args__ = (UniqueConstraint("character_id", "kind", "ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # "star" (pin) | "remind" | "fav" (shortlist) | "note" | "order"
    ref: Mapped[str] = mapped_column(String(300))  # a key from the parsed sheet, e.g. "spell:Moonbeam"
    label: Mapped[str] = mapped_column(String(500), default="", server_default="")  # shown if the thing disappears from the sheet
    note: Mapped[str] = mapped_column(Text, default="", server_default="")  # on "note" rows: the player's note on the thing


class ToolCorrection(Timestamped, Base):
    """An admin's correction to how askdnd reads D&D Beyond, e.g. "Fleet of Foot is always on" or "hide
    Circle Magic from Battle". A parser mistake is wrong for everyone, so it applies to every character in every
    campaign (a campaign's own rulings are HouseRules), and is kept as feedback for improving the parser."""

    __tablename__ = "tool_corrections"
    __table_args__ = (UniqueConstraint("ref", "field"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(300))  # e.g. "feature:Fleet of Foot", "spell:Moonbeam", a Situational key
    field: Mapped[str] = mapped_column(String(30))  # "feature_group" | "situ_group" | "battle"
    value: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(300), default="", server_default="")  # why, in a few words
    set_by: Mapped[str] = mapped_column(String(320), default="", server_default="")


class HouseRule(Timestamped, Base):
    """A DM's ruling for one campaign that changes how askdnd treats something it knows ("Magic Missile: one roll
    for all darts"). It points at the tool's knowledge and never edits it: removing the row brings the tool's value
    back (app/house_rules.py works out the effective value)."""

    __tablename__ = "house_rules"
    __table_args__ = (UniqueConstraint("campaign_id", "target_kind", "target_key", "field"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    target_kind: Mapped[str] = mapped_column(String(20))  # "spell" (a roll recipe); later sheet items and rules terms
    target_key: Mapped[str] = mapped_column(String(200))  # the recipe's name, e.g. "Magic Missile"
    field: Mapped[str] = mapped_column(String(30))  # what it changes (house_rules.FIELDS)
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    set_by: Mapped[str] = mapped_column(String(200), default="", server_default="")  # the DM's (or an admin's) name


class PlayerNote(Timestamped, Base):
    """A player's own structured note on their character (app/player_notes.py): a battle
    combo, a leveling strategy, a personal quest or a general note. Replaces syncing
    character Google Docs. Only the character's player writes them; every player can
    read them; the DM never sees them."""

    __tablename__ = "player_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12))  # "combo" | "leveling" | "quest" | "general"
    # Personal quests belong to the campaign they were written in; combos, leveling plans and notes travel with the character
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), default="", server_default="")  # quests: open | done | abandoned
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # the kind's fields (see player_notes.KINDS)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class CharacterItemNote(Timestamped, Base):
    """A player's note on an item on D&D Beyond ("Filled with holy water from Oakhurst").
    Everyone at the table can read these, the DM included. They're kept apart from the
    D&D Beyond copy so that copy (and the test fixtures made from it, which are in git)
    never holds a player's writing. Replaced on every successful refresh, so a note
    deleted on D&D Beyond goes too."""

    __tablename__ = "character_item_notes"
    __table_args__ = (UniqueConstraint("character_id", "item_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    item_ref: Mapped[str] = mapped_column(String(80))  # the item's key on the sheet: "item:<id>" or "custom:<id>"
    item_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    note: Mapped[str] = mapped_column(Text)


class GameSession(Timestamped, Base):
    """One night of play."""

    __tablename__ = "game_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None] = mapped_column(Integer)  # unknown for sessions in the gap
    played_on: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(20))  # "notes", "transcript" or "account" (Add Session)
    # Children are deleted with the session (the database cascades; passive_deletes lets it).
    recaps: Mapped[list["Recap"]] = relationship(
        back_populates="session", order_by="Recap.version", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list["StoryEvent"]] = relationship(
        back_populates="session", order_by="StoryEvent.position", cascade="all, delete-orphan", passive_deletes=True
    )
    messages: Mapped[list["SessionMessage"]] = relationship(
        order_by="SessionMessage.id", cascade="all, delete-orphan", passive_deletes=True
    )


class Recap(Timestamped, Base):
    """A recap version. The AI draft is kept so Brett's edits can be learned from."""

    __tablename__ = "recaps"
    __table_args__ = (UniqueConstraint("session_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)  # Markdown
    author: Mapped[str] = mapped_column(String(20))  # "ai" (Claude) or "brett" (a person: see author_name)
    author_name: Mapped[str] = mapped_column(String(200), default="", server_default="")  # who, when a person wrote it
    status: Mapped[Status] = mapped_column(_enum(Status), default=Status.DRAFT)
    session: Mapped[GameSession] = relationship(back_populates="recaps")


class StoryEvent(Timestamped, Base):
    __tablename__ = "story_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[EventKind] = mapped_column(_enum(EventKind))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[Status] = mapped_column(_enum(Status), default=Status.DRAFT)
    session: Mapped[GameSession] = relationship(back_populates="events")
    entities: Mapped[list[Entity]] = relationship(secondary="event_entities")


class EventEntity(Base):
    __tablename__ = "event_entities"
    event_id: Mapped[int] = mapped_column(ForeignKey("story_events.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)


class GlossaryTerm(Timestamped, Base):
    """Correct spellings fed to every extraction (fantasy names get mangled)."""

    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("campaign_id", "term"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    misheard_as: Mapped[list[str]] = mapped_column(ARRAY(String(200)), default=list)


class Correction(Timestamped, Base):
    """What the AI got wrong, or Brett's answer to a question it flagged.
    Ones marked standing_instruction are fed into every future draft."""

    __tablename__ = "corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    # "edit": Brett changed the recap (before/after); "answer": before=question, after=answer;
    # "skip": question skipped; "ask": question waiting on someone (asked_of), note = what the asker added
    kind: Mapped[str] = mapped_column(String(20), default="edit", server_default="edit")
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("game_sessions.id", ondelete="SET NULL"))
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    standing_instruction: Mapped[bool] = mapped_column(Boolean, default=False)
    # Deferred questions ("Ask…"): who was asked, who asked, who answered.
    asked_of: Mapped[str] = mapped_column(String(200), default="", server_default="")
    asked_by: Mapped[str] = mapped_column(String(200), default="", server_default="")
    answered_by: Mapped[str] = mapped_column(String(200), default="", server_default="")


class SpeakerLabel(Base):
    """Maps a MacWhisper speaker label to a person, once per campaign."""

    __tablename__ = "speaker_labels"
    __table_args__ = (UniqueConstraint("campaign_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class NoteSource(Timestamped, Base):
    """A Google Doc of notes that the admin syncs into the app."""

    __tablename__ = "note_sources"
    __table_args__ = (UniqueConstraint("campaign_id", "google_doc_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    google_doc_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300), default="")
    # Character notes are hidden from the DM; campaign notes are not.
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    character: Mapped[Character | None] = relationship()
    snapshots: Mapped[list["NoteSnapshot"]] = relationship(
        back_populates="source", order_by="NoteSnapshot.id", cascade="all, delete-orphan"
    )


class NoteSnapshot(Timestamped, Base):
    """The doc's text and images at one sync. A new one is stored only when content changes."""

    __tablename__ = "note_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("note_sources.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)  # Markdown-ish; images appear as [image: name]
    source: Mapped[NoteSource] = relationship(back_populates="snapshots")
    images: Mapped[list["NoteImage"]] = relationship(cascade="all, delete-orphan")


class NoteImage(Base):
    __tablename__ = "note_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("note_snapshots.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[bytes] = mapped_column(LargeBinary)


# ExtractionRun sources that are not session drafts (they never hold Claude's questions).
NON_DRAFTING_SOURCES = ("conversation", "entity")


class ExtractionRun(Timestamped, Base):
    """One call to Claude. Keeps cost visible on the Usage page."""

    __tablename__ = "extraction_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Set for session work; entity runs ("Regenerate description") set entity_id instead.
    session_id: Mapped[int | None] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True, nullable=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"), nullable=True)
    # "notes", "transcript", "account" (drafts); "conversation" (Add Session check); "entity"
    source: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | error
    error: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    to_check: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # things Brett should verify


class JobRun(Base):
    """One run of a background job (the nightly backup), so the Manage overview can
    say when it last worked and flag a failure or a missed night."""

    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), index=True)  # "backup"
    status: Mapped[str] = mapped_column(String(10))  # "ok" | "error"
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Revision(Base):
    """One change to a tracked field, kept so nothing edited in place is lost
    (app/history.py). Stored in the app's Postgres database on Railway. Holds
    the old and new value, who changed it and how (edit, import, Claude rewrite,
    recap, restore). A deleted player note keeps its whole content here."""

    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    table: Mapped[str] = mapped_column(String(40), index=True)
    row_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(300), default="", server_default="")  # e.g. "Star Mounts (Place)"
    field: Mapped[str] = mapped_column(String(40))  # a column, or "deleted" with the row's content in old
    old: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    new: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    actor: Mapped[str] = mapped_column(String(320), default="", server_default="")  # email, or "" for the system
    source: Mapped[str] = mapped_column(String(40), default="edit", server_default="edit")
    batch: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # one import, for Undo
    character_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # set for players' notes (privacy)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Proposal(Timestamped, Base):
    """A suggested change from extraction (entity or glossary) awaiting Brett's OK."""

    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # "entity" or "glossary"
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | rejected


class CreditTopUp(Timestamped, Base):
    """Anthropic credit Brett bought, for the balance estimate on the Usage page."""

    __tablename__ = "credit_topups"
    id: Mapped[int] = mapped_column(primary_key=True)
    amount_usd: Mapped[float] = mapped_column()
    added_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")


class SessionMessage(Timestamped, Base):
    """The Add Session conversation: the reviewer's written account and replies,
    and Claude's questions. Written by people at the table, not a transcript."""

    __tablename__ = "session_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "reviewer" or "claude"
    author: Mapped[str] = mapped_column(String(200), default="", server_default="")  # reviewer's name
    body: Mapped[str] = mapped_column(Text)
    ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # Claude: enough to draft


class TableRoll(Base):
    """A dice roll made on the server while Game Mode is on (app/table_rolls.py): who rolled
    what, and who may see it. "table": everyone; "dm": the roller and the DM see the number,
    everyone else only that a roll happened; "self": the roller only."""

    __tablename__ = "table_rolls"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # A follow-up (damage, reroll, bonus) points at the roll it belongs to, and shares its audience
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("table_rolls.id", ondelete="CASCADE"), index=True)
    who: Mapped[str] = mapped_column(String(80), default="", server_default="")  # shown when there's no character ("DM")
    label: Mapped[str] = mapped_column(String(120))  # "Wis save", "Initiative", "Rend"; a reroll's reason
    # save | check | attack | death | damage | heal | dice; follow-ups: damage | reroll | bonus
    kind: Mapped[str] = mapped_column(String(10))
    formula: Mapped[str] = mapped_column(String(40))  # what was rolled: "d20+7", "4d6+3"
    dice: Mapped[list] = mapped_column(JSONB)  # every die, in order: [14, 6] on Advantage
    kept: Mapped[int | None] = mapped_column(Integer)  # the d20 that counted (d20 rolls only)
    modifier: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(10), default="normal")  # normal | adv | dis
    visibility: Mapped[str] = mapped_column(String(10), default="table")  # table | dm | self
    damage: Mapped[str] = mapped_column(String(40), default="", server_default="")  # an attack's damage dice, rolled next
    crit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # damage doubled for a critical hit
    # Situational bonuses, each rolled: [{"label": "Bless", "formula": "+1d4", "dice": [3], "total": 3}]
    extras: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # Each part or instance on its own line: [{"label": "Dart 2", "kind": "force", "formula": "1d4+1", "dice": [3], "total": 4}];
    # for several rays, each ray's attack roll
    parts: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # an attack's damage to roll next: {"parts": [...], "each": "ray"}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    character: Mapped[Character | None] = relationship()


# Record changes to tracked fields as Revisions on every flush (app/history.py).
from app import history  # noqa: E402,F401
