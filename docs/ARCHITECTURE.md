# askdnd v2 — Architecture (DRAFT)

_Last updated 2026-10-19 · Pairs with [BRIEF.md](BRIEF.md)_

## What changed since v1 (early 2025), and why it matters here

| v1 problem | What's different now | v2 approach |
|---|---|---|
| Retrieval pulled irrelevant pages | Models can **search iteratively with tools**: search, read a whole section, follow a cross-reference, search again. This replaces the old single search that returned the top few chunks. | The model gets tools (search rules, open a page or section, check the glossary) and works the question like a person flipping through the book. |
| Answers had no real analysis | Models reason much better and handle long contexts, so they can read full sections, not fragments. | Books are pre-converted into clean, structured sections (headings, page numbers, stat blocks) so the model reads whole rules, not 500-character chunks. |
| Chunking long PDFs was poor | Models can now **read PDF pages directly**, including tables, stat blocks and layout. | One-time conversion of each book into structured text with an AI model, keeping page numbers and page images (v1's best feature). |
| No official clarifications or community input | Model APIs have a **built-in web search** that can be limited to chosen sites. | Rules answers can check Sage Advice, errata and D&D Beyond forums, label them as such, and skip 2014-rules discussion. |
| No game context | Context windows are large and repeated context is cheap (**prompt caching**). | The whole campaign record and the asker's character fit directly in the prompt, so no vector database is needed for them. |
| Four parallel stores to maintain | — | One database for everything. |

## The stack (recommendation)

| Piece | Choice | Why |
|---|---|---|
| App | **Python (FastAPI)**: one app serving both the web pages and the API | Python is best for PDF and AI work and is what v1 used. One codebase and one deploy. |
| Pages | Server-rendered HTML with light JavaScript (HTMX) | No separate frontend project to set up. Works well on a phone. |
| Database | **Postgres on Railway** (with pgvector for rules search later) | Replaces Qdrant. Users, campaigns, story, characters and notes all live in one place. |
| Files | Existing S3 bucket, new `v2/` prefix | Page images. Kept separate from legacy's data. |
| Campaign pictures | Postgres (`entity_pictures`) | Portraits, maps and banners on campaign pages, resized to WebP (≤1200 px + a 320 px thumbnail). Small and few, so no S3 setup needed. Player characters fall back to their D&D Beyond portrait. |
| Campaign map | AideDD's Sword Coast atlas, embedded | The Map tab shows aidedd.org in a frame; place pages link to its markers. We store only marker names, never the map image. |
| Wild Shape Beasts | `app/data/beasts_2024.json` | SRD 5.2 stat blocks (CC-BY-4.0) for the 91 Beasts, with links to D&D Beyond's pictures; refreshed by `scripts/wild_shape_beasts.py`. Known forms' stat blocks come with the D&D Beyond sheet. |
| Version history | Postgres (`revisions`) | Every change to entries, glossary, sessions, key moments, other names, relationships, facts, characters, people and players' notes (old value, new value, who, how). Manage › History restores; Manage › Data undoes a whole import. Players' notes stay hidden from the DM there too. |
| Database backups | S3 `askdnd-ai/v2/backups/` | Nightly at 10:00 UTC, the `askdnd-backup` Railway cron service runs `scripts/backup_db.py`: every table in one gzipped JSON, 30 days kept. Its AWS key can only use `v2/backups/`. `scripts/restore_db.py` loads one into an empty database. |
| AI (cloud) | **Claude via the Anthropic API** | Tool use, web search, citations, PDF reading. |
| Spending limit | Anthropic Console limit + askdnd's own monthly limit (`campaigns.monthly_limit_usd`) | Set on Manage › Usage; once a month's spending reaches it, askdnd stops calling Claude and says why (`app/spending.py`). |
| Rule books | `private/books/` (gitignored) | Offline copies of the 2024 PHB, DMG and MM, saved from Brett's D&D Beyond sign-in for reference while building. The repo is public: only summaries (`docs/rules/`) and SRD data are committed. |
| Tests and deploys | GitHub Actions + Railway "Wait for CI" | Every push runs ruff (lint) and pytest with a throwaway Postgres; Railway deploys beta only when they pass. |
| AI (local) | **Ollama on Brett's Mac** (~30B-class model; test 2–3 on a real transcript) | The banter filter. Raw transcripts never leave the Mac. |
| Sign-in | **Google sign-in, limited to 5 approved emails** | No passwords to manage. A good setup skill to reuse. |
| Characters | D&D Beyond public character data (unofficial) | Could break without notice. Keep the last good copy so a failure doesn't break the app. |
| Hosting | **New Railway service** at `beta.askdnd.ai` | Legacy is untouched. Switch askdnd.ai over when v2 is ready. |

Note: API usage is **billed separately** from a Claude Pro/Max subscription (Anthropic Console, pay-as-you-go). For 5 users it should be modest; the monthly limit is set both in the Anthropic Console and on Manage › Usage.

## How the pieces fit

```
AFTER EACH SESSION (Brett)
  MacWhisper transcript ──► local filter script (Ollama, on Mac) ──► filtered transcript
        ──► upload on admin page ──► Claude extracts: recap, NPCs, places, quests, loot
        ──► Brett reviews/edits ──► published to campaign record

BEFORE A SESSION (everyone)
  Refresher page = "Previously on…" (campaign record)
                 + character briefing (D&D Beyond data + player notes, explained by Claude)

DURING A SESSION (phase 2)
  Rules question ──► Claude with tools: search books · read section · glossary ·
                     web search (Sage Advice / DDB) · this character · this campaign
                 ──► short answer + reasoning + cited pages with images
```

## What the first real transcript taught us (2026-08-29 session)
- **Echo duplicates everything.** Zoom audio leaks back into Brett's mic, so most lines appear twice under different speaker names. A simple de-duplication pass removed ~45% of the words. **Speaker labels can't be trusted** (DM narration often shows up as "Brett"). Fix at the source: Brett wears headphones during sessions. The pipeline still needs a de-dup step.
- **About half the session is off-topic.** There's a long pre-game catch-up, mid-game breaks and a scheduling chat at the end. The local filter has real work to do, and the cloud model should only ever see the game.
- **The DM's narration carries the story.** Extraction should weight it, and use player lines for decisions and plans.
- **Sessions open with a short player-led recap.** It's useful, but the DM's recap next session will be better for filling gaps.
- **D&D Beyond has a campaign journal** in the Maps VTT that players already write in. It's a possible extra source; check whether it's reachable.
- **Size:** about 63k raw words (≈350 KB) per ~4-hour session; about 34k after de-dup. That's well within one cloud extraction call.

## Data (in plain terms)
- **Campaign** → has sessions, story entries (NPCs, places, quests, items), players and characters.
- **Session** → date, approved recap, extracted events. Raw transcript is NOT stored.
- **Character** → its own name, owner, D&D Beyond ID (and the D&D Beyond campaign its sheet says it's in), latest good D&D Beyond copy, and the player's structured notes (battle combos, leveling strategy, personal quests, general notes), pins and reminders. It belongs to its player, not to a campaign, so all of this travels with it.
- **Campaign character** (`campaign_characters`, since 2026-10-22) → a character in a campaign: its story page there, when it joined and left, and the DM's Wild Shape ruling (what it keeps). One campaign at a time; leaving keeps the row and the story, so who was at the table stays answerable. Personal quests remember the campaign they were written in. The full plan (roles, house rules, more campaigns): `docs/plans/2026-10-21-data-organization.md`.
- **People and roles** (since 2026-10-23): a person's **tool role** (`users.access`: member or admin; owners are `ADMIN_EMAILS`) is about askdnd as a whole: admins set up people, characters, spending and imports. Their **campaign role** (`campaign_members.role`: DM, reviewer or player, with joined and left dates) is about one table. The DM includes Reviewer in their campaign. All rules are in `app/access.py` (`allows()`); Manage › People sets both and draws its chart from those rules.
- **More than one campaign** (since 2026-10-23): story pages live at `/c/<campaign>/…`; app/campaign_paths.py reads the prefix in front of every page, so routes don't repeat it, and old addresses of story pages redirect to the person's current campaign (`users.current_campaign_id`, set by the switcher in the menu bar or by opening a `/c/…` address). `web.campaign(db)` is that campaign. People see only campaigns they have a role in (admins see all). Admins create campaigns and move characters on Manage › Campaigns. The Claude spending limit is tool-wide (`tool_settings`).
- **Changes to the tool's knowledge** (since 2026-10-23) are rows that point at what they change, never edits: a **tool correction** (`tool_corrections`, an admin fixing how askdnd reads D&D Beyond, for everyone) and a **house rule** (`house_rules`, the DM's ruling for one campaign, e.g. one roll for all of Magic Missile's darts). `app/house_rules.py` works out the effective value: tool knowledge, then correction, then house rule. Manage › House rules is the DM's page; the roll window says "House rule" when one applies.
- **Visibility rule**: players' notes, pins and reminders are visible to players, hidden from the DM of the campaign the character is in now (even if that DM is an admin). Everything else is visible to everyone.
- **Book content** (phase 2) → sections with page numbers and page images.

## Build plan: 3 weeks to the first milestone

**Week 1 — Foundation (setup-heavy, which is the learning goal)**
- Clear `main`; new project skeleton; v2 CLAUDE.md and DECISIONS.md
- Railway: new service and Postgres, `beta.askdnd.ai` in Cloudflare, environment variables, Railway CLI
- Anthropic API key with a spending limit; Google sign-in with the 5-email allowlist
- Local filter script; test candidate Ollama models on the recorded session

**Week 2 — Campaign memory**
- Import the Google Doc notes and the filtered transcript
- **Transcript processor GUI** (Brett's request: as much GUI as possible, no Terminal): a local page on Brett's Mac, opened by a double-click launcher. Drag in the MacWhisper JSON → Filter (progress bar) → review cuts with Keep/Cut toggles → "Send to askdnd" uploads only the filtered text to beta. It runs locally because Ollama and the raw transcript stay on the Mac.
- Extraction, a review/edit screen for Brett, the campaign record, the "Previously on…" page

**Next up (as of 2026-10-15, Week 2 status)**
- Done: database and migrations, campaign import, Google Docs notes sync, local transcript Processor GUI, Claude extraction, review page (questions, recap, key moments, suggestions with undo), new design and navigation, Previously on… / Sessions / Campaign pages.
- To do: Brett drafts and publishes Sessions 17–29 from notes; wire **Send to askdnd** from the Processor for the Aug 29 transcript; **Usage** page (app-tracked costs and balance estimate); **Reviewer** role for the DM; **Add Session** for gaps (design to be discussed first; see DECISIONS.md).

**Week 3 — Character briefing and launch to the table**
- Done (2026-10-16): Battle · Character · Party pages, stars and reminders (only the character's player; hidden from the DM), Game Mode, Manage › People with access levels and who plays which character.
- Done (2026-10-18): structured player notes on the Character page (Battle combos over several turns, Leveling strategy, Personal quest, General notes), replacing Notes sync of character Google Docs; visible to players, hidden from the DM.
- Done (2026-10-16): D&D Beyond import (3a). Characters page with a card per character and a full readable sheet; reviewers link and refresh; last good copy kept in `character_snapshots`; `app.characters.character_summary()` is the input for briefings.
- Pull the 5 characters from D&D Beyond; plain-language briefings (wild shapes, spells, features)
- Seed notes from Brett's doc; enforce the visibility rule; phone polish
- Invite the table; dry run before the session

**Status (2026-10-19)**
- Done since: Map tab; Wild Shape planner (forms adjusted for the druid's stats, Moon rules, kept items and traits); Manage regrouped with an access chart; import preview and undo; version history; nightly S3 backups with alerts; tests and lint before every deploy; monthly spending limit.
- Next: Brett drafts and publishes the remaining recaps; plan rules answers (the third core feature) in the planning chat; navigation simplification and D&D Beyond campaign auto-discovery need Brett's input (see `docs/reviews/2026-10-19-app-review.md`).

**Phase 2 (after the session)**
- Rules companion (book conversion, tool-using search, Sage Advice and community input, page images)
- Per-player chat that remembers character reasoning
- Move askdnd.ai to v2; retire or clean up legacy

## Getting more accurate over time (the feedback loop)
Brett reviews every AI-drafted recap before the table sees it, and every correction is kept and reused:
- **Campaign glossary.** Proper nouns with correct spellings and short descriptions (Lillippi, Babbletree, Ashardalon, Mount Hotenow…). Transcription will mangle fantasy names; the glossary is fed to every extraction so mistakes stop recurring. It's seeded from the existing notes.
- **Correction log.** Each edit is saved with what the AI got wrong. Recurring kinds of mistakes become standing instructions for future extractions, e.g. "player banter about real-world jobs is never story."
- **Speaker map.** MacWhisper speaker labels are mapped to people and characters once per campaign.
- **Facts vs. theories.** Brett's notes mix events with his speculation (marked with ←). Extraction keeps them separate, so recaps state facts and list theories as open threads.

## Decided (2026-10-14)
- Everyone has a Google account → Google sign-in with a 5-email allowlist.
- Brett reviews each recap before publishing, and his corrections feed future extractions (above).
- Stack: Python/FastAPI.
- Personal notes and transcripts never go in the git repo; they're imported into the app's database.
