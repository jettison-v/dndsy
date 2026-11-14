"""Shapes the parsed D&D Beyond sheets (app/ddb.py) into what the Battle,
Character and Party pages show. Plain functions over the summary dicts, so
they're easy to test without a browser."""

import json
import re
from urllib.parse import quote

from app import advantage, class_rules, components, conditions, house_rules
from app import roll_recipes as rr

COSTS = ["Action", "Bonus action", "Reaction", "Other"]
COLUMN_LIMIT = 7  # options shown in a Battle column before "See all"


def _cost(activation: str) -> str:
    return activation if activation in ("Action", "Bonus action", "Reaction") else "Other"


# What a feature's own text says it costs, first (feedback 15, Nov 5: D&D Beyond labels some actions "Special", such as
# Oath of Conquest's Conquering Presence, "As an action…", which then showed in no column). scripts/battle_audit.py uses it
STATED = {"Bonus action": r"\b(?:[Aa]s|[Tt]ake|[Uu]se|[Uu]sing|[Ee]xpend) (?:a|your) Bonus Action\b",  # (the 2024 books' term, capitalized)
          "Reaction": r"\b(?:[Tt]ake|[Uu]se|[Aa]s|[Uu]sing) (?:a|your) Reaction\b",
          "Action": r"\b(?:take|as|use) (?:a|an|the) (?:Magic |Utilize |Attack |Study |Search |Influence )?[Aa]ction\b|\b[Aa]s an action\b|\bMagic action\b"}


def stated_cost(text: str) -> str | None:
    """The cost a text states first ("As an action…" is Action), or None."""
    found = [(m.start(), cost) for cost, pat in STATED.items() for m in [re.search(pat, text or "")] if m]
    return min(found)[1] if found else None


ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def ordinal(n: int) -> str:
    return ORDINAL.get(n, f"{n}th")


def _spend(resource: dict, amount: int | None) -> dict:
    """One thing an option uses up, with what's left of it now."""
    unit = resource["name"].split(":")[0].strip()
    if amount is not None and unit.endswith("Points") and amount == 1:
        unit = unit[:-1]
    label = f"{amount} {unit}" if amount is not None and unit.endswith(("Point", "Points")) else (
        f"{amount} use of {unit}" if amount == 1 else f"{amount} uses of {unit}" if amount else unit)
    if resource["name"].startswith("Lay On Hands") and amount:
        label = f"{amount} HP from the pool"
    return {"label": label, "of": resource["name"], "uses": resource["uses"]}


def resource_spends(sheet: dict, name: str, key: str, text: str) -> list[dict]:
    """Which limited resources an option uses ("expend 1 Focus Point", or a
    "Channel Divinity: …" option drawing on Channel Divinity), with how many are left."""
    out = []
    if "Regain" in name:  # e.g. Wild Resurgence: Regain Wild Shape gives a use back
        return out
    for r in sheet.get("actions") or []:
        if not r.get("uses") or r.get("key") == key:
            continue
        base = r["name"].split(":")[0].strip()
        forms = {re.escape(f) for f in (r["name"], base, base[:-1] if base.endswith("s") else base)}
        alt = "|".join(sorted(forms, key=len, reverse=True))
        m = re.search(rf"(?:expend|spend|use)s?\s+(\d+|an?|one|two|three|four|five)\s+(?:uses?\s+of\s+)?(?:your\s+)?(?:{alt})\b", text, re.I)
        amount = None
        if m:
            amount = int(m.group(1)) if m.group(1).isdigit() else _NUMBERS[m.group(1).lower()]
        elif base == "Lay On Hands" and name.startswith(base):
            hp = re.search(r"expend\s+(\d+)\s+Hit Points?\s+from", text)
            amount = int(hp.group(1)) if hp else None
        # "Channel Divinity: Divine Sense" draws on Channel Divinity; "Lay On Hands: Heal" on its pool.
        # (Siblings like "Wild Resurgence: Regain …" are separate abilities.)
        same_family = name.split(":")[0].strip() == base and name != r["name"] and (r["name"] == base or "Pool" in r["name"])
        if not (m or same_family or re.search(rf"(?:use|expend|spend)\s+(?:your\s+)?(?:{alt})\b", text, re.I)):
            continue
        if amount is None and same_family and base in ("Channel Divinity", "Wild Shape"):
            amount = 1
        out.append(_spend(r, amount))
    return out


def slot_spends(sheet: dict, sp: dict) -> list[dict]:
    """Free casts first (from a feat, species or item), then a slot of the spell's
    level (pact slots for Warlock spells) if a slot can be used."""
    free = [{"label": "Free cast" if sp["uses"]["max"] == 1 else "Free casts", "of": "Free casts", "uses": sp["uses"]}] if sp.get("uses") else []
    if not sp.get("level") or (sp.get("uses") and not sp.get("uses_slot")):
        return free
    return free + [{**x, "label": ("or " if free else "") + x["label"]} for x in _slot(sheet, sp)]


def _slot(sheet: dict, sp: dict) -> list[dict]:
    slots = sheet.get("spell_slots") or {}
    pact = slots.get("pact")
    regular = {s["level"]: s for s in slots.get("slots") or []}
    if pact and pact["level"] >= sp["level"] and ("Warlock" in (sp.get("sources") or []) or not regular):
        return [{"label": f"Pact ({ordinal(pact['level'])})", "of": "Pact Magic",
                 "uses": {"left": pact["max"] - pact["used"], "max": pact["max"]}}]
    s = regular.get(sp["level"])
    if not s:
        return []
    # "1st-level", not "1st-level slot": players know what it spends (Brett, 2026-10-22)
    return [{"label": f"{ordinal(sp['level'])}-level", "of": "Spell slots", "uses": {"left": s["max"] - s["used"], "max": s["max"]},
             "higher": [{"level": ordinal(x["level"]), "left": x["max"] - x["used"], "max": x["max"]}
                        for lvl, x in sorted(regular.items()) if lvl > sp["level"]]}]


