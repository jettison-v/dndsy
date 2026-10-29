"""Corner cards in real pages (app.js "corner cards"; Brett, 2026-10-29, docs/mockups/temporary-items.html): every
message you read and dismiss is a card at the bottom right, its kind giving its look, three at most, each with ✕;
someone else's roll arrives as one when their dice aren't thrown."""

from tests.browser.test_table import LOG, battle, save

CARDS = "#cards > .card"


def test_cards_take_their_kind_stack_three_and_close(people, server):
    player = people("player")
    page = battle(player, server)
    page.evaluate("askdndToast('Saved')")
    page.locator(f"{CARDS}.k-ok", has_text="Saved").wait_for()
    page.evaluate("askdndToast({text: \"Cole's sheet isn't open\", kind: 'warn'})")  # as the server sends one (web.notice)
    assert page.locator(f"{CARDS}.k-warn[role=alert]").inner_text().startswith("!")
    page.evaluate("askdndToast('Ends soon', {label: 'Keep going', run: () => { window.kept = true; }}, 'info')")
    page.evaluate("askdndToast(\"Couldn't save the order\", null, 'error')")
    assert page.locator(CARDS).count() == 3  # the oldest left
    assert page.locator(f"{CARDS}.k-ok").count() == 0
    page.locator(f"{CARDS}.k-info .card-act").click()
    assert page.evaluate("window.kept") is True
    page.locator(f"{CARDS}.k-error .card-x").click()
    page.locator(f"{CARDS}.k-error").wait_for(state="detached")
    box = page.locator("#cards").bounding_box()
    view = page.viewport_size
    assert box["x"] + box["width"] > view["width"] - 40 and box["y"] + box["height"] > view["height"] - 40  # bottom right
    assert player.errors == []


def test_someone_elses_roll_arrives_as_a_card(people, server):
    player, dm = people("player", "dm")
    dm.open("/c/main/")
    dm.live()
    dm.page.wait_for_selector(LOG, state="attached")
    page = battle(player, server)
    page.click(save("Con"), modifiers=["Shift"])
    card = dm.page.locator(f"{CARDS}.k-roll")
    card.wait_for(timeout=5000)  # (the browser tests' dice animation is off, so it's a card, not a throw)
    assert "Cole" in card.inner_text() and "rolled" in card.inner_text() and card.locator(".gem.card-ic").count() == 1
    assert page.locator(f"{CARDS}.k-roll").count() == 0  # not for your own roll
    assert player.errors == [] and dm.errors == []
