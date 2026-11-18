"""Found, Fixed, Tried's tables (`fft_`), one row per thing, every row in a workspace (1 for askdnd). States are kept
on the rows and changed only through app/fft/rules.py, which writes an event for each change (`FftEvent`); a test
replays the events and checks they reproduce the rows. Words people write live in their own rows (notes, lines), so
they can be erased without breaking the record (T7)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class _Stamped:
    workspace_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FftItem(_Stamped, Base):
    """A Roadmap item: the one order of all work is the items' order, then each item's areas (R15). "Fixes and polish"
    is the standing item that holds bug batches with no feature of their own."""

    __tablename__ = "fft_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    place: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    section: Mapped[str] = mapped_column(String(10), default="next", server_default="next")  # now, next, later, shipped, not_doing
    standing: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    next_step: Mapped[str] = mapped_column(String(200), default="", server_default="")
    next_whose: Mapped[str] = mapped_column(String(10), default="", server_default="")  # "brett" (skipped by R15), "claude", ""


class FftArea(_Stamped, Base):
    """A batch of Claude's work under one item (issues, a build slice, or both), tried together in rounds. One is
    Claude's at a time: the lock has an owner and lapses (R11)."""

    __tablename__ = "fft_areas"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("fft_items.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    place: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    round_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lock_owner: Mapped[str] = mapped_column(String(60), default="", server_default="")
    lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftIdea(_Stamped, Base):
    """An idea or enhancement on its own list: notes join it ("me too"); accepted onto an item, shipped, or declined
    with why."""

    __tablename__ = "fft_ideas"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(12), default="new", server_default="new")  # new, roadmap, shipped, declined
    item_id: Mapped[int | None] = mapped_column(ForeignKey("fft_items.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")


class FftIssue(_Stamped, Base):
    """The work: a problem to fix, made from notes (R1, R2) or from a failed try (R3). Its state says whose turn it is
    (rules.ISSUE_TURN); closed issues carry their reason."""

    __tablename__ = "fft_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    # to_fix (queued), fixing (in hand), asks (Claude asks Brett), merge_ok (a player-prompted fix waits for Brett's OK,
    # R17), ready (fixed and live: ready to try), closed
    state: Mapped[str] = mapped_column(String(10), default="to_fix", server_default="to_fix", index=True)
    close_reason: Mapped[str] = mapped_column(String(12), default="", server_default="")  # works, wont, same, cant_repro, withdrawn
    close_words: Mapped[str] = mapped_column(Text, default="", server_default="")  # what its senders read
    same_as_id: Mapped[int | None] = mapped_column(ForeignKey("fft_issues.id", ondelete="SET NULL"), nullable=True)
    reopened: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # times it came back after closing
    pr: Mapped[str] = mapped_column(String(300), default="", server_default="")
    fixed_in: Mapped[str] = mapped_column(String(40), default="", server_default="")  # the commit that fixed it
    from_player: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # a player's words prompted it (R17)
    origin_try_id: Mapped[int | None] = mapped_column(ForeignKey("fft_tries.id", ondelete="SET NULL", use_alter=True, name="fft_issues_origin_try_fkey"), nullable=True)
    confirm_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # a player confirms it (R5)
    confirm_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # three days, then Brett's


class FftNote(_Stamped, Base):
    """What anyone sent from a page. A player's waits for an admin (R1): none of it reaches Claude until approved,
    when it's filed as an issue (or joined to one), an idea, an answered question, or declined with why."""

    __tablename__ = "fft_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(60), default="", server_default="")  # who, as Claude may know them (T2)
    role: Mapped[str] = mapped_column(String(12), default="", server_default="")  # admin, dm, player, member
    kind: Mapped[str] = mapped_column(String(10), default="", server_default="")  # problem, idea, question
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    page: Mapped[str] = mapped_column(String(120), default="", server_default="")
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # never an email (T2)
    html: Mapped[str] = mapped_column(Text, default="", server_default="")  # the page as drawn: only on request (T4)
    state: Mapped[str] = mapped_column(String(10), default="waiting", server_default="waiting", index=True)  # waiting, filed, declined
    filed_as: Mapped[str] = mapped_column(String(10), default="", server_default="")  # issue, idea, answered
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("fft_issues.id", ondelete="SET NULL"), nullable=True, index=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("fft_ideas.id", ondelete="SET NULL"), nullable=True)
    try_id: Mapped[int | None] = mapped_column(ForeignKey("fft_tries.id", ondelete="SET NULL", use_alter=True, name="fft_notes_try_fkey"), nullable=True)
    # What its sender last saw and last had a corner card about, as "<where it stands>:<last line to them>" (web.marker):
    # different from now is "new" on Notes you sent and the menu's count (seen), and one card (told)
    seen: Mapped[str] = mapped_column(String(40), default="", server_default="")
    told: Mapped[str] = mapped_column(String(40), default="", server_default="")
    staging: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # relayed from staging: always waits (T6)


