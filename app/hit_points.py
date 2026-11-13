"""Hit points with the working, aware of Wild Shape (roadmap step 5.4, docs/mockups/hp-window.html; decided 2026-10-28).

A hit starts where it really starts: the DM's damage roll for a monster (heard from D&D Beyond's game log,
app/ddb_bridge.py heard_in_game) or a party member's healing roll arrives in Table rolls with its amount and type, and
**Apply to Cole** there opens Cole's hit points window filled in. Without a roll (a trap, a fall), clicking Hit points
opens the same window to type a number. askdnd shows its working by the 2024 rules (`work`), then makes the end result
on the character's D&D Beyond sheet through the bridge, like every other change (only while the sheet can be reached).

- **Which rolls:** damage the DM rolled (a monster's) hits the party; healing and Temporary Hit Points anyone rolled.
  **Who applies:** normally the character's own player; the DM can too, for anyone at the table. A roll is applied
  once to each character (a Fireball can hit several); the applied hit is a follow-up row of the roll (kind "applied"),
  so every open Table rolls shows "Cole took 11" as it shows a reroll.
- **The order** (2024 Player's Handbook, Rules Glossary): Immunity makes it 0; otherwise Resistance halves (rounded
  down), then Vulnerability doubles; each counts once whatever its sources. Temporary Hit Points take it first, then
  your own. In a Wild Shape form the form's resistances count with your own (a species trait doesn't carry over: the
  DM rules), and running out of Temporary Hit Points doesn't end the form. Any defense can be crossed out for a ruling.
- **Concentration:** whenever you take damage, a Constitution save, DC 10 or half the damage taken (up to 30). It's the
  player's to roll (Brett, 2026-10-28: "creates suspense"): the reminder and its roll button show on their Table rolls,
  also when the DM applied the hit.
- **At 0** (app/death_saves.py; Brett, 2026-10-29): dropping to 0 starts Unconscious on the sheet; damage at 0 marks a
  death save failure (two on a critical hit); healing from 0 ends Unconscious and clears the marks. Each is a step that
  can be crossed out for a ruling. Damage left over at least the Hit Point maximum is massive damage, pointed out for
  the DM, who rules (inform, don't advise).
- Healing restores Hit Points, never Temporary ones. Temporary Hit Points don't add up: keep what you have or take the
  new ones (askdnd starts on the higher).
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import characters as chars
from app import ddb_bridge, death_saves, picks, realtime, rules_data, web
from app import wild_shape as ws
from app.auth import current_user, is_admin, is_dm
from app.db import get_db
from app.ddb_sheet import DAMAGE_TYPES
from app.models import Character, TableRoll
from app.templating import templates

router = APIRouter()
MODES = ("damage", "heal", "temp")
TYPES = tuple(sorted(DAMAGE_TYPES))
MAX = 999
KINDS = (("immunity", "Immune to"), ("resistance", "Resistant to"), ("vulnerability", "Vulnerable to"))
HIT = re.compile(r"(\d+d\d+)?(?:\s*[+−-]\s*\d+)?\)?\s*(Acid|Bludgeoning|Cold|Fire|Force|Lightning|Necrotic|Piercing|Poison|"
                 r"Psychic|Radiant|Slashing|Thunder) damage", re.I)


# ------------------------------------------------------------------ a monster's attack: its damage type


def attack_type(db: Session | None, campaign_id: int | None, monster: str, action: str, formula: str = "") -> tuple[str, str]:
    """(damage type, where it's from) for a monster's attack by name. D&D Beyond's roll doesn't carry the type, so it
    comes from the campaign's rules data (its own, its books', the SRD's) and says so: ("bludgeoning", "SRD 5.2.1") for
    an Ogre's Greatclub, ("", "") when the monster or the attack isn't there. With several types in the attack, the
    one whose dice match the roll's (a Bite's 2d10 piercing plus 2d6 fire)."""
    m = rules_data.find("monster", monster, db, campaign_id) if monster else None
    if not m:
        return "", ""
    want = action.strip().lower()
    for group in ("actions", "bonus_actions", "reactions", "legendary_actions"):
        for a in m.get(group) or []:
            name = (a.get("name") or "").lower()
            if name == want or name.startswith(want + " ("):
                hits = HIT.findall(a.get("text") or "")
                dice = (re.match(r"\d+d\d+", formula or "") or [""])[0]
                kind = next((k for d, k in hits if dice and d == dice), hits[0][1] if hits else "")
                return kind.lower(), m.get("source", "") if kind else ""
    return "", ""


# ------------------------------------------------------------------ the working


def _types_in(text: str) -> list[str]:
    return [t for t in TYPES if re.search(rf"\b{t}\b", text or "", re.I)]


def defenses(summary: dict, form: dict | None) -> list[dict]:
    """What changes damage for this character now: [{"key", "kind", "type", "from"}], the form's first. Each key is
    what a crossed-out step is remembered by."""
    out = []
    beast = (form or {}).get("beast") or {}
    for kind, field in (("immunity", "immunities"), ("resistance", "resistances"), ("vulnerability", "vulnerabilities")):
        for t in _types_in(", ".join(beast.get(field) or [])):
            out.append({"key": f"form:{kind}:{t}", "kind": kind, "type": t, "from": f"the {beast['name']}"})
    labels = ((summary or {}).get("proficiencies") or {}).get("defenses") or {}
    for kind, label in (("immunity", "Immunities"), ("resistance", "Resistances"), ("vulnerability", "Vulnerabilities")):
        for t in _types_in(", ".join(labels.get(label) or [])):
            if not any(d["kind"] == kind and d["type"] == t for d in out):
                out.append({"key": f"own:{kind}:{t}", "kind": kind, "type": t,
                            "from": "your sheet" + (" (a species trait doesn't carry over into a form)" if form else "")})
    return out


def con_save(summary: dict, form: dict | None) -> dict:
    """The Constitution save Concentration asks for: {"bonus", "label", "adv"} (in a form, the form's)."""
    for s in ((form or {}).get("saves") or []) + ((summary or {}).get("saves") or []):
        if (s.get("key") or (s.get("short") or "").lower()) == "con":
            adv = s.get("adv") or []
            return {"bonus": s["bonus"], "label": s["label"], "adv": bool(adv or s.get("advantage")),
                    "why": "; ".join(a.get("text", "") for a in adv if isinstance(a, dict)) or "; ".join(s.get("notes") or [])}
    return {"bonus": 0, "label": "+0", "adv": False, "why": ""}


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{-n}"


def work(hp: dict, mode: str, parts: list[dict], defs: list[dict], off: set[str], form: dict | None = None,
         concentration: str = "", save: dict | None = None, temp_take: bool | None = None, death: dict | None = None,
         crit: bool = False) -> dict:
    """The 2024 rules applied to one hit, heal or gift of Temporary Hit Points, as steps the window lists, and its end
    result. `hp` is {"current", "max", "temp"}; `parts` [{"amount", "type"}] (a hit can be several types); `off` the
    keys of steps crossed out (a ruling: a defense, "death", "unconscious"); `death` the marks at 0 (death_saves.state);
    `crit` a critical hit (two failures at 0)."""
    cur, top, temp = int(hp.get("current") or 0), int(hp.get("max") or 0), int(hp.get("temp") or 0)
    out = {"mode": mode, "hp_before": cur, "max": top, "temp_before": temp, "parts": [], "steps": [], "conc": None,
           "down": False, "massive": 0, "taken": 0, "hp_after": cur, "temp_after": temp, "amount": 0,
           "unconscious": False, "up": False, "death_fail": 0}
    if mode == "heal":
        n = sum(max(0, int(p.get("amount") or 0)) for p in parts)
        out.update(amount=n, hp_after=min(top, cur + n))
        out["steps"].append({"title": "Healing", "value": f"+{out['hp_after'] - cur}", "why": f"Restores your own Hit Points, up to {top}; "
                             "never Temporary ones." + (f" {n - (out['hp_after'] - cur)} more would go past your maximum." if cur + n > top else "")})
        if not n:
            out["empty"] = True  # (nothing typed yet: the button waits, nothing to say)
        elif out["hp_after"] == cur:  # (feedback 62: a disabled Heal 0 looked broken; say why nothing happens)
            out["nothing"] = f"Already at full Hit Points ({cur} of {top}): this healing changes nothing."
        if cur == 0 and out["hp_after"] > 0:
            out["up"] = "unconscious" not in off
            out["steps"].append({"key": "unconscious", "off": not out["up"], "title": "Back from 0 Hit Points", "value": "Unconscious ends",
                                 "why": "Healing from 0 ends Unconscious and clears the death save marks."})
        return out
    if mode == "temp":
        n = max(0, sum(int(p.get("amount") or 0) for p in parts))
        take = (n > temp) if temp_take is None else temp_take
        out.update(amount=n, temp_after=n if take else temp, take=take)
        if not n:
            out["empty"] = True
        elif out["temp_after"] == temp:
            out["nothing"] = (f"Keeping the {temp} Temporary Hit Points already there: nothing changes. Choose Take {n} to replace them." if temp
                              else f"Keeping none: nothing changes. Choose Take {n} to give them.")
        out["steps"].append({"title": "Temporary Hit Points don't add up", "value": f"{'take' if take else 'keep'} {n if take else temp}",
                             "why": f"Keep the {temp} you have or take the new {n}; askdnd starts on the higher. You choose.", "choose": True})
        return out
    taken = 0
    for p in parts:
        n, t = max(0, int(p.get("amount") or 0)), (p.get("type") or "").lower()
        row = {"amount": n, "type": t, "steps": []}
        order = [k for k, _ in KINDS]
        mine = sorted((d for d in defs if d["type"] == t), key=lambda d: order.index(d["kind"])) if t else []
        imm = next((d for d in mine if d["kind"] == "immunity" and d["key"] not in off), None)
        for d in mine:
            crossed = d["key"] in off
            if d["kind"] == "immunity":
                after = 0 if not crossed else n
            elif imm:
                continue  # (immune: nothing left to halve or double)
            elif d["kind"] == "resistance":
                after = n // 2 if not crossed else n
            else:
                after = n * 2 if not crossed else n
            word = dict(KINDS)[d["kind"]]
            row["steps"].append({"key": d["key"], "title": f"{word} {t}", "value": f"{n} → {after}", "why": f"From {d['from']}.", "off": crossed})
            if not crossed:
                n = after
        row["after"] = n
        taken += n
        out["parts"].append(row)
    soak = min(temp, taken)
    own = taken - soak
    out.update(amount=taken, taken=taken, temp_after=temp - soak, hp_after=max(0, cur - own))
    if not sum(max(0, int(p.get("amount") or 0)) for p in parts):  # (one that a defense takes whole is still applied: it was a hit)
        out["empty"] = True
    if temp:
        out["steps"].append({"title": "Temporary Hit Points first", "value": f"{temp} → {temp - soak}",
                             "why": f"They take {soak}; {'the rest, ' + str(own) + ', comes off' if own else 'nothing comes off'} your own Hit Points."})
    out["steps"].append({"title": "Your Hit Points", "value": f"{cur} → {out['hp_after']}", "why": f"Of {top}."})
    if form and temp and soak == temp and own:
        out["steps"].append({"title": "Out of Temporary Hit Points", "value": f"still a {form['beast']['name']}",
                             "why": "In the 2024 rules the form doesn't end: the damage comes off your own Hit Points. It ends if "
                                    "you're Incapacitated, die, or choose to."})
    if concentration and taken:
        dc = min(30, max(10, taken // 2))
        out["conc"] = {"spell": concentration, "dc": dc, **(save or con_save({}, None))}
        out["steps"].append({"title": f"Concentration: {concentration}", "value": f"DC {dc}",
                             "why": f"A Constitution save, DC 10 or half the damage taken (up to 30). Yours to roll ({out['conc']['label']}"
                                    f"{', Advantage' if out['conc']['adv'] else ''}): it shows in your Table rolls."})
    if out["hp_after"] == 0 and own:
        left = own - cur
        out["massive"] = left if top and left >= top else 0
        if cur:  # dropped to 0
            out["down"] = True
            out["unconscious"] = "unconscious" not in off
            out["steps"].append({"key": "unconscious", "off": not out["unconscious"], "title": "At 0 Hit Points", "value": "Unconscious",
                                 "why": "Starts Unconscious on your sheet. Death saving throws start on your next turn."})
        elif not out["massive"]:  # hit at 0: a failure, a critical hit two; while Stable, the saves start over
            st = death or {"success": 0, "fail": 0, "stable": False}
            n, had = (2 if crit else 1), (0 if st.get("stable") else st.get("fail", 0))
            out["death_fail"] = 0 if "death" in off else n
            out["steps"].append({"key": "death", "off": not out["death_fail"], "title": "Death saves", "value": f"+{n} failure{'s' if n > 1 else ''}",
                                 "why": ("Damage at 0 Hit Points is a failure; a critical hit, two. " + ("No longer Stable: the saves start over. " if st.get("stable") else "")
                                         + f"{had} before, so this makes {min(3, had + n)}." + (" Three failures: the DM rules what happens." if had + n >= 3 else ""))})
        if out["massive"]:
            out["steps"].append({"title": "Massive damage", "value": f"{left} ≥ {top}", "mass": True,
                                 "why": f"The {left} left over is at least the Hit Point maximum, which kills outright by the rules. The DM rules; "
                                        "askdnd marks nothing for it."})
    return out


# ------------------------------------------------------------------ who, and what a roll brings


def can_apply(db: Session, user: dict | None, character: Character) -> bool:
    """Normally the character's own player; the DM can too, for anyone at the table (an admin as well)."""
    return picks.can_edit(db, user, character) or is_dm(user, character.campaign_id) or is_admin(user)


def _hp_now(c: Character) -> dict:
    """Where a character's Hit Points stand, for Apply to's list (feedback 62: who's hurt, before choosing)."""
    hp = (chars.character_summary(c) or {}).get("hit_points") or {}
    if not hp.get("max"):
        return {}
    return {"hp": f"{hp.get('current', 0)}/{hp['max']}", "full": hp.get("current", 0) >= hp["max"]}


def targets(db: Session, user: dict | None, campaign_id: int) -> list[Character]:
    """Who this person may apply a roll to in this campaign: their own characters, or everyone's for the DM. Only
    characters the bridge reaches (askdnd changes hit points only on D&D Beyond)."""
    rows = db.scalars(select(Character).where(Character.copy_of_id.is_(None)).order_by(Character.name)).all()
    return [c for c in rows if c.campaign_id == campaign_id and ddb_bridge.on_for(db, c) and can_apply(db, user, c)]


def from_roll(db: Session, roll: TableRoll | None) -> tuple[str, list[dict], str]:
    """(mode, parts, where it's from) for a Table rolls entry: its damage (each type on its own) or its healing."""
    if not roll:
        return "", [], ""
    dmg = db.scalar(select(TableRoll).where(TableRoll.parent_id == roll.id, TableRoll.kind == "damage")) if roll.kind == "attack" else None
    src = dmg or roll
    who = roll.character.name if roll.character else roll.who or "Someone"
    if src.kind == "damage":
        parts = [{"amount": x.get("total", 0), "type": x.get("kind") or "", "type_from": x.get("kind_from") or ""}
                 for x in src.parts or [] if x.get("total") is not None]
        return "damage", parts or [{"amount": src.total, "type": ""}], f"{who} · {roll.label}"
    if src.kind in ("heal", "temp"):
        return ("heal" if src.kind == "heal" else "temp"), [{"amount": src.total, "type": ""}], f"{who} · {roll.label}"
    return "", [], ""


def applied(db: Session, roll: TableRoll) -> dict[int, TableRoll]:
    return {r.character_id: r for r in db.scalars(select(TableRoll).where(TableRoll.parent_id == roll.id, TableRoll.kind == "applied"))}


def _context(db: Session, ch: Character) -> tuple[dict, dict | None]:
    summary = ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}  # a hit on its way counts already
    form = None
    if ch.wild_shape and summary:
        beasts = ws.beasts(db, ch.campaign_id)
        beast = ws.beast_for(summary, ch.wild_shape, beasts)
        form = ws.shaped(summary, beast, keep=ws.chosen_keep(summary, ch.wild_shape_keep)) if beast else None
    return summary, form


def working(db: Session, ch: Character, mode: str, parts: list[dict], off: set[str] = frozenset(), temp_take: bool | None = None, crit: bool = False) -> dict:
    summary, form = _context(db, ch)
    hp = summary.get("hit_points") or {}
    defs = defenses(summary, form)
    conc = (ch.concentration or {}).get("spell", "")
    w = work(hp, mode, parts, defs, off, form, conc, con_save(summary, form), temp_take, death_saves.state(summary), crit)
    # Damage types: the ones this character resists (or is immune or vulnerable to) first, then the rest
    first = [t for t in TYPES if any(d["type"] == t for d in defs)]
    return {**w, "defs": defs, "types": first + [t for t in TYPES if t not in first], "first": first, "form": form}


def _read(form) -> tuple[str, list[dict], set[str], bool | None]:
    """(mode, parts, crossed-out keys, take): what the window's form says."""
    mode = form.get("mode") if form.get("mode") in MODES else "damage"
    amounts, types = form.getlist("amount"), form.getlist("type")
    parts = []
    for i, a in enumerate(amounts):
        try:
            n = max(0, min(MAX, int(a or 0)))
        except ValueError:
            n = 0
        t = (types[i] if i < len(types) else "").lower()
        parts.append({"amount": n, "type": t if t in DAMAGE_TYPES else ""})
    # Keep or take is a choice for the amount it was made on (`take_for`): a new amount starts again on the higher (Nov 2:
    # the window opened on "Keep 0" with no amount yet, and typing one left it there, so Set stayed at 0)
    take = form.get("take") if form.get("take_for") == str(sum(p["amount"] for p in parts)) else None
    return mode, parts or [{"amount": 0, "type": ""}], set(form.getlist("off")), (None if take in (None, "") else take == "1")


def _crit(roll: TableRoll | None) -> bool:
    """A critical hit: the attack the damage came from rolled a natural 20 (a damage roll of its own says crit)."""
    return bool(roll and (roll.crit or (roll.kind == "attack" and roll.kept == 20)))


def _roll(db: Session, roll_id: int, ch: Character) -> TableRoll | None:
    r = db.get(TableRoll, roll_id) if roll_id else None
    return r if r and r.parent_id is None and r.campaign_id == ch.campaign_id else None


def _guard(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or not ch or not ddb_bridge.on_for(db, ch) or not can_apply(db, user, ch):
        raise HTTPException(404)
    return ch, user


def _page(request: Request, db: Session, ch: Character, template: str, mode: str, parts: list[dict], off: set[str],
          take: bool | None, roll: TableRoll | None, source: str, crit: bool = False):
    w = working(db, ch, mode, parts, off, take, crit)
    done = applied(db, roll).get(ch.id) if roll else None
    return templates.TemplateResponse(request, template, {
        "c": ch, "w": w, "mode": mode, "parts": parts, "off": off, "roll": roll, "source": source, "done": done, "crit": crit,
        "reachable": ddb_bridge.reachable(ch), "hp": (chars.character_summary(ch) or {}).get("hit_points") or {}})


@router.get("/characters/{character_id:int}/hp")
def window(request: Request, character_id: int, roll: int = 0, mode: str = "damage", quick: int = 0, db: Session = Depends(get_db)):
    """The hit points window, filled in from a Table rolls entry (Apply to …) or empty (Hit points itself); `quick`: the
    small one from − and + on Battle's tile."""
    ch, _ = _guard(db, request, character_id)
    r = _roll(db, roll, ch)
    m, parts, source = from_roll(db, r)
    if not m:
        m, parts = (mode if mode in MODES else "damage"), [{"amount": 0, "type": ""}]
    return _page(request, db, ch, "_hp_quick.html" if quick else "_hp_window.html", m, parts, set(), None, r, source, _crit(r))


def make(db: Session, ch: Character, user: dict, r: TableRoll | None, mode: str, w: dict) -> str:
    """Make the working `w`: the end result goes to D&D Beyond through the bridge, and a roll it came from says so in
    Table rolls. What's said. Not committed."""
    if mode == "damage" and w["taken"]:
        text = f"{ch.name} took {w['taken']}"
        ddb_bridge.add(db, ch, "hp", {"amount": -w["taken"]}, text)
        if w["death_fail"]:
            death_saves.hit(db, ch, w["death_fail"], f"{ch.name}: hit at 0 Hit Points, {w['death_fail']} death save failure{'s' if w['death_fail'] > 1 else ''}")
            text += f" at 0 Hit Points: {'two death save failures' if w['death_fail'] > 1 else 'a death save failure'}"
        if w["unconscious"]:
            death_saves.down(db, ch)
        if w["massive"]:
            text += ": massive damage, the DM rules"
            death_saves.tell(db, ch, "massive", f"massive damage ({w['massive']} left over, at least the maximum of {w['max']}): your ruling")
        elif w["down"]:
            text += ": down to 0, Unconscious" if w["unconscious"] else ": down to 0"
            death_saves.tell(db, ch, "down", "down to 0 Hit Points" + (", Unconscious" if w["unconscious"] else ""))
    elif mode == "heal" and w["amount"]:
        text = f"{ch.name} healed {w['hp_after'] - w['hp_before']}"
        ddb_bridge.add(db, ch, "hp", {"amount": w["amount"]}, text)
        if w["up"]:
            death_saves.up(db, ch, 0, text)
            text += ": back up from 0"
    elif mode == "temp" and w["temp_after"] != w["temp_before"]:
        text = f"{ch.name}: {w['temp_after']} Temporary Hit Points"
        ddb_bridge.add(db, ch, "temp", {"value": w["temp_after"]}, text)
    else:
        text = f"Nothing to change for {ch.name}" if mode != "damage" else f"{ch.name} took no damage"
    if r:
        me = picks.user_row(db, user)
        db.add(TableRoll(campaign_id=r.campaign_id, parent_id=r.id, character_id=ch.id, user_id=me.id if me else None,
                         who=(me.name or me.email)[:80] if me else "", label=text[:120], kind="applied", formula="", dice=[],
                         total=w["taken"] if mode == "damage" else w["amount"], visibility=r.visibility,
                         spec={"mode": mode, "conc": w["conc"]}))
        realtime.announce(db, r.campaign_id, "rolls")
    return text


@router.post("/characters/{character_id:int}/hp/work")
def rework(request: Request, character_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """The working again, after a number, a type, a tab or a crossed-out step changed (the window's own form)."""
    ch, _ = _guard(db, request, character_id)
    mode, parts, off, take = _read(form)
    r = _roll(db, int(form.get("roll") or 0), ch)
    return _page(request, db, ch, "_hp_working.html", mode, parts, off, take, r, form.get("source", "")[:120], form.get("crit") == "1")


@router.post("/characters/{character_id:int}/hp/apply")
def apply(request: Request, character_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Make it: the end result goes to D&D Beyond through the bridge (only while the sheet can be reached), and a roll
    it came from says so in Table rolls, once for this character."""
    ch, user = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    mode, parts, off, take = _read(form)
    r = _roll(db, int(form.get("roll") or 0), ch)
    if r:  # the roll's row is held until this commits, so two presses at once apply it once (the outside review's W1)
        db.execute(select(TableRoll.id).where(TableRoll.id == r.id).with_for_update())
    if r and applied(db, r).get(ch.id):
        raise HTTPException(409, f"This roll was already applied to {ch.name}.")
    w = working(db, ch, mode, parts, off, take, form.get("crit") == "1")
    text = make(db, ch, user, r, mode, w)
    db.commit()
    toast = text + (f". Concentration ({w['conc']['spell']}): a Con save, DC {w['conc']['dc']}" if w["conc"] else "")
    out = HTMLResponse("")
    out.headers["HX-Trigger"] = web.changed(ch, toast=toast, closePanel=True, deliver=True)
    return out


def apply_info(db: Session, user: dict | None, roots: list[TableRoll], kids: list[TableRoll]) -> dict[int, dict]:
    """For Table rolls: what each damage or healing roll offers this viewer (Apply to whom) and who it was applied to,
    with the Concentration save each applied hit asks of the viewer's own character."""
    from app.table_rolls import shown  # (table_rolls lists these; the two import each other's pieces)

    if not user or not roots:
        return {}
    me = picks.user_row(db, user)
    by_root: dict[int, list[TableRoll]] = {}
    for k in kids:
        by_root.setdefault(k.parent_id, []).append(k)
    mine: dict[int, list[Character]] = {}
    out = {}
    for r in roots:
        kinds = {k.kind for k in by_root.get(r.id, [])}
        # Damage the DM rolled (a monster's, or the DM's own dice) hits the party; a character's own damage goes to
        # enemies. Healing and Temporary Hit Points come from anyone (Big C's Cure Wounds, your own Second Wind)
        hurt = r.kind == "damage" or (r.kind == "attack" and "damage" in kinds)
        hit = (hurt and not r.character_id) or r.kind in ("heal", "temp")
        if not hit or shown(r, me.id if me else None, is_dm(user, r.campaign_id)) != "full":
            continue
        if r.campaign_id not in mine:
            mine[r.campaign_id] = targets(db, user, r.campaign_id)
        done = {k.character_id: k for k in by_root.get(r.id, []) if k.kind == "applied"}
        conc = []
        for cid, k in done.items():
            c = (k.spec or {}).get("conc")
            ch = db.get(Character, cid)
            if c and ch and picks.can_edit(db, user, ch):
                conc.append({"cid": cid, "name": ch.name, **c})
        only = r.character_id if (r.detail or {}).get("self") else None  # (Second Wind, a Hit Point Die: the roller's own)
        out[r.id] = {"to": [{"id": c.id, "name": c.name, **_hp_now(c)} for c in mine[r.campaign_id] if c.id not in done and (only is None or c.id == only)],
                     "done": [k.label for k in done.values()], "conc": conc, "dm": is_dm(user, r.campaign_id)}
    return out
