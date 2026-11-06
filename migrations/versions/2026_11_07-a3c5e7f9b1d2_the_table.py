"""askdnd's table (docs/plans/2026-11-06-table-build-plan.md): places with their maps, grid, walls and fog; the DM's
scene pins; tokens; each character's turn on the bar; the campaign's shown place and battle settings.

Revision ID: a3c5e7f9b1d2
Revises: e2b8c4d6f1a3
Create Date: 2026-11-07 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'a3c5e7f9b1d2'
down_revision: Union[str, Sequence[str], None] = 'e2b8c4d6f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("entity_id", sa.Integer, sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("position", sa.Integer, server_default="0", nullable=False),
        sa.Column("map_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True),
        sa.Column("map_w", sa.Integer, server_default="0", nullable=False),
        sa.Column("map_h", sa.Integer, server_default="0", nullable=False),
        sa.Column("grid", JSONB, server_default="{}", nullable=False),
        sa.Column("walls", JSONB, server_default="[]", nullable=False),
        sa.Column("fog", JSONB, server_default="{}", nullable=False),
        *_stamps(),
    )
    op.create_table(
        "scene_pins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("place_id", sa.Integer, sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer, server_default="0", nullable=False),
        sa.Column("x", sa.Float, nullable=True),
        sa.Column("y", sa.Float, nullable=True),
        sa.Column("notes", JSONB, server_default="{}", nullable=False),
        *_stamps(),
    )
    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("place_id", sa.Integer, sa.ForeignKey("places.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("character_id", sa.Integer, sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=True),
        sa.Column("creature", sa.String(80), nullable=True),
        sa.Column("monster", JSONB, nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("x", sa.Float, nullable=False, server_default="0"),
        sa.Column("y", sa.Float, nullable=False, server_default="0"),
        sa.Column("size", sa.Float, nullable=False, server_default="1"),
        sa.Column("hidden", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("hp", JSONB, nullable=True),
        sa.Column("conditions", JSONB, server_default="[]", nullable=False),
        sa.Column("group", sa.String(80), nullable=True),
        *_stamps(),
    )
    op.add_column("characters", sa.Column("turn", JSONB, nullable=True))
    op.add_column("campaigns", sa.Column("shown_place_id", sa.Integer, sa.ForeignKey("places.id", ondelete="SET NULL", name="campaigns_shown_place_id_fkey"), nullable=True))
    op.add_column("campaigns", sa.Column("table_settings", JSONB, server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("campaigns", "table_settings")
    op.drop_column("campaigns", "shown_place_id")
    op.drop_column("characters", "turn")
    op.drop_table("tokens")
    op.drop_table("scene_pins")
    op.drop_table("places")
