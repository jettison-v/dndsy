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
        ("battle", "Battle", "Your plan for a fight by Action, Bonus action and Reaction: what you chose to put there, with See all "
                             "for everything else. + Add and the pin put things on it; open one for Pin, Remind me and "
                             "your note."),
        ("spellbook", "Spell Book", "Your prepared spells with filters, each one's average damage or healing, and Cast at for a higher "
                             "slot. An average informs; it doesn't decide."),
        ("wildshape", "Wild Shape", "You as the beast: your numbers and actions worked out for the form, its full page, and Normal to "
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
        ("character", "Sheet and Reminders", "Your whole character from D&D Beyond in one view, laid out for play; the bell puts "
                                             "anything in your Reminders on Battle."),
        ("plan", "Plan", "Battle combos, leveling strategy, personal quests, notes and shortlists. Nothing is lost when you unprepare. "
                         "The DM never sees your notes."),
        ("party", "Party", "Everyone's numbers, and the party's spells and items pooled by what they do."),
    ]),
]
GROUP_NAMES = {key: name for _, groups in SECTIONS for key, name, _ in groups if key}
GROUP_NAMES["help"] = "Help, any time"

# Battle's + Add in the Action column: opens the side panel with what isn't pinned yet (it only reads)
ADD = '[data-tour="battle"] [data-econ-col="action"] .head-add'
SPELLBOOK = "#spell-bar .spellbook-btn"  # opens the Spell Book, full window (it only reads)

