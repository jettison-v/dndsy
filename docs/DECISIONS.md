# Decision Log

One line per decision: date — decision — why. Newest at the bottom.

- 2026-10-14 — Rebuild as v2 instead of refactoring v1 — v1 had four parallel vector stores and poor retrieval; it was a learning exercise
- 2026-10-14 — Hard fork in the same repo: `v1-legacy` tag + `legacy` branch; v2 on `main` — one repo, old code preserved and still deployable
- 2026-10-14 — Legacy stays live at askdnd.ai and legacy.askdnd.ai; v2 builds at beta.askdnd.ai — no downtime, switch over when v2 is better
- 2026-10-14 — Audience: one table (4 players + DM), private — keeps auth, cost and licensing simple
- 2026-10-14 — Brett's learning goal is project setup, not coding; Claude Code in Auto mode — matches his goal
- 2026-10-14 — First milestone: pre-session refresher (recap + character briefing) before the next session (~3 weeks) — fixes forgetting between sessions; legacy still covers rules lookups
- 2026-10-14 — Character briefings are extended (wild shapes, spells, inventory, action economy), not a fixed template; inform, never advise — players forget what they have; the choices stay theirs
- 2026-10-14 — Raw transcripts are filtered locally with Ollama; only the extracted story is stored — sessions include personal conversation
- 2026-10-14 — Character notes are visible to players, hidden from the DM — Brett's call
- 2026-10-14 — Multi-campaign data model from day one, single-campaign UI at launch — a new campaign may start soon
- 2026-10-14 — Stack: Python/FastAPI + HTMX, Postgres on Railway, Anthropic API, Google sign-in allowlist — simplest stack that does the job; replaces Qdrant
- 2026-10-14 — Brett reviews each recap; corrections feed a glossary and correction log — accuracy improves each session
- 2026-10-14 — Brett wears headphones during sessions — Zoom echo duplicated ~45% of the transcript and scrambled speaker labels
- 2026-10-14 — Switched from Cursor to the Claude desktop app's Code tab — Cursor's own AI agent competed with Claude Code and caused confusion; an editor isn't needed for the setup-learning goal
- 2026-10-14 — Python 3.14 managed by uv; deps pinned in uv.lock — current stable; one tool for Python, deps and running
- 2026-10-14 — v2 is a new Railway service `askdnd-v2` + Postgres in the `askdnd` project's production environment, auto-deploying from `main` — separate from legacy, which deploys from the `legacy` branch
- 2026-10-14 — Railway builds with its auto-detection (Railpack) and a Procfile start command, not railway.json — railway.json is deprecated, and Railway's newer project-wide config could affect the legacy service
- 2026-10-14 — Detached beta.askdnd.ai from legacy's old `dev` environment (May 2025 beta build) and attached it to v2 — Brett approved; a domain can only belong to one service; production domains untouched
- 2026-10-14 — Old local `.env` kept as git-ignored `.env.legacy` — reference for legacy settings without risking a commit
- 2026-10-15 — Allowlist is only Brett's email until launch; Trah or a dummy account is added for multi-account testing — v2 is a surprise for the other players
- 2026-10-15 — Google OAuth app stays in Testing mode with listed test users until launch — Google blocks unlisted accounts as a second lock on top of the app's allowlist
- 2026-10-15 — Allowlist lives in the ALLOWED_EMAILS variable for now, not the database — five users; move to a users table when we add roles (DM vs player) for visibility rules
- 2026-10-15 — Sessions are signed cookies (Starlette SessionMiddleware + Authlib for Google OIDC), allowlist re-checked every request — no session store needed; removing an email takes effect immediately
- 2026-10-15 — Anthropic: dedicated askdnd workspace with a monthly spend limit; standard non-expiring key, no identity federation — Railway can't issue the identity tokens federation needs; the spend limit and the ability to swap keys cover the risk
- 2026-10-15 — Secrets are set with scripts/set-secret.sh (clipboard → .env + Railway) and never pasted into chat — keeps them out of transcripts, history and git
