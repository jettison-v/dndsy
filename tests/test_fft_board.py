"""The Board (app/fft/work_page.py `board`, _board.html, Development's first tab and the design system; item 39, A
sturdier loop, 4 of 4, Brett's picks on The Work Board): every piece of work in one of five columns, from askdnd's own
record, each card its kind and one line of why, amber when stuck; and each issue's round trip in its History."""

from datetime import timedelta

import pytest

from app.fft import rules, work_page
from app.fft.models import FftArea

OWNER = "claude:main"


def _issue(db, title, feature="feedback", **kw):
    i = rules.new_issue(db, "claude", title, feature=feature, **kw)
    db.flush()
    return i


def _pull(db, number, branch, **kw):
    out = rules.pulls_seen(db, "github", [{"number": number, "branch": branch, "state": "open", "title": f"Pull {number}"} | kw])[0]
    db.flush()
    return out


def _where(db) -> dict[str, list[str]]:
    return {k: [c["key"] for c in cards] for k, _, _, cards in work_page.board(db)["cols"]}


def test_each_piece_sits_in_one_column_from_askdnds_record(db):
    """Ready in Claude's order; Building, its one claim; Shipping, a pull request on its way, with its step; Waiting, a
    gate not met; and a pull request with nothing behind it is an Upkeep card of its own."""
    first, second, third = _issue(db, "First"), _issue(db, "Second", feature="hp"), _issue(db, "Third", feature="dice")
    b = db.get(FftArea, second.area_id)
    c = db.get(FftArea, third.area_id)
    assert _where(db)["ready"] == [f"a{first.area_id}", f"a{second.area_id}", f"a{third.area_id}"]
    rules.lock_area(db, OWNER, b)
    _pull(db, 400, f"a{c.id}-fix", tests="running", merge_state="blocked")
    _pull(db, 401, "dependabot/uv/x", by_bot=True, tests="failed")
    c2 = db.get(FftArea, first.area_id)
    c2.held = True
    db.flush()
    got = _where(db)
    assert got["building"] == [f"a{b.id}"]
    assert got["shipping"] == [f"a{c.id}", "p401"]
    assert got["waiting"] == [f"a{first.area_id}"] and got["ready"] == []
    cards = {x["key"]: x for _, _, _, cards in work_page.board(db)["cols"] for x in cards}
    assert (cards[f"a{c.id}"]["stage"], cards[f"a{c.id}"]["stuck"]) == ("review", False)
    assert (cards["p401"]["kind"], cards["p401"]["stage"], cards["p401"]["stuck"]) == ("upkeep", "red", True)
    assert cards[f"a{first.area_id}"]["kind"] == "feedback"


def test_what_waits_on_brett_has_its_own_card_in_yours_to_try(db):
    """A plan can be Ready for Claude and have checks for Brett at once: both show, the try in Yours to try."""
    i = _issue(db, "Back clears what you typed")
    _issue(db, "Also in this plan, still Claude's")
    check = rules.write_check(db, "claude", title="t", steps=["s"], expect="e", issue_ids=[i.id], area_id=i.area_id)
    assert f"a{i.area_id}-yours" not in _where(db)["yours"]  # (a fresh check is Claude's to try first, R18)
    rules.preflight(db, "claude", check, True)
    rules.fix_ready(db, "claude", i, "https://github.com/jettison-v/dndsy/pull/431")
    rules.fix_live(db, "askdnd", i, "3" * 40)  # (its fix is live: its check is Brett's to try, R4)
    db.flush()
    got = _where(db)
    assert f"a{i.area_id}-yours" in got["yours"] and f"a{i.area_id}" in got["ready"]
    cards = {x["key"]: x for _, _, _, cards in work_page.board(db)["cols"] for x in cards}
    assert cards[f"a{i.area_id}-yours"]["why"] == "1 check to try"


def test_a_claim_gone_quiet_and_a_fix_to_what_shipped_lead_ready(db):
    first, second = _issue(db, "First"), _issue(db, "Second", feature="hp")
    b = db.get(FftArea, second.area_id)
    rules.lock_area(db, OWNER, b)
    b.lock_until = rules.now() - timedelta(minutes=1)
    db.flush()
    ready = [c for k, _, _, cards in work_page.board(db)["cols"] if k == "ready" for c in cards]
    assert [(c["key"], c["stage"]) for c in ready] == [(f"a{b.id}", "quiet_claim"), (f"a{first.area_id}", "queue")]
    assert rules.pick_next(db).area.id == b.id  # (the Board's top is what Claude is handed)


