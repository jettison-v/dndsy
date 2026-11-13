"""The connection band (Brett chose B, Nov 13, docs/mockups/connection-drops/; _conn_band.html, app/live.py `dropped`):
at the last session a player closed their D&D Beyond sheet partway through, their rolls stopped reaching the DM's Game
Log, and nothing told them. While your own sheet's connection is worse than it was tonight, a band under the menu bar
says what stopped and how to fix it. D&D Beyond is never called: the fake sheet stands in."""

import re
from datetime import UTC, datetime, timedelta

from app import live
from tests.test_dm_backup import carry, table


def band(html: str) -> str:
    """The band's opening tag and words, or "" when it's hidden."""
    m = re.search(r'<div id="conn-band"[^>]*>.*?</div>(?=\s*</header>|\s*$)', html, re.S)
    assert m, "every signed-in page carries the band's place"
    tag = m.group(0).split(">")[0]
    return "" if " hidden" in tag else m.group(0)


def test_the_band_says_so_when_your_sheets_connection_gets_worse_and_goes_once_its_back(player, dm, db, table):
    """A standing rule (Brett, Nov 13: "a reasonably invasive notification when a connection gets worse"): amber while
    the DM's browser still reaches the sheet, red when nothing does, gone when the sheet is heard again."""
    cole = table
    page = lambda: player.get(f"/characters/{cole.id}/battle").text
    assert band(page()) == ""  # never connected tonight: the pill says what to do, as before

    player.post("/bridge/heard/75423618?pull=1")
    assert band(page()) == ""  # connected

    player.post("/bridge/closed/75423618")
    db.refresh(cole)
    red = band(page())
    assert 'class="conn-band bad"' in red and f'data-band-key="{cole.id}:bad"' in red
    assert "Cole isn't connected to D&amp;D Beyond." in red and "https://www.dndbeyond.com/characters/75423618" in red

    carry(dm)  # the DM's browser can reach it
    amber = band(page())
    assert 'class="conn-band via"' in amber and "Your D&amp;D Beyond sheet closed." in amber
    assert "Your rolls no longer reach the DM's Game Log" in amber and f'data-band-key="{cole.id}:via"' in amber

    player.post("/bridge/heard/75423618?pull=1")
    assert band(page()) == ""  # back: it leaves by itself


def test_only_a_connection_that_got_worse_tonight(player, db, table):
    """Hours later it isn't news: a player who hasn't opened the sheet since the last game sees the pill as before."""
    cole = table
    cole.sheet_seen_at = datetime.now(UTC) - live.DROPPED - timedelta(minutes=1)
    db.flush()
    assert band(player.get(f"/characters/{cole.id}/battle").text) == ""
    cole.sheet_seen_at = datetime.now(UTC) - timedelta(minutes=20)
    db.flush()
    assert "conn-band bad" in band(player.get(f"/characters/{cole.id}/battle").text)


def test_the_band_comes_with_the_pill_and_is_only_for_your_own_sheet(player, dm, db, table):
    """The pill's answer carries it (every page's tick swaps both); the DM, whose sheet it isn't, never gets it."""
    cole = table
    player.post("/bridge/heard/75423618?pull=1")
    player.post("/bridge/closed/75423618")
    answer = player.get(f"/live/pill?c={cole.id}").text
    assert 'id="live-pill"' in answer and 'id="conn-band"' in answer and 'hx-swap-oob="true"' in answer.split('id="conn-band"')[1].split(">")[0]
    assert "conn-band bad" in band(answer)
    assert band(dm.get("/c/main/").text) == ""
    assert band(dm.get(f"/characters/{cole.id}/battle").text) == ""


def test_the_pill_says_where_the_sheet_is_for_the_roll_cards_note(player, db, table):
    """The roll card's amber note opens the sheet (app.js logLine): the pill carries its address."""
    cole = table
    player.post("/bridge/heard/75423618?pull=1")  # (a read: the sheet says which D&D Beyond game it's in)
    pill = player.get(f"/characters/{cole.id}/battle").text.split('id="live-pill"')[1].split(">")[0]
    assert 'data-sheet="https://www.dndbeyond.com/characters/75423618"' in pill
