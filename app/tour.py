"""The new-player tour (? › Take the tour) and Help › What askdnd adds, from one list (Brett, 2026-10-24 and
2026-10-26; docs/plans/2026-10-26-tour.md, mockup docs/mockups/tour.html).

A stop is a page, the thing to light up on it (`at`, a CSS selector; `open` is a tab to click first), and what it is
and why. Stops are grouped; Help's tab shows each group once, with "Show me" starting the tour there. The tour runs
on the person's own pages and changes nothing: app.js ("the tour") walks the stops across pages. Targets carry
`data-tour` where a selector would otherwise be fragile; tests/browser/test_new_player_tour.py walks every stop."""

from sqlalchemy.orm import Session

from app import web, wild_shape
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
        ("rolling", "Rolling and Table rolls", "Click any number to roll it, or find it with Search (⌘F). Rolls go to Table rolls for "
                                               "everyone; DM only and Only me keep a roll private. Apply to on the DM's damage changes "
                                               "your Hit Points."),
        ("dice", "Your dice", "Thrown 3D dice in the set you choose (account menu › Your dice); the table sees your rolls in them."),
        ("conditions", "Conditions and effects", "Invisible, Poisoned, Bless and the rest: what each does to your rolls, offered in "
                                                 "the roll window with its reason, and a reminder when one is due to end. The DM rules."),
    ]),
    ("With your D&D Beyond sheet", [
        ("live", "Live", "The Live pill says whether your D&D Beyond sheet is connected. Nothing to turn on."),
        ("sync", "Playing on your D&D Beyond sheet", "Hit points, Cast, resources and rests changed in askdnd change your D&D Beyond "
                                                     "sheet too, within seconds (where your campaign syncs with D&D Beyond)."),
    ]),
    ("Spells and shapes", [
        ("spellbook", "Spell Book", "Your prepared spells with filters, each one's average damage or healing, and Cast at for a higher "
                             "slot. An average informs; it doesn't decide."),
        ("creatures", "Your creatures", "A familiar, Homunculus, steed or summon: Battle as the creature, its own card on Party and, "
                                        "for a familiar or steed, its own World entry."),
        ("wildshape", "Wild Shape", "You as the beast: your numbers and actions worked out for the form, its full page, and Normal to "
                             "come back (druids)."),
    ]),
    ("Your character", [
        ("character", "Reminders, Sheet and Inventory", "The bell puts anything you tend to forget in your Reminders on Battle; Sheet is "
                                                        "your whole character from D&D Beyond, laid out for play; Inventory has your purse "
                                                        "and + Add item."),
        ("plan", "Plan", "Battle combos, leveling strategy, personal quests, notes and shortlists. Nothing is lost when you unprepare. "
                         "The DM never sees your notes."),
        ("party", "Party", "Everyone's numbers at a glance, and the party's spells and items pooled, filtered by what they do and who has them."),
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
# needs: "character", "caster" (has the Spell Book), "druid" (knows a form), "creatures" (one in play, with Your creatures on)
# or "sync" (the character plays on its D&D Beyond
# sheet: ddb_bridge.plays); without it, the stop is left out. "sync+caster" needs both.
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
    {"group": "rolling", "page": "battle", "needs": "character", "at": '[data-tour="roll"]',
     "what": "Click any number to roll it. One window offers Advantage and extra dice; <b>Enter</b> rolls, <b>Esc</b> "
             "closes, and <b>Shift-click</b> rolls without the window.",
     "why": "Your rolls land in <b>Table rolls</b> for everyone, thrown in your own 3D dice. Pick <b>DM only</b> or "
            "<b>Only me</b> for a private roll."},
    {"group": "rolling", "title": "Table rolls", "page": None, "at": "#table-rolls .rs-head, .rs-edge",
     "what": "<b>Table rolls</b> is everyone's rolls, the DM's too, newest first, on every page. This opens it.",
     "why": "When the DM rolls damage or someone heals you, <b>Apply to</b> on that roll changes your Hit Points in one step."},
    {"group": "rolling", "title": "Search", "page": None, "at": ".search-btn",
     "what": "<b>Search</b> (or <b>⌘F</b>, Ctrl+F on Windows) finds anything about your character, a rule or the story "
             "from any page, as you type.",
     "why": "<b>Enter</b> does it: rolls a check or an attack, opens Cast for a spell, shows a rule's words. "
            "<b>⌘F</b> again gives you the browser's own find."},
    {"group": "dice", "page": None, "at": ".avatar",
     "what": "<b>Your dice</b>, in your account menu here (and a tab in Table rolls' Roll), picks the set your rolls are thrown "
             "in, and how others' rolls show for you.",
     "why": "The table sees your rolls in your dice."},
    {"group": "conditions", "page": "battle", "needs": "character", "at": "#battle-body .cond-add",
     "what": "<b>+ Condition</b> starts one, with how long it lasts. Each shows as a badge after your name, and the roll "
             "window offers what it changes, with the reason.",
     "why": "Nothing ends by itself: a corner card reminds you and the DM when one is due. The DM rules."},
    {"group": "live", "page": None, "at": '[data-tour="live"]',
     "what": "<b>Live</b> says whether your D&D Beyond sheet is connected: open it in Chrome with the askdnd bridge, and "
             "changes go both ways within seconds. There's nothing to turn on when the game starts.",
     "why": "Build and level up on D&D Beyond as always. <b>Refresh now</b> picks up a change made there at once."},
    {"group": "sync", "title": "Hit points", "page": "battle", "needs": "sync", "at": "#battle-body .nt:has(.hp-btns)",
     "what": "<b>−</b> and <b>+</b> on Hit Points open a small window: type the damage or healing and press <b>Enter</b>. "
             "Temporary Hit Points go first, and Concentration's save is worked out for you.",
     "why": "Your D&D Beyond sheet changes too, within seconds. No more doing the sums twice."},
    {"group": "sync", "title": "Cast", "page": "battle", "needs": "sync+caster", "at": '[data-tour="battle"] [data-use-url*="/cast?"]',
     "what": "<b>Cast</b> on a spell asks how: which slot, Pact Magic, as a Ritual. It spends that on your sheet, and "
             "<b>Cast and roll</b> rolls it too.",
     "why": "Slots stay right on D&D Beyond without ticking boxes there. Undo puts it back."},
    {"group": "sync", "title": "Resources and rests", "page": "battle", "needs": "sync", "at": "#battle-body .cond-rest",
     "what": "Press a resource (Wild Shape, Channel Divinity, a slot) to use one or give one back. <b>Rest</b> lists what a "
             "Short or Long Rest brings back, by the 2024 rules.",
     "why": "The DM says when you rest; askdnd does the bookkeeping on your sheet."},
    {"group": "spellbook", "title": "Spell Book", "page": "battle", "needs": "caster", "at": SPELLBOOK,
     "what": "<b>Spell Book</b>, above your columns, opens every spell you have prepared in a large window.", "why": "Battle shows the spells you pinned; the Spell Book has all the rest, one click away, with a pin on each row."},
    {"group": "spellbook", "title": "Spell Book: filters", "page": "battle", "needs": "caster", "panel": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] .ls-fold",
     "what": "Filters narrow the list down: Effect (Damage, Heal, Control…), Casting time, Concentration and more.",
     "why": "Find the spell for this moment without scrolling through all of them."},
    {"group": "spellbook", "title": "Damage and healing", "page": "battle", "needs": "caster", "panel": True, "all": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] .sb-avg-col",
     "what": "<b>Damage / Healing</b> is each spell's average, worked out from its dice and your sheet.",
     "why": "Compare spells at a glance. An average informs; it doesn't decide."},
    {"group": "spellbook", "title": "Cast at", "page": "battle", "needs": "caster", "panel": True,
     "open": [SPELLBOOK], "at": ".peek.open [data-spellbook] .ls-select:has([data-ls-lens])",
     "what": "<b>Cast at</b> works out every average again as if cast with a higher slot.", "why": "See what a higher slot adds before you spend it."},
    {"group": "creatures", "title": "Your creatures", "page": "battle", "needs": "creatures", "at": '[data-tour="creatures"]',
     "what": "The switch by your name shows Battle as one of your creatures: its Hit Points, Armor Class, actions to roll and "
             "when its turn comes, worked out with you. A familiar's Battle also sends it to the pocket dimension or brings it back.",
     "why": "It's a small character of its own, so it isn't forgotten in a fight."},
    {"group": "wildshape", "title": "Wild Shape: pick a form", "page": "battle", "needs": "druid",
     "at": '#battle-body [data-tour="ws-form"]',
     "what": "On the <b>Wild Shape</b> bar, a form's pill opens <b>Shift</b>: it spends a use and gives the Temporary Hit "
             "Points, and Battle is worked out for the beast. <b>Normal</b> (or Leave) brings you back.",
     "why": "Next, what that looks like. (The tour shows a preview; it won't shift you.)"},
    {"group": "wildshape", "title": "Wild Shape: you as the beast", "page": "battle", "needs": "druid", "swap": "form",
     "at": "#battle-body .ws-form",
     "what": "This is Battle in your first Wild Shape form: the beast's AC, Speed and saves in the top row, your own Hit "
             "Points and features, and its attacks in the columns. (A preview: nothing changes, and no one else sees it.)",
     "why": "D&D Beyond shows the beast's stat block. askdnd shows <b>you</b> as the beast."},
    {"group": "wildshape", "title": "The form's full page", "page": "battle", "needs": "druid", "swap": "form",
     "panel": True, "open": ["#battle-body .ws-form [data-modal-url]"], "at": ".peek.open",
     "what": "<b>Full form</b> opens its whole page: everything it can do, worked out for your character.",
     "why": "A second character sheet, for as long as you hold the shape."},
    {"group": "wildshape", "title": "Back to Normal", "page": "battle", "needs": "druid", "swap": "own",
     "at": "#battle-body .ws-chip",
     "what": "<b>Normal</b> opens Leave, a Bonus Action: your own numbers and columns return, and leftover Temporary Hit "
             "Points stay.",
     "why": "Each way is one window, with Undo."},
    {"group": "character", "title": "Reminders", "page": "battle", "needs": "character", "at": '[data-tour="reminders"]',
     "what": "<b>Reminders</b> keeps what you tend to forget beside your turn: anything you ring the bell for on Sheet "
             "(next), and your own (\"Ask the DM about the map\").",
     "why": "They're in front of you when they matter, mid-fight."},
    {"group": "character", "title": "Sheet: your whole character", "page": "sheet", "needs": "character",
     "at": '[data-tour="sheet"]',
     "what": "Everything from D&D Beyond in one view, laid out for play. Click any row for its rules and your note.",
     "why": "Actions, spells, forms, items and features in one place, next to your plans."},
    {"group": "character", "title": "The bell", "page": "sheet", "needs": "character",
     "at": '[data-tour="sheet"] button.pick.remind',
     "what": "The <b>bell</b> on a row adds it to the Reminders you just saw on Battle.", "why": "For the things that are easy to miss mid-fight: an Advantage, a resistance, a feature you rarely use."},
    {"group": "character", "title": "Inventory", "page": "sheet", "needs": "sync", "open": '[data-tab="t-items"]', "at": "#t-items .purse",
     "what": "Inventory starts with your coin purse, every coin you have, in bags too: press it to spend, gain or move coins "
             "between bags. <b>+ Add item</b> browses D&D Beyond's items, says what one would mean for you, and can pay "
             "from the purse. Open an item to equip, attune, use or give it.",
     "why": "All of it lands on your D&D Beyond sheet. A magic item's price is the DM's call."},
    {"group": "plan", "title": "Battle combos", "page": "plan", "needs": "character", "open": '[data-tab="t-combo"]',
     "at": '[data-tour="plan"]',
     "what": "<b>Combos</b> are your plans for a few turns together: the setup, then the payoff. <b>+ Battle combo</b> "
             "starts a new one.",
     "why": "Work it out between sessions; your combos show on Battle, ready for the fight."},
    {"group": "plan", "title": "A combo, turn by turn", "page": "plan", "needs": "character", "panel": True,
     "open": ['[data-tab="t-combo"]', '#t-combo [data-tour="combo"]'], "at": ".peek.open",
     "what": "Click a combo to read it: when to use it, what it needs, and each turn split into action, bonus action, "
             "reaction and movement. <b>Edit</b> changes it.",
     "why": "Everything you worked out, in the order you'll do it."},
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
    {"group": "plan", "title": "Shortlists", "page": "plan", "needs": "caster", "open": '[data-tab="t-spell-list"]',
     "at": '#t-spell-list .ls-views',
     "what": "Your Shortlist is the spells you're weighing up (and, for druids, Wild Shape forms on their own tab). "
             "<b>Shortlist</b> shows just those; <b>All</b> shows every spell you could pick, to compare.",
     "why": "Unprepare a spell and nothing is lost: it stays on your Shortlist with your note, ready for next time."},
    {"group": "plan", "title": "The bookmark", "page": "plan", "needs": "caster", "open": '[data-tab="t-spell-list"]',
     "at": '#t-spell-list :is(button.pick.fav, [data-ls-empty-view="fav"])',
     "what": "The <b>bookmark</b> on a spell puts it on your Shortlist, or takes it off. It's on every spell row here "
             "and on Sheet, next to the pin.",
     "why": "Bookmark a spell while you read about it; decide later what to prepare."},
    {"group": "party", "page": "party", "at": '[data-tour="party"]',
     "what": "<b>At a glance</b> has everyone's key numbers; <b>Spells</b> and <b>Items</b> pool the party's, filtered by what "
             "they do and who has them.",
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
        from app import ddb_bridge

        if ch and ddb_bridge.plays(db, ch):  # (Battle's − and +, Cast, Rest; Sheet's purse and + Add item)
            has.add("sync")
        from app import creatures, vtt
        from app.models import Campaign

        if ch and ch.campaign_id and vtt.on(db.get(Campaign, ch.campaign_id), "creatures") and creatures.in_play(ch, sheet):
            has.add("creatures")  # (the switch by the name on Battle)
        forms = wild_shape.known_forms(sheet)
        if forms:
            has.add("druid")
            swaps = {"form": f"/characters/{cid}/battle/preview?form={quote(forms[0]['name'])}",
                     "own": f"/characters/{cid}/battle/preview"}
    out = []
    for s in STOPS:
        if s.get("needs") and not set(s["needs"].split("+")) <= has:
            continue
        opens = [s["open"]] if isinstance(s.get("open"), str) else s.get("open") or []
        out.append({"group": s["group"], "name": GROUP_NAMES[s["group"]], "title": s.get("title") or GROUP_NAMES[s["group"]],
                    "url": pages[s["page"]], "at": s["at"], "open": opens, "panel": s.get("panel", False),
                    "example": s.get("example"), "all": s.get("all", False), "swap": swaps.get(s.get("swap")), "restore": swaps.get("own") if s.get("swap") else None,
                    "what": s["what"], "why": s["why"]})
    return out
