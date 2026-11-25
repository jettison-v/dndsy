"""Found, Fixed, Tried's tables (`fft_`), one row per thing, every row in a workspace (1 for askdnd). States are kept
on the rows and changed only through app/fft/rules.py, which writes an event for each change (`FftEvent`); a test
replays the events and checks they reproduce the rows. Words people write live in their own rows (notes, lines), so
they can be erased without breaking the record (T7)."""

from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, false, func, true
from sqlalchemy import text as sa_text
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
    # The Roadmap in askdnd (Brett's picks, Nov 20): why it matters, its size (S, M, L), a status line saying where it
    # stands in a few words, and when it shipped. Server defaults only, read when used (the carry-over migration writes
    # items through today's models before these columns exist: as fft_areas' lanes)
    __mapper_args__: ClassVar[dict] = {"eager_defaults": False}
    # (deferred: read only when a page asks, together, so a query by today's model works on a database before them)
    why: Mapped[str] = mapped_column(Text, server_default="", deferred=True, deferred_group="roadmap")
    size: Mapped[str] = mapped_column(String(2), server_default="", deferred=True, deferred_group="roadmap")
    status: Mapped[str] = mapped_column(String(200), server_default="", deferred=True, deferred_group="roadmap")
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=sa_text("NULL"), deferred=True, deferred_group="roadmap")
    # Development's one queue (issue 62, Brett's picks Nov 20): a Roadmap build's place among the builds and the Product Area
    # batches (his drag; none yet: after those placed, in the order they had), and held below the line
    queue_place: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=sa_text("NULL"), deferred=True, deferred_group="roadmap")
    held: Mapped[bool] = mapped_column(Boolean, server_default=false(), deferred=True, deferred_group="roadmap")
    # What it changed, with its numbers (Brett, Nov 20): its first line the headline, each line after it one result
    result: Mapped[str] = mapped_column(Text, server_default="", deferred=True, deferred_group="roadmap")
    # The item's page (issues 60, 61, Brett's picks Nov 21, docs/mockups/roadmap-item-page/): the decisions behind its why, a
    # quiet line under it (the why itself: its first line the headline, each line after it a point); and Scope it, when
    # Brett asked for its scope (first in Claude's queue until its first version is written, or he says Not now)
    why_from: Mapped[str] = mapped_column(Text, server_default="", deferred=True, deferred_group="roadmap")
    scope_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=sa_text("NULL"), deferred=True, deferred_group="roadmap")


class FftCheckWait(_Stamped, Base):
    """A check waiting for its deploy: the pull request its change is in. Until a deploy carrying it is live, the check
    stays Claude's and never reaches For you (Brett, Nov 20)."""

    __tablename__ = "fft_check_waits"
    id: Mapped[int] = mapped_column(primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("fft_checks.id", ondelete="CASCADE"), index=True)
    pr: Mapped[str] = mapped_column(String(300))


