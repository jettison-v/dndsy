"""Advantage, marked the same way everywhere: a small "Adv" badge with the condition
on hover (the `adv` macro in templates/_char.html).

Each advantage is a dict: {"on": "save" | "check" | "initiative" | "attack" | "other",
"target": "con" | "all" | "Perception" | "melee"…, "when": the condition ("" = always),
"source": where it comes from, "from": "race" | "class" | "feat" | "item" | "form"…,
"text": the sentence shown on hover}.

They come from D&D Beyond's "advantage" modifiers (app/ddb_sheet.py, which carry their
restriction text and source: species traits, class features, feats, items) and, in
Wild Shape, from the Beast's own traits and attacks (Pack Tactics, Bloodied Fury…).
"""

import re

KEPT_SOURCES = ("class", "feat")  # Wild Shape keeps class features and feats (not species traits or items)
ABILITY = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}


def for_save(advs: list[dict], key: str) -> list[dict]:
    """Advantages on one saving throw ("con"); "all saves" ones are shown once, apart."""
    return [a for a in advs if a["on"] == "save" and a["target"] == key]


def all_saves(advs: list[dict]) -> list[dict]:
    return [a for a in advs if a["on"] == "save" and a["target"] == "all"]


def for_check(advs: list[dict], skill: str, ability: str) -> list[dict]:
    return [a for a in advs if a["on"] == "check" and a["target"] in (skill, ability, "all")]


def for_attack(advs: list[dict], melee: bool = True, spell: bool = False) -> list[dict]:
    kinds = {"all", "spell" if spell else "melee" if melee else "ranged"}
    return [a for a in advs if a["on"] == "attack" and a["target"] in kinds]


def initiative(advs: list[dict]) -> list[dict]:
    return [a for a in advs if a["on"] == "initiative"]


def carried(advs: list[dict], kept_items=()) -> list[dict]:
    """The ones that still apply in Wild Shape: class features and feats, plus items
    the DM lets the form keep. Species traits (Fey Ancestry…) don't carry over."""
    kept_items = set(kept_items)
    return [a for a in advs if a["from"] in KEPT_SOURCES or (a["from"] == "item" and a["source"] in kept_items)]


def dropped(advs: list[dict], kept_items=()) -> list[dict]:
    keep = carried(advs, kept_items)
    return [a for a in advs if a not in keep]


SENTENCE = re.compile(r"[^.]*\bAdvantage on ([^.]+)\.")
WITH_ADV = re.compile(r"\(with Advantage (if [^)]+)\)")
SKILL_CHECK = re.compile(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) \(([^)]+)\) checks?\s*(.*)", re.I)
SAVE_ON = re.compile(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) saving throws?\s*(.*)", re.I)


def _when(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(",")


def from_beast(beast: dict) -> list[dict]:
    """Advantages a form's own traits give it ("…has Advantage on an attack roll against a
    creature if…", "Advantage on Wisdom (Perception) checks that rely on smell"). Most have
    a condition, which the hover spells out."""
    out = []
    for t in beast.get("traits") or []:
        for m in SENTENCE.finditer(t["text"]):
            rest, a = m.group(1).strip(), None
            if sk := SKILL_CHECK.match(rest):
                a = {"on": "check", "target": sk.group(2).strip(), "when": _when(sk.group(3)), "what": f"{sk.group(2)} checks"}
            elif sv := SAVE_ON.match(rest):
                a = {"on": "save", "target": ABILITY[sv.group(1).lower()], "when": _when(sv.group(2)), "what": f"{sv.group(1).title()} saving throws"}
            elif at := re.search(r"\b(?:an |the )?(?:(melee|ranged) )?attack rolls?\b", rest, re.I):
                kind = (at.group(1) or "all").lower()
                lead = re.match(r"\s*(While [^,]+),", m.group(0))  # "While Bloodied, the boar has Advantage on attack rolls."
                when = _when(rest[at.end():]) or ("w" + lead.group(1)[1:] if lead else "")
                a = {"on": "attack", "target": kind, "when": when, "what": f"{kind + ' ' if kind != 'all' else ''}attack rolls"}
            if a:
                what = a.pop("what")
                out.append({**a, "source": t["name"], "from": "form",
                            "text": f"Advantage on {what}{' ' + a['when'] if a['when'] else ''} · {t['name']} (the form's trait)"})
    return out


def in_attack(name: str, text: str) -> list[dict]:
    """An attack whose own text gives it Advantage ("+9 (with Advantage if the target
    doesn't have all its Hit Points)")."""
    m = WITH_ADV.search(text)
    return [{"on": "attack", "target": "this", "when": m.group(1), "source": name, "from": "form",
             "text": f"Advantage {m.group(1)} · {name} (the form's attack)"}] if m else []


def title(advs: list[dict]) -> str:
    """The hover text for a badge: every source on its own line."""
    return "\n".join(a["text"] for a in advs)


def conditional(advs: list[dict]) -> bool:
    """True when every advantage here needs something (the badge is drawn outlined)."""
    return all(a.get("when") for a in advs)
