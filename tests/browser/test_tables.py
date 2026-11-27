"""The table piece in a real page (_tables.html table_box; the list engine in app.js, `data-ls-table`): every table can be
searched from its title row, and one with finished rows hides them behind Show finished, its tick kept per table
(Brett's picks F1 A and F2 A on docs/mockups/tables-and-tabs/, Nov 27, issue 174)."""

TABLE = '[data-table="demo-roadmap"]'


def _shown(page):
    return page.evaluate(f"""() => [...document.querySelectorAll('{TABLE} tr[data-ls-row]')].filter(r => !r.hidden)
                             .map(r => (r.hasAttribute('data-ls-finished') ? 'F:' : '') + r.querySelector('.dt-id').textContent)""")


def _heads(page):
    return page.evaluate(f"() => [...document.querySelectorAll('{TABLE} tr.dt-group')].filter(r => !r.hidden).length")


def test_show_finished_and_search_on_a_table(people, server):
    admin = people("admin")
    page = admin.open("/manage/design")
    box = page.locator(TABLE)
    box.scroll_into_view_if_needed()
    assert _shown(page) == ["R3", "R19"] and _heads(page) == 0  # (finished rows wait; their group row with them)
    box.locator("[data-ls-finished-toggle]").check()
    assert _shown(page) == ["R3", "R19", "F:R46"] and _heads(page) == 1  # (last, under Finished)
    page.reload()
    assert page.locator(f"{TABLE} [data-ls-finished-toggle]").is_checked() and _shown(page) == ["R3", "R19", "F:R46"]  # (kept)
    page.locator(f"{TABLE} [data-ls-finished-toggle]").uncheck()
    search = page.locator(f"{TABLE} [data-ls-search]")
    search.fill("catalog")
    assert _shown(page) == ["F:R46"]  # (a search finds finished rows too, marked: F2 A)
    search.fill("nothing like this")
    assert _shown(page) == [] and page.locator(f"{TABLE} [data-ls-empty]").is_visible()
    assert not page.locator(f"{TABLE} .table-scroll").is_visible()  # (no headings over nothing: issue 148)
    search.fill("")
    assert _shown(page) == ["R3", "R19"]
    assert not admin.errors, admin.errors