# The stops, in order. page: story, campaign, battle, sheet, plan, party, or None (wherever you are).
# open: selectors clicked in turn first (a tab; + Add, then a row). panel: the stop shows the side panel the tour
# opened (other stops close it). example: an example row on Battle, only on the page ("pin", or "note" with a note).
# swap: Battle shown in a Wild Shape form ("form", the first the druid knows) or as it really is ("own"), from
# /characters/<id>/battle/preview: nothing is saved or announced, and the tour puts the real Battle back.
# needs: "character", "caster" (has the Spell Book) or "druid" (knows a form); without it, the stop is left out.
# all: light every match of `at` together (a column: its heading and each row's cell).
STOPS = [
    {"group": "previously", "page": "story", "open": '[data-tab="t-previously"]', "at": '[data-tour="previously"]',
     "what": "Last session's recap, its key moments and the threads still open. <b>All sessions</b> has every session so"
             " far.",
     "why": "Sessions can be weeks apart, and D&D Beyond doesn't remember the story. A minute here before you play "
            "catches you up."},
    {"group": "memory", "page": "campaign", "at": '[data-tour="campaign"]',
     "what": "Everyone and everywhere the party has met, plus Quests, Relationships, the Glossary and the Map.",
     "why": "askdnd builds it from each session and the DM checks it. Spot a mistake? <b>Suggest a correction</b> on "
            "any entry sends it to the DM."},
    {"group": "battle", "title": "Battle: your turn on one screen", "page": "battle", "needs": "character",
     "at": '[data-tour="battle"]',
     "what": "Your Actions, Bonus actions and Reactions, showing only what you chose to put here. Need something else "
             "mid-fight? <b>See all</b> at the bottom of each column lists everything you can do.",
     "why": "D&D Beyond lists everything you have. Battle is your plan for a fight, so a whole turn fits on one screen."},
    {"group": "battle", "title": "+ Add", "page": "battle", "needs": "character", "panel": True,
     "open": [ADD], "at": ".peek.open",
     "what": "<b>+ Add</b> on a column opens the side panel with everything that isn't on Battle yet.",
     "why": "Everything stays one click away, and only what you pick takes up room."},
    {"group": "battle", "title": "The pin", "page": "battle", "needs": "character", "panel": True,
     "open": [ADD], "at": ".peek.open [data-opt-panel] .pick.star",
     "what": "The <b>pin</b> on a row puts it on Battle, in its column.",
     "why": "Unpin it the same way whenever you like."},
    {"group": "battle", "title": "Pinned: it's on Battle", "page": "battle", "needs": "character", "example": "pin",
     "at": '[data-tour="battle"] [data-econ-col="action"]',
     "what": "Here it is, at the top of its column. (Only an example: the tour doesn't pin anything for you.)",
     "why": "Drag rows up and down to put a column in the order you use it."},
    {"group": "battle", "title": "Open one: Pin and Notes", "page": "battle", "needs": "character", "panel": True,
     "open": [ADD, ".peek.open [data-opt-panel] .ri"], "at": ".peek.open .detail-marks",
     "what": "Click a row's name for its rules and its marks: <b>Pin to Battle</b>, <b>Remind me</b> and <b>Your "
             "note</b>.",
     "why": "Your note is for the why and when (\"save it for the boss\"). Other players can read it; the DM never sees "
            "it."},
    {"group": "battle", "title": "Your note on Battle", "page": "battle", "needs": "character", "example": "note",
     "at": '[data-tour="battle"] [data-econ-col="action"]',
     "what": "With a note, a row shows it right under its name. (An example again.)",
     "why": "The why and when stay next to the thing itself, where you'll see them mid-fight."},
    {"group": "spellbook", "title": "Spell Book", "page": "battle", "needs": "caster", "at": SPELLBOOK,
     "what": "<b>Spell Book</b>, above your columns, opens every spell you have prepared in a large window.", "why": "Battle shows the spells you pinned; the Spell Book has all the rest, one click away."},
    {"group": "spellbook", "title": "Spell Book: filters", "page": "battle", "needs": "caster", "panel": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] .ls-fold",
     "what": "Filters narrow the list down: Effect (Damage, Heal, Control…), Casting time, Concentration and more.",
     "why": "Find the spell for this moment without scrolling through all of them."},
    {"group": "spellbook", "title": "Damage and healing", "page": "battle", "needs": "caster", "panel": True, "all": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] :is(.ls-head > :nth-child(6), .sb-avg-col)",
     "what": "<b>Damage / Healing</b> is each spell's average, worked out from its dice and your sheet.",
     "why": "Compare spells at a glance. An average informs; it doesn't decide."},
    {"group": "spellbook", "title": "Cast at", "page": "battle", "needs": "caster", "panel": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] .ls-select:has([data-ls-lens])",
     "what": "<b>Cast at</b> works out every average again as if cast with a higher slot.", "why": "See what a higher slot adds before you spend it."},
    {"group": "wildshape", "title": "Wild Shape: you as the beast", "page": "battle", "needs": "druid", "swap": "form",
     "at": "#battle-body .ws-form",
     "what": "This is Battle in your first Wild Shape form: the beast's HP, AC and speed, your own features carried "
             "over, and its attacks in the columns. (A preview: nothing changes, and no one else sees it.)",
     "why": "D&D Beyond shows the beast's stat block. askdnd shows <b>you</b> as the beast."},
    {"group": "wildshape", "title": "The form's full page", "page": "battle", "needs": "druid", "swap": "form",
     "panel": True, "open": ["#battle-body .ws-form"], "at": ".peek.open",
     "what": "Click the form's name for its full page: everything it can do, worked out for your character.",
     "why": "A second character sheet, for as long as you hold the shape."},
    {"group": "wildshape", "title": "Back to Normal", "page": "battle", "needs": "druid", "swap": "own",
     "at": "#battle-body .ws-chip",
     "what": "<b>Normal</b> brings you back: your own numbers and columns return.",
     "why": "One click each way, mid-fight."},
    {"group": "rolling", "page": "battle", "needs": "character", "at": '[data-tour="roll"]',
     "what": "Click any number to roll it. One window offers Advantage and extra dice; <b>Enter</b> rolls, <b>Esc</b> "
             "closes, and <b>Shift-click</b> rolls without the window.",
     "why": "With Game Mode on, your rolls land in <b>Table rolls</b> for everyone, thrown in your own 3D dice. Pick "
            "<b>DM only</b> or <b>Just me</b> for a private roll."},
    {"group": "live", "page": None, "at": '[data-tour="live"]',
     "what": "<b>Live</b> turns on Game Mode for the session: your rolls are shared, and askdnd re-reads everyone's D&D "
             "Beyond sheet every few minutes. Changed something there? <b>Refresh now</b> picks it up at once.",
     "why": "Build and level up on D&D Beyond as always. askdnd lays your sheet out for play and never changes it."},
    {"group": "character", "title": "Sheet: your whole character", "page": "sheet", "needs": "character",
     "at": '[data-tour="sheet"]',
     "what": "Everything from D&D Beyond in one view, laid out for play. Click any row for its rules and your note.",
     "why": "Actions, spells, forms, items and features in one place, next to your plans."},
    {"group": "character", "title": "The bell", "page": "sheet", "needs": "character",
     "at": '[data-tour="sheet"] button.pick.remind',
     "what": "The <b>bell</b> on a row adds it to your Reminders.", "why": "For the things that are easy to miss mid-fight: an Advantage, a resistance, a feature you rarely use."},
    {"group": "character", "title": "Reminders", "page": "battle", "needs": "character", "at": '[data-tour="reminders"]',
     "what": "Everything you rang the bell for waits here on Battle. Write your own below (\"Ask the DM about the map\").",
     "why": "Your Reminders sit beside your turn, so they're in front of you when they matter."},
    {"group": "plan", "title": "Battle combos", "page": "plan", "needs": "character", "panel": True,
     "open": ['[data-tab="t-combo"]', '#t-combo [data-tour="combo"]'],
     "at": ".peek.open",
     "what": "Plan a few turns together, each split into action, bonus action, reaction and movement. Click one to "
             "read it; <b>Edit</b> changes it.",
     "why": "Work it out between sessions; your combos show on Battle, ready for the fight."},
    {"group": "plan", "title": "Leveling strategy", "page": "plan", "needs": "character", "open": '[data-tab="t-leveling"]',
     "at": '[data-tour="plan"]',
     "what": "Level by level: what you'll take and why, planned ahead or already done.",
     "why": "Your build plan lives next to your character, not in a separate document."},
    {"group": "plan", "title": "Personal quests", "page": "plan", "needs": "character", "open": '[data-tab="t-quest"]',
     "at": '[data-tour="plan"]',
     "what": "Your character's own goals, each with steps to tick off.",
     "why": "So your character's story doesn't get lost between sessions."},
    {"group": "plan", "title": "Notes", "page": "plan", "needs": "character", "open": '[data-tab="t-general"]',
     "at": '[data-tour="plan"]',
     "what": "Anything else you want to keep, freeform.",
     "why": "Other players can read your notes; <b>the DM never sees them</b>."},
    {"group": "plan", "title": "Shortlists", "page": "plan", "needs": "character", "open": '[data-tab="t-spell-list"]',
     "at": '[data-tour="plan"]',
     "what": "Spells (and, for druids, Wild Shape forms) you're weighing up, next to everything you could pick.",
     "why": "Unprepare a spell and nothing is lost: it stays on your Shortlist with your note, ready for next time."},
    {"group": "party", "page": "party", "at": '[data-tour="party"]',
     "what": "Everyone's key numbers, then the party's spells and items pooled together and grouped by what they do.",
     "why": "See who carries which potions and scrolls, and what the party covers between you (healing, control…)."},
    {"group": "help", "page": None, "at": '[data-tour="help"]',
     "what": "<b>What askdnd adds</b> is this tour as a page to read, the <b>FAQ</b> explains each feature, and "
             "<b>About</b> says what askdnd keeps and who can see it.",
     "why": "Take the tour again from this menu whenever you like."},
]


