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

## Stack
Python (current stable) managed with **uv** · FastAPI serving server-rendered pages (Jinja + HTMX) and the API · Postgres on Railway (pgvector later) · Claude via the Anthropic API · Ollama on Brett's Mac (M4 Pro, 48 GB) for the local transcript filter · Google sign-in limited to an email allowlist · D&D Beyond public character data (unofficial: cache the last good copy and fail gracefully) · S3 `v2/` prefix for page images.

## Privacy and data rules (important)
- **Raw transcripts never go to a cloud service or into the database.** They're filtered locally (Ollama) on Brett's Mac first; only the filtered game content is sent for extraction, and only the extracted story is stored.
- **Never commit** `.env*`, transcripts, campaign notes, character notes, or exports. Campaign data lives in the database, not in git. Keep `.gitignore` strict (`transcripts/`, `private/`, `*.docx`, `.env*`).
- Visibility: **character notes are visible to players but NOT the DM.** Everything else is visible to everyone at the table. Exception: players' **item notes on D&D Beyond** are visible to everyone, DM included (Brett, 2026-10-17); they live only in the database (`character_item_notes`), never in the stored D&D Beyond copy, fixtures or git.
- Set and respect a monthly spend limit on the Anthropic API.

## Product rules
- **Inform, don't advise.** Explain what a player has and how it works, including action, bonus action and reaction options. Never tell them what to do.
- **The DM makes every ruling.** Rules answers inform the DM and players; they don't decide.
- 2024 rules (PHB, DMG, MM) only. Label official clarifications vs. community opinion, and exclude 2014-rules discussion.
- Characters and NPCs can be renamed (e.g. Sarkas → No Name), so model names with aliases.
- AI-drafted recaps are reviewed by Brett before the table sees them; his corrections feed future extractions (glossary + correction log).

## Conventions
- Small, focused commits with clear messages. Run tests before committing.
- Tests for core logic (extraction parsing, visibility rules, D&D Beyond parsing). Don't test against live paid APIs by default.
- Secrets come from environment variables (Railway variables in production, `.env` locally). Document every variable in `.env.example`.
