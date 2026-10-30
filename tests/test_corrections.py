"""The correction ladder (Brett, 2026-10-30, docs/mockups/correction-flow.html): what an item costs, first answer wins:
this campaign's correction, askdnd's correction, a rule, the item's own words, neither. Also items that need no action
and the kind a player marks on their copy (a Dragon-Touched Focus's family)."""

from sqlalchemy import select

from app import character_views as views
from app import characters, house_rules
from app import conditions as cond
from app.models import Campaign, HouseRule, ToolCorrection
from tests.table_setup import char


def potion(sheet) -> dict:
    return next(i for i in sheet["inventory"] if i["definition"]["name"] == "Potion of Healing")


def where(db, cole, name):
    """Which column an item is in for this character now."""
    sheet = views.apply_overrides(characters.character_summary(cole), house_rules.sheet_overrides(db, cole.campaign_id))
    sheet["_item_choices"] = cole.item_choices
    return next(o["cost"] for o in views.options(sheet, set()) if o["name"] == name)


def correct(client, cole, oref, value, scope, field="cost", reason=""):
    return client.post(f"/characters/{cole.id}/override", data={"ref": "x", "oref": oref, "field": field, "value": value, "scope": scope, "reason": reason})


def refreshed(db, sheet):
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    return cole


def test_the_first_answer_wins_this_campaign_then_askdnd_then_a_rule(admin, db, sheet):
    """Brett, 2026-10-30: a campaign's correction is like homebrew, so it beats everything for that table only."""
    cole = refreshed(db, sheet)
    assert where(db, cole, "Potion of Healing") == "Bonus action"  # a rule
    assert correct(admin, cole, "item:Potion of Healing", "Action", "everyone").status_code == 200
    house_rules.invalidate()
    assert where(db, cole, "Potion of Healing") == "Action"  # askdnd's correction beats the rule
    assert correct(admin, cole, "item:Potion of Healing", "Reaction", "campaign").status_code == 200
    assert where(db, cole, "Potion of Healing") == "Reaction"  # this campaign's beats askdnd's
    other = Campaign(name="Elsewhere", slug="elsewhere")
    db.add(other)
    db.commit()
    assert house_rules.sheet_overrides(db, other.id)[("item:Potion of Healing", "cost")] == "Action"  # no other table changes
    assert correct(admin, cole, "item:Potion of Healing", "default", "campaign").status_code == 200
    assert where(db, cole, "Potion of Healing") == "Action"  # removing it brings the next answer back
    assert correct(admin, cole, "item:Potion of Healing", "default", "everyone").status_code == 200
    assert where(db, cole, "Potion of Healing") == "Bonus action"


def test_the_dm_corrects_for_the_campaign_only_admins_for_everyone(admin, dm, player, db, sheet):
    from tests.roles import set_role

    cole = refreshed(db, sheet)
    set_role(db, "dm@example.com", "dm")
    assert correct(dm, cole, "item:Potion of Healing", "Action", "campaign").status_code == 200
    assert correct(dm, cole, "item:Potion of Healing", "Action", "everyone").status_code == 403
    assert correct(player, cole, "item:Potion of Healing", "Action", "campaign").status_code == 403
    assert correct(player, cole, "item:Potion of Healing", "Action", "everyone").status_code == 403
    assert correct(dm, cole, "item:Potion of Healing", "Action", "nobody").status_code == 403
    assert not db.scalars(select(ToolCorrection)).all() and len(db.scalars(select(HouseRule)).all()) == 1


def test_a_campaign_can_correct_everything_the_box_shows_and_house_rules_lists_it(admin, dm, db, sheet):
    from tests.roles import set_role

    cole = refreshed(db, sheet)
    set_role(db, "dm@example.com", "dm")
    correct(dm, cole, "item:Potion of Healing", "hide", "campaign", field="battle", reason="Not at this table")
    page = dm.get("/c/main/manage/house-rules").text
    assert "Potion of Healing" in page and "On Battle: Not on Battle" in page and "Not at this table" in page
    assert "item:Potion of Healing" not in page  # in its own name


def test_correct_this_shows_to_the_dm_and_admins_and_says_who_it_is_for(admin, dm, player, db, sheet):
    from tests.roles import set_role

    cole = refreshed(db, sheet)
    set_role(db, "dm@example.com", "dm")
    ref = f"/characters/{cole.id}/detail?ref=item:{potion(sheet)['id']}"
    assert "Correct this" not in player.get(ref).text
    page = dm.get(ref).text
    assert "Correct this" in page and "Manage › House rules" in page and 'value="everyone"' not in page
    page = admin.get(ref).text
    assert 'value="campaign"' in page and 'value="everyone"' in page and "Tool corrections" in page


