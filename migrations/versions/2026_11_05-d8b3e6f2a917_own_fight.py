"""askdnd runs the fight (VTT slice 2): a fight and its fighters as rows of their own, each step kept for the DM's
Undo, and the DM's battle settings on the campaign.

Revision ID: d8b3e6f2a917
Revises: c4e9a2d7f13b
Create Date: 2026-11-05 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8b3e6f2a917'
down_revision: Union[str, Sequence[str], None] = 'c4e9a2d7f13b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("battle", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"))
    op.create_table(
        "fights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "fighters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fight_id", sa.Integer(), sa.ForeignKey("fights.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("monster", sa.String(120), nullable=False, server_default=""),
        sa.Column("group", sa.String(40), nullable=False, server_default=""),
        sa.Column("initiative", sa.Float(), nullable=True),
        sa.Column("bonus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("hp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hp_max", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("temp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ac", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )
    op.create_table(
        "fight_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fight_id", sa.Integer(), sa.ForeignKey("fights.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("what", sa.String(120), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fight_steps")
    op.drop_table("fighters")
    op.drop_table("fights")
    op.drop_column("campaigns", "battle")
