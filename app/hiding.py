"""Hide, kept on Battle (feedback 14, Trent, Nov 5; docs/mockups/hide-ready.html, Brett chose the recommendations).

Hide's side panel rolls "Hide (Stealth)" (app/templates/_panel_detail.html). At the table the roll is askdnd's (Table
rolls), and a total of 15 or more starts **Hidden**: the 2024 rules' Invisible condition while hidden, kept as askdnd's
own Invisible with the source "Hidden" and the total as the DC to find you (`find`), and started on the D&D Beyond
sheet where the bridge works (Brett's choice 1). Battle's Status row says "Hidden · find DC 17"; the roll window offers
Invisible's Advantage (app/conditions.py) and, for an attack, a tick that ends Hidden (app.js "ends Hidden"). Ending it
is ending Invisible. askdnd only keeps track: whether you could hide, and when you're found, is the DM's.
"""

from sqlalchemy.orm import Session

from app import conditions as cond
from app import ddb_bridge, web
from app.models import Character

LABEL = "Hide (Stealth)"  # the roll Hide's panel makes
DC = 15  # the 2024 rules' Hide action
ENDS = ("It ends when you make a sound louder than a whisper, make an attack roll, cast a spell with a Verbal component, "
        "or an enemy finds you.")


def hidden(ch: Character | None) -> int | None:
    """The DC to find this character while it's hidden, or None."""
    entry = next((c for c in (ch.conditions if ch else None) or [] if c.get("name") == "Invisible" and c.get("source") == "Hidden"), None)
    return entry.get("find") if entry else None


def start(db: Session, ch: Character, total: int) -> bool:
    """Hidden, with `total` as the DC to find it (a Hide roll before it, ended: one hiding at a time). True when it
    went to D&D Beyond too."""
    own = cond.add(ch.conditions, "Invisible", "Hidden", f"Your Stealth total, {total}, is the DC to find you. {ENDS}")
    own[-1]["find"] = total
    synced = ddb_bridge.on_for(db, ch) and ddb_bridge.reachable(ch)  # (can't be reached: Hidden in askdnd, the roll still made)
    if synced:
        ddb_bridge.add(db, ch, "set", {"field": cond.ddb_field("Invisible"), "value": True}, f"{ch.name}: hidden (Invisible)")
    ch.conditions = own
    return synced


def mark(db: Session, row) -> dict | None:
    """A Hide roll at the table, after it's made: Hidden on 15 or more. What the page does next ({"text", "character",
    "deliver"}), as a death save's (app/table_rolls.py death_mark), or None for any other roll."""
    ch = row.character
    if row.kind != "check" or row.label != LABEL or ch is None:
        return None
    if row.total < DC:
        return {"text": f"Not hidden: {row.total} against DC {DC}", "character": ch.id}
    synced = start(db, ch, row.total)
    unreached = ddb_bridge.on_for(db, ch) and not synced
    return {"text": f"Hidden: {row.total} is the DC to find you" + (": Invisible on its way to D&D Beyond" if synced else
                                                                    ". Mark Invisible on D&D Beyond: the sheet can't be reached" if unreached else ""),
            "character": ch.id, **({"deliver": web.deliver_now(ch)} if synced else {})}