class FftLine(_Stamped, Base):
    """One line of a conversation, on a note (with its sender) or on an issue (Brett and Claude, or to every sender of
    its notes). Never a rewritten list: a row each. A player's line waits for approval like a note (T1)."""

    __tablename__ = "fft_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int | None] = mapped_column(ForeignKey("fft_notes.id", ondelete="CASCADE"), nullable=True, index=True)
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), nullable=True, index=True)
    who: Mapped[str] = mapped_column(String(10))  # sender, admin, claude, askdnd
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    to: Mapped[str] = mapped_column(String(10), default="", server_default="")  # sender(s) (they see it), claude, "" (internal)
    text: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class FftPicture(_Stamped, Base):
    """A picture with a note or a line: the full one (only its sender and, if not kept from them, admins) and the
    safe copy (a player's character notes blurred at capture; what approvers and Claude see, T5)."""

    __tablename__ = "fft_pictures"
    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int | None] = mapped_column(ForeignKey("fft_notes.id", ondelete="CASCADE"), nullable=True, index=True)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("fft_lines.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(10), default="page", server_default="page")  # page, added
    key: Mapped[str] = mapped_column(String(200), ForeignKey("stored_files.key"))
    safe_key: Mapped[str | None] = mapped_column(String(200), ForeignKey("stored_files.key"), nullable=True)


class FftCheck(_Stamped, Base):
    """What to try, written once: its versions hold the steps (every edit a new version, R7); it names the devices it
    must pass on. Where it stands is worked out from its tries and issues (rules.check_state)."""

    __tablename__ = "fft_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    devices: Mapped[list] = mapped_column(JSONB, default=lambda: ["laptop"], server_default='["laptop"]')
    minutes: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    place: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    as_character: Mapped[int | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    makes: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # makes something: runs in a test campaign
    retired: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    preflight: Mapped[str] = mapped_column(String(10), default="", server_default="")  # "", passed, failed (R18: tried before it reaches Brett)
    asks: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # Claude asks about it


class FftCheckVersion(_Stamped, Base):
    __tablename__ = "fft_check_versions"
    __table_args__ = (UniqueConstraint("check_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("fft_checks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(500), default="", server_default="")
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # a step each, in the walkthrough's markup
    expect: Mapped[str] = mapped_column(Text, default="", server_default="")
    why: Mapped[str] = mapped_column(Text, default="", server_default="")  # what changed, in words


class FftCheckIssue(Base):
    """The issues a check tries the fix of (it comes back when they're fixed and live, R4)."""

    __tablename__ = "fft_check_issues"
    check_id: Mapped[int] = mapped_column(ForeignKey("fft_checks.id", ondelete="CASCADE"), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), primary_key=True)


class FftRound(_Stamped, Base):
    """A sitting of tries. While one is open nothing merges to askdnd.ai (R11); it ends by hand or idle 12 hours."""

    __tablename__ = "fft_rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftTry(_Stamped, Base):
    """One go at a check: who, on what device, where, on which app version and check version, and how it went. Never
    edited: a correction is a new try that replaces it (R6)."""

    __tablename__ = "fft_tries"
    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("fft_checks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor: Mapped[str] = mapped_column(String(10), default="person", server_default="person")  # person, mini
    device: Mapped[str] = mapped_column(String(12), default="laptop", server_default="laptop")  # laptop, iphone, ipad, mac_mini
    where: Mapped[str] = mapped_column(String(10), default="live", server_default="live")  # live, staging, local
    app_version: Mapped[str] = mapped_column(String(40), default="", server_default="")
    result: Mapped[str] = mapped_column(String(8))  # passed, failed, cant, untried (a correction back to To try)
    cant_kind: Mapped[str] = mapped_column(String(8), default="", server_default="")  # later, blocked, wrong
    blocked_by: Mapped[int | None] = mapped_column(ForeignKey("fft_issues.id", ondelete="SET NULL"), nullable=True)
    why: Mapped[str] = mapped_column(Text, default="", server_default="")
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("fft_tries.id", ondelete="SET NULL"), nullable=True)
    replaced: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    round_id: Mapped[int | None] = mapped_column(ForeignKey("fft_rounds.id", ondelete="SET NULL"), nullable=True)


class FftTryIssue(Base):
    """An issue a failed try named: new, or one still happening; and whether it stops the check passing (R3)."""

    __tablename__ = "fft_try_issues"
    try_id: Mapped[int] = mapped_column(ForeignKey("fft_tries.id", ondelete="CASCADE"), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), primary_key=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    how: Mapped[str] = mapped_column(String(6), default="new", server_default="new")  # new, still
    stops_round: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftQuestion(_Stamped, Base):
    """Something Claude asks Brett: about an issue, a check, an area, or a document (a decision on a mockup, kept with
    the version he saw). Answered in For you only; the answer names the question (R13)."""

    __tablename__ = "fft_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    about: Mapped[str] = mapped_column(String(10))  # issue, check, area, document
    about_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_path: Mapped[str] = mapped_column(String(300), default="", server_default="")  # a decision's document (Manage › Documents)
    doc_version: Mapped[str] = mapped_column(String(20), default="", server_default="")
    text: Mapped[str] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # [{"label", "detail"}]
    mine: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Claude's pick (shown, never preselected)
    answer_choice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class FftEvent(Base):
    """Every change: who, what, which thing, from and to. Append-only (T7); states are kept on the rows and must match
    a replay of these. What people wrote isn't copied here, only referred to."""

    __tablename__ = "fft_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1", index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp(), index=True)  # (when written, not the transaction's start: T8's settle)
    actor: Mapped[str] = mapped_column(String(40))  # "user:3", "claude", "mini", "askdnd"
    kind: Mapped[str] = mapped_column(String(30), index=True)  # rules.EVENTS
    thing: Mapped[str] = mapped_column(String(10))  # note, issue, idea, check, try, area, item, question, round
    thing_id: Mapped[int] = mapped_column(Integer, index=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")  # {"from": …, "to": …, …}
    area_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # for a listener that hears one area


class FftListener(Base):
    """A read mark per listener (the main chat; later an area's own chat), so none takes another's items (T8)."""

    __tablename__ = "fft_listeners"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(60))
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True)
    read_id: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    heard_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftKey(_Stamped, Base):
    """A key for an actor in one place, with what it may do (T6): Claude on askdnd.ai, staging's relay, the Mac Mini.
    Only its hash is kept."""

    __tablename__ = "fft_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    actor: Mapped[str] = mapped_column(String(20))  # claude, relay, mini
    scopes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
