"""The new-player tour (? › Take the tour) and Help › What askdnd adds, from one list (Brett, 2026-10-24 and
2026-10-26; docs/plans/2026-10-26-tour.md, mockup docs/mockups/tour.html).

A stop is a page, the thing to light up on it (`at`, a CSS selector; `open` is a tab to click first), and what it is
and why. Stops are grouped; Help's tab shows each group once, with "Show me" starting the tour there. The tour runs
on the person's own pages and changes nothing: app.js ("the tour") walks the stops across pages. Targets carry
`data-tour` where a selector would otherwise be fragile; tests/browser/test_new_player_tour.py walks every stop."""

from sqlalchemy.orm import Session

from app import web
from app.live import rows_from

# Help › What askdnd adds: sections, each a list of groups (a group key starts the tour there; None has no stops yet)
SECTIONS = [
    ("Before you play", [
        ("previously", "Previously on…", "The last session's recap, key moments and open threads; every session is under All sessions."),
        ("memory", "The campaign's memory", "People, places, quests and how everyone is connected, built from each session and kept right by "
                                            "the DM. Suggest a correction sends a fix to the DM."),
    ]),
    ("On your turn", [
        ("battle", "Battle", "Your plan for a fight by Action, Bonus action and Reaction: only what you chose to put there. + Add and "
                             "the pin put things on it; open one for Pin, Shortlist, Remind me and your note."),
        (None, "Spell Book", "Your prepared spells with filters, and the average damage or healing at each slot level. Averages "
                             "inform; they never recommend."),
        (None, "Wild Shape", "You as the beast: your numbers and actions worked out for the form, its full page, and Normal to "
                             "come back (druids)."),
        (None, "Conditions and effects", "Invisible, Poisoned, Bless and the rest: what each does to your rolls, offered in the roll "
                                         "window with its reason. The DM rules."),
    ]),
    ("Rolling", [
        ("rolling", "Rolling and Table rolls", "Click any number to roll it. With Game Mode on, everyone's rolls are in Table rolls; DM "
                                               "only and Just me keep a roll private."),
        ("live", "Game Mode and Live", "askdnd re-reads everyone's D&D Beyond sheet during play. Build and level up on D&D Beyond as "
                                       "always; askdnd never changes it."),
        (None, "Your dice", "Thrown 3D dice in the set you choose (account menu › Your dice); the table sees your rolls in them."),
    ]),
    ("Your character", [
        ("character", "Sheet and Reminders", "Your whole character from D&D Beyond in one view, laid out for play; the bell keeps "
                                             "anything in your Reminders on Battle."),
        ("plan", "Plan", "Battle combos, leveling strategy, personal quests, notes and shortlists. Nothing is lost when you unprepare. "
                         "The DM never sees your notes."),
        ("party", "Party", "Everyone's numbers, and the party's spells and items pooled by what they do."),
    ]),
]
GROUP_NAMES = {key: name for _, groups in SECTIONS for key, name, _ in groups if key}
GROUP_NAMES["help"] = "Help, any time"

