# askdnd v2: Architecture

_Rewritten 2026-11-02 as today's map (it was the 2026-10-14 draft of the first three weeks; that plan is in git and
the roadmap's Done list). Pairs with [BRIEF.md](BRIEF.md). The picture of the services and who changes each is
[stack.html](stack.html); where every page and module is, CLAUDE.md › Where things are; what's next,
[roadmap.html](roadmap.html) and [plans/2026-11-02-vtt-build-plan.md](plans/2026-11-02-vtt-build-plan.md)._

## The shape in one paragraph

One FastAPI app (server-rendered Jinja pages with HTMX and one app.js) and one Postgres database on Railway, at
askdnd.ai and beta.askdnd.ai (the same service; legacy.askdnd.ai is the old app). Every open page keeps a WebSocket to
its campaign, fed through Postgres, so a change shows on every screen. A Chrome extension in each player's browser, the
**bridge**, sits in their D&D Beyond tab and makes askdnd's changes on their sheet, then askdnd reads the sheet back to
confirm. Claude (the Anthropic API) drafts recaps and explains characters; raw session audio and transcripts never
leave Brett's Mac. Files go to S3 under `v2/`, errors to Sentry, a backup to S3 every night.

## Who owns which data

| Owner | What | How askdnd treats it |
|---|---|---|
| **D&D Beyond** | Each character's sheet: build, level, spells known and prepared, inventory and coins, and its play state (hit points, slots, resource uses, the 15 conditions and Exhaustion, Heroic Inspiration, death saves) | askdnd keeps the last good copy (`character_snapshots`) and never edits it directly. A change goes through the bridge and counts only once a read shows D&D Beyond has it. While it's on its way, pages show it as made, marked ↻ (`ddb_bridge.as_shown`). |
| **askdnd** | The campaign: sessions, recaps, entries, glossary, quests, relationships, history; people, roles and campaigns; Table rolls; Concentration and askdnd's own conditions (item effects, how long one lasts); the fight as heard from D&D Beyond's VTT (`Campaign.fight`) and its reminders; players' notes, pins and shortlists; house rules and tool corrections; dice settings | Postgres. Every edit to story and notes is a revision (Manage › History). |
| **askdnd, coming with the VTT** | Fights askdnd runs, creatures and their hit points and conditions (they have no D&D Beyond sheet), maps and tokens | Their own tables, one row per fighter, changed row by row under the fight's lock, with a log for the DM's Undo (architecture review, Nov 2). Maps in S3. |
| **The rules** | The SRD 5.2.1 as data in git (`app/data/srd/`); books the DM owns (the Monster Manual) only in the database (`book_entries`); a campaign's own creations (`campaign_content`) | Read through `rules_data.catalog/find`: the campaign's own, then its books, then the SRD. |
| **Brett's Mac** | Raw transcripts and their local filter (Ollama); offline copies of the 2024 books (`private/books/`) | Never in git or the cloud. Only the filtered game text is sent for extraction. |
| **The Mac Mini** | Three test seats (real Chrome, real D&D Beyond test accounts) | The live test, by hand or every night at 4:00; a miss goes to Sentry. Never a real player's sheet. |

## How a change travels

**On askdnd's own data** (a roll, a recap edit, a condition's timer): the page posts to a route; the route changes the
database and calls `realtime.announce(db, campaign, kind, …)`; after the commit, Postgres NOTIFY carries "this kind
changed" to every copy of the app, which tells every page at that campaign over its WebSocket; each page fetches what
changed at its usual address (which decides who sees what) and swaps it in place (app.js `showInPlace`). The message
carries data only where waiting for a fetch would be wrong: a roll the whole table sees carries what throwing its dice
takes, and the VTT's token moves will (vtt-roadmap › Live connection).

