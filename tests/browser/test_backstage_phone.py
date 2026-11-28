"""Backstage on a phone (Roadmap item 49, Brett's picks on docs/mockups/workshop-phone/, scope v1, Nov 27): an admin's
Backstage pages on a phone have Workshop's own bottom bar (For you, Development, the Roadmap, Feedback) in place of the
table's, and no Table rolls or Live pill; a laptop and the table's own pages are as they were."""

SHOWN = "el => !!el && el.checkVisibility()"


def _shown(page, selector: str) -> bool:
    return page.evaluate(f"(s) => {{ const el = document.querySelector(s); return ({SHOWN})(el); }}", selector)


def test_an_admins_backstage_on_a_phone_has_workshops_bar_and_no_table_rolls(people, server):
    admin = people("admin")
    admin.page.set_viewport_size({"width": 375, "height": 800})
    page = admin.open("/manage/for-you")
    assert _shown(page, ".backstage-nav") and not _shown(page, ".bottom-nav:not(.backstage-nav)")
    items = page.evaluate("[...document.querySelectorAll('.backstage-nav [data-item]')].map(a => a.dataset.item)")
    assert items == ["for-you", "work", "roadmap", "feedback"]
    assert page.evaluate("document.querySelector('.backstage-nav [data-item=\"for-you\"]').classList.contains('active')")
    assert not _shown(page, "#table-rolls") and not _shown(page, ".bar-end > .live")
    page.locator('.backstage-nav [data-item="work"]').click()
    page.wait_for_url("**/manage/work**")
    assert _shown(page, ".backstage-nav")
    # The table's own pages keep the table's bar and Table rolls
    page = admin.open(f"/characters/{server['cole']}/battle")
    assert not _shown(page, ".backstage-nav") and _shown(page, ".bottom-nav") and _shown(page, "#table-rolls")
    # A laptop is as it was
    admin.page.set_viewport_size({"width": 1280, "height": 800})
    page = admin.open("/manage/for-you")
    assert not _shown(page, ".backstage-nav")
    assert not admin.errors, admin.errors


def test_the_dms_backstage_on_a_phone_drops_table_rolls_and_keeps_the_tables_bar(people, server):
    """Workshop is the admins'; the DM's Backstage keeps the table's bar (to get back to play), without Table rolls."""
    dm = people("dm")
    dm.page.set_viewport_size({"width": 375, "height": 800})
    page = dm.open("/c/main/manage/table")
    assert not _shown(page, ".backstage-nav") and _shown(page, ".bottom-nav") and not _shown(page, "#table-rolls")
    assert not dm.errors, dm.errors


def test_a_backstage_table_is_a_card_per_row_on_a_phone(people, server):
    """Step 2 (tables as cards, from the one table piece): on a phone each row is a card, its title the first line and
    each other cell named by its column; nothing scrolls sideways. On a laptop it's a table as before."""
    admin = people("admin")
    admin.page.set_viewport_size({"width": 375, "height": 800})
    page = admin.open("/manage/work?tab=scheduled")
    row = page.locator('.tbx .dtable tbody tr:not(.dt-group):not(.ls-grouphead)').first
    row.wait_for()
    assert row.evaluate("tr => getComputedStyle(tr).display") == "flex"
    labels = row.evaluate("tr => [...tr.querySelectorAll('td[data-label]:not(.dt-title)')].map(td => td.dataset.label)")
    assert labels, "a card's cells say their column"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    admin.page.set_viewport_size({"width": 1280, "height": 800})
    page = admin.open("/manage/work?tab=scheduled")
    assert page.locator('.tbx .dtable tbody tr').first.evaluate("tr => getComputedStyle(tr).display") == "table-row"
    assert not admin.errors, admin.errors
