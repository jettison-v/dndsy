"""How long a condition lasts (app/conditions.py, app/fight.py follow; Brett, 2026-10-29, docs/mockups/turn-conditions.html):
timed by the turns heard from D&D Beyond's VTT as the DM presses Next. When one runs out or asks for a save, its
player and the DM are reminded; nothing ends by itself."""

from app import fight
from app.models import Campaign
from tests.roles import set_role
from tests.table_setup import char

GAME = "9001"
KEYS = ["t-cole", "t-e1", "t-gob"]  # Cole, then Enemy 1, then a goblin


def at(db, round_: int, turn: int):
    """The DM pressed Next until this round and turn: askdnd hears it."""
    cole = char(db, "Cole")
    order = [{"key": "t-cole", "name": "Cole", "kind": "character", "ddb_id": cole.ddb_id, "initiative": 18},
             {"key": "t-e1", "name": "Enemy 1", "kind": "monster", "initiative": 15},
             {"key": "t-gob", "name": "Goblin", "kind": "monster", "initiative": 9}]
    for i, x in enumerate(order):
        x["active"] = i == turn - 1
    fight.heard(db, db.get(Campaign, cole.campaign_id), {"round": round_, "turn": turn, "order": order})


def walk(db, start: tuple[int, int], end: tuple[int, int]):
    """Each Next from one turn to another, as heard one at a time."""
    r, t = start
    while (r, t) != end:
        t += 1
        if t > len(KEYS):
            r, t = r + 1, 1
        at(db, r, t)


def setup(db, player):
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    campaign.ddb_campaign_id = GAME
    set_role(db, "player@example.com", "player")
    set_role(db, "dm@example.com", "dm")
    return campaign


def condition(db, name):
    return next(c for c in char(db, "Cole").conditions or [] if c["name"] == name)


def reminders(db, email):
    f = fight.for_person(db, db.get(Campaign, char(db, "Cole").campaign_id), email)
    return (f or {}).get("reminders") or []


def start(player, db, name, **lasts):
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/conditions", data={"name": name, **lasts}, headers={"HX-Request": "true"})
    assert r.status_code == 200, r.text


def test_until_the_end_of_your_next_turn_counts_your_next_turn_not_this_one(player, dm, db, sheet):
    setup(db, player)
    at(db, 1, 2)  # Enemy 1's turn: it frightens Cole
    start(player, db, "Frightened", lasts="endnext", whose="self")
    assert condition(db, "Frightened")["lasts"] == {"kind": "endnext", "of": {"self": True}}
    walk(db, (1, 2), (2, 1))  # the goblin's turn, then Cole's: his next turn has begun
    assert not condition(db, "Frightened").get("due")
    at(db, 2, 2)  # and ends
    assert condition(db, "Frightened")["due"] is True and "Frightened" in condition(db, "Frightened")["name"]
    mine = reminders(db, "player@example.com")
    assert [(r["kind"], r["name"], r["mine"]) for r in mine] == [("ends", "Frightened", True)]
    assert [r["mine"] for r in reminders(db, "dm@example.com")] == [False]  # the DM sees it, to know
    page = player.get(f"/characters/{char(db, 'Cole').id}/battle").text
    assert "due to end" in page and "/conditions/keep" in page and 'class="cond-soon"' in page  # pill, Keep, the badge's dot
    assert "data-reminders=" in page
    assert char(db, "Cole").conditions[-1]["name"] == "Frightened"  # still on: nothing ends by itself


def test_a_save_at_the_end_of_each_of_your_turns_reminds_you_as_each_one_begins(player, db, sheet):
    setup(db, player)
    at(db, 1, 2)
    start(player, db, "Paralyzed", lasts="save", ability="Wis", dc="13", whose="self")
    walk(db, (1, 2), (2, 1))  # Cole's turn begins: the reminder comes now, not once the next turn has begun
    saves = [r for r in reminders(db, "player@example.com") if r["kind"] == "save"]
    assert len(saves) == 1 and "at the end of this turn" in saves[0]["text"]
    walk(db, (2, 1), (3, 2))  # it ends, and the next one begins and ends: one more, as it began
    saves = [r for r in reminders(db, "player@example.com") if r["kind"] == "save"]
    assert len(saves) == 2 and saves[0]["ability"] == "Wis" and saves[0]["dc"] == 13 and "mod" in saves[0]
    assert not condition(db, "Paralyzed").get("due")  # a save ends it, not the clock


def test_rounds_count_down_from_the_turn_it_began_on(player, db, sheet):
    setup(db, player)
    at(db, 1, 2)  # begun on Enemy 1's turn
    start(player, db, "Poisoned", lasts="rounds", n="2")
    assert condition(db, "Poisoned")["left"] == 2 and condition(db, "Poisoned")["began"] == "t-e1"
    walk(db, (1, 2), (2, 2))
    assert condition(db, "Poisoned")["left"] == 1 and not condition(db, "Poisoned").get("due")
    walk(db, (2, 2), (3, 2))
    assert condition(db, "Poisoned")["due"] is True
    assert any(r["kind"] == "ends" and "2 rounds" in r["text"] for r in reminders(db, "player@example.com"))


def test_until_the_start_of_someone_elses_turn(player, db, sheet):
    setup(db, player)
    at(db, 1, 1)  # Cole's turn
    start(player, db, "Prone", lasts="startnext", whose="t-e1")
    assert condition(db, "Prone")["lasts"]["of"] == {"key": "t-e1", "name": "Enemy 1"}
    at(db, 1, 2)
    assert condition(db, "Prone")["due"] is True


def test_concentration_counts_its_rounds_on_the_casters_turns(player, db, sheet):
    setup(db, player)
    cole = char(db, "Cole")
    cole.concentration = {"spell": "Moonbeam", "key": "spell:Moonbeam", "level": 2, "round": 1, "rounds": 2}
    at(db, 1, 1)
    walk(db, (1, 1), (2, 1))  # Cole's next turn
    assert char(db, "Cole").concentration["round"] == 2
    walk(db, (2, 1), (3, 1))
    conc = char(db, "Cole").concentration
    assert conc["round"] == 2 and conc["due"] is True
    assert any(r["kind"] == "conc" for r in reminders(db, "player@example.com"))
    assert char(db, "Cole").concentration  # still on until the player ends it


def test_keep_lets_it_last_and_going_back_counts_nothing(player, db, sheet):
    setup(db, player)
    at(db, 1, 1)
    start(player, db, "Prone", lasts="startnext", whose="t-e1")
    at(db, 1, 2)
    assert condition(db, "Prone")["due"] is True
    cole = char(db, "Cole")
    player.post(f"/characters/{cole.id}/conditions/keep", data={"name": "Prone"}, headers={"HX-Request": "true"})
    assert "lasts" not in condition(db, "Prone") and not condition(db, "Prone").get("due")  # until it's ended
    start(player, db, "Poisoned", lasts="rounds", n="1")
    at(db, 1, 1)  # the DM went back a turn
    assert condition(db, "Poisoned")["left"] == 1


def test_reminders_go_to_that_characters_player_and_the_dm_only(player, db, sheet):
    """A standing rule (Brett, 2026-10-29): a reminder is for that character's player and the DM."""
    setup(db, player)
    set_role(db, "other@example.com", "player")
    at(db, 1, 1)
    start(player, db, "Prone", lasts="startnext", whose="t-e1")
    at(db, 1, 2)
    assert reminders(db, "player@example.com") and reminders(db, "dm@example.com")
    assert reminders(db, "other@example.com") == []
