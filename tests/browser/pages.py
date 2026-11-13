"""Driving askdnd's pages by what things are, not where they sit or what they say (Nov 13, the test foundations), so
a change to the menu bar's layout or wording touches the page, not every test. The page marks them for this: each
menu is a door (`[data-door="account" | "manage" | "admin" | "help" | "more" | "party" | "campaign"]`, opened by the
button whose `data-menu` names its id), each item in it `[data-item="<key>"]`, and the Live pill its state in
`data-tone` (step, via, bad, warn, none). tests/menu.py reads the same marks from a page's HTML.

    click_item(page, "tour")       opens whichever door holds that item, then presses it
    open_door(page, "account")     opens a door's menu; returns its locator
    tone(page)                     the Live pill's tone now
    wait_tone(page, "step")        until the pill says so (or one of several)
"""

from playwright.sync_api import Locator, Page

# The door that holds an item, opened by its own button (the one on screen: a phone's bottom bar has its own)
_OPEN = """item => {
  const el = document.querySelector('[data-item="' + item + '"]');
  const menu = el && el.closest('[data-door]');
  if (!menu) return 'no such item: ' + item;
  if (!menu.hidden) return '';
  const btn = [...document.querySelectorAll('[data-menu="' + menu.id + '"]')].find(b => b.checkVisibility());
  if (!btn) return 'no button on screen opens ' + menu.id;
  btn.click();
  return '';
}"""


def open_door(page: Page, key: str) -> Locator:
    """Open a door's menu (if it isn't open) and return it."""
    menu = page.locator(f'[data-door="{key}"]').first
    if menu.is_hidden():
        menu_id = menu.get_attribute("id")
        page.locator(f'[data-menu="{menu_id}"]:visible').first.click()
        menu.wait_for(state="visible")
    return menu


def click_item(page: Page, item: str) -> None:
    """Press an item of the menu bar's menus wherever it lives now: its door is opened first."""
    problem = page.evaluate(_OPEN, item)
    assert not problem, problem
    page.locator(f'[data-item="{item}"]:visible').first.click()


def tone(page: Page) -> str:
    return page.locator("#live-pill").get_attribute("data-tone") or ""


def wait_tone(page: Page, *tones: str, timeout: float = 10000) -> None:
    """Until the Live pill's tone is one of these."""
    page.wait_for_function("ts => ts.includes(document.getElementById('live-pill')?.dataset.tone)", arg=list(tones), timeout=timeout)
