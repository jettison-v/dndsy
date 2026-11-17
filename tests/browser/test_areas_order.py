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


def test_for_yous_chips_open_what_they_say(people, server, browser_db):
    """Brett's note 98 (Nov 17): pressing Try again did nothing and the page threw. The chips were marked like the
    page's show-a-section toggles (data-show); each chip is a link, and pressing it opens its list."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO checks (title, area, setup, path, \"do\", expect, minutes, place, status) VALUES "
                          "('Comes back', 'Sheet', 'laptop', '/party', 'Look.', 'Fixed.', 1, 0, 'again')"))
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/testing")
    for key in ("again", "player", "failed", "ready"):
        page.locator(f'[data-ts-show="{key}"]').click()
        page.wait_for_url(f"**/manage/testing?show={key}")
        assert page.locator(f'[data-ts-show="{key}"]').get_attribute("aria-current") == "true"
    assert not admin.errors, admin.errors


def test_for_you_changes_in_place_and_its_marks_sit_centered(people, server, browser_db):
    """Brett's notes 103, 104 and 96 (Nov 17): a chip or a row changes the list or the check beside it in place, never
    reloading the page; a question says so in a word (Readers, Rebuilt, 1A); the count on your picture sits centered."""
    import json

    engine = create_engine(browser_db[0])
    ask = {"choices": [{"label": "A", "detail": "", "pic": None}, {"label": "B", "detail": "", "pic": None}], "mine": 0}
    with engine.begin() as conn:
        ids = [conn.execute(text("INSERT INTO checks (title, area, setup, path, \"do\", expect, minutes, place, status) VALUES "
                                 "(:t, 'Sheet', 'laptop', '/party', 'Look.', 'Fine.', 1, :n, 'ready') RETURNING id"), {"t": t, "n": n}).scalar()
               for n, t in enumerate(("First", "Second"))]
        conn.execute(text("INSERT INTO feedback (text, status, kind, thread, sender) VALUES ('Which?', 'question', 'question', CAST(:t AS jsonb), "
                          "'Brett (admin)')"), {"t": json.dumps([{"who": "claude", "text": "Which?", "at": "2026-11-17T10:00:00+00:00", "ask": ask}])})
    engine.dispose()
    admin = people("admin")
    page = admin.open(f"/manage/testing?show=ready&check={ids[0]}")
    page.evaluate("window.__stayed = true")
    page.locator(f'[data-check="{ids[1]}"]').click()
    page.locator(f'[data-check-read="{ids[1]}"]').wait_for()
    assert page.evaluate("window.__stayed === true") and page.locator(f'[data-check="{ids[1]}"]').get_attribute("aria-current") == "true"
    page.locator('[data-ts-show="failed"]').click()
    page.wait_for_url("**/manage/testing?show=failed")
    assert page.evaluate("window.__stayed === true")  # (no reload: the list changed in place, note 103)
    assert page.locator("[data-round-start]").count() == 0  # (the whole page body follows the chip: no Start round on Failed)

    page = admin.open("/manage/testing?show=ready")
    assert page.locator('.ts-row [data-state="ask"]').count() == 1  # (a question says so in a word, no mark to decode: 1A)
    badge = page.evaluate("""() => { const b = document.querySelector('.avatar [data-notes-count]'); b.hidden = false; b.textContent = '5';
        const r = b.getBoundingClientRect(), t = document.createRange(); t.selectNodeContents(b); const s = t.getBoundingClientRect();
        return Math.abs((r.top + r.bottom) / 2 - (s.top + s.bottom) / 2); }""")
    assert badge < 1.5, badge  # (note 96)
    assert not admin.errors, admin.errors


def test_feedback_reads_a_note_and_writes_to_claude_or_them(people, server, browser_db):
    """Readers, Rebuilt (Board 3): Feedback is a Reader; a row opens its note in place (no reload) with its state in
    words; ⋯ opens Change what it is; one box writes to Claude or to its sender."""
    import json

    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE email = 'player@example.com'")).scalar()
        ids = [conn.execute(text("INSERT INTO feedback (text, status, kind, thread, sender, user_id, context) VALUES (:t, 'new', 'broken', '[]', "
                                 "'Cathartic (player)', :u, CAST(:c AS jsonb)) RETURNING id"),
                            {"t": t, "u": uid, "c": json.dumps({"page": "Cole · Battle", "pointed": {"label": "Speed", "path": "main"}})}).scalar()
               for t in ("The rolls panel closes by itself.", "Speed should show the swim speed too.")]
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/feedback?tab=new")
    page.evaluate("window.__stayed = true")
    page.locator(f'[data-note="{ids[0]}"]').click()
    page.locator(f'[data-note-read="{ids[0]}"]').wait_for()
    assert page.evaluate("window.__stayed === true") and page.locator(f'[data-note="{ids[0]}"]').get_attribute("aria-current") == "true"
    art = page.locator(f'[data-note-read="{ids[0]}"]')
    assert art.locator(".state-line .sw-claude").count() == 1
    art.locator(".act-more summary").click()
    art.locator(f'[data-show="fbkind-{ids[0]}"]').click()
    assert page.locator(f"#fbkind-{ids[0]}").is_visible() and not art.locator(".act-more").evaluate("d => d.open")
    composer = art.locator("[data-composer]")
    composer.locator('input[value="tell"]').check()
    composer.locator("textarea[name=answer]").fill("Fixed soon, thanks.")
    composer.locator("[data-composer-send]").click()
    page.wait_for_url("**/manage/feedback**")
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        thread = conn.execute(text("SELECT thread FROM feedback WHERE id = :i"), {"i": ids[0]}).scalar()
    engine.dispose()
    assert thread[-1]["to"] == "sender" and thread[-1]["text"] == "Fixed soon, thanks."
    assert not admin.errors, admin.errors