**On a D&D Beyond sheet** (Cast, a potion, Hit points, Prepare, Give):
1. The route checks the sheet can be reached now (its own sheet open with the extension, or the DM's browser as a
   backup), adds a **change** (`BridgeIntent`) and answers with `deliver`, so the page tells the extension at once.
2. The extension asks for the character's **outbox**: askdnd builds one batch from every waiting change, on its copy
   of the sheet if under a minute old, else on a fresh read.
3. The extension makes each request on D&D Beyond from the sheet's own page, checking every total against D&D Beyond
   the moment before writing, and reports back.
4. askdnd **reads the sheet back** and settles each change: live (D&D Beyond has it), again (D&D Beyond was slow), or
   stopped and listed to make by hand. Nothing is ever written over a number D&D Beyond changed meanwhile.

**From D&D Beyond** (a player changes their sheet there, or rolls there): the extension hears the save and asks askdnd
to read the sheet; the read logs what changed (`ddb_bridge.seen`), settles any batch it confirms, and announces it.
Rolls made on D&D Beyond, and the DM's monster rolls in the game log, come into Table rolls. On an open VTT page the
extension follows the fight (order, round, whose turn) and reports it; askdnd only listens to D&D Beyond's VTT.

## Keeping requests out of each other's way

- **Reading D&D Beyond never holds the database** (Nov 2, after it ran beta out of connections):
  `characters.read_released` commits what the request did so far, then reads; the caller takes its lock again,
  checks nothing moved meanwhile, and `characters.store` keeps the read unless a newer copy was kept first.
- **One batch at a time per character**: `ddb_bridge._lock` holds the character's row (FOR NO KEY UPDATE, not FOR
  UPDATE: the stronger lock deadlocked with new rows pointing at the character, Oct 29).
- **One fight writer at a time per campaign**: `fight.lock`, the same kind of lock on the campaign's row; every open
  VTT page reports each turn, and two saved at once doubled reminders (Nov 2).
- **Routes that use the database are plain `def`** and run on worker threads, so the one event loop stays free for
  the live connections. The pool is 10 connections plus 20 more when busy; beta's Postgres allows 100.
