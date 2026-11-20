"""Backstage mode (Brett's picks on Backstage Mode, Nov 20, docs/mockups/backstage-mode/): one design system, two modes.
A Backstage page reads denser and plainer on a laptop (smaller type, plain labels, the whole window's width); the table's
own pages keep Table mode, and so does a phone (its touch sizes and 16px boxes)."""


def _size(page, sel):
    return page.evaluate(f"parseFloat(getComputedStyle(document.querySelector({sel!r})).fontSize)")


def test_backstage_pages_are_dense_and_wide_the_table_keeps_its_look(people, server):
    admin = people("admin")
    admin.page.set_viewport_size({"width": 1600, "height": 900})
    admin.open("/manage/usage")
    assert _size(admin.page, "main.manage-page") < 15, "a Backstage page reads in Backstage mode's smaller type"
    label = admin.page.evaluate("getComputedStyle(document.querySelector('.manage-sec')).textTransform")
    assert label == "none", "its labels are plain words, not capitals"
    cap = admin.page.evaluate("getComputedStyle(document.querySelector('main.manage-page')).maxWidth")
    assert cap == "2200px", f"it uses the window's width up to 2,200px, not the old 1,348px ({cap})"
    admin.open("/c/main/campaign")
    assert _size(admin.page, "main") == 16, "the table's own pages keep Table mode"
    admin.page.set_viewport_size({"width": 375, "height": 812})
    admin.open("/manage/usage")
    assert _size(admin.page, "main.manage-page") == 16, "a phone keeps Table mode's sizes"
