"""askdnd's table (VTT slices 0 and 1; docs/plans/2026-11-02-vtt-build-plan.md): askdnd's VTT in Labs (Manage ›
Settings), the Table button opening askdnd's table where it's on, and the table page's middle, the fight's rows as
heard from D&D Beyond's VTT."""

from app import access, vtt
from app.models import Campaign
from tests.roles import set_role
from tests.table_setup import char
from tests.test_fight import GAME, heard


def test_the_table_page_is_only_where_askdnds_vtt_is_on(player, db, sheet):
    """Brett, 2026-11-02 (DECISIONS): askdnd's VTT's way in is the Table button, D&D Beyond's VTT until it's on, and its
    page is refused while it's off, so no one stumbles on it. It's in Labs (Brett, 2026-11-03): on only with Labs on too."""
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.ddb_campaign_id = GAME
    set_role(db, "player@example.com", "player")
    db.flush()
    access.invalidate()
    campaign.is_test, campaign.vtt_pieces = True, ["sync", "vtt"]  # a test campaign, its VTT toggle on but Labs off
    db.flush()
    access.invalidate()
    assert player.get("/c/main/table").status_code == 404
    assert f'href="https://www.dndbeyond.com/games/{GAME}" target="_blank"' in player.get("/c/main/").text
    campaign.vtt_pieces = ["sync", "labs", "vtt"]
    db.flush()
    access.invalidate()
    page = player.get("/c/main/").text
    assert 'class="nav-table" href="/c/main/table"' in page and f"dndbeyond.com/games/{GAME}\" target=\"_blank\" rel=\"noopener\" title" not in page
    table = player.get("/c/main/table")
    assert table.status_code == 200 and "Nothing on the table yet" in table.text
    assert player.get("/table", follow_redirects=False).status_code == 404  # one address: /c/<campaign>/table


def test_the_tables_middle_is_the_fight_heard_from_d_and_d_beyond(player, dm, db, sheet):
    """VTT Layout › The first step: a row per fighter in turn order while the map stays on D&D Beyond: a character's
    own Hit Points and AC, opening its short version in the side panel; a creature's numbers come when askdnd runs the
    fight; a token the DM hid is the DM's only."""
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.ddb_campaign_id, campaign.vtt_pieces = GAME, ["sync", "labs", "vtt"]
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