def test_the_panel_says_where_the_answer_came_from(admin, player, db, sheet):
    cole = refreshed(db, sheet)
    ref = f"/characters/{cole.id}/detail?ref=item:{potion(sheet)['id']}"
    assert "From the rules" in player.get(ref).text
    correct(admin, cole, "item:Potion of Healing", "Action", "everyone")
    house_rules.invalidate()
    assert "From an askdnd correction" in player.get(ref).text
    correct(admin, cole, "item:Potion of Healing", "Reaction", "campaign")
    page = player.get(ref).text
    assert "From this campaign&#39;s house rule" in page or "From this campaign's house rule" in page
    assert ">Reaction<" in page or "Reaction\n" in page


def test_where_an_answer_comes_from_for_items_nothing_corrects():
    plain = {"name": "Trinket", "base_name": "Trinket", "type": "Wondrous item", "summary": "", "text": ""}
    assert cond.cost_source(plain) == ""
    assert cond.cost_source({**plain, "text": "As a Magic action, you can do something."}) == "text"
    assert cond.cost_source({**plain, "type": "Potion"}) == "rule"
    assert cond.cost_source({**plain, "type": "Scroll"}) == "rule"
    assert cond.cost_source({**plain, "type": "Scroll", "text": "Using a Magic action to read it."}) == "text"


def focus(sheet) -> int:
    """Trah's kind of item, on Cole for the test: the rules list its kinds and its text can't place it."""
    base = potion(sheet)
    row = {**base, "id": 9001, "equipped": True, "isAttuned": True, "quantity": 1,
           "limitedUse": {"maxUses": 1, "resetType": "Dawn", "numberUsed": 0, "resetTypeDescription": ""},
           "definition": {**base["definition"], "id": 9001, "name": "Dragon-Touched Focus (Stirring)", "filterType": "Wondrous item", "subType": None,
                          "type": "Wondrous item", "magic": True, "canAttune": True, "isConsumable": False, "description": "<p>A made-up focus.</p>"}}
    sheet["inventory"].append(row)
    return row["id"]


def test_an_unmarked_kind_is_not_guessed_and_marking_it_places_the_item(player, db, sheet):
    """Brett, 2026-10-30: "I would rather that note not have to exist"."""
    fid = focus(sheet)
    cole = refreshed(db, sheet)
    assert where(db, cole, "Dragon-Touched Focus (Stirring)") == "Action"
    panel = player.get(f"/characters/{cole.id}/detail?ref=item:{fid}").text
    assert "Dragon family" in panel and "Chromatic" in panel and "Metallic" in panel and "The item doesn" in panel
    assert player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Metallic"}).status_code == 204
    db.expire_all()
    assert where(db, cole, "Dragon-Touched Focus (Stirring)") == "Reaction"
    assert player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Chromatic"}).status_code == 204
    db.expire_all()
    assert where(db, cole, "Dragon-Touched Focus (Stirring)") == "No action"
    assert "From the kind marked on this item" in player.get(f"/characters/{cole.id}/detail?ref=item:{fid}").text
    assert player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Bronze"}).status_code == 404
    assert player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": ""}).status_code == 204
    db.expire_all()
    assert not cole.item_choices


def test_a_campaign_correction_still_beats_a_marked_kind(admin, player, db, sheet):
    fid = focus(sheet)
    cole = refreshed(db, sheet)
    player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Metallic"})
    correct(admin, cole, "item:Dragon-Touched Focus (Stirring)", "Bonus action", "campaign")
    db.expire_all()
    assert where(db, cole, "Dragon-Touched Focus (Stirring)") == "Bonus action"


def test_only_the_characters_player_marks_its_kind_and_only_on_items_with_kinds(dm, player, db, sheet):
    fid = focus(sheet)
    cole = refreshed(db, sheet)
    assert dm.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Gem"}).status_code == 404
    assert player.post(f"/characters/{cole.id}/items/{potion(sheet)['id']}/kind", data={"kind": "Gem"}).status_code == 404


def test_no_action_needed_is_its_own_section_that_follows_pinning(admin, player, db, sheet):
    from app import picks

    fid = focus(sheet)
    cole = refreshed(db, sheet)
    player.post(f"/characters/{cole.id}/items/{fid}/kind", data={"kind": "Gem"})
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "No action needed" in page and f"/characters/{cole.id}/all/none?items=1" in page
    assert "All items (1)" in page.split("No action needed", 1)[1]
    assert "you can teleport" not in page  # not pinned, so not listed
    picks.toggle(db, cole, "star", f"item:{fid}", "Focus")
    db.commit()
    section = player.get(f"/characters/{cole.id}/battle").text.split("No action needed", 1)[1]
    assert "Dragon-Touched Focus (Stirring)" in section and "teleport" in section
    assert "Dragon-Touched Focus" in player.get(f"/characters/{cole.id}/all/none?items=1").text
    assert correct(admin, cole, "item:Potion of Healing", "No action", "everyone").status_code == 200
