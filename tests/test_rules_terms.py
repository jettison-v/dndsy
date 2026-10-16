"""Underlined rule terms in side-panel descriptions (app/rules_terms.py)."""

from app import rules_terms as terms

DEMON_ARMOR = ("While wearing this armor, you gain a +1 bonus to Armor Class, and you know Abyssal. In addition, the armor's "
               "clawed gauntlets allow your Unarmed Strikes to deal 1d8 Slashing damage instead of the usual Bludgeoning damage, "
               "and you gain a +1 bonus to the attack and damage rolls of your Unarmed Strikes.")


def names(text, on=None):
    return [t.name for _, _, t in terms.find(text, on if on is not None else terms.underlined({}))]


def test_finds_the_terms_in_a_description():
    assert names(DEMON_ARMOR) == ["Abyssal", "Unarmed Strike", "Unarmed Strike"]


def test_first_mention_only_and_never_the_things_own_name():
    html = str(terms.annotate(DEMON_ARMOR, terms.underlined({})))
    assert html.count('class="term"') == 2 and 'data-term="unarmed-strike">Unarmed Strikes</span>' in html
    assert "armor&#39;s" in html  # the rest is escaped
    seen = ["Unarmed Strike"]
    assert 'data-term="unarmed-strike"' not in str(terms.annotate(DEMON_ARMOR, terms.underlined({}), seen))
    shared = []  # one panel: "What it does" then "Full description"
    terms.annotate("You have the Prone condition.", None, shared)
    assert 'class="term"' not in str(terms.annotate("Stand up from Prone.", None, shared))


def test_case_and_context_keep_ordinary_words_plain():
    assert names("You fall prone and feel a light breeze in the dim light.") == []
    assert names("A heavy door. Bright Light fills the room.") == []
    assert names("Martial Melee weapons that have the Light property") == ["Light"]
    assert names("A Giant appears.") == [] and names("You know Giant and Elvish.") == ["Giant", "Elvish"]
    assert names("You can use a Druidic Focus.") == [] and names("You know Druidic.") == ["Druidic"]
    assert names("Take the Dash action, the Help action, or Help someone.") == ["Dash", "Help action"]


def test_terms_everyone_knows_are_not_underlined_unless_an_admin_says_so():
    text = "You have Advantage on the roll, but the Poisoned condition gives Disadvantage."
    assert names(text) == ["Poisoned"]
    overrides = {("term:Advantage", "underline"): "on", ("term:Poisoned", "underline"): "off"}
    assert names(text, terms.underlined(overrides)) == ["Advantage"]


def test_every_term_has_a_definition_and_a_unique_slug():
    data = terms.as_json()
    assert len(data) == len(terms.TERMS)
    assert all(t["text"] and t["kind"] and t["where"] for t in data.values())
