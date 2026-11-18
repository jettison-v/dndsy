"""A standing rule (CLAUDE.md › Visibility: character notes are visible to players but NOT the DM; Found, Fixed,
Tried's T5): every place a player's own words are drawn is marked `data-private`, so a note's picture covers it in the
copy an admin, the DM and Claude see, and the page as drawn is sent without it (app.js "send a note"). The code review,
Nov 17: row notes, the note box and Reminders weren't marked."""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
WHOLE = {"_forget.html", "_plan_body.html", "_note_panel.html", "_note_form.html", "_notes_macros.html"}  # (marked as a whole)


def test_every_player_note_is_marked_private():
    unmarked = []
    for path in TEMPLATES.glob("*.html"):
        if path.name in WHOLE:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"✎ \{\{", line) and "data-private" not in line:
                unmarked.append(f"{path.name}:{n}")
    assert not unmarked, f"A player's note drawn without data-private: {unmarked}"


def test_the_whole_blocks_are_marked():
    for name in ("_forget.html", "_plan_body.html", "_note_panel.html", "_note_form.html"):
        assert "data-private" in (TEMPLATES / name).read_text(), name
    battle = (TEMPLATES / "_battle_body.html").read_text()
    assert '<div class="section" data-private>' in battle and battle.index("data-private>") < battle.index("Battle combos")  # (the combos)
