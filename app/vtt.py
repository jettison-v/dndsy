"""What a campaign has switched on: Features and Labs (Manage › Settings; Brett, 2026-11-03).

**Features** are finished: one switch each, per campaign, for its DM or an admin. **Labs** is one switch per campaign
that shows the features still being tried, each with its own toggle, a plain description of what it does and where it
sits on the roadmap; a feature leaves Labs once it's settled (it becomes a Feature, or just how askdnd works). A
campaign keeps the keys it switched on (`Campaign.vtt_pieces`), so switching Labs off hides its features without
forgetting them. Pages ask `on(campaign, piece)` (templates: `vtt_on(piece)`) with the piece of code they show; PIECES
says which feature each piece comes with.

A test campaign (`Campaign.is_test`) only says it holds test data (test copies of characters, app/manage_table.py); it
switches nothing on by itself. The dice tray, each person's own, left Labs on Nov 5: it's an option in Your dice (app/dice.py).
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
            "The menu bar's Table button opens askdnd's own table instead of D&D Beyond's VTT: places with their maps (a "
            "picture or a Dungeon Alchemist file), the party's and the DM's creatures as tokens, the DM's scene notes "
            "pinned on the map (hers alone), a creature's stat block and rolls in the side panel, the fight run here "
            "(Start a fight, Initiative, Next turn, Undo) and your turn's bar under the map. Being built: moving and "
            "measuring, fog and spell areas come next; the table moves from D&D Beyond's VTT once it's all here.",
            "askdnd's table (docs/plans/2026-11-06-table-build-plan.md): built to the fight, Nov 7; then moving, fog, areas.",
            labs=True, state="Being built"),
    Feature("creatures", "Your creatures",
            "A familiar, an artificer's Homunculus Servant or Steel Defender, a ranger's companion, a summon or a steed "
            "is a small character of its own: a switch by its master's name on Battle (Vi · Homunculus) shows its Hit "
            "Points, Armor Class, actions to roll and when its turn comes, with what grows with its master worked out. A "
            "familiar exists once Find Familiar is cast, goes to the pocket dimension and back, and disappears at 0 Hit "
            "Points; summons and steeds are worked out for the level cast. Each has its own card on Party and its place "
            "in the fight, and a familiar or steed its own World entry. With Sync with D&D Beyond, its Hit Points and a "
            "familiar's form are kept in step on the sheet's Extras.",
            "Your creatures (docs/plans/2026-11-03-your-creatures.md): finished Nov 5, out of Labs."),
    Feature("initiative", "Initiative from askdnd",
            "Everyone rolls their own Initiative in askdnd before the DM presses Start Combat in D&D Beyond's VTT, a "
            "character's familiar with it, and the number fills in the VTT's combat sidebar (a Homunculus right after "
            "its master). After Start Combat the order is the DM's: drag a row on Party's Rows to move someone. Needs "
            "Sync with D&D Beyond, and extension 0.12.0 with the DM's VTT open.",
            "Initiative in askdnd (docs/mockups/initiative/), Nov 4: being built. Once askdnd's own VTT runs, nothing is "
            "sent to D&D Beyond's.",
            labs=True, state="Being built"),
    Feature("recap_listen", "Listen to the recap",
            "On Story › Previously on… and each session in All sessions, ▶ Listen plays the recap read aloud by a narrator, over the pictures of who and "
            "what each paragraph names, panning slowly, with the words on screen: a \"previously on\" to start the night. "
            "The first Listen on a recap has OpenAI read it (a few cents, counted on Manage › Usage); after that it's kept.",
            "Nice to have, Nov 6 (Brett): tried at the table first.",
            labs=True, state="Ready to try"),
]
LABS = "labs"  # the campaign's Labs switch, kept with the features' keys

# Which feature each piece of code comes with
PIECES = {"ddb_bridge": "sync", "live_state": "sync", "dm_backup": "sync", "vtt_table": "vtt"}

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
            "labs": [{"f": f, "on": f.key in kept} for f in FEATURES if f.labs]}


def switch(campaign: Campaign, key: str, turn_on: bool) -> str:
    """Switch a feature, or Labs, on or off for a campaign; returns what happened."""
    f = feature(key)
    if f is None and key != LABS:
        return "There's no such feature."
    campaign.vtt_pieces = [k for k in (campaign.vtt_pieces or []) if k != key] + ([key] if turn_on else [])
    name = f.name if f else "Labs"
    tail = " Its features keep how you left them." if key == LABS and not turn_on else ""
    return f"{name} is {'on' if turn_on else 'off'} for {campaign.name}.{tail}"
