"""Found, Fixed, Tried: today's open Feedback and Testing carried over, once (app/fft/carry.py)

Revision ID: 3f9c1a7e5b20
Revises: 8de6dc8271e6
Create Date: 2026-12-03

The old tables stay as they are (feedback, feedback_pictures, checks, areas, claude_inbox) until Brett has used the new
tool for a few days: undoing the merge brings the old tool back with nothing lost. Downgrading leaves the carried
rows; the old tables were never changed.
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy.orm import Session

revision: str = "3f9c1a7e5b20"
down_revision: str | Sequence[str] | None = "8de6dc8271e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass  # (the carry-over runs at 0c3e5a7b9d14, once every column the new tool writes exists: here, three of them
    # didn't yet, so a database with open Feedback failed this step; the review of PR #417, Nov 18)


def downgrade() -> None:
    pass
