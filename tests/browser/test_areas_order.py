"""Where it stands in a real browser (app/testing.py; Working with Claude, Brett's picks Nov 17,
docs/mockups/working-together/): the areas a row each, the one in Claude's hands first; Brett drags the others into his
order (7A), the numbers follow, the order is kept and Claude's inbox hears it; it holds together at every width."""

from sqlalchemy import create_engine, text

from tests.browser.test_layout import check


def _areas(url):
    engine = create_engine(url)
    with engine.begin() as conn:
        ids = [conn.execute(text("INSERT INTO areas (title, place, fixing) VALUES (:t, :p, :f) RETURNING id"), {"t": t, "p": p, "f": f}).scalar()
               for p, (t, f) in enumerate((("The Testing card, with a long name to see it wrap", True), ("Item Builder", False),
                                           ("Battle and Sheet", False)))]
        conn.execute(text("INSERT INTO checks (title, area, setup, path, \"do\", expect, minutes, place, area_id) VALUES "
                          "('Headings stay', 'Sheet', 'laptop', '/party', 'Look.', 'They stay.', 1, 0, :a)"), {"a": ids[1]})
    engine.dispose()
    return ids


def test_brett_drags_the_areas_into_his_order(people, server, browser_db):
    card, builder, battle = _areas(browser_db[0])
    admin = people("admin")
    page = admin.open("/manage/testing?show=areas")
    rows = page.locator("[data-area]")
    assert [rows.nth(i).get_attribute("data-area") for i in range(rows.count())] == [str(card), str(builder), str(battle)]
    assert page.locator(f'[data-area="{card}"] .grip').count() == 0  # (the one in Claude's hands stays first)

    with page.expect_response("**/manage/testing/areas/order"):
        page.locator(f'[data-area="{battle}"] .grip').drag_to(page.locator(f'[data-area="{builder}"]'), target_position={"x": 20, "y": 5})
    page.reload()
    rows = page.locator("[data-area]")
    assert [rows.nth(i).get_attribute("data-area") for i in range(rows.count())] == [str(card), str(battle), str(builder)]

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        heard = conn.execute(text("SELECT text FROM claude_inbox WHERE what = 'order' ORDER BY id DESC LIMIT 1")).scalar()
    engine.dispose()
    assert heard and heard.endswith("Battle and Sheet, Item Builder")

    assert check(admin, server, ["/manage/testing?show=areas", "/manage/testing"]) == []


def test_brett_answers_claudes_question_in_for_you(people, server, browser_db):
    """Brett's 5A: Claude's question waits in For you with answers to tap, Claude's own chosen to start with; Brett
    picks another, adds a word, sends; askdnd puts it on the note and in Claude's inbox, and For you moves on."""
    import json

    engine = create_engine(browser_db[0])
    ask = {"choices": [{"label": "Keep it", "detail": "", "pic": None}, {"label": "Remove it", "detail": "", "pic": None}], "mine": 0}
    with engine.begin() as conn:
        fb = conn.execute(text("INSERT INTO feedback (text, status, kind, thread, sender) VALUES ('Why a free-form box?', 'question', 'question', "
                               "CAST(:t AS jsonb), 'Brett (admin)') RETURNING id"),
                          {"t": json.dumps([{"who": "claude", "text": "Keep the box?", "at": "2026-11-17T10:00:00+00:00", "ask": ask}])}).scalar()
    admin = people("admin")
    page = admin.open(f"/manage/testing?ask={fb}")
    form = page.locator(f'[data-question="{fb}"]')
    assert form.locator('[data-choice="0"] input').is_checked()
    form.locator('[data-choice="1"]').click()
    form.locator("textarea[name=answer]").fill("And say why in the help.")
    form.locator("[data-answer]").click()
    page.wait_for_url("**/manage/testing**")
    with engine.connect() as conn:
        status, thread = conn.execute(text("SELECT status, thread FROM feedback WHERE id = :f"), {"f": fb}).one()
        heard = conn.execute(text("SELECT what FROM claude_inbox WHERE feedback_id = :f ORDER BY id DESC LIMIT 1"), {"f": fb}).scalar()
    engine.dispose()
    assert status == "new" and thread[-1]["choice"] == 1 and heard == "answer"
    assert page.locator(f'[data-ask="{fb}"]').count() == 0
    assert not admin.errors, admin.errors