def test_a_scope_waiting_for_brett_is_waiting_and_an_agreed_build_with_no_plan_is_ready(db):
    waiting = rules.new_item(db, "claude", "An idea", section="now")
    agreed = rules.new_item(db, "claude", "An agreed build", section="now")
    db.flush()
    rules.write_scope(db, "claude", waiting, what="w", inside=["i"])
    rules.write_scope(db, "claude", agreed, what="w", inside=["i"])
    rules.agree_scope(db, "user:1", agreed)
    rules.add_step(db, "claude", agreed, "Build it")
    db.flush()
    got = _where(db)
    assert f"i{waiting.id}" in got["waiting"] and f"i{agreed.id}" in got["ready"]


@pytest.mark.parametrize(("pull", "want"), [
    ({"tests": "failed"}, ("red", True)),
    ({"merge_state": "dirty"}, ("conflicts", True)),
    ({"merge_state": "behind"}, ("behind", False)),
    ({"tests": "passed", "auto_merge": True, "merge_state": "blocked"}, ("merging", False)),
    ({"tests": "passed", "merge_state": "clean"}, ("not_merging", True)),
    ({}, ("review", False)),
], ids=["red", "conflicts", "behind", "merging", "not-merging", "review"])
def test_shipping_says_each_pull_requests_step(db, pull, want):
    p = _pull(db, 410, "some-work", **({"tests": "running", "merge_state": "blocked", "auto_merge": False} | pull))
    key, _, stuck = work_page.pull_stage(db, p)
    assert (key, stuck) == want


def test_a_merged_pull_request_is_going_live_until_askdnd_runs_it(db):
    p = rules.pulls_seen(db, "github", [{"number": 420, "state": "merged", "merge_commit": "1" * 40, "closed_at": "2026-11-24T01:00:00Z"}])[0]
    assert work_page.pull_stage(db, p)[0] == "going_live"
    rules.release_live(db, "askdnd", "1" * 40)
    assert work_page.pull_stage(db, p)[0] == "live"


def test_the_board_is_developments_first_tab_and_in_the_design_system(db, admin):
    """A standing rule (Brett, Nov 7: the design system first): the Board is one piece, drawn on Development and on the
    design system page from the same macro, its columns and cards marked for tests and pages."""
    _issue(db, "Back clears what you typed")
    page = admin.get("/manage/work").text
    assert 'data-board' in page and page.count('data-col="') == 5 and 'data-card="a' in page
    assert 'data-tab="board"' in page and admin.get("/manage/work?tab=queue").status_code == 200
    design = admin.get("/manage/design").text
    assert 'id="board"' in design and design.count('data-col="') == 5 and 'data-stuck' in design


def test_an_issues_history_carries_its_pull_requests_round_trip(db, admin):
    """Its round trip (Brett's pick 3 on The Work Board): opened, tests, merged and live, in the issue's own window."""
    i = _issue(db, "Back clears what you typed")
    rules.fix_ready(db, "claude", i, "https://github.com/jettison-v/dndsy/pull/430")
    _pull(db, 430, f"i{i.id}-fix")
    rules.pulls_seen(db, "github", [{"number": 430, "state": "merged", "merge_commit": "2" * 40, "closed_at": "2026-11-24T01:00:00Z"}])
    rules.release_live(db, "askdnd", "2" * 40)
    db.flush()
    from app.fft import feedback_page

    said = [e.kind for e in feedback_page.issue_view(db, i, None)["events"]]
    assert {"pull_new", "pull_live"} <= set(said) and "issue_live" in said


def test_the_queues_controls_come_back_to_the_queue(db, admin):
    """The Board is Development's first tab: a lane, a hold or a rename pressed on the Queue returns to the Queue."""
    i = _issue(db, "Back clears what you typed")
    page = admin.get("/manage/work?tab=queue").text
    assert 'name="back" value="/manage/work?tab=queue"' in page and 'name="back" value="/manage/work"' not in page
    r = admin.post(f"/manage/testing/areas/{i.area_id}", data={"do": "hold", "back": "/manage/work?tab=queue"}, follow_redirects=False)
    assert r.headers["location"] == "/manage/work?tab=queue"


