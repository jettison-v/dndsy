"""askdnd's rolls in D&D Beyond's Game Log (app/gamelog.py; Brett, 2026-10-29, option B): each in the Game Log's own
shape as askdnd's (source "askdnd", ⓐ after the name), addressed as D&D Beyond addresses its own, sent from the player's
sheet only where the bridge works; never counted twice when the game log brings it back."""

import json

from sqlalchemy import select

from app import characters, gamelog
from app.models import TableRoll
from tests.table_setup import char

GAME, DM = 8215895, 109525691


def in_game(db, sheet):
    """Cole's sheet in a D&D Beyond game (its campaign), as D&D Beyond's character data says."""
    sheet["campaign"] = {"id": GAME, "dmUserId": DM, "name": "Test Campaign"}
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    return cole


def row(cole, **kw):
    return TableRoll(**{"id": 7, "campaign_id": cole.campaign_id, "character_id": cole.id, "label": "Pistol", "kind": "attack",
                        "formula": "d20+5", "dice": [6, 17], "kept": 17, "modifier": 5, "total": 22, "mode": "adv",
                        "visibility": "table", "extras": [], "parts": [], "crit": False, **kw})


def test_a_roll_is_sent_as_askdnds_in_the_game_logs_own_shape(db, sheet):
    """Tested on Vi (Oct 29): the Game Log shows and keeps these, ⓐ marking them askdnd's; advantage as D&D Beyond keeps
    it (keep highest); no dice set named (D&D Beyond shows its basic dice)."""
    cole = in_game(db, sheet)
    (m,) = gamelog.messages(db, row(cole), cole)
    assert (m["source"], m["gameId"], m["messageScope"], m["messageTarget"], m["eventType"]) == ("askdnd", str(GAME), "gameId", str(GAME), "dice/roll/fulfilled")
    d = m["data"]
    assert d["action"] == "Pistol ⓐ" and d["context"]["name"] == "Cole" and "setId" not in d and d["rollId"] == "askdnd-7-0"
    r = d["rolls"][0]
    assert (r["rollType"], r["rollKind"], r["diceNotation"]["set"][0]["operation"], r["result"]["total"]) == ("to hit", "advantage", 2, 22)
    assert r["diceNotation"]["constant"] == 5 and r["result"]["values"] == [6, 17]


def test_saves_damage_types_criticals_bless_and_private_rolls(db, sheet):
    cole = in_game(db, sheet)
    save = gamelog.messages(db, row(cole, label="Con save", kind="save", dice=[13], kept=13, total=18, mode="normal",
                                     extras=[{"label": "Bless", "formula": "+1d4", "dice": [3], "total": 3}], visibility="dm"), cole)[0]
    r = save["data"]["rolls"][0]
    assert save["data"]["action"] == "Con ⓐ" and r["rollType"] == "save"  # (D&D Beyond: "Con ⓐ: Save")
    assert [s["dieType"] for s in r["diceNotation"]["set"]] == ["d20", "d4"] and r["diceNotation"]["constant"] == 2  # 13 + 3 + 2 = 18
    assert (save["messageScope"], save["messageTarget"]) == ("userId", str(DM))  # for the DM only
    hit = gamelog.messages(db, row(cole, kind="damage", formula="1d10+1 piercing", dice=[4, 9], kept=None, modifier=1, total=14, mode="normal",
                                    crit=True, parts=[{"label": "", "kind": "piercing", "crit": True, "formula": "2d10+1", "dice": [4, 9], "total": 14}],
                                    visibility="self"), cole)[0]
    r = hit["data"]["rolls"][0]
    assert hit["data"]["action"] == "Pistol ⓐ crit" and (r["rollType"], r["rollKind"]) == ("piercing", "critical hit")
    assert r["diceNotation"]["set"][0]["count"] == 2 and r["diceNotation"]["constant"] == 1
    assert hit["messageTarget"] == "self"  # (the sheet puts in whoever is signed in there)


def test_only_where_the_bridge_works_and_the_sheet_is_in_a_game(db, sheet, monkeypatch):
    from app import config

    cole = char(db, "Cole")
    assert gamelog.messages(db, row(cole), cole) == []  # not in a D&D Beyond game
    cole = in_game(db, sheet)
    assert gamelog.messages(db, row(cole), None) == []  # plain dice: no sheet to send them from
    monkeypatch.setattr(config, "DDB_BRIDGE", False)
    assert gamelog.messages(db, row(cole), cole) == []


def test_a_roll_made_in_askdnd_comes_back_with_what_to_send_and_is_not_kept_twice(player, db, sheet):
    """The roll's answer carries the messages for the player's page to hand the extension; when another sheet in the
    game hears askdnd's roll in the game log, it isn't recorded again (ddb_bridge.heard_in_game)."""
    cole = in_game(db, sheet)
    r = player.post("/rolls", data={"character": cole.id, "kind": "save", "label": "Wis save", "mod": "+3"}, headers={"X-Requested-With": "fetch"})
    out = r.json()
    assert out["gamelog"]["ddbId"] == "75423618" and out["gamelog"]["messages"][0]["data"]["action"] == "Wis ⓐ"
    before = db.scalar(select(TableRoll.id).order_by(TableRoll.id.desc()))
    heard = {**out["gamelog"]["messages"][0], "userId": "1", "id": "x"}
    assert player.post("/bridge/others-roll/75423618", json=heard).json() == {"ok": False}
    assert db.scalar(select(TableRoll.id).order_by(TableRoll.id.desc())) == before
    sent = json.dumps(out["gamelog"])
    assert "Icewind" not in sent and '"source": "askdnd"' in sent
