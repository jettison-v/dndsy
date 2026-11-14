"""The extension's listener on D&D Beyond's VTT page (extension/askdnd-bridge/vtt-page.js) in a real browser: fed the
VTT's own messages, in the shapes its game server sends them (read Oct 29), it tells askdnd the fight as the VTT
shows it. Brett, 2026-10-29: two characters added mid-fight were missed; adding someone is two steps in the VTT
(into the encounter, then into combat), and both are followed."""

import json
from pathlib import Path

LISTENER = Path(__file__).parent.parent.parent / "extension/askdnd-bridge/vtt-page.js"
VTT = "https://www.dndbeyond.com/games/1"  # (a stand-in at D&D Beyond's address: the listener runs there, never on askdnd)


def vtt_page(page):
    """The listener on a stand-in VTT page, as the extension runs it on D&D Beyond's (not on askdnd's pages, whose
    Content Security Policy rightly refuses a socket to D&D Beyond)."""
    page.context.route(VTT, lambda r: r.fulfill(status=200, content_type="text/html", body="<!doctype html><title>VTT</title><main>Stand-in VTT</main>"))
    page.context.add_init_script(path=str(LISTENER))
    page.goto(VTT)


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
    player = people("player")
    player.allow("games.dndbeyond.com.invalid")  # (the stand-in game server's address: never meant to connect)
    page = player.page
    vtt_page(page)
    page.evaluate("""() => {
        window.told = [];
        addEventListener('message', e => { if (e.data && e.data.askdndBridge === 'from-vtt') window.told.push(e.data.fight); });
        window.sent = [];  // (what the page sends its game server: kept here, as the socket never connects)
        WebSocket.prototype.send = function (d) { window.sent.push(String(d)); };
        window.vtt = new WebSocket('wss://games.dndbeyond.com.invalid/test');  // (never connects: only its messages matter)
        Object.defineProperty(window.vtt, 'readyState', { value: 1 });
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
    send(act("TOKEN_ADD", {"id": "t-cole", "name": "Cole", "type": "CHARACTER", "entityId": 75423618,
                          "imageUrl": "https://www.dndbeyond.com/avatars/cole.png"}),
         act("TOKEN_ADD", {"id": "t-trah", "name": "Trah", "type": "CHARACTER", "entityId": 135831636}),
         act("ADD_TO_ENCOUNTER", ["t-cole", "t-trah"]),
         act("UPDATE_INITIATIVE", [{"group": "Pending", "key": "t-cole", "initiative": 15}, {"group": "Pending", "key": "t-trah", "initiative": 5}]),
         act("INCREMENT_COMBAT_TURN"), act("DECREMENT_COMBAT_TURN"))  # (a tell() for the line below to follow)
    assert send(act("ADD_TO_COMBAT", ["t-cole", "t-trah"])) == (4, ["Cole", "Vi", "Ogre*", "Trah"])  # sorted; still the Ogre's turn
    f = page.evaluate("window.told[window.told.length - 1]")
    assert f["turn"] == 3 and f["order"][0]["ddb_id"] == "75423618" and f["order"][0]["kind"] == "character"
    assert f["order"][0]["image"] == "https://www.dndbeyond.com/avatars/cole.png"  # the picture the VTT draws it with
    ogre = next(x for x in f["order"] if x["name"] == "Ogre")
    assert ogre["kind"] == "monster" and ogre["monster_id"] == "4904825" and f["order"][0]["monster_id"] is None
    assert send(act("INCREMENT_COMBAT_TURN")) == (4, ["Cole", "Vi", "Ogre", "Trah*"])
    assert send(act("INCREMENT_COMBAT_TURN")) == (5, ["Cole*", "Vi", "Ogre", "Trah"])
    assert send(act("UPDATE_INITIATIVE", [{"group": "Enemy", "key": "4904825", "initiative": 20}])) == (5, ["Ogre", "Cole*", "Vi", "Trah"])
    assert send(act("REMOVE_FROM_ENCOUNTER", {"entityKey": "t-trah", "group": "Party Member"})) == (5, ["Ogre", "Cole*", "Vi"])
    assert send(act("TOKEN_DELETE", "t-ogre")) == (5, ["Cole*", "Vi"])  # taken off the map
    assert send(act("END_COMBAT")) is None  # (the sidebar starts again from Add all tokens: captured on the Mac Mini, Nov 4)
    # Before Start Combat (0.12.0, Initiative from askdnd): who the DM added is told as waiting, with where the sidebar
    # keeps each, and their numbers as they're rolled
    assert send(act("ADD_TO_ENCOUNTER", ["t-vi", "t-cole"])) == (0, ["Cole", "Vi"])  # (no numbers yet: by name, as the VTT ties)
    assert send(act("UPDATE_INITIATIVE", [{"group": "Party Member", "key": "t-cole", "initiative": 15}])) == (0, ["Cole", "Vi"])
    f = page.evaluate("window.told[window.told.length - 1]")
    assert f["waiting"] is True and (f["order"][0]["group"], f["order"][0]["gkey"], f["order"][0]["initiative"]) == ("Party Member", "t-cole", 15)
    assert send(act("START_COMBAT")) == (1, ["Cole*", "Vi"])  # from the groups, as the VTT starts one
    assert page.evaluate("window.__askdndVtt.log") == []  # every action known


def test_on_the_dms_page_a_number_askdnd_hands_it_goes_out_as_the_pages_own(people):
    """0.12.0 (captured on the Mac Mini, Nov 4): the VTT takes UPDATE_INITIATIVE only with the connection's own client id,
    the one its CONNECT message carried; a number askdnd hands the page goes out so, and nothing goes before that."""
    player = people("player")
    player.allow("games.dndbeyond.com.invalid")  # (the stand-in game server's address: never meant to connect)
    page = player.page
    vtt_page(page)
    page.evaluate("""() => {
        window.sent = [];
        WebSocket.prototype.send = function (d) { window.sent.push(String(d)); };
        window.vtt = new WebSocket('wss://games.dndbeyond.com.invalid/test');
        Object.defineProperty(window.vtt, 'readyState', { value: 1 });
        window.vtt.addEventListener('error', () => {});
    }""")
    ask = "s => window.postMessage({askdndBridge: 'to-vtt', type: 'set', sets: s}, location.origin)"
    page.evaluate(ask, [{"group": "Party Member", "key": "t-vi", "initiative": 14}])
    page.wait_for_timeout(300)
    assert page.evaluate("window.sent") == []  # (no CONNECT yet: it doesn't know who it is)
    page.evaluate("""() => window.vtt.send(JSON.stringify({type: 'CONNECT', meta: {source: 'CLIENT', clientActionIndex: 0, clientId: 'c-1'}}))""")
    page.evaluate(ask, [{"group": "Party Member", "key": "t-vi", "initiative": 14}, {"group": "x", "key": "y", "initiative": "no"}])
    page.wait_for_function("window.sent.length >= 2")
    page.wait_for_timeout(300)
    sent = [json.loads(x) for x in page.evaluate("window.sent")]
    assert len(sent) == 2  # (the CONNECT, then one: a set that isn't a number is left out)
    m = sent[1]
    assert (m["type"], m["meta"]["clientId"], m["meta"]["clientActionIndex"], m["payload"]) == \
        ("UPDATE_INITIATIVE", "c-1", 1, [{"group": "Party Member", "key": "t-vi", "initiative": 14}])
