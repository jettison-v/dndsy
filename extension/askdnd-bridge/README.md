# askdnd bridge

askdnd's panel beside your own D&D Beyond sheet. It hears the sheet's changes the moment they save, and makes
askdnd's changes there, as you; askdnd counts a change only once it has read it back from D&D Beyond
(app/ddb_bridge.py; docs/mockups/ddb-overlay.html; the requests are listed in app/ddb_fields.py). It covers what a
player changes in play:
- hit points and temporary hit points, Death Saving Throws, Heroic Inspiration, conditions and Exhaustion, Hit Dice
  (D&D Beyond takes those only as a Short Rest);
- spell slots, Pact Magic slots, limited uses;
- an item's count, equipped, attuned, charges, coins (absolute amounts, never the sheet's +/− deltas), adding another
  of an item, removing one, moving it into or out of a container;
- rolls made on the sheet come into Table rolls marked "on D&D Beyond"; and the player's askdnd rolls go into D&D
  Beyond's game log from their open sheet (0.9.3, app/gamelog.py), as askdnd's own: source "askdnd" and ⓐ after the
  name, never passed off as D&D Beyond's.
Left out: experience points, custom names and custom items. Prepared spells come with casting (roadmap Phase 2).

After askdnd changes the character, every open copy of the sheet shows D&D Beyond's numbers in place, through the
sheet's own store (no reload, no request but the read the sheet makes when it opens); only if D&D Beyond's page has
changed so that doesn't work does the sheet reload.

Where it works: on askdnd's own sites (beta.askdnd.ai, askdnd.ai) and, from this folder, askdnd on your own
computer (http://localhost:8000); on the characters of a campaign that has the bridge switched on (Manage › Settings ›
Virtual tabletop › D&D Beyond bridge; a test campaign always has it), never on a test copy (it shares a real
character's sheet). askdnd itself runs it only where `DDB_BRIDGE=1` (beta and your own computer).

The table adds it from the Chrome Web Store (unlisted: the link is in app/config.py `BRIDGE_EXTENSION_URL` and Help ›
FAQ). For working on it, load this folder instead:
1. chrome://extensions, switch on **Developer mode** (top right).
2. **Load unpacked**, and pick this folder (`extension/askdnd-bridge`). Remove the store's copy first, or the two
   both answer.
3. Sign in to askdnd (beta, or http://localhost:8000) and to D&D Beyond, in the same Chrome. Opening any askdnd page
   connects the extension to that askdnd (it gets its own key, so it works even when Chrome blocks third-party
   cookies); after askdnd restarts, or to switch between beta and your computer, open an askdnd page there again.
4. Open your character's D&D Beyond sheet: the askdnd panel slides in on the left (the red **askdnd** tab brings it
   back). It only shows: no buttons sit over D&D Beyond's own. Make changes in askdnd (its own tab is
   `/characters/<id>/bridge`) or on the sheet itself.

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

## Publishing to the Chrome Web Store

1. Raise `version` in manifest.json (the store refuses a version it already has), then
   `uv run python -m scripts.build_extension`: it writes `private/extension/askdnd-bridge-<version>.zip`, this folder
   without localhost.
2. On the developer dashboard (https://chrome.google.com/webstore/devconsole), the item › **Package** › **Upload new
   package**, pick the zip, then **Submit for review**. The table's Chrome updates it on its own once it's approved.

The listing (first upload: **+ New item**, then fill in each tab with these):
- **Store listing.** Name: askdnd bridge. Summary: "Keeps your D&D Beyond sheet and askdnd in step, both ways: hears your
  sheet's changes and makes askdnd's there, as you." Description: the first paragraph of this file, then "For the
  players of a campaign on askdnd that uses it. Not affiliated with Wizards of the Coast or D&D Beyond." Category:
  Tools. Language: English. Icon: icons/icon-128.png. Screenshot: private/extension/listing-screenshot.png (1280×800).
- **Privacy.** Single purpose: "Keep a player's own D&D Beyond character sheet and askdnd, their table's companion app,
  showing the same numbers." Permissions: *storage*, its key to askdnd until Chrome closes; *alarms*, a check every 30
  seconds while someone is using askdnd or a sheet; *host permission dndbeyond.com*, to hear the player's sheet save
  and to make askdnd's changes there with the sheet's own requests; *host permission askdnd.ai and beta.askdnd.ai*, to
  talk to askdnd. Remote code: No. Data: website content (the character sheet's numbers and rolls), sent to askdnd only;
  not sold, not used for anything else, not used for credit. Privacy policy: https://beta.askdnd.ai/help?tab=about#bridge-privacy
- **Distribution.** Visibility: **Unlisted**. Regions: all.
