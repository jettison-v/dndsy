"""What a campaign has switched on: Features and Labs (Manage › Settings; Brett, 2026-11-03).

**Features** are finished: one switch each, per campaign, for its DM or an admin. **Labs** is one switch per campaign
that shows the features still being tried, each with its own toggle, a plain description of what it does and where it
sits on the roadmap; a feature leaves Labs once it's settled (it becomes a Feature, or just how askdnd works). A
campaign keeps the keys it switched on (`Campaign.vtt_pieces`), so switching Labs off hides its features without
forgetting them. Pages ask `on(campaign, piece)` (templates: `vtt_on(piece)`) with the piece of code they show; PIECES
says which feature each piece comes with.

A test campaign (`Campaign.is_test`) only says it holds test data (test copies of characters, app/manage_table.py); it
switches nothing on by itself. Some Labs features are each person's own instead: the dice tray, in Your dice
(app/dice.py `prefs`), listed on Settings for the DM to see.
"""

from dataclasses import dataclass

from app.models import Campaign


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    about: str  # what it does, in plain words
    roadmap: str  # where it sits on the roadmap
    labs: bool = False
    state: str = "Ready"  # in Labs: "Being built" (still changing) or "Ready to try"


FEATURES: list[Feature] = [
    Feature("sync", "Sync with D&D Beyond",
            "Every change made in askdnd or on D&D Beyond reaches the other, through the askdnd extension in each player's "
            "Chrome: hit points, conditions and death saves, Heroic Inspiration, casting, resources and rests, items and "
            "coins, adding items (Add item, Give loot) and Give, preparing spells, and the DM's browser making changes for a player whose sheet is "
            "closed. Tell the table first: D&D Beyond's terms don't allow tools like this.",
            "Live character state (Phase 1) and the D&D Beyond bridge; finished Nov 3."),
    Feature("vtt", "askdnd's VTT",
            "The menu bar's Table button opens askdnd's own table instead of D&D Beyond's VTT: the turn order across the "
            "top, Table rolls and the side panel around the middle, and everyone's dice thrown across the screen. For now "
            "the middle lists the fight heard from D&D Beyond's VTT, and the map stays there.",
            "The VTT, slices 0 to 10 (docs/plans/2026-11-02-vtt-build-plan.md): 0 and 1 built; 2, askdnd runs the fight, next.",
            labs=True, state="Being built"),
    Feature("creatures", "Your creatures",
            "A familiar, an artificer's Homunculus Servant or Steel Defender, a ranger's companion or a summon on a "
            "character's D&D Beyond sheet gets a switch by the character's name on Battle (Vi · Homunculus): Battle "
            "becomes the creature's, with its own Hit Points, Armor Class, actions to roll and when its turn comes, and "
            "the numbers that grow with its master worked out. Its rolls say whose they are.",
            "Your creatures (docs/plans/2026-11-03-your-creatures.md): slice 1, Battle as the creature, being built; "
            "its Hit Points synced with D&D Beyond next.",
            labs=True, state="Being built"),
]
LABS = "labs"  # the campaign's Labs switch, kept with the features' keys

# Which feature each piece of code comes with
PIECES = {"ddb_bridge": "sync", "live_state": "sync", "dm_backup": "sync", "vtt_table": "vtt"}

# Labs features that are each person's own (app/dice.py): listed on Settings so the DM knows they're there
PERSONAL = [
    Feature("dice_tray", "Dice tray: less intrusive dice",
            "Your own rolls are still thrown across the whole screen wherever you roll. Others' rolls tumble in a small "
            "tray in the bottom-left corner instead, so they don't cover the page you're planning on; on askdnd's table "
            "every roll is thrown across the screen. Each person chooses it in Your dice.",
            "Dice (decided Oct 23, docs/mockups/dice-two-ways.html); in Labs since Nov 3.", labs=True, state="Ready to try"),
]


def feature(key: str) -> Feature | None:
    return next((f for f in FEATURES if f.key == key), None)


def on(campaign: Campaign | dict | None, piece: str) -> bool:
    """Does this campaign (a Campaign, or the menu bar's `here`) show this piece (or feature)?"""
    f = feature(PIECES.get(piece, piece))
    if campaign is None or f is None:
        return False
    get = campaign.get if isinstance(campaign, dict) else lambda k: getattr(campaign, k)
    kept = get("vtt_pieces") or []
    return f.key in kept and (not f.labs or LABS in kept)


def rows(campaign: Campaign) -> dict:
    """Manage › Settings: the Features with whether each is on here, whether Labs is, and the Labs features."""
    kept = campaign.vtt_pieces or []
    return {"features": [{"f": f, "on": f.key in kept} for f in FEATURES if not f.labs],
            "labs_on": LABS in kept,
            "labs": [{"f": f, "on": f.key in kept} for f in FEATURES if f.labs],
            "personal": PERSONAL}


def switch(campaign: Campaign, key: str, turn_on: bool) -> str:
    """Switch a feature, or Labs, on or off for a campaign; returns what happened."""
    f = feature(key)
    if f is None and key != LABS:
        return "There's no such feature."
    campaign.vtt_pieces = [k for k in (campaign.vtt_pieces or []) if k != key] + ([key] if turn_on else [])
    name = f.name if f else "Labs"
    tail = " Its features keep how you left them." if key == LABS and not turn_on else ""
    return f"{name} is {'on' if turn_on else 'off'} for {campaign.name}.{tail}"
