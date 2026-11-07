"""Staging (Nov 6, docs/SETUP_LOG.md › A staging copy): every page says it's staging, the Staging label and an amber
menu bar, so no one mistakes it for the table's askdnd; the table's askdnd never does."""

from app.templating import templates


def test_staging_says_so_on_every_page_and_beta_never_does(player, monkeypatch):
    page = player.get("/party").text
    assert "staging-mark" not in page and "data-staging" not in page and "<title>Staging" not in page
    monkeypatch.setitem(templates.env.globals, "staging", True)
    page = player.get("/party").text
    assert 'class="staging-mark"' in page and "<body data-staging" in page and "<title>Staging · " in page