def stops_for(db: Session, user: dict | None) -> list[dict]:
    """This person's stops, with each page's address. Character stops need their own character in this campaign;
    Spell Book stops a spellcaster, Wild Shape stops a druid who knows a form."""
    from urllib.parse import quote

    from app import characters
    from app.character_pages import _known_forms
    from app.models import Character

    email = ((user or {}).get("email") or "").lower()
    mine = next((r for r in rows_from(db) if email and r["owner"] == email), None)
    cbase = web.base()
    pages = {"story": f"{cbase}/", "campaign": f"{cbase}/campaign", "party": "/party", None: None}
    has = set()
    swaps = {}
    if mine:
        cid = mine["id"]
        pages |= {"battle": f"/characters/{cid}/battle", "sheet": f"/characters/{cid}", "plan": f"/characters/{cid}/plan"}
        has.add("character")
        ch = db.get(Character, cid)
        sheet = characters.character_summary(ch) if ch else None
        if sheet and sheet.get("spells"):  # Battle shows the Spell Book (character_pages._spellbar)
            has.add("caster")
        forms = _known_forms(sheet)
        if forms:
            has.add("druid")
            swaps = {"form": f"/characters/{cid}/battle/preview?form={quote(forms[0]['name'])}",
                     "own": f"/characters/{cid}/battle/preview"}
    out = []
    for s in STOPS:
        if s.get("needs") and s["needs"] not in has:
            continue
        opens = [s["open"]] if isinstance(s.get("open"), str) else s.get("open") or []
        out.append({"group": s["group"], "name": GROUP_NAMES[s["group"]], "title": s.get("title") or GROUP_NAMES[s["group"]],
                    "url": pages[s["page"]], "at": s["at"], "open": opens, "panel": s.get("panel", False),
                    "example": s.get("example"), "all": s.get("all", False), "swap": swaps.get(s.get("swap")), "restore": swaps.get("own") if s.get("swap") else None,
                    "what": s["what"], "why": s["why"]})
    return out
