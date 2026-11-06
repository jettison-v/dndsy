"""A companion's story (Your creatures, slice 9; Creatures as Characters board 4): its World entry and what it's done,
kept on its master: {"familiar": {"entity": 12, "log": [{"on": "2026-11-05", "what": "cast", "form": "Owl", ...}]}}.

Revision ID: c4e9a2d7f13b
Revises: b6d2f8a41c07
Create Date: 2026-11-05 16:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4e9a2d7f13b'
down_revision: Union[str, Sequence[str], None] = 'b6d2f8a41c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("creature_story", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("characters", "creature_story")
