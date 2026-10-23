"""The VTT switch (VTT Phase 0, item 0.1; docs/mockups/vtt-switch.html).

askdnd is growing into the table's virtual tabletop one piece at a time. Each piece merges into `main` early and stays
hidden until a campaign switches it on: a test campaign (`Campaign.is_test`) sees every piece, finished or not; any
other campaign sees only the Ready pieces switched on in its Manage › Settings (`Campaign.vtt_pieces`), and can switch
them back off. Pages ask `on(campaign, key)` (templates: `vtt_on(key)`) before showing a piece.
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


# Every VTT piece, in roadmap order. Add one here when its work starts (ready=False), and set ready=True when the table
# can have it.
PIECES: list[Piece] = []


def piece(key: str) -> Piece | None:
    return next((p for p in PIECES if p.key == key), None)


def on(campaign: Campaign | dict | None, key: str) -> bool:
    """Does this campaign (a Campaign, or the menu bar's `here`) show this piece?"""
    p = piece(key)
    if campaign is None or p is None:
        return False
    get = campaign.get if isinstance(campaign, dict) else lambda k: getattr(campaign, k)
    return bool(get("is_test")) or (p.ready and key in (get("vtt_pieces") or []))


def rows(campaign: Campaign) -> list[dict]:
    """Manage › Settings › Virtual tabletop: each piece, whether it's ready, and whether it's on here."""
    return [{"p": p, "on": on(campaign, p.key), "can_switch": p.ready and not campaign.is_test} for p in PIECES]


def switch(campaign: Campaign, key: str, turn_on: bool) -> str:
    """Switch a Ready piece on or off for a campaign that isn't a test one; returns what happened."""
    p = piece(key)
    if p is None:
        return "There's no such VTT piece."
    if campaign.is_test:
        return f"{campaign.name} is a test campaign: it already has every piece."
    if not p.ready:
        return f"{p.name} is still being built."
    pieces = [k for k in (campaign.vtt_pieces or []) if k != key] + ([key] if turn_on else [])
    campaign.vtt_pieces = pieces
    return f"{p.name} is {'on' if turn_on else 'off'} for {campaign.name}."
