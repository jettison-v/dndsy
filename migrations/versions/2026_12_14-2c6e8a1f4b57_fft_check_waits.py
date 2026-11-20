"""A check waits for its deploy (Brett, Nov 20: "Ensure the test/checks do not arrive on Prod until the deployment is
confirmed"): a check written with the pull request its change is in reaches For you only once a deploy carrying that
pull request is live. Its own table, so nothing that reads checks changes shape. Only adds.

Revision ID: 2c6e8a1f4b57
Revises: 7a1c3e5b9d24
"""

import sqlalchemy as sa
from alembic import op

revision = "2c6e8a1f4b57"
down_revision = "7a1c3e5b9d24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fft_check_waits",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("check_id", sa.Integer(), sa.ForeignKey("fft_checks.id", ondelete="CASCADE"), nullable=False, index=True),
                    sa.Column("pr", sa.String(300), nullable=False),
                    sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_table("fft_check_waits")
