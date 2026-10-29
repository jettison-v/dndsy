"""The extension's listener on D&D Beyond's VTT page (extension/askdnd-bridge/vtt-page.js) in a real browser: fed the
VTT's own messages, in the shapes its game server sends them (read Oct 29), it tells askdnd the fight as the VTT
shows it. Brett, 2026-10-29: two characters added mid-fight were missed; adding someone is two steps in the VTT
(into the encounter, then into combat), and both are followed."""

import json
from pathlib import Path

LISTENER = Path(__file__).parent.parent.parent / "extension/askdnd-bridge/vtt-page.js"


def sync():
    tokens = {"t-vi": {"name": "Vi", "type": "CHARACTER", "entityId": 172836541, "hidden": False},
              "t-ogre": {"name": "Ogre", "type": "MONSTER", "entityId": 4904825, "hidden": False}}
    encounter = {"groups": {"Enemy": {"4904825": {"tokenIds": ["t-ogre"], "initiative": 9, "initiativeBonus": -1}},
                            "Party Member": {"t-vi": {"tokenIds": ["t-vi"], "initiative": 11, "initiativeBonus": 1}}},
                 "round": 4, "turn": 1,
                 "combat": {"activeId": "t-vi", "combatants": [{"tokenId": "t-vi", "initiative": 11, "initiativeBonus": 1},
                                                              {"tokenId": "t-ogre", "initiative": 9, "initiativeBonus": -1}]}}
    return {"type": "SYNC", "payload": {"game": {"tokens": {"ids": list(tokens), "entities": tokens}, "encounter": encounter}}}


def act(kind, payload=None):
    return {"type": kind, "meta": {"source": "SERVER"}, **({"payload": payload} if payload is not None else {})}


def test_the_listener_follows_the_fight_as_the_vtt_does(people):
    page = people("player").page
    page.context.add_init_script(path=str(LISTENER))
    page.reload()
    page.evaluate("""() => {
        window.told = [];
        addEventListener('message', e => { if (e.data && e.data.askdndBridge === 'from-vtt') window.told.push(e.data.fight); });
        window.vtt = new WebSocket('wss://games.dndbeyond.com.invalid/test');  // (never connects: only its messages matter)
        window.vtt.addEventListener('error', () => {});
    }""")

    def send(*messages):
        before = page.evaluate("window.told.length")
        for m in messages:
            page.evaluate("m => window.vtt.dispatchEvent(new MessageEvent('message', {data: m}))", json.dumps(m))
        page.wait_for_function(f"window.told.length > {before}")
        f = page.evaluate("window.told[window.told.length - 1]")
        return f and (f["round"], [x["name"] + ("*" if x["active"] else "") for x in f["order"]])

    assert send(sync()) == (4, ["Vi*", "Ogre"])
    assert send(act("INCREMENT_COMBAT_TURN")) == (4, ["Vi", "Ogre*"])
    # Two characters added mid-fight: on the map, into the encounter (waiting), their initiative, then into combat
    send(act("TOKEN_ADD", {"id": "t-cole", "name": "Cole", "type": "CHARACTER", "entityId": 75423618}),
         act("TOKEN_ADD", {"id": "t-trah", "name": "Trah", "type": "CHARACTER", "entityId": 135831636}),
         act("ADD_TO_ENCOUNTER", ["t-cole", "t-trah"]),
         act("UPDATE_INITIATIVE", [{"group": "Pending", "key": "t-cole", "initiative": 15}, {"group": "Pending", "key": "t-trah", "initiative": 5}]),
         act("INCREMENT_COMBAT_TURN"), act("DECREMENT_COMBAT_TURN"))  # (a tell() for the line below to follow)
    assert send(act("ADD_TO_COMBAT", ["t-cole", "t-trah"])) == (4, ["Cole", "Vi", "Ogre*", "Trah"])  # sorted; still the Ogre's turn
    f = page.evaluate("window.told[window.told.length - 1]")
    assert f["turn"] == 3 and f["order"][0]["ddb_id"] == "75423618" and f["order"][0]["kind"] == "character"
    assert send(act("INCREMENT_COMBAT_TURN")) == (4, ["Cole", "Vi", "Ogre", "Trah*"])
    assert send(act("INCREMENT_COMBAT_TURN")) == (5, ["Cole*", "Vi", "Ogre", "Trah"])
    assert send(act("UPDATE_INITIATIVE", [{"group": "Enemy", "key": "4904825", "initiative": 20}])) == (5, ["Ogre", "Cole*", "Vi", "Trah"])
    assert send(act("REMOVE_FROM_ENCOUNTER", {"entityKey": "t-trah", "group": "Party Member"})) == (5, ["Ogre", "Cole*", "Vi"])
    assert send(act("TOKEN_DELETE", "t-ogre")) == (5, ["Cole*", "Vi"])  # taken off the map
    assert send(act("END_COMBAT")) is None
    assert send(act("START_COMBAT")) == (1, ["Vi*"])  # from the groups, as the VTT starts one
    assert page.evaluate("window.__askdndVtt.log") == []  # every action known
