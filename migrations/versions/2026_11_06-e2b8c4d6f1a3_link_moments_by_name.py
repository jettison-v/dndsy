"""One time (Brett, Nov 6: Captain Barrel had no dot from Last session): link every key moment to the World entries it
names but isn't linked to. A draft links its moments only to entries that existed when it was drafted, so people and
places accepted from that draft were never linked. By proper names only (app/mentions.py: an entry's own name and its
other names, never a description like "the captain"; a longer name claims its words first); quests are left out.
From now on, accepting an entry from a draft links that session's moments itself (app/review.py link_moments).

Revision ID: e2b8c4d6f1a3
Revises: d1a7e3c5b9f2
Create Date: 2026-11-06 11:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app import mentions


# revision identifiers, used by Alembic.
revision: str = 'e2b8c4d6f1a3'
down_revision: Union[str, Sequence[str], None] = 'd1a7e3c5b9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    db = op.get_bind()
    names: dict[int, list[tuple[str, int]]] = {}
    for eid, campaign_id, name in db.execute(sa.text("SELECT id, campaign_id, name FROM entities WHERE kind <> 'quest'")):
        names.setdefault(campaign_id, []).append((name, eid))
    for eid, campaign_id, alias in db.execute(sa.text(
            "SELECT e.id, e.campaign_id, a.alias FROM entity_aliases a JOIN entities e ON e.id = a.entity_id "
            "WHERE e.kind <> 'quest' AND NOT a.misspelling")):
        names.setdefault(campaign_id, []).append((alias, eid))
    finders = {c: mentions.finder(ns) for c, ns in names.items()}
    have = {(ev, en) for ev, en in db.execute(sa.text("SELECT event_id, entity_id FROM event_entities"))}
    rows = []
    for ev, text, campaign_id in db.execute(sa.text(
            "SELECT se.id, se.text, gs.campaign_id FROM story_events se JOIN game_sessions gs ON gs.id = se.session_id")):
        for en in finders.get(campaign_id, lambda _t: [])(text or ""):
            if (ev, en) not in have:
                rows.append({"ev": ev, "en": en})
                have.add((ev, en))
    if rows:
        db.execute(sa.text("INSERT INTO event_entities (event_id, entity_id) VALUES (:ev, :en)"), rows)


def downgrade() -> None:
    pass  # (links can't be told from the ones drafts made; they're harmless to keep)