def options(sheet: dict, starred: set[str] | None = None) -> list[dict]:
    """Everything the character can do on a turn, as one list: attacks, spells,
    features and items, each with what it costs (action, bonus action…)."""
    starred = starred or set()
    attacks = {a["name"]: a for a in sheet.get("attacks") or []}
    advs = sheet.get("attack_adv") or []
    rules = class_rules.turn(sheet)
    mastered = class_rules.masteries(sheet)
    action_names = {a["name"] for a in sheet.get("actions") or []}
    out = []

    def add(**o):
        o.setdefault("tags", [])
        o.setdefault("uses", None)
        o.setdefault("hit", "")
        o.setdefault("meta", "")
        o.setdefault("text", "")
        o.setdefault("summary", "")
        o.setdefault("spends", [])
        o.setdefault("adv", [])
        o["starred"] = o["key"] in starred
        o.setdefault("oref", o["key"])
        moved = (sheet.get("_overrides") or {}).get(f"{o['oref']}|cost")
        if moved:
            was = (o.get("use") or {}).get("said")
            o["cost"], o["cost_from"] = moved, "campaign" if f"{o['oref']}|cost" in (sheet.get("_campaign_corrections") or ()) else "askdnd"
            o["tags"] = [t for t in o["tags"] if t != was]
            if o.get("use"):
                o["use"] = {**o["use"], "said": COST_NAMES.get(moved, moved)}
        out.append(o)

    for a in sheet.get("attacks") or []:
        mastery = _mastery(a, mastered)
        props = [p for p in a["properties"] if p not in class_rules.MASTERIES]  # a mastery only counts if you've mastered the weapon
        tags = ([f"×{rules['attacks']} per Attack action"] if rules["attacks"] > 1 else []) + ([f"Mastery: {mastery}"] if mastery else [])
        add(key=a["key"], oref=f"attack:{a['name']}", kind="attack", cost="Action", name=a["name"], hit=a["to_hit"], tags=tags,
            adv=advantage.for_attack(advs, melee="/" not in (a.get("range") or "")),
            meta=" · ".join(x for x in (a["range"], a["damage"], ", ".join(props)) if x),
            text=f"{mastery}: {class_rules.MASTERIES[mastery]}." if mastery else "",
            common=True)
    for sp in sheet.get("spells") or []:
        cost = sp["casting_time"] if sp["casting_time"] in ("Action", "Bonus action", "Reaction") else None
        if not cost:
            continue
        level = "cantrip" if not sp["level"] else ordinal(sp["level"])
        effect = sp["damage"] or (f"heals {sp['healing']}" if sp["healing"] else "")
        spends = slot_spends(sheet, sp)
        says_level = any(x["of"] == "Spell slots" for x in spends)  # "1st-level slot" already gives the level
        tags = ([] if says_level else [level]) + (["Conc."] if sp["concentration"] else [])
        add(key=sp["key"], kind="spell", cost=cost, name=sp["name"], hit=sp["attack"] or sp["save"], tags=tags, level=sp["level"] or 0,
            adv=advantage.for_attack(advs, spell=True) if sp["attack"] else [], cast=bool(sp["level"] or sp["concentration"]),
            spends=spends, need=components.need(sp, sheet, components.rules_for()),
            meta=" · ".join(x for x in (sp["range"], effect, sp["trigger"] if cost == "Reaction" else "") if x),
            text=sp.get("text") or sp["summary"], summary=sp["summary"], recipe=house_rules.spell(sp["name"]) or sp.get("roll"),
            # Smites are cast right after you hit, so they belong with the fight (tool correction built in, 2026-10-23)
            common=cost == "Reaction" or (not sp["level"] and bool(sp["attack"] or sp["save"]) and bool(sp["damage"]))
            or (cost == "Bonus action" and sp["name"].endswith(" Smite")))
    _magic_action_familiar(sheet, add)
    for o in sheet.get("_familiar_options") or []:  # a familiar's, on its master's Battle (app/companions.py master_options)
        add(**o)
    for o in sheet.get("_item_creature_options") or []:  # an item that brings a creature, and commanding it (app/item_creatures.py)
        add(**o)
    for a in sheet.get("actions") or []:
        cost, from_text = _cost(a["activation"]), ""
        if cost == "Other" and a["activation"] in ("Special", None, "") and (said := stated_cost(a.get("text") or "")):
            cost, from_text = said, "text"  # (D&D Beyond's "Special": what its own text says)
        if _not_an_action(a, cost, rules, action_names):
            continue
        hit, meta, unarmed = "", "", a["name"].startswith("Unarmed Strike")
        if unarmed:
            if a["name"] != "Unarmed Strike" or cost == "Action":
                continue  # the attack is listed once, from the attacks; "(Dex.)" variants are the same strike
            u = attacks.get("Unarmed Strike") or {}
            hit, meta = u.get("to_hit", ""), u.get("damage", "")
        recipe = _feature_recipe(sheet, a["name"])  # (a checked recipe says how it rolls: Land's Aid deals damage, Nov 9)
        add(key=a["key"], kind="feature", cost=cost, name=a["name"], hit=hit, meta=meta, uses=a["uses"], text=a["text"], cost_from=from_text or None,
            **({"recipe": recipe} if recipe is not None else {}),
            spends=[] if a["uses"] else resource_spends(sheet, a["name"], a["key"], a["text"] or ""),
            summary=a.get("summary", ""),
            common=not a.get("rule") and (unarmed or cost == "Reaction" or bool(a["uses"] and a["source"] in ("class", "feat", "race"))))
    have = {class_rules._norm(o["name"]) for o in out}
    for r in rules["options"]:
        if class_rules._norm(r["name"]) not in have:
            add(key=f"rule:{r['name']}", kind="feature", cost=r["cost"], name=r["name"], meta=r["meta"], text=r["meta"],
                tags=[r["source"]], common=True)
    _general_options(sheet, add, mastered, have)
    for it in sheet.get("inventory") or []:
        for a in conditions.item_actions(it):  # magic items that grant an action (Ring of Invisibility…)
            add(key=a["key"], oref=f"item:{it['base_name']}#{a['key'].split('#')[1]}", kind="item", cost=a["cost"], name=a["name"],
                meta=a["meta"], text=a["text"], summary=a["text"], starts=a.get("starts"), ends=a.get("ends"), item=a["item"], note=a.get("note", ""),
                common=False)  # in See all; the player pins what they'd use
        ch, left = it["charges"], conditions.item_left(it)
        if not it["battle"] or (not left and (not ch or ch["reset"] == "Used up")):
            continue  # (used up: off Battle, and D&D Beyond's sheet still lists it)
        uses = ch if ch and (ch["max"] > 1 or ch["reset"] != "Used up") else None
        first = re.split(r"(?<=[.!?])\s", it["summary"] or "", maxsplit=1)[0]
        choice = (sheet.get("_item_choices") or {}).get(it["key"].split(":", 1)[1], "")
        cost, said = conditions.item_cost(it, choice)
        kinds = conditions.item_options(it)
        kind = next((c for c in (kinds or {}).get("choices") or [] if c["name"] == choice), None)
        add(key=it["key"], oref=f"item:{it['base_name']}", kind="item", cost=cost, name=it["name"], uses=uses,
            tags=([said] if said and said.lower() != cost.lower() and cost != "No action" else []) + ([f"×{left}"] if left > 1 and not uses else []),
            meta=(kind or {}).get("what") or (first if len(first) <= 120 else first[:119].rsplit(" ", 1)[0] + "…"),
            text=it.get("text") or it["summary"], summary=it["summary"], common="healing" in it["name"].lower(),
            recipe=rr.item_for(sheet, it["base_name"]) or rr.item_for(sheet, it["name"]), cost_from=conditions.cost_source(it, choice),
            use={"mark": (kinds or {}).get("label", "") if not kind else "", "id": it["key"].split(":", 1)[1], "left": left, "said": said, "verb": {"Potion": "Drink", "Scroll": "Read"}.get(it["type"], "Use"),
                 "gives": it["type"] == "Potion", "back": ch["reset_phrase"] if ch else ""})
    unarmed = attacks.get("Unarmed Strike")
    for o in out:
        rollable(o, unarmed)
        first = next(iter((o.get("recipe") or {}).get("events") or []), None)
        if o.get("kind") == "item" and not o.get("hit") and first and first.get("on") == "save" and first.get("dc"):
            o["hit"] = f"{first['save']} {first['dc']}"  # (an item's save with its own DC: Potion of Fire Breath's Dex 13)
    return planned(sheet, out)


