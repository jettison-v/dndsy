"""Check your numbers (Show the Math, option E; Brett chose it Nov 12, docs/mockups/show-the-math/): every attack, spell,
item, Wild Shape form, check and save a character rolls, on one large window, with how askdnd's number adds up and
what it was checked against. For a player's first session, or the DM looking over a new character: one look instead of
rolling everything. It's the coverage report askdnd keeps for its own tests (app/roll_plan.py, scripts/roll_coverage.py),
written for people. Opened from the character's ⓘ line (`/characters/<id>/numbers`)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import roll_math
from app import wild_shape as ws
from app.db import get_db
from app.templating import templates

router = APIRouter()

# What each row was checked against (its status), most trusted first; `kind` styles its tag
VERDICTS = {
    "dm": ("Your DM's ruling", "dm", "A correction for this campaign (Manage › House rules)."),
    "rules": ("2024 rules", "ok", "askdnd's rules for it, checked against the 2024 books; the sheet gives the numbers."),
    "sheet": ("The sheet", "ok", "The D&D Beyond sheet's own numbers, added up by askdnd."),
    "unchecked": ("Not checked yet", "warn", "From D&D Beyond's data or read from its words: askdnd hasn't checked it against the 2024 rules."),
    "gap": ("Something's missing", "bad", ""),
    "none": ("Nothing to roll", "faint", ""),
}


def _verdict(plan: dict, math: dict) -> tuple[str, str]:
    """A row's status and why, from its plan (app/roll_plan.py `_judge`): a gap first, then a correction, then what the
    rest was checked against."""
    srcs = set((plan.get("sources") or {}).values()) | ({math["dice"]} if math.get("dice") else set())
    srcs |= {r["src"] for k in ("bonus", "dc", "dmg") for r in math.get(k) or []}
    if plan.get("status") == "gap":
        return "gap", "; ".join(plan.get("gaps") or [])
    if "correction" in srcs or "dm" in srcs:
        return "dm", ""
    if plan.get("status") == "unchecked" or srcs & {"ddb", "text", "read"}:
        return "unchecked", ""
    if plan.get("status") == "no roll" and not math:
        return "none", ""
    if srcs & {"checked", "rule", "rules"}:
        return "rules", "; ".join(plan.get("notes") or [])
    return "sheet", ""


def _dice_text(o: dict) -> tuple[str, str]:
    """What it rolls besides the d20, at its own level: the recipe's text (and how the dice grow), else the sheet's."""
    for key in ("hit", "other"):
        r = (o.get("rolls") or {}).get(key) or {}
        effs = r.get("effects") or []
        if effs:
            at = effs[0]["at"].get(str(r.get("base"))) or next((v for v in effs[0]["at"].values() if v), None)
            if at:
                grows = len(r.get("levels") or []) > 1
                return at["text"], (f"more when cast with a higher slot (up to level {r['levels'][-1]})" if grows else at.get("why", ""))
    return str(o.get("dice") or ""), ""


def option_rows(sheet: dict) -> list[dict]:
    """Battle's options that roll something, each with askdnd's numbers, their parts and what they were checked against."""
    from app.character_views import options
    from app.roll_plan import plan as plan_of

    out = []
    for o in options(sheet, set()):
        p = o.get("plan") or plan_of(sheet, o)
        m = o.get("math") or {}
        dice, grows = _dice_text(o)
        hit = str(o.get("hit") or "")
        if not hit and not dice:
            continue
        verdict, why = _verdict(p, m)
        bonus = (p.get("attack") or {}).get("bonus")
        save = p.get("save") or {}
        same = next((r for r in out if r["name"] == o["name"] and r["dice"] == dice and r["bonus"] == bonus and r["save_dc"] == save.get("dc")), None)
        if same:  # (the Unarmed Strike as an Action and a Bonus Action: one row, both costs)
            same["cost"] += f" · {o.get('cost', '')}"
            continue
        out.append({"bonus": bonus, "save_dc": save.get("dc"),
            "name": o["name"], "cost": o.get("cost", ""), "kind": o.get("kind", ""),
            "to_hit": {"text": f"{bonus:+d}".replace("-", "−"), "m": {"rows": m.get("bonus"), "total": f"{bonus:+d}"}} if bonus is not None else None,
            "dc": {"text": f"DC {save['dc']} {save.get('ability', '')}".strip(), "m": {"rows": m.get("dc"), "total": save["dc"]}} if save.get("dc") else None,
            "dice": dice, "grows": grows, "dmg": m.get("dmg") or [],
            "verdict": verdict, "why": why, "house": [r.get("text", "") for r in (o.get("recipe") or {}).get("house_rules") or []],
            "group": "Spells" if o.get("kind") == "spell" else "Items" if o.get("kind") == "item" else "Attacks and features",
        })
    return out


def d20_rows(sheet: dict) -> list[dict]:
    """Checks, saves and Initiative: the sheet's own numbers and their parts."""
    out = []
    for a in sheet.get("abilities") or []:
        sv = next((x for x in sheet.get("saves") or [] if x["short"] == a["short"]), None)
        check = a.get("check_label") or a["label"]
        out.append({"name": f"{a['name']} check", "label": check, "group": a["name"],
                    "rows": roll_math.checked(roll_math.rows(a.get("check_parts") or [(f"{a['name']} modifier", a["label"])]), check)})
        if sv:
            out.append({"name": f"{a['short']} save", "label": sv["label"], "rows": roll_math.checked(roll_math.rows(sv.get("parts")), sv["bonus"]), "group": a["name"]})
        for sk in sheet.get("skills") or []:
            if sk.get("ability") == a["short"]:
                out.append({"name": sk["name"], "label": sk["label"], "rows": roll_math.checked(roll_math.rows(sk.get("parts")), sk["bonus"]), "group": a["name"]})
    if sheet.get("initiative"):
        out.append({"name": "Initiative", "label": sheet["initiative"], "rows": roll_math.checked(roll_math.rows(sheet.get("initiative_parts")), sheet["initiative"]),
                    "group": "Initiative"})
    return out