class FftScope(_Stamped, Base):
    """A Roadmap item's scope, one version at a time: what it is, what's in, what's not now, open questions, and what
    changed from the version before. Brett's one OK (`agreed_at`) is on the version he read (The Roadmap in askdnd)."""

    __tablename__ = "fft_scopes"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("fft_items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    what: Mapped[str] = mapped_column(Text, default="", server_default="")
    inside: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    not_now: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    questions: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    changed: Mapped[str] = mapped_column(Text, default="", server_default="")
    actor: Mapped[str] = mapped_column(String(40), default="", server_default="")
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agreed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Reviewing a scope (issue 54, Brett's picks Nov 20): Needs changes… on this version (it's Claude's turn to write the
    # next), and Claude's suggested answer to each open question (in the questions' order; "" for none)
    changes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suggested: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class FftAddition(_Stamped, Base):
    """Something Brett added to a Roadmap item, in his words (said in chat and written down by Claude, or added in
    askdnd), and Claude's answer: in scope (and the version it went into), later, or a question back."""

    __tablename__ = "fft_additions"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("fft_items.id", ondelete="CASCADE"), index=True)
    words: Mapped[str] = mapped_column(Text)
    where: Mapped[str] = mapped_column(String(10), default="askdnd", server_default="askdnd")  # askdnd, chat, discussion
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    answer: Mapped[str] = mapped_column(String(10), default="", server_default="")  # "", in, later, question
    answer_words: Mapped[str] = mapped_column(Text, default="", server_default="")
    scope_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Reviewing a scope (issue 54): a comment on one line of a version ("what", "in:2", "not:0"; "q:1" is his answer to
    # its second open question), the line as it read then, and held: his own, not sent to Claude until he answers the
    # scope (Scope looks right, or Needs changes…)
    on_line: Mapped[str] = mapped_column(String(12), default="", server_default="")
    line_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    on_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    held: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftStep(_Stamped, Base):
    """One step of a Roadmap item, Brett's or Claude's; the first not done is its next step, and one of Brett's waits
    in For you until he ticks it."""

    __tablename__ = "fft_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("fft_items.id", ondelete="CASCADE"), index=True)
    place: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    whose: Mapped[str] = mapped_column(String(10), default="claude", server_default="claude")  # brett, claude
    text: Mapped[str] = mapped_column(String(200))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftArea(_Stamped, Base):
    """A batch of Claude's work under one item, tried together in rounds: a Product Area's fixes under Fixes and polish
    (`key` names it in app/data/taxonomy.json; Brett, Nov 18), or a Roadmap build's own (no key). One is Claude's at a
    time: the lock has an owner and lapses (R11)."""

    __tablename__ = "fft_areas"
    __mapper_args__: ClassVar[dict] = {"eager_defaults": False}  # (the lane columns' defaults are read when used, never fetched on insert:
    # the carry-over migration writes areas before they exist)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("fft_items.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)
    title: Mapped[str] = mapped_column(String(80))
    place: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    round_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    lock_owner: Mapped[str] = mapped_column(String(60), default="", server_default="")
    lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The lane its plan takes (the work flow's slice 3, Brett's picks Nov 19): ship (no test from Brett), look (merged,
    # Brett tries the batch after), careful (his round first). Picked by rules (app/fft/lanes.py), moved up by anyone,
    # down only by an admin, with who and why; an incident keeps it at careful until `careful_until` (30 days). No
    # Python default: a row the carry-over migration (0c3e5a7b9d14) writes through this model never names them.
    lane: Mapped[str] = mapped_column(String(10), server_default="")
    lane_by: Mapped[str] = mapped_column(String(80), server_default="")
    lane_why: Mapped[str] = mapped_column(String(300), server_default="")
    careful_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=sa_text("NULL"))
    # Below Work's cut line (Brett's picks on The Work Pages, Nov 20): Claude takes only the plans above it
    held: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # A Product Area batch's place in Development's one queue (issue 62), beside the Roadmap builds
    queue_place: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=sa_text("NULL"))


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
    __mapper_args__: ClassVar[dict] = {"eager_defaults": False}  # (`kind`'s default is read when used, never fetched on insert:
    # the carry-over migration writes issues before that column exists, as fft_areas' lanes)
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)  # what it's about (app/fft/taxonomy.py)
    kind: Mapped[str] = mapped_column(String(12), server_default="fix")  # fix or improvement (rules.ISSUE_KINDS; Nov 20). No
    # Python default: written only for an improvement, so the carry-over (migration 0c3e5a7b9d14, through today's models)
    # never writes a column its database doesn't have yet
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
    people: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # needs more than one person (its own rounds)


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
    # The goal, first (Clearer checks, Roadmap item 6, Brett's picks Nov 21): what was wrong before, what's true now
    before: Mapped[str] = mapped_column(Text, default="", server_default="")
    now: Mapped[str] = mapped_column(Text, default="", server_default="")


class FftCheckIssue(Base):
    """The issues a check tries the fix of (it comes back when they're fixed and live, R4)."""

    __tablename__ = "fft_check_issues"
    check_id: Mapped[int] = mapped_column(ForeignKey("fft_checks.id", ondelete="CASCADE"), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), primary_key=True)


class FftNoteIssue(Base):
    """A note's other issues, after its issue was Split… into several (issue 22, Brett's pick 2A, Nov 21): the note is the
    evidence of each, and its sender hears how each one turns out. The issue it was filed as stays `FftNote.issue_id`."""

    __tablename__ = "fft_note_issues"
    note_id: Mapped[int] = mapped_column(ForeignKey("fft_notes.id", ondelete="CASCADE"), primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), primary_key=True, index=True)