def planned(sheet: dict, rows: list[dict], scope: str = "own") -> list[dict]:
    """Every row on a Battle made ready to roll the same way, whoever's Battle it is (Brett, Nov 12: "applies as
    globally as possible"): the character's own (options), a Wild Shape form's (app/wild_shape.py `shaped`), a
    creature's (app/creatures.py, app/table_creatures.py). Each row with a to-hit or a save gets its roll plan
    (app/roll_plan.py: an Unarmed Strike's Damage, Grapple or Shove, the riders and modifiers its `scope` allows), its
    dice at every level, and how its numbers add up (Show the Math, app/roll_math.py). A row that already has a plan
    (one of the character's own, copied onto a form's Battle) keeps it. tests/test_roll_math.py walks every form and
    creature of the party's sheets."""
    from app.roll_math import option_math
    from app.roll_plan import SAVE, effects, plan  # (the roll card's: what each roll button plays, app/roll_plan.py)

    for o in rows:
        if "plan" in o:
            continue
        if str(o.get("hit") or "")[:1] in "+-\u2212" or SAVE.match(str(o.get("hit") or "")):  # (a to-hit, or a save spell's "Dex 15")
            o["plan"] = plan(sheet, o, scope)
        rec = o.get("recipe") if (o.get("recipe") or {}).get("events") else None
        if rec and "rolls" not in o:  # (its dice at every level it can be cast at, for each of its buttons)
            o["rolls"] = {"hit": effects(rec, sheet, o["name"], True), "other": effects(rec, sheet, o["name"], False)}
        o["math"] = option_math(sheet, o, o.get("plan"))  # (how its numbers add up: Show the Math, app/roll_math.py)
    return rows


# What an option rolls (the roll buttons: _char.html hit()): its to-hit, else dice in its details,
# else dice its text says you regain ("regains 2d4 + 2 Hit Points") or deal ("1d6 fire damage").
# Features that make Unarmed Strikes (Flurry of Blows) roll the Unarmed Strike.
DICE = r"(\d+d\d+(?:\s*[+\u2212-]\s*\d+(?!d))?)"
HEALS = re.compile(r"\b(?:regains?|restores?|heals?)\s+" + DICE + r"(?!\s*(?:[+\u2212-]\s*\d+\s*)?(?:expended\s+)?charges)", re.I)
DEALS = re.compile(DICE + r"\s+(?:[a-z]+\s+){0,2}damage\b", re.I)
# a flat damage with no dice, an Unarmed Strike's "5 ft · 3 bludgeoning" (feedback, Nov 4: it never rolled)
FLAT = re.compile(r"(?:^|·)\s*(0|[1-9]\d?)\s+(?:acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|"
                  r"slashing|thunder)\b", re.I)
MAKES_UNARMED = re.compile(r"\bmake (?:one|two|three|an?) Unarmed Strikes?\b", re.I)


def _dice(text: str) -> str:
    m = re.search(DICE, text or "")
    return re.sub(r"\s+", "", m.group(1)).replace("\u2212", "-") if m else ""


def roll_data(kind: str, label: str, mod="", dmg="", advs=(), note="", rolls=None, plan=None, slot=0, save="", math=None,
              parts=None) -> dict[str, str]:
    """A roll button's data attributes, the one place they're made: every roll button's template (_char.html
    `roll_attrs`) and Search's rows (app/search.py, copied whole onto the button it makes), so a roll from Search is the
    button's own roll. `data-plan` is everything the roll card plays (app/roll_plan.py `button`: the option's `plan`,
    `rolls` its dice at each level); the rest says what the button is. `advs`: Advantage with its reasons, those without
    a `when` always on. `math`: how its numbers add up (app/roll_math.py), or `parts`, a check's or save's own
    [(what, amount)] as the sheet gives them."""
    from app import roll_math
    from app.roll_plan import button

    d = {"roll": kind, "label": label}
    if mod:
        d["mod"] = str(mod).replace("\u2212", "-")
    if dmg:
        d["dmg"] = dmg
    advs = list(advs or ())
    if any(not a.get("when") for a in advs):
        d["adv"] = "1"
    if advs:
        d["adv-why"] = "\n".join(a.get("text") or "" for a in advs)
    if slot:
        d["slot"] = str(slot)
    math = dict(math or {})
    if parts and mod not in ("", None) and (got := roll_math.checked(roll_math.rows(parts), str(mod).replace("\u2212", "-"))):
        math["bonus"] = got
    d["plan"] = json.dumps(button(kind, label, mod, dmg, note, plan, rolls, save, math=math))
    return d


def option_rolls(o: dict) -> list[dict]:
    """An option's rolls as Battle draws them (_char.html `hit`): its to-hit ("hit", the attack, then damage), else
    the roll its words or recipe make (a "chip": a save's damage, healing), with the hit's plain text between when it
    isn't a to-hit (a save's "Dex 15"). Each part: `button` ("hit", "chip" or None for text), `attrs` (roll_data),
    `title`, `text`. Search makes the first button's roll."""
    hit = str(o.get("hit") or "")
    to_hit = bool(hit) and hit[0] in "+-\u2212"
    rec = o.get("recipe") if (o.get("recipe") or {}).get("events") else None
    out = []
    if rec:
        from app.roll_plan import effects

        # (a Wild Shape form's or a creature's row isn't one of Battle's options: its recipe has no levels or tokens)
        rolls = o.get("rolls") or {"hit": effects(rec, {}, o["name"], True), "other": effects(rec, {}, o["name"], False)}
        hits = [e for e in rec["events"] if e.get("on") == "hit"]
        first = next((e for e in rec["events"] if e.get("on") != "hit"), None)
        if hits and to_hit:
            out.append({"button": "hit", "title": "Roll to hit", "text": hit,
                        "attrs": roll_data("attack", o["name"], hit, "", o.get("adv"), rolls=rolls["hit"], plan=o.get("plan"), math=o.get("math"))})
        elif hit:
            out.append({"button": None, "text": hit})
        if first:
            kind = {"heal": "heal", "temp": "temp", "plain": "dice"}.get(first.get("on"), "damage")
            save = bool(hit) and not to_hit
            out.append({"button": "chip", "title": "Roll", "text": "Heal" if first.get("on") == "heal" else "Roll",
                        "attrs": roll_data(kind, o["name"], rolls=rolls["other"], plan=o.get("plan") if save else None,
                                           save=hit if save else "", math=o.get("math"))})
        return out
    dmg = o["dice"] if "dice" in o else _dice(o.get("meta") or "")
    heal = o["heal"] if "heal" in o else ("heals " in (o.get("meta") or "") or "healing" in (o.get("name") or "").lower())
    kind = "heal" if heal else "damage"
    word = "Heal" if heal else "Roll"
    if to_hit:
        out.append({"button": "hit", "title": "Roll to hit" + (" (then damage)" if dmg else ""), "text": hit,
                    "attrs": roll_data("attack", o["name"], hit, dmg, o.get("adv"), plan=o.get("plan"), math=o.get("math"))})
    elif hit:
        out.append({"button": None, "text": hit})
        if dmg:
            out.append({"button": "chip", "title": f"Roll {dmg}", "text": word,
                        "attrs": roll_data(kind, o["name"], "", dmg, plan=o.get("plan"), save=hit, math=o.get("math"))})
    elif dmg:
        out.append({"button": "chip", "title": f"Roll {dmg}", "text": word, "attrs": roll_data(kind, o["name"], "", dmg, math=o.get("math"))})
    return out


def item_roll(o: dict, sheet: dict | None = None) -> dict | None:
    """An item's one roll as its button carries it (a potion's healing, Keoghtom's Ointment, a Soul Coin), for the Use
    window: `attrs` (the button's, plan and all), `kind`, `formula` (its dice at the plan's own level, types left out).
    The Use window rolls only this, so using an item and pressing its Roll are the same roll (Brett, Nov 10). An item
    whose recipe says what using it rolls (`use`: a check, a save, the weapon's own attack with a save on a hit) gets that
    roll, made from the sheet's own numbers (`use_roll`)."""
    if sheet is not None and (use := (o.get("recipe") or {}).get("use")):
        return use_roll(o, sheet, use)
    for r in option_rolls(o):
        attrs = r.get("attrs") or {}
        plan = json.loads(attrs.get("plan") or "null") or {}
        rolls = plan.get("rolls") or {}
        if r.get("button") != "chip" or plan.get("play") not in ("single", "save") or not rolls.get("effects"):
            continue
        at = rolls["effects"][0]["at"].get(str(rolls.get("base", 0))) or next(iter(rolls["effects"][0]["at"].values()), None)
        if at and at.get("parts"):
            return {"attrs": attrs, "kind": attrs.get("roll"), "formula": "+".join(p.split(" ")[0] for p in at["parts"]), "text": at.get("text") or ""}
    return None


