"""roles per campaign (data organization step 2)

The DM tick and Reviewer access move from the person (users.is_dm, users.access) to their role in each campaign
(campaign_members.role: dm, reviewer or player, with joined and left dates). users.access becomes the tool role:
member or admin (or removed).

Revision ID: ab6c8d2e5f71
Revises: 9a5b7c1d4e60
Create Date: 2026-10-23 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ab6c8d2e5f71'
down_revision: Union[str, Sequence[str], None] = '9a5b7c1d4e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaign_members', sa.Column('joined_on', sa.Date(), server_default=sa.func.current_date(), nullable=False))
    op.add_column('campaign_members', sa.Column('left_on', sa.Date(), nullable=True))
    op.drop_constraint('campaign_members_campaign_id_user_id_key', 'campaign_members', type_='unique')
    op.create_index('campaign_members_one_current', 'campaign_members', ['campaign_id', 'user_id'], unique=True,
                    postgresql_where=sa.text('left_on IS NULL'))
    # Everyone who can sign in today is at the table of every campaign (there is one): DM if ticked, else reviewer
    # if they had Reviewer access, else player. Existing rows keep their role unless the tick or Reviewer says more.
    op.execute("""
        INSERT INTO campaign_members (campaign_id, user_id, role, joined_on)
        SELECT c.id, u.id, CASE WHEN u.is_dm THEN 'dm' WHEN u.access = 'reviewer' THEN 'reviewer' ELSE 'player' END,
               u.created_at::date
        FROM users u CROSS JOIN campaigns c
        WHERE u.access IN ('player', 'reviewer', 'admin')
          AND NOT EXISTS (SELECT 1 FROM campaign_members m WHERE m.user_id = u.id AND m.campaign_id = c.id)
    """)
    op.execute("UPDATE campaign_members m SET role = 'dm' FROM users u WHERE u.id = m.user_id AND u.is_dm")
    op.execute("""UPDATE campaign_members m SET role = 'reviewer' FROM users u
                  WHERE u.id = m.user_id AND u.access = 'reviewer' AND m.role = 'player'""")
    op.execute("UPDATE campaign_members m SET joined_on = u.created_at::date FROM users u WHERE u.id = m.user_id")
    op.execute("UPDATE users SET access = 'member' WHERE access IN ('player', 'reviewer')")
    # Restoring an old access value from version history must give a tool role
    for col in ('old', 'new'):
        op.execute(f"""UPDATE revisions SET {col} = '"member"'::jsonb
                       WHERE "table" = 'users' AND field = 'access' AND {col} IN ('"player"'::jsonb, '"reviewer"'::jsonb)""")
    op.drop_column('users', 'is_dm')


def downgrade() -> None:
    op.add_column('users', sa.Column('is_dm', sa.Boolean(), server_default='false', nullable=False))
    op.execute("""UPDATE users u SET is_dm = true FROM campaign_members m
                  WHERE m.user_id = u.id AND m.role = 'dm' AND m.left_on IS NULL""")
    op.execute("""UPDATE users u SET access = CASE WHEN EXISTS (
                      SELECT 1 FROM campaign_members m WHERE m.user_id = u.id AND m.left_on IS NULL AND m.role IN ('reviewer', 'dm'))
                  THEN 'reviewer' ELSE 'player' END
                  WHERE access = 'member'""")
    for col in ('old', 'new'):
        op.execute(f"""UPDATE revisions SET {col} = '"player"'::jsonb
                       WHERE "table" = 'users' AND field = 'access' AND {col} = '"member"'::jsonb""")
    op.execute("DELETE FROM campaign_members WHERE left_on IS NOT NULL")
    op.execute("UPDATE campaign_members SET role = 'player' WHERE role = 'reviewer'")
    op.drop_index('campaign_members_one_current', 'campaign_members')
    op.create_unique_constraint('campaign_members_campaign_id_user_id_key', 'campaign_members', ['campaign_id', 'user_id'])
    op.drop_column('campaign_members', 'left_on')
    op.drop_column('campaign_members', 'joined_on')
