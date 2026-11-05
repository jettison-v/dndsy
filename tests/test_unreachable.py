"""A change for D&D Beyond says it can't reach the sheet where it starts (Brett, Nov 5: "stop them early with a warning,
rather than letting them get too far into the workflow and then having it fail"). The campaign syncs with D&D Beyond,
but no sheet and no DM's browser can reach Cole's (ddb_bridge.how is None)."""

import pytest

from app import ddb_bridge, giving, hiding, table_rolls
from app.models import Campaign
from tests.table_setup import char


@pytest.fixture
def unreached(db, sheet, monkeypatch):
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()
    monkeypatch.setattr(ddb_bridge, "how", lambda ch: None)
    return char(db, "Cole")


def test_battle_says_so_where_a_condition_starts_and_ends(player, db, unreached):
    page = player.get(f"/characters/{unreached.id}/battle").text
    box = page.split('class="cond-pill cond-add"')[1]
    assert "can&#39;t be reached: open it in Chrome with the askdnd bridge to start a condition here" in box
    assert "Effects below are askdnd's own and still work" in box
    conditions = box.split('<div class="ls-label">Conditions</div>')[1].split('<div class="ls-label mt-2">Effects</div>')
    assert "disabled" in conditions[0] and "disabled" not in conditions[1]  # (D&D Beyond's greyed; askdnd's effects not)


def test_an_items_panel_says_so_instead_of_its_buttons(player, db, unreached, sheet):
    potion = next(i for i in sheet["inventory"] if i["definition"]["name"] == "Potion of Healing")
    panel = player.get(f"/characters/{unreached.id}/detail?ref=item:{potion['id']}").text
    assert "to equip, attune, count, give or move it here" in panel and "/equip" not in panel


def test_the_item_browser_and_prepare_spells_say_so_at_the_top(player, db, unreached, monkeypatch):
    monkeypatch.setattr(giving, "_catalog", {"at": 0.0, "tried": 0.0, "items": []})
    monkeypatch.setattr(giving.ddb, "_get_json", lambda url, timeout: {"data": []})
    w = player.get(f"/characters/{unreached.id}/items/browse").text
    assert 'class="unreached"' in w and w.index('class="unreached"') < w.index("data-ib-said")  # (at the top, not by the button)
    p = player.get(f"/characters/{unreached.id}/spells/prepare").text
    assert "to prepare spells here" in p and p.index('class="unreached"') < p.index('class="use-said"')


def test_a_hide_roll_still_rolls_and_says_to_mark_invisible_on_the_sheet(player, db, unreached, monkeypatch):
    monkeypatch.setattr(table_rolls, "die", lambda n: 18 if n == 20 else 1)
    r = player.post("/rolls", data={"character": unreached.id, "kind": "check", "label": hiding.LABEL, "mod": "+2"})
    assert r.status_code == 200 and "Mark Invisible on D&D Beyond: the sheet can't be reached" in r.json()["death"]["text"]
    db.refresh(unreached)
    assert hiding.hidden(unreached) == 20