def use_roll(o: dict, sheet: dict, use: dict) -> dict | None:
    """What using an item rolls, by its recipe's `use` (app/data/rules/<book>.json): {"check": "Arcana", "dc": 10}
    (Hat of Wizardry), {"save": "Con", "dc": 15} (Dust of Sneezing and Choking: you roll yours too), {"attack": true,
    "rider": {name, save, dc, says}} (Hammer of Thunderbolts: its own attack, thrown, and on a hit a save for the DM).
    The numbers are the sheet's; the DC and words are the recipe's."""
    note = use.get("says") or ""
    if beads := use.get("beads") or use.get("spells"):  # (a Necklace's bead, the DM having set them; a wand's or staff's spell)
        from app import roll_recipes as rr
        from app.roll_plan import _spell_dc, effects

        out = []
        for i, b in enumerate(beads):
            rec, attrs = rr.spell(b["spell"]), None
            first = next((e for e in (rec or {}).get("events") or [] if e.get("on") not in ("hit", "rider")), None)
            if first:
                kind = {"heal": "heal", "temp": "temp", "plain": "dice"}.get(first.get("on"), "damage")
                # (a save with the item's own DC, Wand of Fireballs' 15; else the caster's: a staff "using your spell save DC")
                dc = b.get("dc") or _spell_dc(sheet)
                save = f"{first['save']} {dc}" if first.get("on") == "save" and first.get("save") and dc else ""
                attrs = roll_data(kind, b["spell"], rolls=effects(rec, sheet, b["spell"], False), save=save)
            out.append({**b, "attrs": attrs, "i": i})
        return {"attrs": None, "kind": "beads", "beads": out, "formula": "", "text": "", "ask": "Which bead" if use.get("beads") else "Which spell"}
    if skill := use.get("check"):
        sk = next((x for x in sheet.get("skills") or [] if x["name"] == skill), None)
        if not sk:
            return None
        note = f"DC {use['dc']}" + (f": {note}" if note else "") if use.get("dc") else note
        attrs = roll_data("check", f"{skill} check", sk["label"], note=note, advs=sk.get("adv"))
        return {"attrs": attrs, "kind": "check", "formula": "", "text": f"{skill} {sk['label']}" + (f" · DC {use['dc']}" if use.get("dc") else "")}
    if ab := use.get("save"):
        sv = next((x for x in sheet.get("saves") or [] if x["short"].lower() == ab.lower()), None)
        if not sv:
            return None
        note = f"DC {use['dc']}" + (f": {note}" if note else "") if use.get("dc") else note
        attrs = roll_data("save", f"{sv['short']} save", sv["label"], note=note, advs=sv.get("adv"))
        return {"attrs": attrs, "kind": "save", "formula": "", "text": f"{sv['short']} save {sv['label']}" + (f" · DC {use['dc']}" if use.get("dc") else "")}
    if use.get("attack"):
        weapon = next((x for x in options(sheet, set()) if x.get("kind") == "attack" and x["name"] == o["name"]), None)
        hit = next((r for r in option_rolls(weapon) if r.get("button") == "hit"), None) if weapon else None
        if not hit:
            return None
        attrs = dict(hit["attrs"])
        plan = json.loads(attrs["plan"])
        if rd := use.get("rider"):
            plan["riders"] = [*(plan.get("riders") or []), {"name": rd["name"], "when": "hit", "says": rd.get("says", ""), "on": "item",
                                                           "act": {"kind": "save", "save": rd["save"], "dc": int(rd["dc"])}}]
        if note:
            plan["notes"] = [*(plan.get("notes") or []), note]
        attrs["plan"] = json.dumps(plan)
        return {"attrs": attrs, "kind": "attack", "formula": "", "text": f"{weapon.get('hit')} to hit"}
    return None


def rollable(o: dict, unarmed: dict | None = None) -> dict:
    """Sets o["dice"] (damage or healing dice, "" if none) and o["heal"]; gives a feature that
    makes Unarmed Strikes the Unarmed Strike's to-hit and damage."""
    recipe = o.get("recipe")
    if recipe is not None and not recipe.get("events") and recipe.get("checked") and recipe.get("checked") != "D&D Beyond":
        o["dice"], o["heal"] = "", False  # (a checked recipe that rolls nothing: Create Eldritch Cannon, Find Steed; never its words' dice)
        return o
    if recipe and recipe.get("events"):  # an audited (or D&D Beyond) recipe says exactly what rolls
        if all(e["on"] == "rider" for e in recipe["events"]):  # (Hunter's Mark: added to hits, never rolled on casting)
            o["dice"], o["heal"] = "", False
            return o
        other = [e for e in recipe["events"] if e["on"] not in ("hit", "rider")]
        o["dice"] = (other or recipe["events"])[0]["parts"][0] if (other or recipe["events"])[0].get("parts") else ""
        o["heal"] = bool(other) and other[0]["on"] == "heal"
        return o
    text = f"{o.get('summary') or ''} {o.get('text') or ''}"
    if not o.get("hit") and unarmed and o.get("kind") == "feature" and MAKES_UNARMED.search(text):
        o["hit"] = unarmed.get("to_hit", "")
        o["meta"] = o.get("meta") or unarmed.get("damage", "")
    meta = o.get("meta") or ""
    # (an item's first sentence can hold dice that aren't a roll: how many doses it has)
    o["dice"], o["heal"] = "" if o.get("use") else _dice(meta), "heals " in meta or "healing" in (o.get("name") or "").lower()
    if not o["dice"]:
        m = HEALS.search(text)
        d = None if m else DEALS.search(text)
        o["dice"], o["heal"] = (_dice(m.group(1)), True) if m else (_dice(d.group(1)), False) if d else ("", o["heal"])
    if not o["dice"] and str(o.get("hit") or "")[:1] in "+-\u2212" and o.get("hit") and (f := FLAT.search(meta)):
        o["dice"] = f.group(1)
    return o


def _feature_recipe(sheet: dict, name: str) -> dict | None:
    """A class feature's checked recipe (app/roll_recipes.py `feature`), its {tokens} filled from this sheet."""
    from app.roll_plan import fill

    r = rr.feature(name)
    if r is None:
        return None
    return {**r, "events": [{**e, "parts": [fill(x, sheet) for x in e.get("parts") or []]} for e in r.get("events") or []]}


def _mastery(attack: dict, mastered: dict[str, str]) -> str | None:
    """The mastery property this character can use with this weapon, if any."""
    kind = (attack.get("base") or "").lower()
    name = attack["name"].lower()
    for weapon, mastery in mastered.items():
        if weapon == kind or re.search(rf"\b{re.escape(weapon)}\b", name):
            return mastery
    return None


def _not_an_action(a: dict, cost: str, rules: dict, action_names: set[str]) -> bool:
    """D&D Beyond actions that aren't options on a turn: weapon masteries ("Vex
    (Dart)", shown on the weapon), riders on a hit (Stunning Strike, shown under
    "On a hit"), resource pools (Sorcery Points) and the bare Channel Divinity pool
    when its options are listed separately."""
    name = a["name"]
    if class_rules.is_mastery_action(name) or name in rules["replaced"]:
        return True
    if cost in ("Action", "Bonus action") and (name in class_rules.RESOURCE_ACTIONS or name.endswith(": Healing Pool")):
        return True
    return name == "Channel Divinity" and any(n.startswith("Channel Divinity:") for n in action_names)