# The stops, in order. page: story, campaign, battle, sheet, plan, party, or None (wherever you are).
# needs: "character" (your own character in this campaign); without one, those stops are left out.
STOPS = [
    {"group": "previously", "page": "story", "open": '[data-tab="t-previously"]', "at": '[data-tour="previously"]',
     "what": "The last session's recap, its key moments and the threads still open. <b>All sessions</b> has every one.",
     "why": "D&D Beyond doesn't remember your campaign. Read this before you play: sessions can be weeks apart."},
    {"group": "memory", "page": "campaign", "at": '[data-tour="campaign"]',
     "what": "Everyone and everywhere the party has met, with Quests, Relationships, the Glossary and the Map.",
     "why": "It's built from each session, and the DM keeps it right. Spot a mistake? <b>Suggest a correction</b> on any entry "
            "sends it to the DM."},
    {"group": "battle", "title": "Battle: your turn on one screen", "page": "battle", "needs": "character",
     "at": '[data-tour="battle"]',
     "what": "Action, Bonus action and Reaction, showing only what you chose to put here. <b>+ Add</b> on a column lists the rest.",
     "why": "D&D Beyond lists everything you have. Battle is your plan for a fight, so your turn fits on one screen."},
    {"group": "rolling", "page": "battle", "needs": "character", "at": '[data-tour="roll"]',
     "what": "Click any number to roll it, with Advantage and extra dice in one window. <b>Enter</b> rolls, <b>Esc</b> closes, "
             "<b>Shift-click</b> skips the window.",
     "why": "With Game Mode on, rolls land in <b>Table rolls</b> for everyone, in your own 3D dice. Pick <b>DM only</b> or "
            "<b>Just me</b> when it's private."},
    {"group": "live", "page": None, "at": '[data-tour="live"]',
     "what": "<b>Live</b> turns on Game Mode for the session: your rolls are shared, and askdnd re-reads everyone's D&D Beyond "
             "sheet every few minutes. <b>Refresh now</b> after you change something there.",
     "why": "Build and level up on D&D Beyond as always. askdnd lays your sheet out for play, and never changes it."},
    {"group": "character", "title": "Sheet: your whole character", "page": "sheet", "needs": "character",
     "at": '[data-tour="sheet"]',
     "what": "Everything from D&D Beyond in one view, laid out for play. Every row opens its rules and your note.",
     "why": "Actions, spells, forms, items and features in one place, next to your plans."},
    {"group": "character", "title": "Reminders", "page": "battle", "needs": "character", "at": '[data-tour="reminders"]',
     "what": "The <b>bell</b> on anything on Sheet adds it to your Reminders here, or write your own on Plan "
             "(\"Ask the DM about the map\").",
     "why": "Never forget anything mid-battle: an Advantage, a resistance, a promise."},
    {"group": "plan", "title": "Battle combos", "page": "plan", "needs": "character", "open": '[data-tab="t-combo"]',
     "at": '[data-tour="plan"]',
     "what": "Plan a few turns together, each split into action, bonus action, reaction and movement.",
     "why": "Work it out between sessions; it shows on Battle when the moment comes."},
    {"group": "plan", "title": "Leveling strategy", "page": "plan", "needs": "character", "open": '[data-tab="t-leveling"]',
     "at": '[data-tour="plan"]',
     "what": "Level by level: what you'll take and why, planned or done.",
     "why": "Your build plan next to your character, not in a separate document."},
    {"group": "plan", "title": "Personal quests", "page": "plan", "needs": "character", "open": '[data-tab="t-quest"]',
     "at": '[data-tour="plan"]',
     "what": "Your character's own goals, with steps you tick off.",
     "why": "So your story doesn't get lost between sessions."},
    {"group": "plan", "title": "Notes", "page": "plan", "needs": "character", "open": '[data-tab="t-general"]',
     "at": '[data-tour="plan"]',
     "what": "Anything else, freeform.",
     "why": "Other players can read your notes; <b>the DM never sees them</b>."},
    {"group": "plan", "title": "Shortlists", "page": "plan", "needs": "character", "open": '[data-tab="t-spell-list"]',
     "at": '[data-tour="plan"]',
     "what": "Spells (and Wild Shape forms, for druids) you're weighing up, beside everything you could pick.",
     "why": "Nothing is lost when you unprepare a spell: it stays on your Shortlist with your note, ready for next time."},
    {"group": "party", "page": "party", "at": '[data-tour="party"]',
     "what": "Everyone's key numbers, then the party's spells and items pooled together, grouped by what they do.",
     "why": "Spread the potions and scrolls around, and see what the party covers between you (healing, control…) before "
            "you prepare."},
    {"group": "help", "page": None, "at": '[data-tour="help"]',
     "what": "<b>What askdnd adds</b> is this tour to read, the <b>FAQ</b> says how each feature works, and <b>About</b> says "
             "what askdnd keeps and who sees it.",
     "why": "Take the tour again from this menu whenever you like."},
]


def stops_for(db: Session, user: dict | None) -> list[dict]:
    """This person's stops, with each page's address. Character stops need their own character in this campaign."""
    email = ((user or {}).get("email") or "").lower()
    mine = next((r for r in rows_from(db) if email and r["owner"] == email), None)
    cbase = web.base()
    pages = {"story": f"{cbase}/", "campaign": f"{cbase}/campaign", "party": "/party", None: None}
    if mine:
        cid = mine["id"]
        pages |= {"battle": f"/characters/{cid}/battle", "sheet": f"/characters/{cid}", "plan": f"/characters/{cid}/plan"}
    out = []
    for s in STOPS:
        if s.get("needs") == "character" and not mine:
            continue
        out.append({"group": s["group"], "name": GROUP_NAMES[s["group"]], "title": s.get("title") or GROUP_NAMES[s["group"]],
                    "url": pages[s["page"]], "at": s["at"], "open": s.get("open"), "what": s["what"], "why": s["why"]})
    return out
