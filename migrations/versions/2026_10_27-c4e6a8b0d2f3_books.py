"""books (data strategy, 2026-10-27): book_entries, a private rules book's entries, and each campaign's books

book_entries holds entries copied in from books the DM owns (scripts/book_load.py), never the public repo;
campaigns.books lists the books a campaign's lookups use (app/books.py), the 2024 core books to start with.

Revision ID: c4e6a8b0d2f3
Revises: c4e8a1f3b6d2
Create Date: 2026-10-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'c4e6a8b0d2f3'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1f3b6d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'book_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('book', sa.String(length=40), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('image', sa.String(length=500), server_default='', nullable=False),
        sa.Column('data', JSONB(), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('book', 'kind', 'key'),
    )
    op.create_index('ix_book_entries_book', 'book_entries', ['book'])
    op.add_column('campaigns', sa.Column('books', JSONB(), nullable=False,
                                         server_default=sa.text("""'["phb-2024", "dmg-2024", "mm-2024"]'::jsonb""")))


def downgrade() -> None:
    op.drop_column('campaigns', 'books')
    op.drop_table('book_entries')
