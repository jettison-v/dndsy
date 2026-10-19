# askdnd v2 — whole-app review (2026-10-19)

askdnd was built feature by feature over about a week. This review steps back and looks at the whole thing: what's solid, what's missing from the original plan, and what to tidy. Each suggestion says how big it is (S = under an hour, M = a session, L = several sessions) and who's needed.

## What's working well

- **Privacy rules are in one place.** Who can see and do what lives in one function (`access.allows`), and the People page's chart is drawn from it. Players' notes, stars and reminders never reach the DM, including in History.
- **Nothing is lost silently any more.** Version history records edits with who and how; imports are previewed and can be undone; the whole database is backed up nightly to S3 (tested restore).
- **D&D Beyond is used carefully.** The last good copy is kept, failures show the old copy with a warning, and players' private notes are stripped before anything is stored.
- **Rules come from the books.** Druid and Wild Shape rules, rule-term hovers and the Beast list were checked against the 2024 PHB, DMG and MM; the public repo holds only summaries and SRD data.
- **Tests:** 242 automated tests cover the rules, privacy and importing.
- **Setup knowledge is written down:** DECISIONS.md and SETUP_LOG.md record why things are the way they are.

## Gaps against the original plan (docs/BRIEF.md)

| Planned | Status |
|---|---|
| Pre-session refresher: story recap | Built, but only Sessions 17 and 19 are drafted on beta; 12 sessions wait (about $1.43 to draft them all) |
| Pre-session refresher: character briefing in plain language | Battle and Character pages cover the facts; the Claude-written briefing ("here's what you can do and why you built it this way") isn't built |
| Campaign memory from transcripts | Built (Processor on the Mac → filtered text → drafts). Only the Aug 29 transcript exists |
| **Rules answers that cite book pages** | **Not started.** The third of the three core features |

## Suggestions

### High priority

1. ✅ *Done 2026-10-19.* **Run the tests automatically before every deploy** (S, me + one Railway click). Today, pushing `main` deploys beta even if a test would fail; tests only run when I run them here. Add a GitHub Actions workflow that runs the tests on every push, and turn on Railway's "Wait for CI" so beta only deploys when they pass. A habit worth reusing on every project.
2. ✅ *Done 2026-10-19.* **Know that backups and other jobs ran** (S). The nightly backup could fail quietly. Have it record each run in the database so the Manage overview shows "Last backup: 6 hours ago" in red if a night is missed. The same card can flag D&D Beyond refreshes that keep failing.
3. ✅ *Done 2026-10-19.* **Close the version-history gaps** (S–M). History covers names, descriptions, quests, glossary, sessions, characters, people and players' notes. It doesn't yet cover key moments (story events), relationships, other names and spellings, or facts from the table, and undoing a recap suggestion deletes rows without keeping them. Add those so "anything unrecoverable has history" is fully true.
4. **Draft and publish the remaining recaps** (M, Brett). The campaign record is only as good as what's published; 12 sessions are waiting. This also feeds the campaign path idea later.
5. **Decide when to build rules answers** (L, planning chat). It's the remaining core feature, and the books are now available offline in `private/books/`. Worth a planning conversation: scope, which questions, how page citations should look, cost.

### Medium priority

6. **Tidy the code built in layers** (M, me). Same behaviour, easier to change:
   - One shared helper for "the campaign" (three copies today) and one for "sign in and check permission" (eleven small variants).
   - Split the largest files: `ddb.py` (1,400 lines: fetching, cleaning and parsing together) and `character_pages.py` (Battle, Character, Party and Wild Shape routes together).
   - Group `app.css` by page (it grew by appending) and make the browser pick up new CSS and JS automatically instead of the hand-edited `?v=50` numbers.
   - Remove leftovers: the unused `character_notes` table and the old `is_admin` flag on people.
7. **Bring the docs up to date** (S, me). `ARCHITECTURE.md`'s build plan still lists "player notes" and "Notes sync" as to-dos; CLAUDE.md doesn't mention Manage, History or backups. Future sessions read these first, so stale docs cost time.
8. **An app-level spending cap** (S). CLAUDE.md asks for a monthly limit. The Anthropic workspace limit exists; askdnd could also refuse new drafts past a monthly amount you set on the Usage page and say why, instead of failing mid-draft.
9. **Simplify navigation** (M, with Brett). The top bar has seven items and the Character page nine tabs. Ideas: fold Party into Battle and Character as a switcher; group Character's tabs (Play: Actions, Spells, Wild Shape · Sheet: Inventory, Features, Skills, Situational · About: Background, Notes); a phone pass after.
10. **Use more of the D&D Beyond campaign** (S–M). See below.

### Lower priority

11. **Drafting runs inside the website** (M, later). Claude drafts run in a background thread of the web server; a deploy interrupts them (handled, but you have to re-run). The backup job showed the pattern for a separate worker if drafting grows.
12. **Plan the askdnd.ai switch and legacy shutdown** (M, Brett decides). The old app still serves askdnd.ai with its own S3 data and services; decide when v2 takes over, what to keep from legacy, and what to turn off (cost).
13. **Accessibility check** (S). Keyboard use and contrast across pages, especially the side panels and modals.
14. **Campaign path on the map** (on hold; see DECISIONS.md).

## What the D&D Beyond campaign offers

Checked on 2026-10-19 with Brett's sign-in (campaign "The Adventure Begins", DM The_Merriest).

| What | Available to askdnd? | Possible use |
|---|---|---|
| Campaign name, DM's username, the four characters and their D&D Beyond IDs | Yes, in each character's public data | Find and link every character automatically from the campaign (no pasting links); notice when someone joins or leaves |
| **Lillippi** (level 10 Tiefling Bard, an unassigned character Mary made) | No: her sheet is private | If Mary makes it public, askdnd can show her like a party member (Battle, Character) |
| Characters' Notes tab (allies, enemies, organizations, other notes) | Yes, but askdnd deliberately hides it today | Could seed the new player notes, or suggest people and places for the campaign record, with each player's agreement |
| **Game Log** (every roll: who, which check or attack, result, time) | Only when signed in; askdnd's server can't read it without storing a D&D Beyond login, which it shouldn't | Session timelines that line up with transcripts, "roll of the night", attendance. Possible later through the Mac (like the Processor) |
| Campaign description and public notes | Yes, but empty | Mary could write there and askdnd would show it |
| Maps VTT, encounters, content sharing | DM-only or not data | No clear use yet |
