"""strip players' custom-item notes from stored D&D Beyond copies

Earlier copies kept customItems[].notes (never shown, but player writing the DM
mustn't see). app.ddb.sanitize now drops them on every refresh; this cleans the
copies already stored. Data only; nothing to undo.

Revision ID: 5e1f0c9a7b21
Revises: 120d9a962b0f
Create Date: 2026-10-17 09:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = '5e1f0c9a7b21'
down_revision: Union[str, Sequence[str], None] = '120d9a962b0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE character_snapshots
        SET raw = jsonb_set(raw, '{customItems}',
                            (SELECT coalesce(jsonb_agg(item - 'notes'), '[]'::jsonb) FROM jsonb_array_elements(raw->'customItems') AS item))
        WHERE raw IS NOT NULL AND jsonb_typeof(raw->'customItems') = 'array'
    """)


def downgrade() -> None:
    pass
