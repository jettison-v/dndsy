"""Several issues on one check (Working with Claude, Brett's 2A, Nov 17): a note sent from a check names it
(feedback.check_id), as many as Brett finds, in place of the one note its failure made (checks.failed_id, moved over).
checks.makes: a check that makes something, which runs in a test campaign (Board 6).

Revision ID: f2c4e6a8b0d1
Revises: e1b3d5f7a9c2
"""

import sqlalchemy as sa
from alembic import op

revision = "f2c4e6a8b0d1"
down_revision = "e1b3d5f7a9c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("check_id", sa.Integer(), sa.ForeignKey("checks.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_feedback_check_id", "feedback", ["check_id"])
    op.execute("UPDATE feedback SET check_id = checks.id FROM checks WHERE checks.failed_id = feedback.id")
    op.drop_column("checks", "failed_id")
    op.add_column("checks", sa.Column("makes", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("checks", "makes")
    op.add_column("checks", sa.Column("failed_id", sa.Integer(), sa.ForeignKey("feedback.id", ondelete="SET NULL"), nullable=True))
    op.execute("UPDATE checks SET failed_id = sub.id FROM (SELECT max(id) AS id, check_id FROM feedback WHERE check_id IS NOT NULL GROUP BY check_id) sub "
               "WHERE sub.check_id = checks.id")
    op.drop_index("ix_feedback_check_id", "feedback")
    op.drop_column("feedback", "check_id")
