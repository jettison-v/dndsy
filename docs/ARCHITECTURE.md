# askdnd v2 — Architecture (DRAFT)

_Last updated 2026-10-14 · Pairs with [BRIEF.md](BRIEF.md)_

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
| AI (cloud) | **Claude via the Anthropic API** | Tool use, web search, citations, PDF reading. |
| AI (local) | **Ollama on Brett's Mac** (~30B-class model; test 2–3 on a real transcript) | The banter filter. Raw transcripts never leave the Mac. |
| Sign-in | **Google sign-in, limited to 5 approved emails** | No passwords to manage. A good setup skill to reuse. |
| Characters | D&D Beyond public character data (unofficial) | Could break without notice. Keep the last good copy so a failure doesn't break the app. |
| Hosting | **New Railway service** at `beta.askdnd.ai` | Legacy is untouched. Switch askdnd.ai over when v2 is ready. |

Note: API usage is **billed separately** from a Claude Pro/Max subscription (Anthropic Console, pay-as-you-go). For 5 users it should be modest; we'll set a monthly spend limit.

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
- **Character** → owner, D&D Beyond ID, latest snapshot, notes ("why I built it this way").
- **Visibility rule**: character notes are visible to players, hidden from the DM. Everything else is visible to everyone.
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
- **To do: player notes on the Character page.** Bring each player's character notes ("why I built it this way", from Notes sync) into the Character view, visible to players and hidden from the DM, like stars and reminders.
- Done (2026-10-16): D&D Beyond import (3a). Characters page with a card per character and a full readable sheet; reviewers link and refresh; last good copy kept in `character_snapshots`; `app.characters.character_summary()` is the input for briefings.
- Pull the 5 characters from D&D Beyond; plain-language briefings (wild shapes, spells, features)
- Seed notes from Brett's doc; enforce the visibility rule; phone polish
- Invite the table; dry run before the session

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
