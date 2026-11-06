"""A published recap's narration (Listen, a Labs feature; Brett, Nov 6): the voice reading it, kept in file storage
like a picture, made the first time someone presses Listen.

Revision ID: d1a7e3c5b9f2
Revises: c4e9a2d7f13b
Create Date: 2026-11-06 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a7e3c5b9f2'
down_revision: Union[str, Sequence[str], None] = 'c4e9a2d7f13b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recaps", sa.Column("narration_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True))


def downgrade() -> None:
    op.drop_column("recaps", "narration_key")
