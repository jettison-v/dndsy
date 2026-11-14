"""app/access.py's questions answered from a fixed set of rows (what `_rows()` keeps): the gaps mutation testing found
(foundation F8, scripts/mutation.py access): a campaign or a set of rows passed in that was ignored, and the two rules
everyone at a table has."""

import pytest

from app import access

ROWS = {
    access.CAMPAIGNS: [{"id": 1, "slug": "main", "name": "Main"}, {"id": 2, "slug": "other", "name": "Other"}],
    "dana@example.com": {"id": 10, "access": access.MEMBER, "roles": {1: access.PLAYER, 2: access.DM}, "current": 2},
    "pat@example.com": {"id": 11, "access": access.MEMBER, "roles": {1: access.PLAYER}, "feedback": True},
    "lee@example.com": {"id": 12, "access": access.ADMIN, "roles": {}},
}


@pytest.fixture
def rows(monkeypatch):
    monkeypatch.setattr(access, "_rows", lambda: ROWS)
    monkeypatch.setattr(access.config, "ADMIN_EMAILS", "")
    monkeypatch.setattr(access.config, "REVIEWER_EMAILS", "")
    return ROWS


def test_the_campaign_someone_is_in_is_theirs_not_the_first(rows):
    assert access.current_campaign_id("dana@example.com") == 2
    assert access.current_campaign_id("pat@example.com") == 1


def test_is_dm_asks_about_the_campaign_it_is_given(rows):
    assert access.is_dm("dana@example.com", 2)
    assert not access.is_dm("dana@example.com", 1)


def test_sends_feedback_reads_the_rows_it_is_given():
    """The page of accounts passes its own rows (Manage › Accounts): an admin there, or an account switched on there."""
    given = {"sam@example.com": {"access": access.ADMIN}, "kit@example.com": {"access": access.MEMBER, "feedback": True}}
    assert access.sends_feedback("sam@example.com", given)
    assert access.sends_feedback("kit@example.com", given)
    assert not access.sends_feedback("kit@example.com", {"kit@example.com": {"access": access.MEMBER}})


def test_sends_feedback_from_the_kept_rows(rows):
    assert access.sends_feedback("pat@example.com") and access.sends_feedback("lee@example.com")
    assert not access.sends_feedback("dana@example.com") and not access.sends_feedback(None)


@pytest.mark.parametrize("campaign_role", [None, access.PLAYER, access.REVIEWER, access.DM])
def test_everyone_at_the_table_reads_and_suggests(campaign_role):
    assert access.allows("read", access.MEMBER, campaign_role)
    assert access.allows("suggest", access.MEMBER, campaign_role)
    assert not access.allows("read", None, campaign_role), "someone who can't sign in reads nothing"