class FftDocComment(_Stamped, Base):
    """A comment pinned to a spot on a mockup (issue 24, Brett's picks Nov 21, docs/mockups/mockup-comments/): where he
    clicked (x as a share of the page's width, y in pixels from its top), the words nearest it, and his words. Held,
    his own, until Save my picks answers the mockup's question; then it goes with the answer (`question_id`, `sent_at`)."""

    __tablename__ = "fft_doc_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc: Mapped[str] = mapped_column(String(300), index=True)  # its docs/ path, as docs/library.json lists it
    page: Mapped[str] = mapped_column(String(300), default="", server_default="")  # the board it's on, for a design of several
    n: Mapped[int] = mapped_column(Integer)  # the pin's number on this mockup
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    near: Mapped[str] = mapped_column(String(200), default="", server_default="")  # the words nearest the pin, as the page shows them
    words: Mapped[str] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("fft_questions.id", ondelete="SET NULL"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Comments made on claude.ai, brought in when Claude checks in (item 39, 6 of 6: either place, merged): where it was
    # made, claude.ai's own mark for it (so it's brought in once) and when; placed by its words (`near`), not a spot
    origin: Mapped[str] = mapped_column(String(10), default="askdnd", server_default="askdnd")  # "askdnd" or "claude.ai"
    ext_id: Mapped[str] = mapped_column(String(64), default="", server_default="")
    made_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftRound(_Stamped, Base):
    """A sitting of tries. While one is open nothing merges to askdnd.ai (R11); it ends by hand or idle 12 hours."""

    __tablename__ = "fft_rounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # (a lighter round, Brett's pick Nov 19: a sitting holds Claude's merges in its own area(s); ▶ Try it holds nothing)
    holds: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


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


class FftLocalTry(_Stamped, Base):
    """A change waiting for Brett's try on his Mac before it merges (Brett, Nov 19: while he's Available, Look work
    gets a local round). What changed and what to look at are Claude's words, as it would say them in chat; `path` is
    the page to open on Claude's local server. Answered good (it may merge), off (his words; it goes back to its plan)
    or left (Available turned off first: it merges as Look work does, and its check comes to him on askdnd.ai)."""

    __tablename__ = "fft_local_tries"
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    pr: Mapped[str] = mapped_column(String(300), default="", server_default="")
    changed: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # a line each
    look_at: Mapped[str] = mapped_column(Text, default="", server_default="")
    path: Mapped[str] = mapped_column(String(300), default="/", server_default="/")
    answer: Mapped[str] = mapped_column(String(8), default="", server_default="")  # "", good, off, left
    words: Mapped[str] = mapped_column(Text, default="", server_default="")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftQuestion(_Stamped, Base):
    """Something Claude asks Brett: about an issue, a check, an area, or a document (a decision on a mockup, kept with
    the version he saw). Answered in For you only; the answer names the question (R13)."""

    __tablename__ = "fft_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    about: Mapped[str] = mapped_column(String(10))  # issue, check, area, document
    about_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_path: Mapped[str] = mapped_column(String(300), default="", server_default="")  # a decision's document (Backstage › Documents)
    doc_version: Mapped[str] = mapped_column(String(20), default="", server_default="")
    text: Mapped[str] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")  # [{"label", "detail"}]
    mine: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Claude's pick (shown, never preselected)
    answer_choice: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Picks made on its mockup, saved from inside askdnd (Brett's round, Nov 18): [{"name", "value", "label"}]
    picks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
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
    actor: Mapped[str] = mapped_column(String(20))  # claude, relay, mini, github
    scopes: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftSeen(Base):
    """When a person last opened an issue in Feedback (Brett's round, Nov 18, issue 32: a conversation's lines say when
    they were said and which are new since you last looked). Anything said there after it, by someone else, is new."""

    __tablename__ = "fft_seen"
    __table_args__ = (UniqueConstraint("user_id", "issue_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    issue_id: Mapped[int] = mapped_column(ForeignKey("fft_issues.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FftPull(_Stamped, Base):
    """A pull request as GitHub last reported it (scripts/github_report.py, run by GitHub on each pull request event, each
    test run and each push to main; item 39, scope v4, Nov 23): its state, its tests, whether it's behind main, and the
    work it's linked to by its branch name (`a12-…` an area, `i110-…` an issue, `r39-…` a Roadmap item) or by an issue
    that names it. One with nothing behind it is Upkeep: no pull request without a card. Changed only in rules.py."""

    __tablename__ = "fft_pulls"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    branch: Mapped[str] = mapped_column(String(200), default="", server_default="")
    by_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # (Dependabot's: upkeep, no claim)
    state: Mapped[str] = mapped_column(String(10), default="open", server_default="open")  # open, merged, closed
    tests: Mapped[str] = mapped_column(String(10), default="", server_default="")  # "", running, passed, failed
    merge_state: Mapped[str] = mapped_column(String(12), default="", server_default="")  # GitHub's: clean, behind, blocked, dirty, …
    auto_merge: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    head: Mapped[str] = mapped_column(String(40), default="", server_default="")
    updated_by_askdnd_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # (brought up to date with main)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("fft_issues.id", ondelete="SET NULL"), nullable=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("fft_items.id", ondelete="SET NULL"), nullable=True)
    # Deploys mark themselves live (item 39, 2 of 4): its merge commit, and when askdnd.ai first ran a version holding it
    merge_commit: Mapped[str] = mapped_column(String(40), default="", server_default="")
    live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Opened for work nobody had claimed (item 39, 3 of 4): a gap until it closes or its plan is claimed
    unclaimed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftSentDoc(_Stamped, Base):
    """A page Claude sent to askdnd before its repo copy lands (item 39, scope v7, Nov 24: a page is data, not code, so it
    reaches Brett in seconds, not after a pull request and a deploy): its Documents entry, as docs/library.json would
    list it. Backstage › Documents shows it while it differs from the repo's copy, and the first minute of a deploy whose
repo copy is the same removes it (rules.prune_landed_pages). Changed only in rules.py."""

    __tablename__ = "fft_sent_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(300), unique=True)  # its docs/ path, as library.json's `source`
    entry: Mapped[dict] = mapped_column(JSONB, default=dict)  # title, kind, status, date, what, link
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FftSentFile(_Stamped, Base):
    """One file of a sent page (the page itself, or its boards, pictures and styles beside it), served in Documents'
    sealed frame exactly as the repo's copy would be."""

    __tablename__ = "fft_sent_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(300), unique=True)  # under docs/, without the "docs/"
    body: Mapped[bytes] = mapped_column(LargeBinary)
    digest: Mapped[str] = mapped_column(String(64))  # sha256 of body: once the repo's copy is the same, it has landed
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FftChat(_Stamped, Base):
    """Something Brett said to Claude in the Code tab, saved as it arrived (a Claude Code hook, `feedback.py chat said`;
    his pick 2A on Talking both ways, Nov 24: "We need to work here"). Claude files each onto its Roadmap item or issue,
    or as just chat; one left unfiled is a gap. Changed only in rules.py."""

    __tablename__ = "fft_chats"
    id: Mapped[int] = mapped_column(primary_key=True)
    words: Mapped[str] = mapped_column(Text)
    session: Mapped[str] = mapped_column(String(64), default="", server_default="")
    said_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    filed_as: Mapped[str] = mapped_column(String(10), default="", server_default="")  # "", item, issue, chat
    filed_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FftReview(_Stamped, Base):
    """One of Workshop's reviews (app/fft/reviews.json) as this workspace runs it: how often (Brett's pick, which he can
    change) and whether its schedule is on (turned on once it has run once; Roadmap item 46, the pass's "not now").
    A row is made the first time a review is run or set. Changed only in rules.py."""

    __tablename__ = "fft_reviews"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40))
    cadence: Mapped[str] = mapped_column(String(12), default="", server_default="")  # "" = the catalog's; weekly, monthly, phase, on_demand, off
    scheduled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class FftReviewRun(_Stamped, Base):
    """A review run: asked (waits its turn, or for Deploys to be on again), starting, running (`on`: what it's on),
    waiting (on Brett: `question_id` in For you), then done (its one-page `result`), stopped or skipped (`why`). One
    runs at a time and none starts while Deploys is Paused (Roadmap item 46, the pass's six changes). `inputs` are what
    Run… asked (Dig into a feature: feature, issues, words, against, characters, device, depth; Polish an area: area,
    focus, devices); `result`: {"summary", "covered", "missed", "findings": [{"what", "became", "ref"}], "numbers":
    {"found", "fixed", "picks", "open"}}. Changed only in rules.py."""

    __tablename__ = "fft_review_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    review: Mapped[str] = mapped_column(String(40), index=True)
    how: Mapped[str] = mapped_column(String(10), default="asked", server_default="asked")  # asked (Run now, Run…), scheduled
    asked_by: Mapped[str] = mapped_column(String(40), default="", server_default="")  # the event's actor
    state: Mapped[str] = mapped_column(String(10), default="asked", server_default="asked", index=True)
    inputs: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    on: Mapped[str] = mapped_column(String(200), default="", server_default="")
    question_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    why: Mapped[str] = mapped_column(String(300), default="", server_default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
