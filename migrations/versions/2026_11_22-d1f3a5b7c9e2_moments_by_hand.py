"""story_events.by_hand: a key moment a person wrote or edited, which Claude drafting the session again leaves in place
(Nov 16: a redraft published over a session played since kept the first draft's moments too, so they showed in pairs).

Claude's moments are written in the same transaction as the recap version it drafted, so they share its created_at; a
moment that matches no recap of Claude's in its session was added by a person (the review page, an entry's page, or
brought back from history), as was one a person edited since (a revision of its text or kind with someone's name).

Revision ID: d1f3a5b7c9e2
Revises: c9e1a3b5d7f8
"""

import sqlalchemy as sa
from alembic import op

revision = "d1f3a5b7c9e2"
down_revision = "c9e1a3b5d7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story_events", sa.Column("by_hand", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""
        UPDATE story_events e SET by_hand = true
        WHERE NOT EXISTS (SELECT 1 FROM recaps r WHERE r.session_id = e.session_id AND r.author = 'ai'
                          AND r.created_at = e.created_at)
           OR EXISTS (SELECT 1 FROM revisions v WHERE v."table" = 'story_events' AND v.row_id = e.id
                      AND v.field IN ('text', 'kind') AND v.actor <> '')
    """)


def downgrade() -> None:
    op.drop_column("story_events", "by_hand")
