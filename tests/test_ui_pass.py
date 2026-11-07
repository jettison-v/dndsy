"""The UI and UX pass (Brett, 2026-11-02, docs/artifacts/ui-ux-pass.html): rules the pages keep. How things look at every
width is tests/browser/test_layout.py's (Manage › Design system draws the tile with a change on its way and buttons)."""

import re

import pytest

from app import characters
from app.models import Campaign
from tests.table_setup import char, owned_by


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def lists(page: str) -> dict[str, str]:
    """Each shared list on a page, by its name, with its markup up to the next list."""
    parts = re.split(r'(?=data-list=")', page)[1:]
    return {re.match(r'data-list="([^"]+)"', p).group(1): p for p in parts}


def test_a_list_starts_on_all_the_first_time(player, db):
    """Question 3: the views keep their order; which one a list starts on is where you left it, All the first time."""
    page = player.get(f"/characters/{char(db, 'Cole').id}").text
    switches = re.findall(r'<div class="seg ls-views".*?</div>', page, re.S)
    assert switches
    for sw in switches:
        assert re.findall(r'data-ls-view="(\w+)" aria-pressed="true"', sw) == ["all"], sw


def test_full_notes_is_on_every_list_a_player_can_write_notes_on(player, dm, db):
    """A standing rule (Brett, 2026-10-17: character notes are visible to players, never the DM): the DM gets no Full
    notes. Question 4: every player's list has it, before the first note too, the Spell Book and Prepare spells as well."""
    cole = char(db, "Cole")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    mine = lists(player.get(f"/characters/{cole.id}").text)
    assert {"sheet-spells", "sheet-items", "sheet-features"} <= set(mine)
    for name in ("sheet-spells", "sheet-items", "sheet-features"):
        assert "data-ls-notes" in mine[name], name
    assert "data-ls-notes" in player.get(f"/characters/{cole.id}/spellbook").text
    assert "data-ls-notes" in player.get(f"/characters/{cole.id}/spells/prepare").text
    assert "data-ls-notes" not in dm.get(f"/characters/{cole.id}").text
    assert "data-ls-notes" not in dm.get(f"/characters/{cole.id}/spellbook").text


def test_coins_are_a_purse_with_the_total_in_gold(player, db):
    """Question 6: each coin in its metal, the total in gold; pressing it opens Change coins where the bridge works.
    Brett, 2026-11-02: small, at the right end of Items' toolbar."""
    cole = char(db, "Cole")
    summary = characters.character_summary(cole)
    cur = dict(summary["currency"])
    for b in summary["bag_coins"]:  # (a bag's coins count too: feedback 47, Cole's 7,000 gp in his Bag of Holding)
        for k, v in b["coins"].items():
            cur[k] = cur.get(k, 0) + v
    assert summary["bag_coins"] == [{"name": "Bag of Holding", "coins": {"gp": 7000}}]
    page = player.get(f"/characters/{cole.id}").text
    purse = page.split('class="purse"', 1)[1].split("</button>", 1)[0]
    for k, v in cur.items():
        assert f'class="coin-{k}"' in purse and f"<b>{v:,}</b><small>{k}</small>" in purse
    assert f'class="purse" data-use-url="/characters/{cole.id}/coins"' in page
    if len(cur) > 1:  # (on Sheet › Items the total is the purse's hover text, so the toolbar stays one line)
        assert "gp in all: Change coins" in purse
    assert "In Bag of Holding: 7,000 gp" in purse
    assert "In Bag of Holding: 7,000 gp (change a bag's coins on D&amp;D Beyond)" in player.get(f"/characters/{cole.id}/coins").text


def test_an_item_on_its_way_is_marked_in_its_row(player, db):
    """Question 1: one ↻ after anything on its way to D&D Beyond, items too: equipping marks the row's ✓."""
    cole = char(db, "Cole")
    it = next(i for i in characters.character_summary(cole)["inventory"] if i["key"].startswith("item:") and i.get("equipped"))
    iid = it["key"].split(":", 1)[1]
    assert player.post(f"/characters/{cole.id}/items/{iid}/equip", data={"on": ""}).status_code == 204
    row = player.get(f"/characters/{cole.id}").text.split(f'data-ref="{it["key"]}"', 1)[1][:2500]
    assert re.search(r'class="sh-status [a-z]+" data-sync="on"', row)


def test_a_spell_on_its_way_is_marked_in_prepare_spells(player, db):
    """Question 1: the Prepare spells window marks a spell on its way after its name, as every other place does."""
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/prepare?key=spell:Healing Word", data={"to": "unprepare"}).status_code == 200
    row = player.get(f"/characters/{cole.id}/spells/prepare").text.split('data-name="Healing Word"', 1)[1][:1200]
    assert 'data-sync="on"' in row and "↻" not in row
