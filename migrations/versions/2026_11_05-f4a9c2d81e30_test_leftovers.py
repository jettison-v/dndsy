"""A one-time clean-up of test leftovers (Brett, 2026-11-05: "a one time cleanup" of the test accounts and characters
cluttering the menus; askdnd itself never deletes, so this is the one place it happens). Deleted for good:

- Characters: Brett's first Vi and Spurt (his own D&D Beyond account, never used in testing), Roscoe Norell (Levi took
  over his testing on Nov 3), and every test copy that sits at no table (the first try at test copies). Never one at a
  real table now, and never a test copy still at one.
- Their World entries, where each is only that character's own entry in a test campaign.
- Accounts removed on Manage › Accounts that another account of the same name replaced (two players'
  older ones), with nothing attached, and only if no Railway sign-in list names them: a removed account's
  record is what keeps it out, so a listed one stays.

What cascades with them is test history only (VTT test's rolls and bridge changes for these characters). There's no
going back: downgrade does nothing. Each deletion is printed, so Railway's deploy log says what went.

Revision ID: f4a9c2d81e30
Revises: e3b81c6d2f47
Create Date: 2026-11-05 13:00:00

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a9c2d81e30'
down_revision: Union[str, Sequence[str], None] = 'e3b81c6d2f47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# D&D Beyond sheets: Brett's first Vi and Spurt the Sorcerer (his own account), Roscoe Norell
SHEETS = ["172836541", "172836747", "173133567"]


def _listed() -> set[str]:
    """Every email a Railway sign-in list names (app/config.py): owners, the allowlist and reviewers."""
    return {e.strip().lower() for k in ("ADMIN_EMAILS", "ALLOWED_EMAILS", "REVIEWER_EMAILS") for e in (os.getenv(k) or "").split(",") if e.strip()}


def upgrade() -> None:
    conn = op.get_bind()
    at_a_table = """exists (select 1 from campaign_characters cc join campaigns c on c.id = cc.campaign_id
                            where cc.character_id = ch.id and cc.left_on is null {extra})"""
    chars = conn.execute(sa.text(
        "select ch.id, ch.name from characters ch where "
        f"(ch.ddb_id = any(:sheets) and not {at_a_table.format(extra='and c.is_test is not true')})"
        f" or (ch.copy_of_id is not null and not {at_a_table.format(extra='')})"), {"sheets": SHEETS}).all()
    ids = [c.id for c in chars]
    if ids:
        entries = conn.execute(sa.text(
            "select distinct e.id, e.name from campaign_characters cc join entities e on e.id = cc.entity_id"
            " join campaigns c on c.id = e.campaign_id"
            " where cc.character_id = any(:ids) and c.is_test and e.kind = 'pc'"
            " and not exists (select 1 from campaign_characters o where o.entity_id = e.id and o.character_id <> all(:ids))"),
            {"ids": ids}).all()
        conn.execute(sa.text("delete from characters where id = any(:ids)"), {"ids": ids})
        conn.execute(sa.text("delete from entities where id = any(:ids)"), {"ids": [e.id for e in entries]})
        print(f"Test leftovers: deleted characters {', '.join(f'{c.name} ({c.id})' for c in chars)};"
              f" their entries {', '.join(f'{e.name} ({e.id})' for e in entries) or 'none'}")
    nothing = " and ".join(f"not exists (select 1 from {t} x where x.{col} = u.id)" for t, col in (
        ("campaign_members", "user_id"), ("characters", "owner_id"), ("player_notes", "author_id"), ("table_rolls", "user_id"),
        ("feedback", "user_id"), ("speaker_labels", "user_id"), ("campaign_content", "created_by_id")))
    people = conn.execute(sa.text(
        "select u.id, u.name, lower(u.email) as email from users u where u.access = 'removed' and " + nothing +
        " and exists (select 1 from users o where o.id <> u.id and o.name = u.name and coalesce(o.access, '') <> 'removed')")).all()
    gone = [p for p in people if p.email not in _listed()]
    if gone:
        conn.execute(sa.text("delete from bridge_keys where lower(email) = any(:emails)"), {"emails": [p.email for p in gone]})
        conn.execute(sa.text("delete from users where id = any(:ids)"), {"ids": [p.id for p in gone]})
        print(f"Test leftovers: deleted replaced accounts {', '.join(f'{p.name} ({p.id})' for p in gone)}")


def downgrade() -> None:
    pass  # (deleted for good)
