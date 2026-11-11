"""What class features, subclass features and feats change about a turn in battle
(2024 Player's Handbook), beyond what D&D Beyond lists as actions.

D&D Beyond's action list covers things you activate (Rage, Flurry of Blows, Second
Wind). It doesn't say how many attacks your Attack action makes, which extras you
can add when an attack hits (Sneak Attack, Stunning Strike, Divine Strike), or that
some of its "actions" aren't actions at all (Stunning Strike is a rider on a hit;
"Vex (Dart)" is a weapon mastery). This table fills that in, so the Battle page is
right for every character without per-character fixes.

Each rule applies when the character has that class (or subclass) at that level,
or the feat. Rules are written in our own words (the repo is public); the audit of
every class is in docs/rules/battle-actions.md. Rules that depend on a choice the
player made (Elemental Fury's Primal Strike, Hunter's Prey) have `needs`: they apply
only when the sheet shows that choice.

Effects:
- attacks: the Attack action makes this many attacks (Extra Attack). Doesn't stack:
  the highest wins (PHB multiclassing rule).
- note: (column, text) shown under that Battle column's heading.
- rider: (when, effect) — an extra you add when an attack hits (or misses), with
  `cost` if it spends something. Shown in "On a hit" under the columns.
- option: (column, meta) — an option to add when D&D Beyond doesn't list it.
- replaces: D&D Beyond action names this rule stands in for (hidden from columns).

Text can use {placeholders}: lv (class level), half (half of it), pb, sneak
(Sneak Attack dice), ma (Martial Arts die), rage (Rage Damage), dc_str / dc_dex /
dc_con / dc_int / dc_wis / dc_cha (8 + modifier + PB), mod_int / mod_wis / mod_cha.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    cls: str  # class name, or "Feat"
    level: int
    name: str
    sub: str | None = None  # subclass, for subclass features
    attacks: int | None = None
    attacks_with: str = ""  # Thirsting Blade: only with the pact weapon
    note: tuple[str, str] | None = None
    option: tuple[str, str] | None = None
    needs: str | None = None
    replaces: tuple[str, ...] = ()
    group: str = ""  # rules sharing a group: only the highest level applies (an upgrade replaces the original)


def _ma(lv: int) -> int:
    return 6 if lv < 5 else 8 if lv < 11 else 10 if lv < 17 else 12


def _rage(lv: int) -> int:
    return 2 if lv < 9 else 3 if lv < 16 else 4


R = Rule
RULES: list[Rule] = [
    # ------------------------------------------------------------------ Barbarian
    R("Barbarian", 5, "Extra Attack", attacks=2),
    R("Barbarian", 10, "Retaliation", sub="Path of the Berserker", option=("Reaction", "When a creature within 5 ft damages you: one melee attack against it")),
    R("Barbarian", 10, "Battering Roots", sub="Path of the World Tree",
      note=("Action", "Battering Roots: +10 ft reach with Heavy or Versatile melee weapons on your turn")),
    # ------------------------------------------------------------------ Bard
    R("Bard", 6, "Extra Attack", sub="College of Valor", attacks=2,
      note=("Action", "You can cast an action cantrip in place of one of those attacks (Valor)")),
    R("Bard", 14, "Battle Magic", sub="College of Valor", option=("Bonus action", "After you cast an action spell: one weapon attack")),
    R("Bard", 3, "Agile Strikes", sub="College of Dance",
      note=("Bonus action", "Spending Bardic Inspiration as part of an action, Bonus Action or Reaction also lets you make one Unarmed Strike (Dance)")),
    # ------------------------------------------------------------------ Cleric
    R("Cleric", 3, "War Priest", sub="War Domain", option=("Bonus action", "One weapon attack or Unarmed Strike")),
    # ------------------------------------------------------------------ Druid
    R("Druid", 3, "Circle Forms", sub="Circle of the Moon", replaces=("Wild Shape: Circle Forms",),
      note=("Bonus action", "Circle Forms change your Wild Shape (higher-CR forms, AC 13 + Wis, more Temporary HP); they aren't a separate action")),
    # ------------------------------------------------------------------ Fighter
    R("Fighter", 2, "Action Surge", note=("Action", "Action Surge: one more action on your turn (not the Magic action)")),
    R("Fighter", 5, "Extra Attack", attacks=2),
    R("Fighter", 11, "Two Extra Attacks", attacks=3),
    R("Fighter", 20, "Three Extra Attacks", attacks=4),
    R("Fighter", 3, "Improved Critical", sub="Champion", group="crit", note=("Action", "Weapons and Unarmed Strikes score a Critical Hit on 19–20 (Champion)")),
    R("Fighter", 15, "Superior Critical", sub="Champion", group="crit", note=("Action", "Weapons and Unarmed Strikes score a Critical Hit on 18–20 (Champion)")),
    R("Fighter", 7, "War Magic", sub="Eldritch Knight", group="war-magic", note=("Action", "You can replace one of those attacks with an action Wizard cantrip (War Magic)")),
    R("Fighter", 18, "Improved War Magic", sub="Eldritch Knight", group="war-magic",
      note=("Action", "You can replace two of those attacks with a level 1 or 2 action Wizard spell (Improved War Magic)")),
    # ------------------------------------------------------------------ Monk
    R("Monk", 5, "Extra Attack", attacks=2),
    R("Monk", 10, "Heightened Focus", note=("Bonus action", "Flurry of Blows makes three Unarmed Strikes instead of two (Heightened Focus)")),
    R("Monk", 5, "Stunning Strike", replaces=("Stunning Strike",)),  # (its rider: app/data/rules/phb-2024.json)
    # ------------------------------------------------------------------ Paladin
    R("Paladin", 2, "Paladin's Smite",
      note=("Bonus action", "Divine Smite: cast right after you hit with a melee weapon or Unarmed Strike; once per Long Rest without a slot (Paladin's Smite)")),
    R("Paladin", 5, "Extra Attack", attacks=2),
    R("Paladin", 3, "Sacred Weapon", sub="Oath of Devotion",
      note=("Action", "When you take the Attack action you can use Channel Divinity for Sacred Weapon (+Cha to hit for 10 minutes)")),
    R("Paladin", 3, "Vow of Enmity", sub="Oath of Vengeance",
      note=("Action", "When you take the Attack action you can use Channel Divinity for Vow of Enmity (Advantage against one creature for 1 minute)")),
    R("Paladin", 15, "Soul of Vengeance", sub="Oath of Vengeance",
      option=("Reaction", "Right after the target of your Vow of Enmity attacks: one melee attack against it")),
    # ------------------------------------------------------------------ Ranger
    R("Ranger", 5, "Extra Attack", attacks=2),
    R("Ranger", 17, "Precise Hunter", note=("Action", "Advantage on attack rolls against the creature marked by your Hunter's Mark")),
    R("Ranger", 3, "Primal Companion", sub="Beast Master",
      note=("Action", "You can give up one of your attacks to command your beast to use Beast's Strike")),
    R("Ranger", 3, "Command your beast", sub="Beast Master", option=("Bonus action", "Your Primal Companion takes an action from its stat block")),
    # ------------------------------------------------------------------ Rogue
    R("Rogue", 2, "Cunning Action", option=("Bonus action", "Dash, Disengage or Hide")),
    R("Rogue", 3, "Steady Aim", option=("Bonus action", "If you haven't moved this turn: Advantage on your next attack roll; your Speed is 0 until the end of the turn")),
    R("Rogue", 3, "Fast Hands", sub="Thief", option=("Bonus action", "Sleight of Hand check, Utilize action, or the Magic action to use a magic item")),
    R("Rogue", 3, "Psychic Blade (second)", sub="Soulknife",
      option=("Bonus action", "After you attack with a Psychic Blade: one attack with a second blade (1d4 Psychic), if your other hand is free")),
    # ------------------------------------------------------------------ Sorcerer
    R("Sorcerer", 2, "Metamagic", note=("Action", "Metamagic: spend Sorcery Points to change a spell as you cast it")),
    # ------------------------------------------------------------------ played at this table, from 2014 books
    # (feedback 15, Nov 5: Big C's Oath of Conquest and Divine Soul, Xanathar's; Vi's Artillerist, Tasha's). Not in the
    # 2024 Player's Handbook, so only what Battle needs: the extras added to a roll or a hit
    # ------------------------------------------------------------------ Warlock
    R("Warlock", 5, "Thirsting Blade", needs="Thirsting Blade", attacks=2, attacks_with="your pact weapon"),
    R("Warlock", 12, "Devouring Blade", needs="Devouring Blade", attacks=3, attacks_with="your pact weapon"),
    # ------------------------------------------------------------------ Wizard
    R("Wizard", 3, "Potent Cantrip", sub="Evoker",
      note=("Action", "Potent Cantrip: a damaging cantrip that misses or is saved against still deals half damage")),
    R("Wizard", 10, "Empowered Evocation", sub="Evoker", note=("Action", "Empowered Evocation: +{mod_int} to one damage roll of your Evocation spells")),
    # ------------------------------------------------------------------ Feats
    R("Feat", 1, "Polearm Master: Pole Strike", needs="Polearm Master", option=("Bonus action", "After the Attack action with a Quarterstaff, Spear or Heavy Reach weapon: one attack with the other end (1d4 Bludgeoning)")),
    R("Feat", 1, "Polearm Master: Reactive Strike", needs="Polearm Master",
      option=("Reaction", "When a creature enters your reach (Quarterstaff, Spear or Heavy Reach weapon): one melee attack")),
    R("Feat", 1, "Sentinel", note=("Reaction", "Sentinel: Opportunity Attacks also when a creature within 5 ft Disengages or hits someone else; a hit stops its movement")),
    R("Feat", 1, "War Caster", note=("Reaction", "War Caster: instead of an Opportunity Attack you can cast a 1-action spell at the creature")),
    R("Feat", 1, "Defensive Duelist", option=("Reaction", "Holding a Finesse weapon, when a creature hits you with a melee attack: +{pb} AC until your next turn")),
    R("Feat", 1, "Dual Wielder",
      note=("Bonus action", "Dual Wielder: after attacking with a Light weapon in the Attack action, the extra attack can use a non-Light one-handed melee weapon")),
]

MASTERIES = {
    "Cleave": "On a melee hit, one more attack against a second creature within 5 ft of the first (once per turn; no ability modifier to damage)",
    "Graze": "On a miss, deal damage equal to the ability modifier you attacked with",
    "Nick": "The Light weapon's extra attack is part of the Attack action instead of a Bonus Action (once per turn)",
    "Push": "On a hit, push a Large or smaller creature up to 10 ft away",
    "Sap": "On a hit, the creature has Disadvantage on its next attack roll before your next turn",
    "Slow": "On a hit that deals damage, its Speed drops by 10 ft until your next turn",
    "Topple": "On a hit, Con save (DC 8 + the attack's ability modifier + PB) or Prone",
    "Vex": "On a hit that deals damage, Advantage on your next attack roll against it before the end of your next turn",
}
_MASTERY_NAME = re.compile(rf"^(?:({'|'.join(MASTERIES)}) \((.+)\)|(.+) \(({'|'.join(MASTERIES)})\))$")
RESOURCE_ACTIONS = {"Sorcery Points", "Focus Points", "Luck Points", "Superiority Dice", "Psionic Energy Dice"}


def _norm(name: str | None) -> str:
    """'Oath of Conquest (XGtE)' -> 'oath of conquest'; curly quotes straightened."""
    return re.sub(r"\s*\(.*\)$", "", (name or "").replace("’", "'")).strip().lower()


def _has(sheet: dict, text: str) -> bool:
    names = [x.get("name") or "" for x in (sheet.get("features") or []) + (sheet.get("actions") or [])]
    return any(text.lower() in _norm(n) or text.lower() in (n or "").lower() for n in names)


def _values(sheet: dict, level: int) -> dict:
    pb = sheet.get("proficiency_bonus") or 2
    mods = {a["short"].lower(): a["modifier"] for a in sheet.get("abilities") or []}
    v = {"lv": level, "half": level // 2, "pb": pb, "sneak": f"{(level + 1) // 2}d6", "ma": f"1d{_ma(level)}", "rage": _rage(level)}
    for k, m in mods.items():
        v[f"dc_{k}"] = 8 + m + pb
        v[f"mod_{k}"] = f"{m:+d}"
    return v


def _fmt(text: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def active(sheet: dict) -> list[tuple[Rule, dict]]:
    """The rules that apply to this character, each with its placeholder values."""
    levels, subs = {}, {}
    for c in sheet.get("classes") or []:
        levels[c["name"]] = c["level"]
        subs[c["name"]] = _norm(c.get("subclass"))
    feats = {_norm(f["name"]) for f in sheet.get("features") or [] if f.get("source") == "Feat"}
    out = []
    for r in RULES:
        if r.cls == "Feat":
            if _norm(r.name) not in feats and not (r.needs and _norm(r.needs) in feats):
                continue
            lv = sum(levels.values())
        else:
            lv = levels.get(r.cls, 0)
            if lv < r.level or (r.sub and subs.get(r.cls) != _norm(r.sub)):
                continue
        if r.needs and not _has(sheet, r.needs):
            continue
        out.append((r, _values(sheet, lv)))
    top = {}
    for r, _ in out:
        if r.group and r.level >= top.get(r.group, 0):
            top[r.group] = r.level
    return [(r, v) for r, v in out if not r.group or r.level == top[r.group]]


def turn(sheet: dict) -> dict:
    """Everything the Battle page needs from the rules: attacks per Attack action
    (and from what), column notes, "on a hit" riders, extra options, and the
    D&D Beyond action names to leave out of the columns."""
    rules = active(sheet)
    best, source, scoped = 1, "", []
    for r, _ in rules:
        if r.attacks and not r.attacks_with and r.attacks > best:
            best, source = r.attacks, f"{r.name} ({r.sub or r.cls})"
        elif r.attacks and r.attacks_with:
            scoped.append((r.attacks, f"{r.attacks} attacks with {r.attacks_with} ({r.name})"))
    # Extra Attack from a class or book this table doesn't cover still counts
    for f in sheet.get("features") or []:
        n = {"extra attack": 2, "two extra attacks": 3, "three extra attacks": 4}.get(_norm(f["name"]), 0)
        if n > best:
            best, source = n, f"{f['name']} ({f['source']})"
    notes: dict[str, list[str]] = {"Action": [], "Bonus action": [], "Reaction": []}
    notes["Action"] += [f"Attack action: {text}" for n, text in scoped if n > best]
    riders, options, replaced = [], [], set()
    for r, v in rules:
        if r.note:
            notes[r.note[0]].append(_fmt(r.note[1], v))
        if r.option:
            options.append({"name": r.name.split(": ")[-1] if r.cls == "Feat" else r.name, "cost": r.option[0],
                            "meta": _fmt(r.option[1], v), "source": r.sub or r.cls})
        replaced.update(r.replaces)
    from app import rules_book  # (what can be added once it hits: the rules book's adds, with the words Battle shows)

    riders = [{"name": a["name"].split(" (")[0], "when": a["trigger"], "effect": a.get("effect") or a.get("says") or "", "cost": a.get("cost") or "",
               "source": a["source"]} for a in rules_book.adds(sheet) if a.get("trigger")]
    return {"attacks": best, "attacks_from": source, "notes": notes, "riders": riders, "options": options, "replaced": replaced}


def masteries(sheet: dict) -> dict[str, str]:
    """Weapon kind -> the mastery property this character can use with it
    ("Dagger" -> "Nick"), from D&D Beyond's Weapon Mastery choices."""
    out = {}
    for x in (sheet.get("features") or []) + (sheet.get("actions") or []):
        m = _MASTERY_NAME.match(x.get("name") or "")
        if m:
            mastery, weapon = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            out[weapon.strip().lower()] = mastery
    return out


def is_mastery_action(name: str) -> bool:
    return bool(_MASTERY_NAME.match(name or ""))
