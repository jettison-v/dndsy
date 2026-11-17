"""The item builder in a real browser (DM Tools › an item; docs/mockups/item-builder/, Brett's 1A and 3A, Nov 16):
what an item does in play is added a piece at a time, each piece's questions are pickers (chips, steppers, the dice
picker), and each piece reads as one sentence, the same one DM Tools' list shows."""


def test_an_item_is_built_a_piece_at_a_time_and_reads_the_same_everywhere(people, server):
    dm = people("dm")
    page = dm.open("/c/main/dm/items/new")
    form = page.locator("[data-item-builder]")
    assert form.locator("[data-hb-piece]:visible").count() == 0  # (a new item has nothing yet: only + Add)
    form.locator("[data-hb-name]").fill("Leviathan Compass")

    def add(kind):
        form.locator("[data-hb-add] > summary").click()
        form.locator(f'[data-hb-new="{kind}"]').click()
        return form.locator(f'[data-hb-piece="{kind}"][data-open]').first

    roll = add("roll")
    roll.locator('[data-pick="save"]').click()
    roll.locator('[data-dice-picker] [data-step="1"]').click()  # two dice
    roll.locator('[data-dp-die="6"]').click()
    roll.locator('[data-dp-type="force"]').click()
    roll.locator('[data-pick="Dex"]').click()
    roll.locator('input[name="roll0_dc"]').fill("14")
    assert roll.locator('[data-dp="box"]').input_value() == "2d6 force"
    assert roll.locator("[data-hb-says]").inner_text() == "2d6 force · Dex save DC 14, half on a success"
    assert roll.locator("text=It does").count() == 0 or not roll.locator('[data-hb-when="none"]').is_visible()  # (a save always damages)
    roll.locator('[data-dp="box"]').fill("3d8 cold")  # typing sets the pickers
    assert roll.locator('[data-dp-die="8"]').get_attribute("aria-pressed") == "true"
    assert roll.locator('[data-dp-type="cold"]').get_attribute("aria-pressed") == "true"
    assert roll.locator('[data-dp="n"]').input_value() == "3"
    roll.locator(".hb-body [data-hb-toggle]").click()  # Done: it folds to its line
    assert not roll.locator(".hb-body").is_visible()

    bonus = add("add")
    bonus.locator('[data-dp-flat="1"]').click()
    bonus.locator('[data-pick="check"]').click()
    assert bonus.locator("[data-hb-says]").inner_text() == "+1 to ability checks"
    bonus.locator("[data-hb-remove]").click()  # removed: hidden, empty, and + Add offers it again
    assert form.locator('[data-hb-piece="add"]:visible').count() == 0
    assert not form.locator('[data-hb-new="add"]').is_disabled()

    charges = add("charges")
    charges.locator('input[name="charges"]').fill("3")
    charges.locator('[data-pick="dawn"]').click()
    charges.locator('input[name="charges_regain"]').fill("1d3")
    assert form.locator('[data-hb-new="charges"]').is_disabled()  # (an item has its charges once)
    lines = [form.locator(f'[data-hb-piece="{k}"]:visible [data-hb-line]').first.inner_text() for k in ("roll", "charges")]
    assert lines == ["3d8 cold · Dex save DC 14, half on a success", "3 charges, back at dawn (1d3)"]

    form.locator("button[type=submit]").click()
    page.wait_for_url("**/c/main/dm")
    listed = page.locator(".dm-items .record").filter(has_text="Leviathan Compass").locator(".dm-says").inner_text()
    assert listed == "Leviathan Compass: " + lines[0] + " · " + lines[1]  # the list says what the builder said

    page.locator(".dm-items a", has_text="Leviathan Compass").first.click()
    page.wait_for_url("**/dm/items/**")
    again = [page.locator(f'[data-hb-piece="{k}"]:visible [data-hb-line]').first.inner_text() for k in ("roll", "charges")]
    assert again == lines  # reopened, each piece folded to the same line
    assert page.locator("[data-hb-piece][data-open]").count() == 0
    assert dm.errors == []
