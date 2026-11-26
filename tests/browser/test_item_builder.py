"""The item builder in a real browser (DM Tools › an item; docs/mockups/item-builder/, Brett's 1A and 3A, Nov 16):
what an item does in play is added a piece at a time, each piece's questions are pickers (chips, steppers, the dice
picker), and each piece reads as one sentence, the same one DM Tools' list shows."""


LINES = """root => [...root.querySelectorAll('[data-hb-piece]')].filter(p => !p.hidden).map(p => [p.dataset.hbPiece, p.querySelector('[data-hb-line]').textContent])"""


def test_an_item_is_built_a_piece_at_a_time_and_reads_the_same_everywhere(people, server):
    dm = people("dm")
    page = dm.open("/c/main/dm/items/new")
    form = page.locator("[data-item-builder]")
    assert form.locator("[data-hb-piece]:visible").count() == 0  # (a new item has nothing yet: only + Add)
    form.locator("[data-hb-name]").fill("Leviathan Compass")

    def add(kind):
        form.locator("[data-hb-add] > summary").click()
        form.locator(f'[data-hb-new="{kind}"]').click()
        return form.locator(f'[data-hb-piece="{kind}"][data-open]').last

    roll = add("roll")
    roll.locator('[data-pick="save"]').click()
    roll.locator('[data-dice-picker] [data-step="1"]').click()  # two dice
    roll.locator('[data-dp-die="6"]').click()
    roll.locator('[data-dp-type="force"]').click()
    roll.locator('[data-pick="Dex"]').click()
    roll.locator('input[name="roll0_dc"]').fill("14")
    assert roll.locator('[data-dp="box"]').input_value() == "2d6 force"  # the pickers write the box
    assert not roll.locator('[data-hb-when="none"]').is_visible() and roll.locator('[data-hb-when="save"]').first.is_visible()
    roll.locator('[data-dp="box"]').fill("3d8 cold")  # typing sets the pickers
    assert roll.locator('[data-dp-die="8"]').get_attribute("aria-pressed") == "true"
    assert roll.locator('[data-dp-type="cold"]').get_attribute("aria-pressed") == "true"
    assert roll.locator('[data-dp="n"]').input_value() == "3"
    roll.locator(".hb-body [data-hb-toggle]").click()  # Done: it folds to its line
    assert not roll.locator(".hb-body").is_visible()

    spare = add("roll")  # a second roll, removed: hidden, emptied, and + Add offers it again
    spare.locator('[data-dp="box"]').fill("1d4")
    spare.locator("[data-hb-remove]").click()
    assert form.locator('[data-hb-piece="roll"]:visible').count() == 1 and form.locator('input[name="roll1_dice"]').input_value() == ""
    assert not form.locator('[data-hb-new="roll"]').is_disabled()

    bonus = add("add")
    bonus.locator('[data-dp-flat="1"]').click()
    bonus.locator('[data-pick="check"]').click()
    assert bonus.locator('[data-dp="box"]').input_value() == "+1"
    charges = add("charges")
    charges.locator('input[name="charges"]').fill("3")
    charges.locator('[data-pick="dawn"]').click()
    charges.locator('input[name="charges_regain"]').fill("1d3")
    assert form.locator('[data-hb-new="charges"]').is_disabled()  # (an item has its charges once)
    built = form.evaluate(LINES)
    assert [k for k, _ in built] == ["roll", "add", "charges"] and all(line for _, line in built)

    form.locator("button[type=submit]").click()
    page.wait_for_url("**/c/main/dm")
    row = page.locator('[data-table="items"] [data-item="leviathan-compass"]')
    listed = row.evaluate("r => [...r.querySelectorAll('[data-say]')].map(s => [s.dataset.say, s.querySelector('[data-said]').textContent])")
    assert listed == built  # the list says what the builder said, piece by piece (the words: tests/test_homebrew.py)

    row.click()  # (a row opens the builder in Items' large window: Brett's pick IT3, Nov 25)
    window = page.locator(".peek.open [data-item-builder]")
    window.wait_for()
    assert window.evaluate(LINES) == built  # reopened, each piece folded to the same line
    assert page.locator(".peek.open [data-hb-piece][data-open]").count() == 0
    assert dm.errors == []


def test_a_refused_item_in_its_window_comes_back_with_its_error_under_the_box(people, server):
    """Issue 172: Items' large window, refused, draws again in place: what was typed stays, the piece is open and the
    error sits under its box (before, a card said only "Not done: try again.")."""
    dm = people("dm")
    page = dm.open("/c/main/dm")
    dm.allow("422")  # (the refusal is the point)
    page.locator('[data-item="new-item"]').click()
    win = page.locator("aside.peek [data-item-builder]")
    win.locator("[data-hb-name]").fill("Wand of Tests")
    win.locator("[data-hb-add] > summary").click()
    win.locator('[data-hb-new="charges"]').click()
    charges = win.locator('[data-hb-piece="charges"][data-open]')
    charges.locator('input[name="charges"]').fill("3")
    charges.locator('[data-pick="dawn"]').click()
    charges.locator('input[name="charges_regain"]').fill("lots")
    win.locator("button[type=submit]").first.click()
    error = page.locator("aside.peek [data-hb-regain] [data-field-error]")
    error.wait_for(state="visible")  # (shown only with words in it: _form_bits.html field())
    assert page.locator("aside.peek [data-hb-name]").input_value() == "Wand of Tests"
    assert page.locator("aside.peek").evaluate("p => p.classList.contains('open')")
    assert page.locator("#cards > *").count() == 0  # (no "Not done" card: the window says it)


def test_the_item_builders_open_pieces_fit_every_width(people, server):
    """Each piece opened (a roll with a save, a bonus, charges) holds together at every width: its chips wrap, nothing
    spills or overlaps (the layout check every main page gets)."""
    from tests.browser.test_layout import POLISH_FROM, WIDTHS, problems

    dm = people("dm")
    page, found = dm.page, []
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        dm.open("/c/main/dm/items/new")
        form = page.locator("[data-item-builder]")
        form.locator("[data-hb-name]").fill("A Long-Named Compass of the Drowned Leviathan's Heart")
        for kind in ("roll", "add", "charges"):
            form.locator("[data-hb-add] > summary").click()
            form.locator(f'[data-hb-new="{kind}"]').click()
        form.locator('[data-hb-piece="roll"][data-open] [data-pick="save"]').click()
        found += problems(page, f"the item builder at {width}px", hard_only=width < POLISH_FROM)  # (DM Tools: polish is the weekly sweep's)
    assert not found, "\n".join(found)
    assert dm.errors == []
