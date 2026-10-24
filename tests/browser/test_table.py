"""The table's core flows in real browsers (tests/browser/conftest.py): pages load cleanly, the roll window's keys,
and rolls reaching everyone at the table live, with a DM-only roll's number kept from the other players."""

import time

LOG = "#roll-log > li"


def save(ability: str) -> str:
    """A save's roll button (Battle's header tiles and Sheet's rows share the roll attributes)."""
    return f'[data-roll=save][data-label="{ability} save"]:visible >> nth=0'


def battle(person, server):
    page = person.open(f"/characters/{server['cole']}/battle")
    page.wait_for_selector(save("Dex"))
    return page


def newest(page) -> str:
    return " ".join(page.locator(LOG).first.inner_text().split())


def test_the_main_pages_load_without_errors(people, server):
    admin = people("admin")
    for path in ("/c/main/", "/c/main/?tab=sessions", "/c/main/campaign", "/c/main/campaign?tab=quests",
                 f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}",
                 f"/characters/{server['cole']}/plan", "/c/main/party", "/c/main/manage", "/c/main/manage/settings",
                 "/manage/campaigns", "/manage/dice", "/manage/design", "/help"):
        admin.open(path)
        admin.page.wait_for_load_state("networkidle")
        assert admin.page.locator("main").count(), path
    assert admin.errors == []


def test_enter_rolls_and_esc_closes_whatever_was_clicked_last(people, server):
    player = people("player")
    page = battle(player, server)
    win = page.locator(".roll-win")
    # Advantage, then Enter: rolls (it used to press Advantage again)
    page.click(save("Dex"))
    win.locator("[data-mode=adv]").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}') && document.querySelector('{LOG}').textContent.includes('Adv')")
    page.keyboard.press("Escape")
    assert win.count() == 0
    # A d4, then Enter: one d4 added, not two
    page.click(save("Dex"))
    win.locator("summary").click()
    win.locator("[data-add-die='4']").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}').textContent.includes('+1d4')")
    page.keyboard.press("Escape")
    # Clicking the window's text leaves nothing focused: Enter still rolls
    page.click(save("Wis"))
    win.locator(".rw-title").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.keyboard.press("Escape")
    # Over a side panel, Esc closes the roll window only
    page.locator('[data-panel-url$="/all/action?add=1"]').first.click()
    panel = page.locator(".peek.open")
    panel.locator("[data-roll]").first.click()
    win.wait_for()
    page.keyboard.press("Escape")
    assert win.count() == 0 and panel.count() == 1
    page.keyboard.press("Escape")
    panel.wait_for(state="detached")
    assert player.errors == []


def test_a_roll_reaches_the_dms_screen_within_a_second(people, server):
    player, dm = people("player", "dm")
    dm.open("/c/main/")
    dm.live()
    dm.page.wait_for_selector(LOG, state="attached")  # the log is collapsed on Story
    before = dm.page.locator(LOG).count()
    page = battle(player, server)
    start = time.monotonic()
    page.click(save("Con"), modifiers=["Shift"])  # Shift: roll straight away
    dm.page.wait_for_function(f"document.querySelectorAll('{LOG}').length > {before}", timeout=5000)
    took = time.monotonic() - start
    assert "Con save" in newest(dm.page)
    assert took < 1.5, f"took {took:.1f} s: the live connection should beat the 30-second fallback poll"
    assert player.errors == [] and dm.errors == []


def test_a_dm_only_roll_reaches_everyone_but_only_the_dm_sees_it(people, server):
    player, other, dm = people("player", "other", "dm")
    for p in (other, dm):
        p.open("/c/main/")
        p.live()
        p.page.wait_for_selector(LOG, state="attached")  # the log is collapsed on Story
    counts = {p: p.page.locator(LOG).count() for p in (other, dm)}
    page = battle(player, server)
    page.click(save("Cha"))
    page.locator(".roll-win [data-to=dm]").click()
    page.keyboard.press("Enter")
    for p in (other, dm):
        p.page.wait_for_function(f"document.querySelectorAll('{LOG}').length > {counts[p]}", timeout=5000)
    assert "Cha save" in newest(dm.page)
    hidden = newest(other.page)
    assert "Rolled for the DM" in hidden and "Cha save" not in hidden
    assert player.errors == [] and other.errors == [] and dm.errors == []
