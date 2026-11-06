"""Hide kept on Battle (app/hiding.py; feedback 14, docs/mockups/hide-ready.html): a Hide roll at the table of 15 or
more starts Hidden (askdnd's Invisible with the DC to find you, and Invisible on the D&D Beyond sheet)."""

from sqlalchemy import select

from app import conditions as cond
from app import hiding, table_rolls
from app.models import BridgeIntent
from tests.table_setup import char


def test_a_hide_roll_of_15_or_more_starts_hidden_on_battle_and_on_the_sheet(player, db, sheet, monkeypatch):
    cole = char(db, "Cole")
    dice = iter([3, 12, 10])
    monkeypatch.setattr(table_rolls, "die", lambda n: next(dice) if n == 20 else 1)
    panel = player.get(f"/characters/{cole.id}/detail?ref=rule%3Abasic%3AHide").text
    assert 'data-label="Hide (Stealth)"' in panel and "DC 15" in panel and "starts <b>Hidden</b>" in panel

    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": hiding.LABEL, "mod": "+5"})
    assert r.json()["death"]["text"] == "Not hidden: 8 against DC 15" and hiding.hidden(cole) is None

    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": hiding.LABEL, "mod": "+5"})
    assert r.json()["death"]["text"].startswith("Hidden: 17 is the DC to find you") and r.json()["death"]["deliver"]
    db.refresh(cole)
    assert hiding.hidden(cole) == 17
    intent = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id).order_by(BridgeIntent.id.desc())).first()
    assert intent.data == {"field": cond.ddb_field("Invisible"), "value": True}  # (Invisible on the sheet: Brett's choice 1)
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "<b>Hidden</b>" in page and "find DC 17" in page and 'data-hidden="17"' in page and "End Hidden" in page

    other = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Stealth check", "mod": "+5"})
    assert "death" not in other.json()  # (only a Hide roll hides)


def test_ending_invisible_ends_hidden(player, db, sheet):
    cole = char(db, "Cole")
    hiding.start(db, cole, 18)
    db.commit()
    player.post(f"/characters/{cole.id}/conditions/end", data={"name": "Invisible"})
    db.refresh(cole)
    assert hiding.hidden(cole) is None and 'data-hidden' not in player.get(f"/characters/{cole.id}/battle").text


def test_hide_leaves_an_invisible_from_a_spell_as_it_is(player, db, sheet, monkeypatch):
    """Code review, Nov 5: Hide never replaces an Invisible something else gave (Greater Invisibility, with its own
    end): it says the DC to find you and changes nothing, so an attack's "ends Hidden" can't end the spell."""
    cole = char(db, "Cole")
    cole.conditions = [{"name": "Invisible", "source": "Greater Invisibility", "lasts": {"kind": "rounds", "left": 10}}]
    db.flush()
    monkeypatch.setattr(table_rolls, "die", lambda n: 18 if n == 20 else 1)
    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": hiding.LABEL, "mod": "+5"})
    assert r.json()["death"]["text"] == "Already Invisible (Greater Invisibility): 23 is the DC to find you"
    db.refresh(cole)
    assert cole.conditions[0]["source"] == "Greater Invisibility" and hiding.hidden(cole) is None
