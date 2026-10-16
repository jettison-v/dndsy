"""Rule terms that get a quiet dotted underline in side-panel descriptions, with a
short definition on hover or tap ("Unarmed Strike", "Abyssal", "Prone").

The definitions are our own short summaries of the 2024 Player's Handbook (Rules
Glossary, and chapter 2 for languages). They inform; the DM makes every ruling.

Balance: matching is case-sensitive, because 2024 text capitalizes its rule terms
("Unarmed Strikes", "the Prone condition") and ordinary words stay lowercase. Only
the first mention in a panel is underlined. Terms every player knows (`basic`) are
defined but not underlined unless an admin turns them on; an admin can also turn
any term off. Those choices are stored in sheet_overrides as ("term:<name>", "underline").
"""

import re
from dataclasses import dataclass, field

from markupsafe import Markup, escape

GLOSSARY = "Player's Handbook (2024), Rules Glossary"
LANGUAGES = "Player's Handbook (2024), chapter 2: Languages"


@dataclass(frozen=True)
class Term:
    name: str
    kind: str
    text: str
    forms: tuple[str, ...] = ()  # other spellings that count as this term (plurals, "Dash action")
    basic: bool = False  # everyone knows it: defined, but not underlined unless an admin turns it on
    where: str = GLOSSARY
    bare: bool = True  # False: the name alone is too common a word ("Light"), only `forms` count
    slug: str = field(init=False, default="")

    def __post_init__(self):
        object.__setattr__(self, "slug", re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-"))


def _t(name, kind, text, *forms, basic=False, where=GLOSSARY, bare=True):
    return Term(name, kind, text, tuple(forms), basic, where, bare)


def _language(name, speakers, rare=True, *forms):
    kind = "Rare language" if rare else "Standard language"
    return _t(name, kind, f"A language. Typically spoken by {speakers}. Knowing a language means you can speak, read and write it.",
              *forms, where=LANGUAGES)


TERMS: list[Term] = [
    # Conditions
    _t("Blinded", "Condition", "You can't see, and you automatically fail any ability check that needs sight. Attack rolls against you have Advantage; your attack rolls have Disadvantage.", "Blinded condition"),
    _t("Charmed", "Condition", "You can't attack the charmer or target them with damaging abilities or magical effects. The charmer has Advantage on ability checks to interact with you socially.", "Charmed condition"),
    _t("Deafened", "Condition", "You can't hear, and you automatically fail any ability check that needs hearing.", "Deafened condition"),
    _t("Exhaustion", "Condition", "Comes in levels (1 to 6), which add up. Each level gives −2 to every d20 Test and −5 feet of Speed. At level 6 you die. Finishing a Long Rest removes one level.", "Exhaustion condition", "Exhausted"),
    _t("Frightened", "Condition", "You have Disadvantage on ability checks and attack rolls while the source of your fear is within line of sight, and you can't willingly move closer to it.", "Frightened condition"),
    _t("Grappled", "Condition", "Your Speed is 0 and can't increase. You have Disadvantage on attack rolls against anyone other than the grappler. The grappler can move you with it (costing it extra movement). You can use an action to try to escape: Strength (Athletics) or Dexterity (Acrobatics) against the grapple's DC.", "Grappled condition"),
    _t("Incapacitated", "Condition", "You can't take any action, Bonus Action or Reaction, and you can't speak. Your Concentration is broken. If you're Incapacitated when you roll Initiative, you have Disadvantage on it.", "Incapacitated condition"),
    _t("Invisible", "Condition", "You can't be seen, so effects that need to see their target don't affect you (unless the creator can somehow see you). Attack rolls against you have Disadvantage and yours have Advantage, except against a creature that can see you. You have Advantage on Initiative.", "Invisible condition", "Invisibility condition"),
    _t("Paralyzed", "Condition", "You're Incapacitated and your Speed is 0. You automatically fail Strength and Dexterity saving throws. Attack rolls against you have Advantage, and a hit from within 5 feet is a Critical Hit.", "Paralyzed condition"),
    _t("Petrified", "Condition", "You're turned to stone with your gear. You're Incapacitated, your Speed is 0, and you automatically fail Strength and Dexterity saves. Attack rolls against you have Advantage. You have Resistance to all damage and can't be Poisoned.", "Petrified condition"),
    _t("Poisoned", "Condition", "You have Disadvantage on attack rolls and ability checks.", "Poisoned condition"),
    _t("Prone", "Condition", "You can only crawl, or spend half your Speed to stand up. You have Disadvantage on attack rolls. Attacks against you have Advantage from within 5 feet and Disadvantage from farther away.", "Prone condition"),
    _t("Restrained", "Condition", "Your Speed is 0 and can't increase. Attack rolls against you have Advantage; your attack rolls have Disadvantage. You have Disadvantage on Dexterity saving throws.", "Restrained condition"),
    _t("Stunned", "Condition", "You're Incapacitated. You automatically fail Strength and Dexterity saving throws, and attack rolls against you have Advantage.", "Stunned condition"),
    _t("Unconscious", "Condition", "You're Incapacitated and Prone, you drop what you're holding, your Speed is 0, and you're unaware of your surroundings. You automatically fail Strength and Dexterity saves. Attack rolls against you have Advantage, and a hit from within 5 feet is a Critical Hit.", "Unconscious condition"),

    # Actions
    _t("Attack action", "Action", "Make one attack with a weapon or an Unarmed Strike (more if a feature like Extra Attack says so).", "Attack actions", basic=True),
    _t("Dash", "Action", "For the rest of the turn, you get extra movement equal to your Speed.", "Dash action"),
    _t("Disengage", "Action", "For the rest of the turn, your movement doesn't provoke Opportunity Attacks.", "Disengage action"),
    _t("Dodge", "Action", "Until the start of your next turn, attack rolls against you have Disadvantage if you can see the attacker, and you have Advantage on Dexterity saving throws. You lose this if you're Incapacitated or your Speed is 0.", "Dodge action"),
    _t("Help action", "Action", "Either help an ally with an ability check (they get Advantage on their next check with a skill or tool you know), or distract an enemy within 5 feet of you (an ally's next attack against it has Advantage). Lasts until the start of your next turn."),
    _t("Hide action", "Action", "While Heavily Obscured or behind Three-Quarters or Total Cover, and out of enemies' line of sight, make a DC 15 Dexterity (Stealth) check. On a success you have the Invisible condition until you make noise, attack, cast a spell with a Verbal component, or someone finds you."),
    _t("Influence action", "Action", "Try to change a creature's attitude with a Charisma check (Deception, Intimidation, Performance or Persuasion) or a Wisdom (Animal Handling) check. The DM sets the DC and the outcome."),
    _t("Magic action", "Action", "Cast a spell that takes an action, use a magic item, or use a magical feature."),
    _t("Ready action", "Action", "Choose a trigger and an action (or a spell). When the trigger happens before your next turn, you can take that action with your Reaction. A readied spell needs Concentration until it's released."),
    _t("Search action", "Action", "Make a Wisdom check to discern something: Insight, Medicine, Perception or Survival."),
    _t("Study action", "Action", "Make an Intelligence check to recall or work something out: Arcana, History, Investigation, Nature or Religion."),
    _t("Utilize action", "Action", "Use a nonmagical object, like opening a door or drinking from a waterskin."),

    # Combat and play
    _t("Unarmed Strike", "Rule", "A punch, kick, head-butt or similar. Choose one each time:\n• Damage: Strength + Proficiency Bonus to hit; 1 + Strength modifier Bludgeoning damage.\n• Grapple: the target (within reach, no more than one size larger) makes a Strength or Dexterity save against DC 8 + Strength modifier + Proficiency Bonus, or is Grappled.\n• Shove: the same save, or you push it 5 feet or knock it Prone.", "Unarmed Strikes"),
    _t("Opportunity Attack", "Rule", "When a creature you can see leaves your reach, you can use your Reaction to make one melee attack against it (weapon or Unarmed Strike) just before it leaves. Disengage, teleporting, or being moved without using movement doesn't provoke one.", "Opportunity Attacks"),
    _t("Concentration", "Rule", "Some spells and effects last only while you concentrate. It ends if you start another Concentration effect, become Incapacitated, or die. When you take damage, make a Constitution save (DC 10, or half the damage if higher, up to 30) or it ends."),
    _t("Temporary Hit Points", "Rule", "A buffer that's lost before your real Hit Points. They don't add up: if you get more, you keep whichever you choose. They can't be healed and last until a Long Rest unless the effect says otherwise.", "Temporary Hit Point"),
    _t("Heroic Inspiration", "Rule", "When you have it, you can spend it to reroll any one die right after rolling it; you must use the new roll. You can have only one at a time."),
    _t("Bloodied", "Rule", "A creature is Bloodied while it has half its Hit Points or fewer. Some features only work against (or while) Bloodied."),
    _t("Critical Hit", "Rule", "Rolling a 20 on the d20 for an attack. It hits regardless of AC, and you roll the attack's damage dice twice and add them together (modifiers are added once).", "Critical Hits", basic=True),
    _t("Death Saving Throw", "Rule", "At the start of each turn at 0 Hit Points, roll a d20: 10 or higher is a success, otherwise a failure. Three successes and you're stable; three failures and you die. A 1 counts as two failures; a 20 gets you back up with 1 Hit Point.", "Death Saving Throws", "Death Saves", "Death Save"),
    _t("Surprise", "Rule", "If you're surprised when combat starts, you have Disadvantage on your Initiative roll.", "Surprised"),
    _t("Difficult Terrain", "Rule", "Every foot of movement in it costs 1 extra foot."),
    _t("Half Cover", "Rule", "+2 to AC and Dexterity saving throws, from an obstacle that blocks at least half of you."),
    _t("Three-Quarters Cover", "Rule", "+5 to AC and Dexterity saving throws, from an obstacle that blocks about three-quarters of you."),
    _t("Total Cover", "Rule", "You can't be targeted directly by an attack or spell, though you can still be caught in an area of effect."),
    _t("Heavily Obscured", "Rule", "You can't see into it: trying to see something there is as if you had the Blinded condition. Darkness, thick fog and dense foliage are examples."),
    _t("Lightly Obscured", "Rule", "Dim Light, patchy fog or moderate foliage. You have Disadvantage on Wisdom (Perception) checks to see things in it."),
    _t("Dim Light", "Rule", "Shadows or twilight. The area is Lightly Obscured."),
    _t("Darkness", "Rule", "No light at all. The area is Heavily Obscured.", "magical Darkness"),
    _t("Darkvision", "Sense", "Within its range you see in Dim Light as if it were Bright Light, and in Darkness as if it were Dim Light (in shades of gray)."),
    _t("Blindsight", "Sense", "Within its range you see things without relying on sight, even while Blinded or in Darkness, including Invisible creatures that aren't behind Total Cover."),
    _t("Tremorsense", "Sense", "Within its range you know where creatures and moving objects are if they touch the same ground or liquid as you. It doesn't detect anything flying."),
    _t("Truesight", "Sense", "Within its range you see in normal and magical Darkness, see Invisible creatures and objects, see through visual illusions (and succeed on saves against them), see a shape-shifter's true form, and see into the Ethereal Plane."),
    _t("Resistance", "Rule", "You take half damage (rounded down) from that damage type. More than one Resistance to the same type doesn't stack."),
    _t("Vulnerability", "Rule", "You take double damage from that damage type."),
    _t("Immunity", "Rule", "Damage of that type, or that condition, doesn't affect you at all."),
    _t("Attunement", "Rule", "Some magic items only work once you bond with them, which takes a Short Rest spent focusing on the item. You can be attuned to at most three items. It ends if you're more than 100 feet from the item for 24 hours, you die, or someone else attunes to it.", "Attune", "Attuned"),
    _t("Ritual", "Rule", "A spell with the Ritual tag can be cast as a ritual: it takes 10 minutes longer and uses no spell slot. You still need to have it prepared.", "as a Ritual"),
    _t("Emanation", "Rule", "An area of effect that spreads out from a creature or object in every direction and moves with it."),
    _t("Telepathy", "Sense", "Talk mind to mind with a creature within range. It doesn't need to share a language with you, but it must understand at least one language."),
    _t("Hit Point Dice", "Rule", "When you finish a Short Rest you can spend some: roll each one and add your Constitution modifier to regain that many Hit Points. A Long Rest gets them all back.", "Hit Point Die", "Hit Dice", "Hit Die"),
    _t("Short Rest", "Rule", "One hour of light activity. You can spend Hit Point Dice to heal, and some features come back.", "Short Rests", basic=True),
    _t("Long Rest", "Rule", "Eight hours, at least six of them asleep. You regain all Hit Points and Hit Point Dice and lose one level of Exhaustion. Once per 24 hours.", "Long Rests", basic=True),
    _t("Advantage", "Rule", "Roll two d20s and use the higher. Advantage and Disadvantage cancel out, however many of each you have.", basic=True),
    _t("Disadvantage", "Rule", "Roll two d20s and use the lower. Advantage and Disadvantage cancel out, however many of each you have.", basic=True),
    _t("d20 Test", "Rule", "Any ability check, attack roll or saving throw.", "d20 Tests"),
    _t("Shape-Shifting", "Rule", "Changing into another form. Unless the effect says otherwise, you keep your personality, memories, Hit Points and Hit Point Dice; the new form decides how you move and what you can physically do.", "shape-shift", "Shape-Shift", "shape-shifts"),

    # Weapon properties (only in phrases that are clearly the property, since the words are common)
    _t("Finesse", "Weapon property", "You can use Strength or Dexterity for the attack and damage rolls (the same one for both)."),
    _t("Light", "Weapon property", "When you take the Attack action and attack with a Light weapon, you can make one extra attack as a Bonus Action with a different Light weapon. Don't add your ability modifier to that attack's damage unless it's negative.", "Light weapon", "Light weapons", "Light property", bare=False),
    _t("Heavy", "Weapon property", "You have Disadvantage on attack rolls with it if your Strength (melee) or Dexterity (ranged) is less than 13.", "Heavy weapon", "Heavy weapons", "Heavy property", bare=False),
    _t("Thrown", "Weapon property", "You can throw it to make a ranged attack, using the same ability as for a melee attack with it.", "Thrown weapon", "Thrown weapons", "Thrown property", bare=False),
    _t("Versatile", "Weapon property", "You can use it with one or two hands; the larger damage die is for two hands."),
    _t("Loading", "Weapon property", "You can fire only one piece of ammunition from it per action, Bonus Action or Reaction, however many attacks you'd normally get."),
    _t("Ammunition", "Weapon property", "Each attack uses a piece of ammunition. After a fight you can recover half of what you used (rounded down) by spending a minute searching.", "Ammunition property"),
    _t("Two-Handed", "Weapon property", "You need two hands to attack with it.", "Two-Handed property"),
    _t("Reach", "Weapon property", "It adds 5 feet to your reach when you attack with it, and for Opportunity Attacks.", "Reach property", "Reach weapon", bare=False),

    # Languages
    _language("Common", "most people of the Material Plane", False),
    _language("Common Sign Language", "people who sign instead of speaking", False),
    _language("Draconic", "dragons and dragonborn", False),
    _language("Dwarvish", "dwarves", False),
    _language("Elvish", "elves", False),
    _language("Giant", "giants", False),
    _language("Gnomish", "gnomes", False),
    _language("Goblin", "goblinoids", False),
    _language("Halfling", "halflings", False),
    _language("Orc", "orcs", False),
    _language("Abyssal", "demons of the Abyss (a rare language)"),
    _language("Celestial", "celestials (a rare language)"),
    _language("Deep Speech", "aberrations (a rare language)"),
    _language("Druidic", "druids; it's their secret language, and only druids can learn it"),
    _language("Infernal", "devils of the Nine Hells (a rare language)"),
    _language("Primordial", "elementals (a rare language). Its dialects are Aquan, Auran, Ignan and Terran, and speakers of one understand the others"),
    _language("Sylvan", "the fey (a rare language)"),
    _language("Thieves' Cant", "criminal guilds; it's a secret mix of jargon and signs", True, "Thieves’ Cant"),
    _language("Undercommon", "traders of the Underdark (a rare language)"),
]

BY_SLUG = {t.slug: t for t in TERMS}
_FORMS = {form: t for t in TERMS for form in ((t.name,) if t.bare else ()) + t.forms}
# Languages that are also ordinary words or creature names are only underlined in a
# language context ("you know Giant", "speak Celestial", "Abyssal and Infernal").
_LANGUAGE_CONTEXT = {"Common", "Druidic", "Giant", "Goblin", "Halfling", "Orc", "Celestial", "Draconic", "Elvish", "Dwarvish", "Gnomish"}
_LANG_CUE = re.compile(r"(?:know|knows|speak|speaks|understand|understands|read|write|languages?|tongues?|in|and|or|,)\s*$")
_PATTERN = re.compile(r"(?<![\w'’-])(" + "|".join(re.escape(f) for f in sorted(_FORMS, key=len, reverse=True)) + r")(?![\w'’-])")


def underlined(overrides: dict[tuple[str, str], str]) -> set[str]:
    """Slugs of the terms to underline, after admin choices ("term:<name>" / "underline")."""
    on = set()
    for t in TERMS:
        choice = overrides.get((f"term:{t.name}", "underline"))
        if choice == "on" or (choice is None and not t.basic):
            on.add(t.slug)
    return on


def find(text: str, on: set[str] | None = None) -> list[tuple[int, int, Term]]:
    """(start, end, term) for every term mention worth underlining, in order."""
    found = []
    for m in _PATTERN.finditer(text or ""):
        t = _FORMS[m.group(1)]
        if on is not None and t.slug not in on:
            continue
        if t.name in _LANGUAGE_CONTEXT and not _LANG_CUE.search(text[max(0, m.start() - 20):m.start()]):
            continue
        found.append((m.start(), m.end(), t))
    return found


def annotate(text: str, on: set[str] | None = None, seen: list | None = None) -> Markup:
    """Escape `text` and wrap the first mention of each term in a focusable span.
    `seen` (a list shared by several blocks of one panel) keeps later blocks from
    underlining a term again; put the panel's own name in it to skip self-reference."""
    seen = seen if seen is not None else []
    out, pos = [], 0
    for start, end, t in find(text, on):
        if t.slug in seen or t.name in seen:
            continue
        seen.append(t.slug)
        out.append(escape(text[pos:start]))
        out.append(Markup('<span class="term" tabindex="0" role="button" aria-haspopup="dialog" data-term="{}">{}</span>').format(
            t.slug, text[start:end]))
        pos = end
    out.append(escape(text[pos:]))
    return Markup("").join(out)


def as_json() -> dict:
    return {t.slug: {"name": t.name, "kind": t.kind, "text": t.text, "where": t.where, "basic": t.basic} for t in TERMS}