def _magic_action_familiar(sheet: dict, add) -> None:
    """Find Familiar as a Magic action (feedback 15, Nov 5): its own casting time is an hour, but Wild Companion (a
    Druid's: a Wild Shape use or a slot) and Pact of the Chain (no slot) cast it as a Magic action, so it's on Battle's
    Action column, opening its Cast window (app/casting.py ways, wild_ways)."""
    sp = next((x for x in sheet.get("spells") or [] if x["name"] == "Find Familiar"), None)
    have = {f.get("name") for f in sheet.get("features") or []} | {a.get("name") for a in sheet.get("actions") or []}
    how = [w for name, w in (("Wild Companion", "a Wild Shape use or a slot (Wild Companion)"), ("Pact of the Chain", "no slot (Pact of the Chain)"))
           if name in have]
    if not sp or not how:
        return
    add(key=sp["key"], kind="spell", cost="Action", name="Find Familiar", tags=["Magic action"], level=sp["level"] or 1, cast=True,
        meta="As a Magic action: " + " or ".join(how), text=sp.get("text") or sp.get("summary") or "", summary=sp.get("summary") or "",
        cost_from="rule", common=False)


def _general_options(sheet: dict, add, mastered: dict[str, str], have: set[str]) -> None:
    """Options every character has from the core rules: the Opportunity Attack and
    the Light weapon's extra attack."""
    attacks = sheet.get("attacks") or []
    melee = [a for a in attacks if "/" not in (a.get("range") or "") and "(" not in (a.get("range") or "")]
    best = max(melee, key=lambda a: int(a["to_hit"].replace("−", "-") or 0), default=None)
    if "opportunity attack" not in have and best:
        add(key="rule:Opportunity Attack", kind="feature", cost="Reaction", name="Opportunity Attack", hit=best["to_hit"],
            meta=f"When a creature you can see leaves your reach: one melee attack ({best['name']})",
            text="When a creature you can see leaves your reach (using its action, Bonus Action, Reaction or movement), "
                 "you can take a Reaction to make one melee attack with a weapon or an Unarmed Strike against it, right before it leaves.",
            common=True)
    light = [a for a in melee if "Light" in a["properties"]]
    if len(light) >= 2:
        nick = any(_mastery(a, mastered) == "Nick" for a in light)
        add(key="rule:Light weapon extra attack", kind="feature", cost="Action" if nick else "Bonus action", name="Light weapon extra attack",
            meta=("Part of the Attack action (Nick), once per turn: " if nick else "After attacking with a Light weapon in the Attack action: ")
            + "one attack with your other Light weapon; no ability modifier to its damage unless negative",
            common=True)


def _battle_override(sheet: dict, oref: str) -> str | None:
    return (sheet.get("_overrides") or {}).get(f"{oref}|battle")


COST_NAMES = {"Bonus action": "Bonus Action", "No action": "No action needed"}
COST_FROM = {"campaign": "From this campaign's house rule", "askdnd": "From an askdnd correction", "rule": "From the rules",
             "choice": "From the kind marked on this item", "text": "From its own description", "": "The item doesn't say"}


def battle_columns(sheet: dict, starred: set[str], order: dict[str, list[str]] | None = None, pinned_only: bool = False) -> dict:
    """Action / Bonus action / Reaction columns: pinned first, then the common options (or the
    player's own drag-and-drop order); the rest is behind "See all". With `pinned_only` (anyone who
    can see the player's pins), only what the player pinned: Battle shows their plan
    (Brett, 2026-10-21: fewer automatic choices, to encourage planning and learning). Items sit in a
    section of their own at the end of a column, by the same rules, in their own order ("<cost> items");
    the rest are in the side panel (Brett, 2026-10-30, docs/mockups/potions-and-charges.html)."""
    cols, order = {}, order or {}
    for cost in ("Action", "Bonus action", "Reaction", "No action"):
        everything = []
        for o in options(sheet, starred):
            v = _battle_override(sheet, o["oref"])
            if o["cost"] != cost or (v == "hide" and not o["starred"]):
                continue
            everything.append({**o, "common": o["common"] if v is None else v == "common"})
        shown = [o for o in everything if o["starred"]] + ([] if pinned_only else [o for o in everything if o["common"] and not o["starred"]])
        if order.get(cost):
            rank = {k: i for i, k in enumerate(order[cost])}
            shown.sort(key=lambda o: rank.get(o["key"], len(rank)))  # stable: new ones keep their place after
        items = [o for o in shown if o["kind"] == "item"]
        if order.get(f"{cost} items"):
            rank = {k: i for i, k in enumerate(order[f"{cost} items"])}
            items.sort(key=lambda o: rank.get(o["key"], len(rank)))
        options_only = [o for o in shown if o["kind"] != "item"]
        item_count = sum(o["kind"] == "item" for o in everything)
        cols[cost] = {"shown": options_only[:COLUMN_LIMIT], "items": items[:COLUMN_LIMIT], "item_count": item_count, "all": everything,
                      "count": len(everything) - item_count}
    rules = class_rules.turn(sheet)
    for cost, col in cols.items():
        col["notes"] = rules["notes"].get(cost, [])
    if rules["attacks"] > 1:
        cols["Action"]["sub"] = f"One per turn · the Attack action makes {rules['attacks']} attacks"
        cols["Action"]["notes"].insert(0, f"From {rules['attacks_from']}")
    return cols


def find(sheet: dict, ref: str) -> dict | None:
    """The thing a pin or reminder points at, wherever it lives on the sheet. A spell's key looks in
    the spells first: a situational rule can share it (Absorb Elements' "Reaction spell: …"). An item's
    action ("item:12#turn-invisible") opens the item."""
    ref = ref.split("#", 1)[0]
    order = ("situational", "actions", "spells", "features", "inventory", "creatures", "attacks")
    if ref.startswith("spell:"):
        order = ("spells",) + tuple(s for s in order if s != "spells")
    for section in order:
        for x in sheet.get(section) or []:
            if x.get("key") == ref:
                return {**x, "section": section}
    for book in sheet.get("spellbook") or []:  # spells you could prepare but don't have yet
        for x in book["spells"]:
            if x.get("key") == ref:
                return {**x, "section": "spells", "class": book["class"]}
    return None


# What anyone can do as an Action (2024 PHB), on Battle under the Action column; each opens its rule in the side panel
# with the rolls it calls for (feedback 8, Nov 4). Attack isn't listed: the attacks are the column's own rows.
BASIC_ACTIONS = ("Dash", "Disengage", "Dodge", "Help", "Hide", "Influence", "Magic", "Ready", "Search", "Study", "Utilize")
BASIC_SKILLS = {"Hide": ("Stealth",), "Search": ("Insight", "Medicine", "Perception", "Survival"),
                "Study": ("Arcana", "History", "Investigation", "Nature", "Religion"),
                "Influence": ("Deception", "Intimidation", "Performance", "Persuasion", "Animal Handling")}


def basic_action(sheet: dict, name: str) -> dict | None:
    """One of the actions anyone can take, for the side panel: its rule (rules_terms' summary), the checks it rolls,
    and for Dash the movement it gives."""
    from app import rules_terms

    if name not in BASIC_ACTIONS:
        return None
    t = next((t for t in rules_terms.TERMS if t.name in (name, f"{name} action")), None)
    skills = [k for want in BASIC_SKILLS.get(name, ()) for k in sheet.get("skills") or [] if k["name"] == want]
    speed = (sheet.get("speed") or {}).get("walk") if name == "Dash" else None
    return {"name": name, "key": f"rule:basic:{name}", "section": "basic", "summary": t.text if t else "", "where": t.where if t else "",
            "skills": skills, "speed": speed}


