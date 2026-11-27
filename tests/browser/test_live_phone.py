"""The Live pill and window on a phone (issue 8, Brett: "The widget on mobile should let the player know that the sheet
needs to be opened on desktop or somewhere that can run the chrome extension"): below 900px the window says where your
sheet connects instead of asking a phone to open it."""

import json

from sqlalchemy import create_engine, text

SERVER_ENV = {"DDB_BRIDGE": "1"}  # (as askdnd.ai runs: a sheet connects only where the bridge may run)


def test_on_a_phone_the_live_window_says_where_your_sheet_connects(people, server, browser_db):
    """Issue 8: below 900px the Live window opens with where your sheet connects (Chrome on a computer, with the
    bridge) instead of asking a phone to open it; on a laptop that line stays hidden."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:  # (the campaign syncs with D&D Beyond: your sheet has something to connect)
        conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST(:p AS json)"), {"p": json.dumps(["sync"])})
    engine.dispose()
    player = people("player")
    for width, shown in ((375, True), (1280, False)):
        player.page.set_viewport_size({"width": width, "height": 812})
        page = player.open("/c/main/party")
        page.locator("#live-pill").click()
        line = page.locator('#live-menu [data-live-say="phone"]')
        line.wait_for(state="attached")
        assert line.evaluate("el => el.checkVisibility()") is shown, f"the phone's line at {width}px"
    assert not player.errors, player.errors
