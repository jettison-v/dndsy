"""The DM as a backup: campaigns.backup_heard_at (DM Backup Option A, Brett 2026-11-02)

When a DM's browser with any D&D Beyond page open was last heard: while it's recent, that browser makes the changes of
a character whose own sheet is closed (app/ddb_bridge.py `carried`).

Revision ID: f6b2d8e3a9c4
Revises: e5a1c7d2f4b8
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6b2d8e3a9c4'
down_revision: Union[str, Sequence[str], None] = 'e5a1c7d2f4b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('backup_heard_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('campaigns', 'backup_heard_at')