def form_rows(sheet: dict, keep, beasts) -> list[dict]:
    """Each Wild Shape form the character knows: its AC, Temporary Hit Points, Initiative and attacks, as askdnd works
    them out (app/wild_shape.py `shaped`), with what changed each."""
    out = []
    for kf in ws.known_forms(sheet, beasts):
        beast = ws.beast_for(sheet, kf["name"], beasts)
        if not beast:
            continue
        f = ws.shaped(sheet, beast, lite=True, keep=keep)
        attacks = [o for col in f["columns"].values() for o in col["all"] if o.get("source") == "form" and o.get("hit") and str(o["hit"])[0] in "+-−"]
        out.append({"name": beast["name"], "ac": f["ac"], "ac_why": f["ac_says"], "temp": f["temp_hp"], "temp_why": f["temp_why"],
                    "initiative": f["initiative"], "init_rows": roll_math.checked(roll_math.rows(f["initiative_parts"]), f["initiative"]),
                    "attacks": [{"name": o["name"], "hit": o["hit"], "m": {"rows": (o.get("math") or {}).get("bonus"), "total": o["hit"]},
                                 "meta": o.get("meta", "")} for o in attacks]})
    return out


@router.get("/characters/{character_id:int}/numbers")
def numbers(request: Request, character_id: int, db: Session = Depends(get_db)):
    """The large window: Check <character>'s numbers."""
    from app.character_pages import _load, _view

    user, ch, stop = _load(request, db, character_id)
    if stop:
        return stop
    ctx = _view(db, ch, user)
    s = ctx["sheet"]
    if not s:
        return HTMLResponse("", status_code=404)
    rows = option_rows(s)
    forms = form_rows(s, ws.chosen_keep(s, ch.wild_shape_keep), ctx["beasts"]) if ctx.get("druid") else []
    groups = [(g, [r for r in rows if r["group"] == g]) for g in ("Attacks and features", "Spells", "Items")]
    return templates.TemplateResponse(request, "_check_numbers.html", {
        **ctx, "groups": [(g, rs) for g, rs in groups if rs], "d20": d20_rows(s), "forms": forms, "verdicts": VERDICTS,
        "counts": {k: sum(1 for r in rows if r["verdict"] == k) for k in VERDICTS}})
