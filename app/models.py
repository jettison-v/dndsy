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
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _enum(cls):
    return Enum(cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class Role(StrEnum):
    DM = "dm"
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
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)  # can review and publish


class Campaign(Timestamped, Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    dm_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    members: Mapped[list["CampaignMember"]] = relationship(back_populates="campaign")


class CampaignMember(Base):
    """A user's role in one campaign (the DM of one campaign may play in another)."""

    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(_enum(Role))
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
    aliases: Mapped[list["EntityAlias"]] = relationship(cascade="all, delete-orphan")


class EntityAlias(Base):
    """Other names: renames (Sarkas -> No Name), nicknames, common mis-transcriptions."""

    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("entity_id", "alias"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(300), default="")  # e.g. "former name"


class Character(Timestamped, Base):
    """Player character details; its name and aliases live on the linked entity."""

    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), unique=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ddb_id: Mapped[str | None] = mapped_column(String(40))  # D&D Beyond character id
    player_name: Mapped[str] = mapped_column(String(200), default="", server_default="")  # who plays it, before they have an account
    entity: Mapped[Entity] = relationship()
    owner: Mapped[User | None] = relationship()


class CharacterNote(Timestamped, Base):
    """Why a player built their character this way. Hidden from the DM (see visibility.py)."""

    __tablename__ = "character_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)


class GameSession(Timestamped, Base):
    """One night of play."""

    __tablename__ = "game_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None] = mapped_column(Integer)  # unknown for sessions in the gap
    played_on: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(20))  # "notes" or "transcript"
    recaps: Mapped[list["Recap"]] = relationship(back_populates="session", order_by="Recap.version")
    events: Mapped[list["StoryEvent"]] = relationship(back_populates="session", order_by="StoryEvent.position")


class Recap(Timestamped, Base):
    """A recap version. The AI draft is kept so Brett's edits can be learned from."""

    __tablename__ = "recaps"
    __table_args__ = (UniqueConstraint("session_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)  # Markdown
    author: Mapped[str] = mapped_column(String(20))  # "ai" or "brett"
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
    # "edit": Brett changed the recap (before/after); "answer": before=question, after=answer
    kind: Mapped[str] = mapped_column(String(20), default="edit", server_default="edit")
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("game_sessions.id", ondelete="SET NULL"))
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    standing_instruction: Mapped[bool] = mapped_column(Boolean, default=False)


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


class ExtractionRun(Timestamped, Base):
    """One call to Claude that drafted a session. Keeps cost visible."""

    __tablename__ = "extraction_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # "notes" or "transcript"
    model: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | error
    error: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    to_check: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # things Brett should verify


class Proposal(Timestamped, Base):
    """A suggested change from extraction (entity or glossary) awaiting Brett's OK."""

    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # "entity" or "glossary"
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | rejected
