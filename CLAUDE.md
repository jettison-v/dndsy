# askdnd v2

A companion app for one D&D 2024 table (4 players + DM, playing on Zoom with D&D Beyond). It does three things: a **pre-session refresher** (story recap plus character briefing), **campaign memory** built from session transcripts, and **rules answers** that cite book pages. Read these before significant work:

- `docs/BRIEF.md`: what we're building and why (the product)
- `docs/ARCHITECTURE.md`: stack, data, build plan
- `docs/DECISIONS.md`: running decision log. **Append to it** whenever a meaningful decision is made in a session (one line: date, decision, why).

## Working with Brett
- Brett is the owner and is not a developer. His goal is to **learn project setup** (repos, branches, hosting, domains, environments, secrets, tooling) so he can reuse it on future projects. Learning to code is not a goal.
- He works in the **Code tab of the Claude desktop app** (local folder `~/Code/dndsy`) in Auto mode. Handle the code; don't explain it line by line. Planning and product discussion happen in a separate Claude Project chat; decisions from there land in `docs/`.
- At each setup milestone, give a **short plain-English recap**: what was set up, why, and anything he'd do the same way on a new project. Append the recap to `docs/SETUP_LOG.md`.
- When something needs Brett (a dashboard click, a login, a DNS record), say exactly where to click and what to enter. Then wait.
- Prefer CLIs (`railway`, `gh`) over dashboards when they can do the job.

## Repo and environments
- `main` = v2. Tag `v1-legacy` and branch `legacy` = the old app. A read-only copy is at `../dndsy-legacy`. Use it as reference (PDF→page-image pipeline, structure analysis, link extraction), but don't copy its architecture.
- **Never modify the `legacy` branch, the legacy Railway service, legacy Qdrant collections, or S3 paths outside `v2/`.** Legacy serves askdnd.ai and legacy.askdnd.ai.
- v2 deploys to a **new Railway service** (in the existing `askdnd` Railway project) at `beta.askdnd.ai`. DNS is in Cloudflare (proxied records). askdnd.ai moves to v2 only when Brett says so.
- Pushing to `main` deploys to beta. That's fine, but keep `main` working.

## Where things are (as of 2026-10-19)
- **Manage** (`/manage`, app/manage.py): one overview of admin and reviewer pages (DM guide, Inbox, Recaps, History, House rules, People with the access chart, Characters with tool corrections, Usage, Data, Design system). Access rules live only in `app/access.py` (`allows()`).
- **Version history** (app/history.py): records edits automatically; Manage › History restores; imports are previewed and can be undone.
- **Backups**: the `askdnd-backup` Railway cron service dumps the database to S3 `v2/backups/` nightly; `scripts/restore_db.py` restores into an empty database.
- **Local data**: the local app uses `askdnd_beta`, a copy of beta from the newest backup (`scripts/pull_beta.sh` refreshes it; stop the server first). Local changes never reach beta. Automatic drafting is off locally (`AUTO_DRAFT`).
- **Spending limit**: Manage › Usage (app/spending.py); every Claude call checks it first.
- **Rule books**: offline copies in `private/books/` (gitignored). **The repo is public**: never commit book text or Monster Manual stat blocks; summaries go in `docs/rules/`, SRD data in `app/data/`.
- Shared page helpers (the campaign, sign-in checks, message pages): app/web.py. D&D Beyond: app/ddb.py (fetching and cleaning) and app/ddb_sheet.py (parsing the sheet).

## Stack
Python (current stable) managed with **uv** · FastAPI serving server-rendered pages (Jinja + HTMX) and the API · Postgres on Railway (pgvector later) · Claude via the Anthropic API · Ollama on Brett's Mac (M4 Pro, 48 GB) for the local transcript filter · Google sign-in limited to an email allowlist · D&D Beyond public character data (unofficial: cache the last good copy and fail gracefully) · S3 `v2/` prefix for page images.

## Privacy and data rules (important)
- **Raw transcripts never go to a cloud service or into the database.** They're filtered locally (Ollama) on Brett's Mac first; only the filtered game content is sent for extraction, and only the extracted story is stored.
- **Never commit** `.env*`, transcripts, campaign notes, character notes, or exports. Campaign data lives in the database, not in git. Keep `.gitignore` strict (`transcripts/`, `private/`, `*.docx`, `.env*`).
- Visibility: **character notes are visible to players but NOT the DM.** Everything else is visible to everyone at the table. Exceptions, visible to everyone including the DM (Brett, 2026-10-17): a character's **D&D Beyond Background tab and backstory** (personality traits, ideals, bonds, flaws, appearance, backstory) and players' **item notes on D&D Beyond**. The rest of D&D Beyond's Notes tab (allies, enemies, organizations, other notes) is never stored. None of the player's writing goes into test fixtures or git (item notes live only in `character_item_notes`; `scripts/ddb_fixture.py` strips traits and notes).
- Set and respect a monthly spend limit on the Anthropic API.

## Product rules
- **Inform, don't advise.** Explain what a player has and how it works, including action, bonus action and reaction options. Never tell them what to do.
- **The DM makes every ruling.** Rules answers inform the DM and players; they don't decide.
- 2024 rules (PHB, DMG, MM) only. Label official clarifications vs. community opinion, and exclude 2014-rules discussion.
- Characters and NPCs can be renamed (e.g. Sarkas → No Name), so model names with aliases.
- AI-drafted recaps are reviewed by Brett before the table sees them; his corrections feed future extractions (glossary + correction log).

## Conventions
- Small, focused commits with clear messages. Run `uv run ruff check app scripts tests` and `uv run pytest -q` before committing. GitHub Actions runs both on every push, and Railway waits for them before deploying beta.
- When a feature or a visibility rule changes, update the About and FAQ pages (`app/templates/about.html`, `faq.html`) to match. When a campaign-content workflow changes (recaps, entries, suggestions, review), also update the DM guide (`app/templates/dm_guide.html`, Manage › DM guide), which the DM reads instead of the code.
- Tests for core logic (extraction parsing, visibility rules, D&D Beyond parsing). Don't test against live paid APIs by default.
- Secrets come from environment variables (Railway variables in production, `.env` locally). Document every variable in `.env.example`.