- **More than one copy of the app works**: the live connection goes through Postgres, locks are in Postgres, and the
  in-memory caches (roles for 10 seconds, D&D Beyond's item and spell lists) expire on their own.

## The stack

| Piece | Choice | Why |
|---|---|---|
| App | **Python (FastAPI)**, managed with uv: one app for the pages and the API | Python suits the PDF and AI work; one codebase, one deploy. |
| Pages | Server-rendered Jinja with HTMX and `app/static/app.js` | No separate frontend project; works on a phone. The VTT's map gets its own script, loaded only on the table page. |
| Database | **Postgres on Railway** | Everything in one place; Alembic migrations in `migrations/`. |
| Live connection | WebSockets (`/live/connect`) fed by Postgres NOTIFY/LISTEN (`app/realtime.py`) | Reaches pages on any copy of the app; no extra service. |
| The bridge | Chrome extension `extension/askdnd-bridge/`, unlisted on the Chrome Web Store | D&D Beyond has no API for writing; the player's own signed-in tab makes the change, as their sheet would. Packaged by `scripts/build_extension.py`. |
| Files | S3 `askdnd-ai/v2/files/` (a folder locally), through `app/files.py` | Keys `<campaign id>/<sha256>.<ext>`, listed in `stored_files`, served by each feature's own route after its access check, never public links. The app's AWS key reads and writes `v2/files/`, never deletes. |
| Backups | The `askdnd-backup` Railway cron service, nightly to S3 `v2/backups/` | Every table as gzipped JSON, 30 days kept; `files.sweep()` checks files and removes ones unused for 35 days. `scripts/restore_db.py` loads one into an empty database. |
| AI (cloud) | **Claude via the Anthropic API** | Extraction, recaps, briefings. Every call checks the monthly limit first (`app/spending.py`, Manage › Usage). |
| AI (local) | Ollama on Brett's Mac | The transcript filter. Raw transcripts never leave the Mac. |
| Sign-in | Google, for the people askdnd knows (Manage › Accounts; owners in `ADMIN_EMAILS`) | No passwords to keep. Roles per campaign; every rule in `app/access.py`. |
| Rules data | SRD 5.2.1 in `app/data/srd/` (built by `scripts/srd_import.py`); books in `book_entries` | Public data in git, private books only in the database (uploaded on Manage › Backups and imports). |
| Dice | @3d-dice/dice-box-threejs, vendored in `app/static/vendor/` | Thrown 3D dice made to land on askdnd's numbers. |
| Errors | Sentry (project askdnd-v2), pages' errors through `POST /errors/page` | Private by default: no bodies, cookies, query strings, emails or names. |
| Tests and deploys | GitHub Actions (Server tests, Browser tests) + Railway "Wait for CI"; main protected (both must pass on an up-to-date branch) | `scripts/deploy_check.py` follows each merge to beta. |
| Hosting and DNS | Railway service `askdnd-v2`; Cloudflare DNS, records written by Railway | askdnd.ai and beta.askdnd.ai; www redirects to askdnd.ai. |

## Data (in plain terms)
- **Campaign** → sessions, story entries (NPCs, places, quests, items), members with roles, characters, house rules,
  its books, its VTT pieces, and the fight heard from its D&D Beyond game.
- **Session** → date, approved recap, extracted events. Raw transcripts are never stored.
- **Character** → its own name, owner, D&D Beyond id (and the D&D Beyond campaign its sheet is in), the last good copy
  of its sheet, its player's notes, pins and reminders, askdnd's own conditions and Concentration. It belongs to its
  player, not a campaign, so all of this travels with it. A **test copy** (`copy_of_id`) shares the sheet and has its
  own play state, and the bridge never writes through it.
- **Campaign character** (`campaign_characters`) → a character at one table: its story page there, when it joined and
  left, the DM's Wild Shape ruling, the player's choices of item kinds. Leaving keeps the row and the story.
- **People and roles** → a tool role (`users.access`: member or admin) and a role per campaign (`campaign_members`:
  DM, reviewer or player, with dates). The DM includes Reviewer in their campaign.
- **The bridge's records** → each change (`bridge_intents`), each batch (`bridge_batches`) and a log of what changed
  where (`bridge_log`), so a change's whole life can be followed.
- **Corrections** → rows that point at what they change, never edits: a tool correction (admins, everyone) and a house
  rule (the DM, one campaign). `app/house_rules.py` works out the value top down.
- **Visibility** → players' notes, pins and reminders are visible to players and hidden from the DM (even an admin
  DM); everything else is visible to everyone at the table.

## What the first real transcript taught us (2026-08-29 session)
- **Echo duplicates everything.** Zoom audio leaks back into Brett's mic, so most lines appear twice under different
  speaker names; de-duplication removed about 45% of the words, and speaker labels can't be trusted. Headphones fix it
  at the source; the pipeline still de-duplicates.
- **About half the session is off-topic** (catch-up, breaks, scheduling): the local filter has real work to do, and
  the cloud model only ever sees the game.
- **The DM's narration carries the story**; player lines carry decisions and plans.
- **Size:** about 63k raw words per ~4-hour session, about 34k after de-duplication: one extraction call.

## Getting more accurate over time (the feedback loop)
Brett reviews every AI-drafted recap before the table sees it, and every correction is kept and reused: a **campaign
glossary** of proper nouns fed to every extraction, a **correction log** whose recurring kinds become standing
instructions, a **speaker map** per campaign, and **facts kept apart from theories** (Brett's speculation becomes open
threads, not recap).

## Decided (2026-10-14, still standing)
- Google sign-in for the people askdnd knows.
- Brett reviews each recap before publishing; his corrections feed future extractions.
- Python/FastAPI.
- Personal notes and transcripts never go in git; campaign data lives in the database.