def unarmed_choices(sheet: dict, x: dict) -> dict | None:
    """An Unarmed Strike's three ways (2024 PHB: Damage, Grapple, Shove; feedback 5, Nov 4), with the DC askdnd works
    out: 8 + Strength modifier + Proficiency Bonus, or Dexterity for a Monk's Martial Arts."""
    if not (x.get("name") or "").startswith("Unarmed Strike"):
        return None
    if x.get("unarmed_dc"):  # (a Wild Shape form's own: the form's Strength or Dexterity, app/wild_shape.py)
        return {"dc": x["unarmed_dc"], "from": x.get("unarmed_from") or ""}
    mods = {a["key"]: a.get("modifier") or 0 for a in sheet.get("abilities") or []}
    pb = sheet.get("proficiency_bonus") or 2
    monk = any(a.get("martial_arts") for a in sheet.get("attacks") or [] if a["name"] == "Unarmed Strike")
    use = "dexterity" if monk and mods.get("dexterity", 0) > mods.get("strength", 0) else "strength"
    return {"dc": 8 + mods.get(use, 0) + pb, "from": f"8 + {use.title()} modifier ({mods.get(use, 0):+d}) + Proficiency Bonus ({pb:+d})"
            + (" · Martial Arts lets you use Dexterity" if use == "dexterity" else "")}


def detail(sheet: dict, ref: str, starred: set[str] = frozenset()) -> dict | None:
    """Everything the side panel shows for one thing: the thing itself, how it
    works on a turn (if it's an option), and where it comes from."""
    if ref.startswith("rule:basic:"):
        b = basic_action(sheet, ref.removeprefix("rule:basic:"))
        return {"x": b, "opt": None, "section": "basic", "roll": None} if b else None
    x = find(sheet, ref)
    if x is None and not ref.startswith(("attack:", "rule:")):
        return None
    opt = next((o for o in options(sheet, set(starred)) if o["key"] == ref), None)
    if x is None:
        x = {"name": opt["name"], "section": "attacks", "text": opt.get("text", "")} if opt else None
    if x is None:
        return None
    if x["section"] == "situational":  # point at the feature or spell it comes from
        x["related"] = next((f for f in sheet.get("features") or [] if f["name"] == x.get("source")), None)
    if x["section"] == "spells":
        for book in sheet.get("spellbook") or []:
            same = next((s for s in book["spells"] if s["name"] == x["name"]), None)
            if same:
                x.setdefault("state", same["state"])
                x.setdefault("class", book["class"])
                x.setdefault("prep", same.get("prep"))  # Prepare or Unprepare (app/preparing.py)
    roll = opt
    if roll is None and x["section"] in ("spells", "inventory", "attacks", "actions", "features", "creatures"):
        weapon = next((a for a in sheet.get("attacks") or [] if a["name"] == x.get("name")), None)
        effect = x.get("damage") or (f"heals {x['healing']}" if x.get("healing") else "")
        recipe = house_rules.spell(x.get("name") or "") or x.get("roll") if x["section"] == "spells" else rr.item_for(sheet, x.get("name") or "")
        roll = rollable({"name": x.get("name") or "", "kind": "spell" if x["section"] == "spells" else "item", "recipe": recipe,
                         "hit": x.get("attack") or x.get("save") or (weapon or {}).get("to_hit", ""), "meta": effect if isinstance(effect, str) else "",
                         "summary": x.get("summary") or "", "text": x.get("text") or "", "adv": []})
    if roll is not None and not (roll.get("dice") or (roll.get("hit") or "")[:1] in ("+", "-", "\u2212")):
        roll = None
    return {"x": x, "opt": opt, "section": x["section"], "roll": roll, "unarmed": unarmed_choices(sheet, x)}


def label_for(sheet: dict, ref: str) -> str:
    """Short text for Reminders."""
    x = find(sheet, ref)
    if not x:
        return ""
    if x["section"] == "situational":
        return x["text"] + (f" ({x['source']})" if x["source"] else "")
    if x["section"] == "creatures":
        return f"{x['name']} ({x.get('group') or 'form'}, CR {x.get('cr')})"
    detail = x.get("summary") or x.get("text") or ""
    detail = re.split(r"(?<=[.!?])\s", detail, maxsplit=1)[0]
    return f"{x['name']}: {detail}" if detail else x["name"]


def reminders(sheet: dict, remind: dict[str, str], order: list[str] | None = None, notes: dict[str, str] | None = None) -> list[dict]:
    """Reminders in the player's order (drag and drop), else the order they were
    added; today's sheet text when the thing still exists, the saved label otherwise,
    with the player's note on why."""
    notes = notes or {}
    out = [{"ref": ref, "text": label_for(sheet, ref) or saved, "note": notes.get(ref, "")}
           for ref, saved in remind.items() if label_for(sheet, ref) or saved]
    if order:
        rank = {k: i for i, k in enumerate(order)}
        out.sort(key=lambda r: rank.get(r["ref"], len(rank)))
    return out


# ------------------------------------------------------------------ party


def party_row(character, sheet: dict | None) -> dict:
    if not sheet:
        return {"c": character, "sheet": None}
    saves = sorted(sheet["saves"], key=lambda s: -s["bonus"])[:2]
    ss = sheet.get("spell_slots") or {}
    slots = [{"label": ordinal(s["level"]), "uses": {"left": s["max"] - s["used"], "max": s["max"]}} for s in ss.get("slots") or []]
    if ss.get("pact"):
        p = ss["pact"]
        slots.append({"label": f"Pact ({ordinal(p['level'])})", "uses": {"left": p["max"] - p["used"], "max": p["max"]}})
    return {
        "c": character,
        "sheet": sheet,
        "classes": " / ".join(f"{k['name']} {k['level']}" for k in sheet["classes"]),
        "top_saves": saves,
        # limited uses (Wild Shape, Focus Points…) and spell slots, each with dots for what's left
        "resources": [{"name": a["name"], "uses": a["uses"]} for a in sheet.get("actions") or []
                      if a.get("uses") and a.get("source") in ("class", "feat", "race")],
        "slots": slots,
    }


SPELL_GROUPS = [
    ("Healing and recovery", lambda s: bool(s["healing"]) or "Healing" in s["tags"]),
    ("Rituals (no slot needed, +10 minutes)", lambda s: s["ritual"]),
    ("Reactions", lambda s: s["casting_time"] == "Reaction"),
    ("Protection and buffs", lambda s: bool({"Buff", "Warding"} & set(s["tags"]))),
    ("Control and debuffs", lambda s: bool({"Control", "Debuff"} & set(s["tags"]))),
    ("Damage", lambda s: bool(s["damage"]) or "Damage" in s["tags"]),
    ("Getting around", lambda s: bool({"Movement", "Teleportation"} & set(s["tags"]))),
    ("Finding things out", lambda s: bool({"Detection", "Foreknowledge", "Scrying", "Communication"} & set(s["tags"]))),
]


def _panel_url(character, key: str) -> str:
    return f"/characters/{character.id}/detail?ref={quote(key, safe='')}"


def _who(r: dict, note: str, url: str) -> dict:
    """One character holding a spell or an item, for Party's lists: a portrait (or their initial, in their table-rolls
    color), a short note ("item", "1/Long Rest", "×2 3/7") and their side panel for it."""
    c = r["c"]
    return {"name": c.name, "note": note, "url": url, "portrait": (r["sheet"] or {}).get("portrait") or "", "hue": c.id % 6,
            "label": f"{c.name} ({note})" if note else c.name}