def test_a_plan_claimed_outside_the_queue_still_shows_and_an_items_pull_request_shows_once(db):
    """Claimed by hand under an item whose scope isn't agreed: it's in Building all the same. A pull request from an
    r<item>- branch shows once, however many plans its item has."""
    it = rules.new_item(db, "claude", "Not agreed yet", section="now")
    db.flush()
    plan = rules.new_area(db, "claude", it, "Not agreed yet: the build")
    db.flush()
    rules.lock_area(db, OWNER, plan)
    assert _where(db)["building"] == [f"a{plan.id}"]
    rules.unlock_area(db, OWNER, plan)
    built = rules.new_item(db, "claude", "Agreed", section="now")
    db.flush()
    rules.write_scope(db, "claude", built, what="w", inside=["i"])
    rules.agree_scope(db, "user:1", built)
    rules.add_step(db, "claude", built, "Build it")
    one, two = rules.new_area(db, "claude", built, "One"), rules.new_area(db, "claude", built, "Two")
    db.flush()
    _pull(db, 440, f"r{built.id}-board")
    assert _where(db)["shipping"] == [f"a{one.id}"]
    assert f"a{two.id}" in _where(db)["ready"]


def test_your_order_says_each_plans_place_in_the_boards_words(db, admin):
    """Step 36 (Brett, Nov 24: "It may need some changes to match the Board's newer style"): Your order keeps his order,
    lanes and holds, and says each plan's stage as the Board does, its column, with the Board's kind on the row."""
    first, second = _issue(db, "First"), _issue(db, "Second", feature="hp")
    b = db.get(FftArea, second.area_id)
    rules.lock_area(db, OWNER, b)
    db.flush()
    page = admin.get("/manage/work?tab=queue").text
    row = lambda aid: page.split(f'data-key="a{aid}"', 1)[1].split("</tr>", 1)[0]
    assert 'data-col-word="ready"' in row(first.area_id) and 'data-col-word="building"' in row(b.id)
    assert 'data-kind-tag="feedback"' in row(first.area_id)
    assert f'data-kind="feedback" data-key="a{first.area_id}"' in page


def test_a_plan_with_two_pull_requests_on_their_way_shows_both(db):
    """A card is one piece that ends in one pull request (Nov 24: #490 was hidden behind #488, both on one plan)."""
    i = _issue(db, "Two pieces")
    _pull(db, 488, f"a{i.area_id}-one", tests="running", merge_state="blocked")
    _pull(db, 490, f"a{i.area_id}-two", tests="failed")
    cards = {x["key"]: x for _, _, _, cards in work_page.board(db)["cols"] for x in cards}
    assert cards[f"a{i.area_id}"]["pr"] == 488 and cards[f"a{i.area_id}-p490"]["pr"] == 490 and cards[f"a{i.area_id}-p490"]["stuck"]


def test_a_builds_row_in_your_order_says_its_plans_column(db, admin):
    """A Roadmap build with a plan has no Board card of its own (its plan has): its row in Your order says its plan's
    column, not the older stage words (Nov 24: item 39's row said Claude's next)."""
    it = rules.new_item(db, "claude", "Agreed", section="now")
    db.flush()
    rules.write_scope(db, "claude", it, what="w", inside=["i"])
    rules.agree_scope(db, "user:1", it)
    rules.add_step(db, "claude", it, "Build it")
    plan = rules.new_area(db, "claude", it, "Agreed: the build")
    db.flush()
    rules.lock_area(db, OWNER, plan)
    db.flush()
    page = admin.get("/manage/work?tab=queue").text
    row = page.split(f'data-key="i{it.id}"', 1)[1].split("</tr>", 1)[0]
    assert 'data-col-word="building"' in row


def test_short_marks_on_cards_and_the_roadmap_list(db, admin):
    """Brett's picks P2 and P4 on Our Work, page by page (Nov 24): Board cards and the Roadmap list carry short marks (P12,
    R39), the full word on hover; the Roadmap list's titles are plain, the row opens the item."""
    i = _issue(db, "Back clears what you typed")
    it = rules.new_item(db, "claude", "An idea", section="now")
    db.flush()
    rules.write_scope(db, "claude", it, what="w", inside=["i"])  # (its card waits for your OK: a Roadmap card, R not I)
    db.flush()
    board = admin.get("/manage/work").text
    assert f'title="plan {i.area_id}" data-mark="a{i.area_id}">P{i.area_id}</abbr>' in board
    assert f'data-mark="r{it.id}">R{it.id}</abbr>' in board
    road = admin.get("/manage/roadmap").text
    assert f'title="Roadmap item {it.id}" data-mark="r{it.id}">R{it.id}</abbr>' in road
    row = road.split(f'data-item="{it.id}"', 1)[1].split("</tr>", 1)[0]
    assert "<a " not in row.split("</td>", 3)[2]  # (its title plain: the row opens it)
