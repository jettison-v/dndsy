"""A setting's switch in a real page (_settings.html, app.js "the switch"; the UI review's pick 1, Brett Nov 16,
docs/mockups/one-switch/): flipped, it saves itself where it is, with a corner card and no reload; a two-way switch
(Trophy Case) saves the pressed choice the same way; a refused flip says why and the switch stays."""


def test_a_switch_saves_itself_in_place(people, server):
    dm = people("dm")
    page = dm.open("/c/main/manage/settings?tab=features#features")
    page.evaluate("window.__stayed = true")  # (a reload would lose it)
    sw = page.locator("#features form[data-switch] .switch").first
    before = sw.get_attribute("aria-checked")
    sw.click()
    page.locator("#cards > .card").first.wait_for()
    page.wait_for_function(f"document.querySelector('#features form[data-switch] .switch').getAttribute('aria-checked') !== '{before}'")
    assert page.evaluate("window.__stayed === true")
    page.reload()  # (saved: the page drawn again says so)
    assert page.locator("#features form[data-switch] .switch").first.get_attribute("aria-checked") != before
    # Trophy Case: the two-way switch, saving on press
    choice = page.locator('form[data-choice="counts"]')
    other = choice.locator('button[aria-pressed="false"]').first
    value = other.get_attribute("value")
    other.click()
    page.wait_for_function(f"document.querySelector('form[data-choice=\"counts\"] button[value=\"{value}\"]').getAttribute('aria-pressed') === 'true'")
    page.reload()
    assert page.locator(f'form[data-choice="counts"] button[value="{value}"]').get_attribute("aria-pressed") == "true"
    assert dm.errors == []


def test_a_switch_that_isnt_yours_is_dimmed_and_never_sends(people, server):
    """Test campaign is an admin's: the DM sees its switch dimmed, with who changes it."""
    dm = people("dm")
    page = dm.open("/c/main/manage/settings?tab=campaign#test")
    sw = page.locator('[data-setting="test"] .switch')
    assert sw.is_disabled() and page.locator('[data-setting="test"] .note').count() == 1
    assert dm.errors == []
