import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import characters
from app.config import sqlalchemy_url
from app.models import (
    Campaign,
    CampaignMember,
    Character,
    Entity,
    EntityAlias,
    EntityKind,
    Role,
    User,
)
from app.visibility import can_view_character_notes, can_view_published_story


def test_sqlalchemy_url_uses_psycopg():
    assert sqlalchemy_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert sqlalchemy_url("postgres://h/db") == "postgresql+psycopg://h/db"
    assert sqlalchemy_url("postgresql+psycopg://h/db") == "postgresql+psycopg://h/db"
    assert sqlalchemy_url(None) == ""


def test_character_notes_hidden_from_dm():
    """A standing rule (CLAUDE.md › Privacy): character notes are visible to players but never the DM."""
    assert can_view_character_notes(Role.PLAYER)
    assert not can_view_character_notes(Role.DM)
    assert not can_view_character_notes(None)


def test_published_story_visible_to_whole_table():
    """A standing rule (CLAUDE.md › Privacy): everything except character notes is visible to everyone at the table
    once published."""
    assert can_view_published_story(Role.PLAYER)
    assert can_view_published_story(Role.DM)
    assert not can_view_published_story(None)


def make_campaign(db):
    campaign = Campaign(name="Test Campaign", slug="test")
    db.add(campaign)
    db.flush()
    return campaign


def test_renamed_character_found_by_old_name(db):
    campaign = make_campaign(db)
    player = User(email="player@example.com", name="Player")
    pc = Entity(campaign_id=campaign.id, kind=EntityKind.PC, name="No Name")
    pc.aliases.append(EntityAlias(alias="Sarkas", note="former name"))
    db.add_all([player, pc])
    db.flush()
    ch = Character(name=pc.name, owner_id=player.id)
    db.add(ch)
    characters.join(db, ch, pc)

    found = db.scalars(
        select(Entity).join(EntityAlias).where(EntityAlias.alias == "Sarkas")
    ).one()
    assert found.name == "No Name"


def test_role_is_per_campaign(db):
    one, two = Campaign(name="One", slug="one"), Campaign(name="Two", slug="two")
    user = User(email="dm@example.com", name="DM")
    db.add_all([one, two, user])
    db.flush()
    db.add_all([
        CampaignMember(campaign_id=one.id, user_id=user.id, role=Role.DM),
        CampaignMember(campaign_id=two.id, user_id=user.id, role=Role.PLAYER),
    ])
    db.flush()
    roles = {m.campaign.slug: m.role for m in db.scalars(select(CampaignMember))}
    assert roles == {"one": Role.DM, "two": Role.PLAYER}


def test_user_email_unique(db):
    db.add_all([User(email="a@example.com", name="A"), User(email="a@example.com", name="B")])
    with pytest.raises(IntegrityError):
        db.flush()


STAIRS = """
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
revs = [r.revision for r in ScriptDirectory.from_config(cfg).walk_revisions("base", "heads")]
for rev in reversed(revs):
    command.upgrade(cfg, rev)
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, rev)
command.downgrade(cfg, "base")
command.upgrade(cfg, "heads")
command.check(cfg)
command.downgrade(cfg, "base")
"""


def test_migrations_go_down_and_up_and_match_models(db_engine):
    """Each migration, from an empty database: up, down one, up again; then all the way down and up,
    and the models match the migrations (fails if app/models.py changes without a migration).

    A downgrade that fails, or an upgrade that can't run twice after its own downgrade, is
    caught here before a deploy needs it (foundations F3, docs/plans/2026-11-13-engineering-practices.md).
    """
    import os

    url = db_engine.url.render_as_string(hide_password=False)
    env = {"DATABASE_URL": url, "PATH": os.environ["PATH"]}
    from app.db import Base

    Base.metadata.drop_all(db_engine)
    try:
        run = subprocess.run([sys.executable, "-c", STAIRS], env=env, capture_output=True, text=True)
        assert run.returncode == 0, run.stderr[-4000:]
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)
