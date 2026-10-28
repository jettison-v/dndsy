# askdnd bridge (a local proof)

askdnd's panel beside your own D&D Beyond sheet. It hears the sheet's changes the moment they save, and makes
askdnd's changes there, as you; askdnd counts a change only once it has read it back from D&D Beyond
(app/ddb_bridge.py; docs/mockups/ddb-overlay.html; the requests are listed in app/ddb_fields.py). It covers what a
player changes in play:
- hit points and temporary hit points, Death Saving Throws, Heroic Inspiration, conditions and Exhaustion, Hit Dice
  (D&D Beyond takes those only as a Short Rest);
- spell slots, Pact Magic slots, limited uses;
- an item's count, equipped, attuned, charges, coins (absolute amounts, never the sheet's +/− deltas), adding another
  of an item, removing one, moving it into or out of a container;
- rolls made on the sheet come into Table rolls marked "on D&D Beyond" (only heard; nothing goes into D&D Beyond's
  game log).
Left out: experience points, custom names and custom items. Prepared spells come with casting (roadmap Phase 2).

After askdnd changes the character, every open copy of the sheet shows D&D Beyond's numbers in place, through the
sheet's own store (no reload, no request but the read the sheet makes when it opens); only if D&D Beyond's page has
changed so that doesn't work does the sheet reload.

Load it (Chrome):
1. chrome://extensions, switch on **Developer mode** (top right).
2. **Load unpacked**, and pick this folder (`extension/askdnd-bridge`).
3. Sign in to askdnd on http://localhost:8000 and to D&D Beyond, in the same Chrome. Opening any askdnd page connects
   the extension (it gets its own key to askdnd, so it works even when Chrome blocks third-party cookies); after
   askdnd restarts, open an askdnd page again.
4. Open your character's D&D Beyond sheet: the askdnd panel slides in on the left (the red **askdnd** tab brings it
   back). It only shows: no buttons sit over D&D Beyond's own. Make changes in askdnd (its own tab is
   `http://localhost:8000/characters/<id>/bridge`) or on the sheet itself.

What it may do: only the D&D Beyond requests in the list (ddb-page.js `WRITES`, the same as askdnd's), only for the
sheet that's open, only for a change someone made. It stores nothing; D&D Beyond gives the sheet a 5-minute token from your own sign-in. Unofficial: D&D Beyond
offers no way for other tools to change a sheet, so a change on their side can break it. When it does, askdnd shows
"Not on D&D Beyond yet", never a wrong number.

It's awake whenever someone is using it, with no switch: opening or using an askdnd page or a D&D Beyond sheet keeps
it on for 30 more minutes, and Game Mode keeps it on for the whole game (6 hours, with a warning and Keep going). A
change saved on a D&D Beyond sheet is always recorded. Asleep, only its background check of D&D Beyond (every 30
seconds) stops; the corner badge says "asleep". Admins change the timers on Manage › askdnd › D&D Beyond bridge.

After D&D Beyond changes its sheet, an admin runs Manage › askdnd › D&D Beyond bridge › **Check everything**: every
kind of change the test character can take, out and back, each confirmed.

After changing these files, reload the extension (chrome://extensions, the ↻ on askdnd bridge) and then reload any open
D&D Beyond sheet: a sheet opened before the reload can't take changes (askdnd tries another copy of the sheet, and
after 3 tries lists the change to make by hand).