def pooled_spells(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Everyone's spells for planning: each spell once, with who can cast it.
    `url` opens the first caster's side panel; each `who` opens that caster's."""
    spells: dict[str, dict] = {}
    for r in rows:
        if not r["sheet"]:
            continue
        for sp in r["sheet"]["spells"]:
            entry = spells.setdefault(sp["name"], {**sp, "who": [], "url": _panel_url(r["c"], sp["key"])})
            note = f"{sp['uses']['max']}/{sp['uses']['reset']}" if sp["uses"] and not sp["uses_slot"] else (
                "item" if sp["sources"] == ["Item"] else "")
            entry["who"].append(_who(r, note, _panel_url(r["c"], sp["key"])))
    groups, placed = [], set()
    for title, test in SPELL_GROUPS:
        found = [s for n, s in sorted(spells.items(), key=lambda kv: (kv[1]["level"], kv[0])) if n not in placed and test(s)]
        placed |= {s["name"] for s in found}
        if found:
            groups.append((title, found))
    rest = [s for n, s in sorted(spells.items(), key=lambda kv: (kv[1]["level"], kv[0])) if n not in placed]
    if rest:
        groups.append(("Everything else", rest))
    return groups


def pooled_items(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Magic items and consumables across the party, with who carries them."""
    items: dict[tuple, dict] = {}
    for r in rows:
        if not r["sheet"]:
            continue
        for it in r["sheet"]["inventory"]:
            if not (it["magic"] or it["battle"]):
                continue
            ch = it["charges"]
            if "healing" in it["name"].lower() or "regain" in it["summary"].lower()[:120]:
                group = "Healing"
            elif (ch and ch["reset"] == "Used up") or it["type"] in ("Potion", "Scroll"):
                group = "One use"
            elif it["attunement"] == "required":
                group = "Needs attunement"
            elif ch:
                group = "Charges"
            else:
                group = "Other magic items"
            entry = items.setdefault((group, it["name"]), {"name": it["name"], "summary": it["summary"], "who": [],
                                                           "url": _panel_url(r["c"], it["key"])})
            note = (f"×{it['quantity']}" if it["quantity"] > 1 else "") + (f" {ch['left']}/{ch['max']}" if ch and ch["reset"] != "Used up" else "")
            entry["who"].append(_who(r, note.strip(), _panel_url(r["c"], it["key"])))
    order = ["Healing", "One use", "Charges", "Needs attunement", "Other magic items"]
    return [(g, sorted((v for (gg, _), v in items.items() if gg == g), key=lambda v: v["name"])) for g in order
            if any(gg == g for gg, _ in items)]


def _holders(rows: list[dict], out: list[dict]) -> list[str]:
    """Who has it: the characters holding at least one of these, in the party's order (no chip that matches nothing)."""
    held = {n for x in out for n in x["f"]["who"]}
    return [r["c"].name for r in rows if r["c"].name in held]


def _spell_does(sp: dict) -> str:
    return f"heals {sp['healing']}" if sp["healing"] else sp["damage"] or ""


def party_spell_list(rows: list[dict]) -> dict:
    """Party › Spells in the shared list (DESIGN.md › Lists and filters): each spell once, under the group of what it does,
    filtered by that, who has it, Concentration, and (under More filters) level and casting time."""
    out = []
    for title, spells in pooled_spells(rows):
        for sp in spells:
            time = {"Action": "Action", "Bonus action": "Bonus", "Reaction": "Reaction"}.get(sp["casting_time"], "Longer")
            level = "Cantrip" if not sp["level"] else ordinal(sp["level"])
            out.append({**sp, "group": title, "level_label": level, "time": time, "does": _spell_does(sp),
                        "f": {"does": title.split(" (")[0], "who": [w["name"] for w in sp["who"]], "conc": "Conc." if sp["concentration"] else "No Conc.",
                              "level": level, "time": time}})
    levels = sorted({s["level"] for s in out})
    groups = [{"key": "does", "label": "What it does", "values": list(dict.fromkeys(s["f"]["does"] for s in out))},  # (Rituals, not its heading's note)
              {"key": "who", "label": "Who has it", "values": _holders(rows, out)},
              {"key": "conc", "label": "Concentration", "values": ["Conc.", "No Conc."]},
              {"key": "level", "label": "Level", "values": ["Cantrip" if not n else ordinal(n) for n in levels], "more": True},
              {"key": "time", "label": "Casting time", "values": [t for t in ("Action", "Bonus", "Reaction", "Longer") if any(s["time"] == t for s in out)], "more": True}]
    return {"rows": out, "groups": groups if out else []}


def party_item_list(rows: list[dict]) -> dict:
    """Party › Items in the shared list: magic items and consumables, grouped by what they are, filtered by that and who
    carries them."""
    out = [{**it, "group": title, "f": {"kind": title, "who": [w["name"] for w in it["who"]]}}
           for title, items in pooled_items(rows) for it in items]
    groups = [{"key": "kind", "label": "What it is", "values": list(dict.fromkeys(i["group"] for i in out))},
              {"key": "who", "label": "Who has it", "values": _holders(rows, out)}]
    return {"rows": out, "groups": groups if out else []}


def party_coins(rows: list[dict]) -> int:
    rate = {"pp": 10, "gp": 1, "ep": 0.5, "sp": 0.1, "cp": 0.01}
    purses = [p for r in rows if r["sheet"] for p in [r["sheet"]["currency"], *(b["coins"] for b in r["sheet"].get("bag_coins") or [])]]
    return int(sum(v * rate.get(k, 0) for p in purses for k, v in p.items()))  # (bags' coins too: feedback 47)


def granted_spells(sheet: dict) -> list[dict]:
    """Spells from species, feats, items and class features that aren't on a class's spell list."""
    classes = {b["class"] for b in sheet.get("spellbook") or []}
    in_books = {sp["name"] for b in sheet.get("spellbook") or [] for sp in b["spells"] if sp["state"] != "available"}
    return [sp for sp in sheet.get("spells") or [] if not (set(sp["sources"]) & classes) and sp["name"] not in in_books]


# ------------------------------------------------------------------ admin regrouping
# An admin can correct how askdnd groups anything from D&D Beyond. Corrections
# are stored by name (tool_corrections) so they apply to every character.

ITEM_GROUPS = [("battle", "Usable in battle"), ("equipped", "Equipped"), ("Weapons", "Weapons"), ("Armor", "Armor"),
               ("Magic items", "Magic items"), ("Potions and scrolls", "Potions and scrolls"), ("Gear", "Gear")]
OVERRIDE_CHOICES = {
    "hide": [("hide", "Hidden everywhere in askdnd")],
    "cost": [("Action", "Action"), ("Bonus action", "Bonus action"), ("Reaction", "Reaction"), ("No action", "No action needed"), ("Other", "Other (not on your turn)")],
    "battle": [("common", "Shown on Battle"), ("normal", "Only in See all"), ("hide", "Not on Battle")],
    "feature_group": [("use", "Things you can use"), ("passive", "Always on (in your numbers)")],
    "situ_group": [("situational", "Situational"), ("in_numbers", "Already in your numbers")],
    "item_group": ITEM_GROUPS,
}
# Rule-term underlines (set from the term's pop-up, not the regrouping box); here so Manage › Characters can label them.
TERM_CHOICES = {"underline": [("on", "Underlined"), ("off", "Not underlined")]}
FIELD_LABELS = {"hide": "Show in askdnd", "cost": "Section (what it costs)", "battle": "On Battle",
                "feature_group": "Features group", "situ_group": "Situational group", "item_group": "Inventory group",
                "underline": "Underlined in descriptions"}
ITEM_KINDS = {"Other Gear": "Gear", "Wondrous item": "Wondrous", "Rod": "Rod, staff or wand", "Staff": "Rod, staff or wand", "Wand": "Rod, staff or wand"}
# By D&D Beyond's item type, before its category: ammunition is "Other Gear" there (tool correction built in, 2026-10-23)
TYPE_GROUPS = {"Ammunition": "Weapons"}
CATEGORY_GROUPS = {"Weapon": "Weapons", "Armor": "Armor", "Wondrous item": "Magic items", "Ring": "Magic items", "Rod": "Magic items",
                   "Staff": "Magic items", "Wand": "Magic items", "Potion": "Potions and scrolls", "Scroll": "Potions and scrolls"}


def override_ref(x: dict, section: str | None = None) -> str:
    """The name-based handle an override is stored under (same for every character)."""
    section = section or x.get("section", "")
    name = x.get("base_name") or x.get("name") or ""
    prefix = {"features": "feature", "inventory": "item", "attacks": "attack", "spells": "spell", "actions": "action",
              "creatures": "form"}.get(section)
    return f"{prefix}:{name}" if prefix else x.get("key", "")


def fields_for(section: str, opt: dict | None) -> list[str]:
    """Which corrections make sense for one thing (every thing can be hidden)."""
    fields = ["hide"]
    if opt:
        fields += ["cost", "battle"]
    fields += {"features": ["feature_group"], "situational": ["situ_group"], "inventory": ["item_group"]}.get(section, [])
    return fields


def sheet_actions(sheet: dict, star: set | None = None) -> list[dict]:
    """Sheet's Actions tab: everything Battle offers except spells cast with an Action (those are on the Spells tab,
    like D&D Beyond), keeping attack cantrips and every Bonus Action and Reaction spell (feedback 42, Nov 7: Trah's
    Shield and Counterspell were on Battle but not here; tests/test_party_sheets.py keeps the two in step)."""
    return [o for o in options(sheet, star)
            if o["kind"] != "spell" or o.get("cost") in ("Bonus action", "Reaction") or (o["tags"] and o["tags"][0] == "cantrip" and o["hit"])]


TURN_COSTS = ("Action", "Bonus action", "Reaction")
OPTION_KINDS = (("attack", "Attacks"), ("feature", "Features"), ("spell", "Spells"), ("item", "Items"), ("rule", "Rules"))


def option_groups(opts: list[dict]) -> list[dict]:
    """Battle's "See all" and "+ Add" panels, bucketed (Brett, 2026-10-22: the lists grow every level):
    attacks, features, spells by level, items, then rules everyone has (Opportunity Attack…). Each group
    says its kind, for the panel's filter chips."""
    def kind(o):
        return "rule" if o["key"].startswith("rule:") and o["kind"] == "feature" else o["kind"]
    out = []
    for k, label in OPTION_KINDS:
        mine = [o for o in opts if kind(o) == k]
        if k == "spell":
            for lvl in sorted({o.get("level") or 0 for o in mine}):
                rows = [o for o in mine if (o.get("level") or 0) == lvl]
                out.append({"kind": k, "label": "Cantrips" if not lvl else f"{ordinal(lvl)}-level spells", "opts": rows})
        elif mine:
            out.append({"kind": k, "label": label, "opts": mine})
    return out
# A feature's own words, when no Battle option carries it (Wild Companion: "As a Magic action, …")
TURN_WORDS = (("Reaction", re.compile(r"\b(?:as|take|use your|uses? a) (?:a )?Reaction\b", re.I)),
              ("Bonus action", re.compile(r"\b(?:as|take|use) a Bonus Action\b", re.I)),
              ("Action", re.compile(r"\b(?:as|take) (?:a|an|the \w+) (?:Magic )?action\b|\bMagic action\b", re.I)))


def feature_rows(sheet: dict, opts: list[dict]) -> list[dict]:
    """Sheet › Features as list rows (_feature_list.html): what each feature is used as on a turn (from the
    options it gives, matched by name: "Wild Shape", "Wild Shape: Circle Forms"…) and its limited uses."""
    def mine(name: str, n: str) -> bool:
        return name == n or name.startswith((n + ":", n + " ("))
    out = []
    for f in sheet.get("features") or []:
        n = f["name"]
        costs = {o["cost"] for o in opts if mine(o["name"], n)}
        turn = [c for c in TURN_COSTS if c in costs]
        if not turn and f.get("use"):
            text = f"{f.get('summary') or ''} {f.get('text') or ''}"
            turn = [next((cost for cost, rx in TURN_WORDS if rx.search(text)), "Other")]
        turn = turn or ["Always on"]
        act = next((a for a in sheet.get("actions") or [] if mine(a["name"], n) and a.get("uses")), None)
        # (and the count it opens: Use one and Give one back, app/resources.py)
        out.append({**f, "turn": turn, "uses": act["uses"] if act else None, "uses_field": f"uses:{act['id']}" if act and act.get("id") else ""})
    return out


def apply_overrides(sheet: dict, overrides: dict[tuple[str, str], str]) -> dict:
    """Return the sheet with admin regrouping applied."""
    if not sheet:
        return sheet
    sheet = dict(sheet)
    get = lambda x, section, field: overrides.get((override_ref(x, section), field))
    for section in ("features", "situational", "inventory", "creatures", "attacks", "actions", "spells"):
        sheet[section] = [x for x in sheet.get(section) or [] if get(x, section, "hide") != "hide"]
    sheet["spellbook"] = [{**b, "spells": [x for x in b["spells"] if get(x, "spells", "hide") != "hide"]}
                          for b in sheet.get("spellbook") or []]
    sheet["features"] = [{**f, "use": f["use"] if get(f, "features", "feature_group") is None else get(f, "features", "feature_group") == "use"}
                         for f in sheet["features"]]
    sheet["situational"] = [{**x, "in_numbers": (x["kind"] == "bonus") if get(x, "situational", "situ_group") is None
                             else get(x, "situational", "situ_group") == "in_numbers"} for x in sheet["situational"]]
    items = []
    hb = getattr(overrides, "homebrew", None) or {}  # (a homebrew item that rolls is a Battle item: app/homebrew.py)
    rolls = {n for n, e in hb.items() if e.get("rolls")}
    for it in sheet["inventory"]:
        group = get(it, "inventory", "item_group") or (
            "battle" if it["battle"] or " ".join((it.get("name") or "").replace("’", "'").lower().split()) in rolls else "equipped" if it["equipped"]
            else TYPE_GROUPS.get(it.get("type") or "") or CATEGORY_GROUPS.get(it.get("category"), "Gear"))
        items.append({**it, "group": group, "battle": group == "battle",
                      # the Inventory list's filter values (_item_list.html)
                      "kind_label": "Custom" if it.get("custom") else ITEM_KINDS.get(it.get("category") or "", it.get("category") or "Gear"),
                      "use_labels": (["Usable in battle"] if group == "battle" else []) + (["Has uses"] if it.get("charges") else []),
                      "attune_label": {"attuned": "Attuned", "required": "Needs attunement"}.get(it.get("attunement") or "", "")})
    sheet["inventory"] = items
    sheet["_overrides"] = {f"{r}|{fld}": v for (r, fld), v in overrides.items()}
    sheet["_campaign_corrections"] = {f"{r}|{fld}" for r, fld in getattr(overrides, "campaign", ())}
    sheet["_homebrew"] = getattr(overrides, "homebrew", None) or {}  # (the campaign's homebrew items: app/homebrew.py)
    return sheet
