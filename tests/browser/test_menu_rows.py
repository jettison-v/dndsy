"""A menu's row opens its page from anywhere on it, not only its words (issue 7, Brett, Nov 19: "You have to click the
text in the menu to navigate to the page, but you should be able to click anywhere in the container instead")."""

from tests.browser.pages import open_door


def test_a_menu_row_opens_its_page_from_its_far_edge(people, server):
    admin = people("admin")
    page = admin.open("/c/main/campaign")
    for door, item, lands in (("manage", "overview", "/manage/askdnd"), ("manage", "inbox", "/manage/inbox"), ("account", "help", "/help")):
        menu = open_door(page, door)
        row = menu.locator(f'[data-item="{item}"]')
        within = row.locator("xpath=ancestor::*[@data-half][1]")  # (Backstage's menu has two halves side by side: a row spans its half)
        box, menu_box = row.bounding_box(), (within if within.count() else menu).bounding_box()
        assert box["width"] >= menu_box["width"] - 24, f"{door} › {item} isn't as wide as its menu"
        page.mouse.click(box["x"] + box["width"] - 3, box["y"] + box["height"] - 3)  # (its far corner, away from its words)
        page.wait_for_url(f"**{lands}*")
        admin.open("/c/main/campaign")
