"""Found, Fixed, Tried: today's open Feedback and Testing carried over, once, after every column the tool writes exists

Revision ID: 0c3e5a7b9d14
Revises: 9a4d6b1e3f72
Create Date: 2026-12-07

The carry-over first ran at 3f9c1a7e5b20, through today's models, before 5b7d2e9a1c44, 7c1e4f2a9d30 and 9a4d6b1e3f72 had
added the columns those models write (fft_areas.key, fft_issues.feature, fft_questions.picks): on askdnd.ai, with open
Feedback, that step would have failed (the review of PR #417, Nov 18). It runs here, last; a database that already
carried (it records `carried_over`) carries nothing twice. A later migration adding a column the carry writes goes
before this one, or the carry moves after it.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

revision: str = "0c3e5a7b9d14"
down_revision: str | Sequence[str] | None = "9a4d6b1e3f72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("feedback"):
        return  # (a database made after the old tables went: nothing to carry)
    from app.fft.carry import carry_over

    db = Session(bind=op.get_bind())
    carry_over(db)
    db.flush()


def downgrade() -> None:
    pass  # (the carried rows stay; the old tables were never changed)
