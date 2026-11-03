"""The VTT switch (VTT Phase 0, item 0.1; docs/mockups/vtt-switch.html).

askdnd is growing into the table's virtual tabletop one piece at a time. Each piece merges into `main` early and stays
hidden until a campaign switches it on: a test campaign (`Campaign.is_test`) sees every piece, finished or not; any
other campaign sees only the Ready pieces switched on in its Manage › Settings (`Campaign.vtt_pieces`), and can switch
them back off. Pages ask `on(campaign, key)` (templates: `vtt_on(key)`) before showing a piece.

Pieces that belong together are one switch (Brett, 2026-11-02, DECISIONS): Play through askdnd (the bridge, casting,
resources and rests, the DM as a backup) and askdnd's VTT. A campaign keeps the switch's key, so a piece of it that
becomes Ready later comes on with it; until then the switch gives the pieces of it that are Ready.
"""

from dataclasses import dataclass

from app.models import Campaign


@dataclass(frozen=True)
class Piece:
    key: str
    name: str
    phase: str  # the roadmap's number, e.g. "1.1" (docs/plans/2026-10-22-vtt-roadmap.md)
    about: str
    ready: bool = False  # finished: a campaign that isn't a test can switch it on
    switch: str = ""  # the switch it comes with (SWITCHES), else its own


@dataclass(frozen=True)
class Switch:
    key: str
    name: str
    about: str


SWITCHES: list[Switch] = [
    Switch("play", "Play through askdnd",
           "askdnd and each player's D&D Beyond sheet kept in step, both ways, through the askdnd extension. "
           "Tell the table first: D&D Beyond's terms don't allow tools like this."),
    Switch("vtt", "askdnd's VTT", "The menu bar's Table button opens askdnd's own table instead of D&D Beyond's VTT."),
]


# Every VTT piece, in roadmap order. Add one here when its work starts (ready=False), and set ready=True when the table
# can have it.
PIECES: list[Piece] = [
    Piece("ddb_bridge", "D&D Beyond bridge", "4",
          "The askdnd extension keeps each player's D&D Beyond sheet and askdnd in step, both ways. "
          "Tell the table first: D&D Beyond's terms don't allow tools like this.", ready=True, switch="play"),
    Piece("live_state", "Casting, resources and rests", "1.2",
          "Casting spends a slot, class resources count down and rests bring things back, all through the bridge. "
          "Still being reviewed.", switch="play"),
    Piece("dm_backup", "The DM as a backup", "4",
          "When a player's sheet is closed, the DM's browser with any D&D Beyond page open makes their changes, with the DM's "
          "rights on D&D Beyond. Still being reviewed.", switch="play"),
    Piece("table_dice", "Everyone's rolls thrown across the screen", "3.11",
          "Others' rolls are thrown across the page like your own, instead of the small tray"),
    Piece("vtt_table", "askdnd's table", "1",
          "askdnd's own table page: the fight, Table rolls and the side panel around the map (VTT Layout). Being built "
          "slice by slice (docs/plans/2026-11-02-vtt-build-plan.md).", switch="vtt"),
]


def piece(key: str) -> Piece | None:
    return next((p for p in PIECES if p.key == key), None)


def switch_of(key: str) -> Switch | None:
    return next((w for w in SWITCHES if w.key == key), None)


def parts(switch_key: str) -> list[Piece]:
    return [p for p in PIECES if p.switch == switch_key]


def on(campaign: Campaign | dict | None, key: str) -> bool:
    """Does this campaign (a Campaign, or the menu bar's `here`) show this piece?"""
    p = piece(key)
    if campaign is None or p is None:
        return False
    get = campaign.get if isinstance(campaign, dict) else lambda k: getattr(campaign, k)
    kept = get("vtt_pieces") or []
    return bool(get("is_test")) or (p.ready and (key in kept or bool(p.switch) and p.switch in kept))


def rows(campaign: Campaign) -> list[dict]:
    """Manage › Settings › Virtual tabletop: each switch with what it gives now and what comes later, then each piece
    that is its own switch."""
    out = []
    for w in SWITCHES:
        ps = parts(w.key)
        ready = [p for p in ps if p.ready]
        out.append({"key": w.key, "name": w.name, "about": w.about, "phase": "", "parts": ps,
                    "ready": bool(ps) and len(ready) == len(ps), "some_ready": bool(ready),
                    "on": campaign.is_test or (bool(ready) and all(on(campaign, p.key) for p in ready)),
                    "can_switch": bool(ready) and not campaign.is_test})
    for p in PIECES:
        if not p.switch:
            out.append({"key": p.key, "name": p.name, "about": p.about, "phase": p.phase, "parts": [], "ready": p.ready,
                        "some_ready": p.ready, "on": on(campaign, p.key), "can_switch": p.ready and not campaign.is_test})
    return out


def switch(campaign: Campaign, key: str, turn_on: bool) -> str:
    """Switch a switch (or a piece that is its own) on or off for a campaign that isn't a test one; returns what
    happened. A piece of a switch is switched with it."""
    p = piece(key)
    w = switch_of(p.switch if p and p.switch else key)
    if w is None and p is None:
        return "There's no such VTT piece."
    if campaign.is_test:
        return f"{campaign.name} is a test campaign: it already has every piece."
    name, keys = (w.name, {w.key, *(q.key for q in parts(w.key))}) if w else (p.name, {p.key})
    if not (any(q.ready for q in parts(w.key)) if w else p.ready):
        return f"{name} is still being built."
    kept = [k for k in (campaign.vtt_pieces or []) if k not in keys]
    campaign.vtt_pieces = kept + ([w.key if w else p.key] if turn_on else [])
    return f"{name} is {'on' if turn_on else 'off'} for {campaign.name}."
