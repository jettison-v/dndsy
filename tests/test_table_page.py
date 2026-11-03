"""The two switches and askdnd's table (VTT slices 0 and 1; docs/plans/2026-11-02-vtt-build-plan.md): Play through
askdnd and askdnd's VTT on Manage › Settings, the Table button opening askdnd's table where its switch is on, and the
table page's middle, the fight's rows as heard from D&D Beyond's VTT."""

import dataclasses

from app import access, vtt
from app.models import Campaign
from tests.roles import set_role
from tests.table_setup import char
from tests.test_fight import GAME, heard


def test_play_through_askdnd_is_one_switch_that_grows(monkeypatch):
    """Brett, 2026-11-02 (DECISIONS): the bridge, casting, resources and rests, and the DM as a backup come together as
    Play through askdnd. Until Brett has reviewed live state, the switch gives what's Ready (the bridge); a piece that
    becomes Ready later comes on with it, without switching again."""
    table = Campaign(name="Main", vtt_pieces=[])
    assert vtt.switch(table, "play", True) == "Play through askdnd is on for Main." and table.vtt_pieces == ["play"]
    assert vtt.on(table, "ddb_bridge") and not vtt.on(table, "live_state") and not vtt.on(table, "dm_backup")
    play = next(r for r in vtt.rows(table) if r["key"] == "play")
    assert play["on"] and play["some_ready"] and not play["ready"] and [p.key for p in play["parts"]] == ["ddb_bridge", "live_state", "dm_backup"]
    reviewed = [dataclasses.replace(p, ready=True) if p.key in ("live_state", "dm_backup") else p for p in vtt.PIECES]
    monkeypatch.setattr(vtt, "PIECES", reviewed)
    assert vtt.on(table, "live_state") and vtt.on(table, "dm_backup")  # came on with the switch
    monkeypatch.undo()
    old = Campaign(name="Old", vtt_pieces=["ddb_bridge", "table_dice"])  # switched on before the switches grouped it
    assert vtt.on(old, "ddb_bridge") and next(r for r in vtt.rows(old) if r["key"] == "play")["on"]
    vtt.switch(old, "play", False)
    assert old.vtt_pieces == ["table_dice"] and not vtt.on(old, "ddb_bridge")
    assert vtt.switch(table, "vtt", True) == "askdnd's VTT is still being built." and not vtt.on(table, "vtt_table")


def test_the_table_page_is_only_where_askdnds_vtt_is_on(player, db, sheet):
    """Brett, 2026-11-02 (DECISIONS): askdnd's VTT's way in is the Table button, D&D Beyond's VTT until it's on, and its
    page is refused while it's off, so no one stumbles on it. A test campaign has it."""
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.ddb_campaign_id = GAME
    set_role(db, "player@example.com", "player")
    db.flush()
    access.invalidate()
    assert player.get("/c/main/table").status_code == 404
    assert f'href="https://www.dndbeyond.com/games/{GAME}" target="_blank"' in player.get("/c/main/").text
    campaign.is_test = True
    db.flush()
    access.invalidate()
    page = player.get("/c/main/").text
    assert 'class="nav-table" href="/c/main/table"' in page and f"dndbeyond.com/games/{GAME}\" target=\"_blank\" rel=\"noopener\" title" not in page
    table = player.get("/c/main/table")
    assert table.status_code == 200 and "No fight yet" in table.text
    assert player.get("/table", follow_redirects=False).status_code == 404  # one address: /c/<campaign>/table


def test_the_tables_middle_is_the_fight_heard_from_d_and_d_beyond(player, dm, db, sheet):
    """VTT Layout › The first step: a row per fighter in turn order while the map stays on D&D Beyond: a character's
    own Hit Points and AC, opening its short version in the side panel; a creature's numbers come when askdnd runs the
    fight; a token the DM hid is the DM's only."""
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.ddb_campaign_id, campaign.is_test = GAME, True
    set_role(db, "player@example.com", "player")
    set_role(db, "dm@example.com", "dm")
    db.flush()
    access.invalidate()
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard(hidden_goblin=True)})
    cole = char(db, "Cole")
    page = player.get("/c/main/table").text
    middle = page[page.index('class="tb-middle"'):]
    assert "<b>Cole</b>" in middle and "<b>Enemy 1</b>" in middle and "Goblin" not in middle
    assert f'data-panel-url="/characters/{cole.id}/brief"' in middle and f'data-panel-url="/characters/{cole.id}/vital/hp"' in middle
    assert '<td class="ft-init">18<span class="ft-now">Now</span></td>' in middle
    dms = dm.get("/c/main/table").text
    assert "<b>Goblin</b>" in dms and ">Hidden</span>" in dms
    party = player.get("/party").text
    assert "<th>Conditions and reminders</th>" in party and "pt-track-wrap always" not in party  # Party's Rows: the same rows
