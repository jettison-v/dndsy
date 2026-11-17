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
