# Setup Log

Plain-English recaps of each setup milestone, written for reuse on future projects.

## 2026-10-14 — Week 1, part 1: project skeleton and hosting

**What we set up**
- **A clean `main` branch.** All v1 code was removed from `main`. It isn't lost: the `legacy` branch and `v1-legacy` tag still hold it. Leftover local junk (old virtual environment, caches, session files, logs) was deleted. The old secrets file was renamed `.env.legacy` and is ignored by git.
- **A strict `.gitignore`.** Git now refuses secrets (`.env*`), transcripts, private notes, exports and Word/PDF files by default. Only `.env.example` (which holds variable *names*, never values) is allowed.
- **A v2 project skeleton.** Python 3.14 managed by **uv**, which installs Python itself, keeps dependencies in `pyproject.toml`, and pins exact versions in `uv.lock` so your Mac and the server run the same thing. There's a small FastAPI app with a `/health` check and a placeholder home page, two tests, and a README.
- **Railway hosting.** In the existing `askdnd` project we added a new service, **askdnd-v2**, that deploys automatically whenever `main` is pushed to GitHub, plus a **Postgres** database. The app gets the database address through a *reference variable* (`DATABASE_URL=${{Postgres.DATABASE_URL}}`), so the password is never copied by hand. Railway detected uv by itself and built the app; the `Procfile` tells it how to start.
- **A domain.** `beta.askdnd.ai` points at v2: a CNAME record in Cloudflare (proxied) sends traffic to Railway, and a TXT record proves to Railway that we own the domain so it can issue an HTTPS certificate.

**What we checked first**
- Before wiping `main`, we confirmed the legacy production service deploys from the `legacy` branch, not `main`. If it had deployed from `main`, wiping it would have taken askdnd.ai down. **Always check which branch a live service deploys from before you change that branch.**
- `beta.askdnd.ai` was already attached to an old legacy "dev" environment. A domain can only live on one service, so we detached it there first. askdnd.ai and legacy.askdnd.ai weren't touched.

**Reuse this on a new project**
1. One repo; preserve the old version with a tag and a branch before starting over.
2. Write `.gitignore` *before* the first commit of new work, and keep `.env.example` as the list of every variable the app needs.
3. `uv init` → `uv add` your libraries → `uv run pytest` to test → `uv run uvicorn …` to run locally.
4. `railway login` → `railway link` → `railway add --database postgres` → `railway add --repo <github repo> --branch main --service <name>`.
5. Wire the database with a reference variable, not a pasted password.
6. `railway domain <your subdomain>`, then add the CNAME + TXT records it prints into Cloudflare (proxied, SSL mode Full).
7. Link your local folder to the *new* service (`railway link -s <name>`) so CLI commands can't accidentally hit an old one.

**Where things are**
- Railway URL: https://askdnd-v2-production.up.railway.app
- Beta: https://beta.askdnd.ai (health check at `/health`)

## 2026-10-15 — Week 1, part 2: secrets, Anthropic API key, Google sign-in

**What we set up**
- **Anthropic API key.** It lives in its own **askdnd workspace** in the Anthropic Console. Spending is capped by a **$20 prepaid balance with auto-reload off**: when the credit runs out, calls stop, so a leaked or runaway key can only cost so much. (The Console didn’t show a spend-limit setting for this account.) It's a normal key with no expiry. Identity federation (keyless sign-in) needs a hosting platform that issues identity tokens, and Railway doesn't, so it isn't worth it here. We checked the key with a free call that lists models.
- **Google sign-in.** A Google Cloud OAuth app in **Testing** mode, with Brett as the only test user. Testing mode means Google itself blocks anyone not on that list, which keeps the app a surprise for the table. The app adds its own lock on top: an `ALLOWED_EMAILS` list (just Brett for now), checked on every page load, so removing an email locks that person out right away.
- **Login cookie.** After signing in, the app remembers you with a signed cookie for 30 days. `SESSION_SECRET` is the key that signs it. Local and production use *different* random secrets, so a local copy can never be used to fake a production login.
- **A secret-setting script.** `scripts/set-secret.sh NAME --clipboard` saves a value to both the local `.env` and Railway without ever showing it on screen, in shell history or in chat.

**Gotchas we hit**
- Google says "Ineligible accounts not added" if you add a test user who's already on the list. It's harmless.
- The Google setup went into the default "My First Project". Better practice is **one Google Cloud project per app**; renaming the project is enough.
- Behind Railway's proxy the app sees plain `http`, so Google would reject the callback address. The fix is to tell the web server to trust the proxy's "this was https" header (`--proxy-headers` in the Procfile).

**Reuse this on a new project**
1. Copy and paste secrets; never type them into a chat or a commit. Use a script that reads the clipboard and writes to `.env` and the host's variables together.
2. Give every API provider its own workspace or project per app, with a spend limit.
3. Google sign-in recipe: create a Cloud project → Google Auth Platform → **External** audience in **Testing** mode → add test users → create a **Web application** client with one redirect URI per environment (`https://<domain>/auth/callback` and `http://localhost:8000/auth/callback`) → save the client ID and secret as secrets.
4. Gate access twice: Google's test-user list, plus an allowlist in your app. When you go live, publish the Google app and keep the allowlist.
5. To add a player later: add their email to `ALLOWED_EMAILS` (`railway variable set ALLOWED_EMAILS=a@x.com,b@y.com -s askdnd-v2`) and to Google's test users (until the app is published).

## 2026-10-15 — Week 1, part 3: local transcript filter (in progress)

**What we set up**
- **Ollama on Brett's Mac** runs AI models locally; our script talks to it at `127.0.0.1:11434`, so raw transcripts never leave the Mac. No extra app needed.
- **MacWhisper export:** *Segments* + *.json*, with speaker names, timestamps and milliseconds on. Save to `transcripts/raw/<date>.json` (git-ignored).
- **The filter** (`uv run python -m transcript_filter transcripts/raw/<date>.json`):
  1. *Echo de-dup* (plain code): Zoom echo makes the same words appear twice; drops the copy (about 39% of words).
  2. *Table-talk filter* (local model): labels each line game or table talk, using private campaign notes in `transcripts/context.md`.
  3. Writes the filtered transcript to `transcripts/filtered/` and a **review page** to `transcripts/review/` that shows exactly what was cut.
- **Scoring:** `uv run python -m transcript_filter.score …` compares a run to hand labels (`transcripts/gold/`), so prompts and models can be compared with numbers instead of gut feel.

**Lessons**
- A local model can loop and never finish; cap its output, retry smaller pieces, and flag what still fails rather than crash.
- Tell the model what *doesn't* count. Our group's other games (castles, spells, giants) fooled it until the prompt said so.
- Keep private context (names, campaign details) in git-ignored files, and keep only the code in git.

**Next steps**
- Done: gemma4:12b is the default (0% game lost, 100% table talk removed on the hand-labeled first 45 min; full session in 18 min). Brett reviewed the full page and approved the cuts.
- Check the mid-session break (around 2:00–2:35) and the end; add hand labels for them.

## 2026-10-15 — Week 2: database, campaign import, Google Docs sync, processor GUI

**What we set up**
- **Postgres on the Mac** (Homebrew, version 18 to match Railway) for development and tests. **Migrations** (Alembic) are versioned scripts that change the database structure; Railway runs them automatically before each deploy starts the app.
- **The data model**: campaigns, members with per-campaign roles, everything named in the story with aliases (renames like Sarkas → No Name), characters, sessions, recaps (keeping the AI draft), story events, glossary, corrections. No table for transcripts, by design.
- **Admin import page** on beta: upload a campaign "bundle" file; re-importing updates instead of duplicating. The campaign skeleton (48 entities, glossary, sessions 17–29) went in this way.
- **Notes sync from Google Docs**: a "Sync now" button reads your docs through the Google Docs API using your own Google sign-in with **read-only** access, asked for on each click and never stored. All tabs, nested bullets, tables (with merged cells), links and images come through; images are shrunk automatically; drawings like the family tree come from Drive's export.
- **askdnd Processor**: a double-click Mac app that opens a local page to add a MacWhisper export, filter it with a progress bar, review cuts with Keep buttons, and save the final transcript.

**Gotchas**
- Google needs every API turned on separately (Drive API *and* Docs API) and every return address listed exactly (redirect URIs), and changes can take minutes.
- In Google's Testing mode, saved long-term access expires after 7 days. Asking each time is simpler and safer.
- A database that isn't publicly reachable is safer; data goes in through the app (admin pages) instead.
- Commit only after tests pass: piping test output through `tail` hides failures from `&&` chains.

**Reuse this on a new project**
1. Same database engine and major version locally as in production.
2. Migrations in the repo, applied automatically on deploy.
3. Admin-only pages for data you'd otherwise load by hand.
4. For Google data: one Cloud project per app, enable each API, minimal read-only scope, list every redirect URI.
5. For anything private and local: a localhost-only web page plus a small `.app` launcher is a cheap, friendly GUI.

## 2026-10-15 — Week 2: extraction, review and the new look

**What we set up**
- **Story extraction with Claude** (Opus 5.5, structured JSON output, automatic fallback if a safety filter misfires). Each session costs about 10–15¢; every run's cost is recorded and shown.
- **Review flow**: Claude's questions (answer, skip, or use in every future draft), the recap (edit), key moments (edit/add/delete), suggested updates (accept, edit, reject, undo). Nothing reaches the table until you publish.
- **A design system** (docs/DESIGN.md) and a clickable mockup before building: dark theme inspired by D&D Beyond, readable type, "Done" drawers for anything already handled, and one top bar for everyone plus an admin-only **Manage** menu.
- **Pages for the table**: Previously on… (home), Sessions, Campaign, and a Characters placeholder.
- **HTMX**: buttons on the review page update just that area instead of reloading the page.

**Reuse this on a new project**
1. Mock up important screens with fake data before building them; iterate on the mockup, not the code.
2. Write the design rules down (colors, type, components) in the repo, so every future session follows them.
3. Keep "what a button does" in a plain module with tests (app/review.py) and keep routes thin.
4. A local-only sign-in shortcut (DEV_LOGIN_EMAIL) makes it possible to preview real pages without going through Google.

## 2026-10-16 — The living campaign record and "Ask…"

**What we set up**
- **A page for every person, place, faction, quest and item** (click any name on the Campaign page or under a key moment). It shows the summary, other names, relationships, facts the table added, and every published key moment that mentions it.
- **Facts from anyone at the table**, which a reviewer merges or rejects (with Undo). Merging never rewrites the summary; **Regenerate description** is a separate button where Claude proposes a rewrite you accept, edit or discard (and can undo).
- **@-mentions**: type @ and a few letters in any text box to insert a name spelled correctly.
- **Relationships and a family tree**, added by hand, by import, or suggested by Claude in drafts.
- **Ask…** on Claude's questions: send one to the DM or a player; it waits under "Waiting on <name>" and shows up on their Previously on… page once they sign in.

**Reuse this on a new project**
1. Keep "who added what" (author, status, undo) on anything people at the table can contribute; review before it shows.
2. When the app calls a paid API for something new, record the cost in the same place as the rest, so one Usage page tells the whole story.
3. Use a separate local database with made-up data for previews, so real data on your machine is never touched by testing.

## 2026-10-16 — Characters from D&D Beyond

**What we set up**
- **A Characters page** with a card per character (species, classes, HP, AC, speed, key resources like Wild Shape and Focus Points) and a full sheet per character: abilities and saves, resources and what restores them, actions / bonus actions / reactions, spells with casting time, range, concentration and ritual, Wild Shape forms, features, skills, and inventory with attunement and charges.
- **Refresh from D&D Beyond** buttons (one character or all), for you and the DM. askdnd keeps the last copy that worked, so if D&D Beyond is down or changes, the page still shows the last good sheet with a quiet note.
- **Linking**: paste a character's D&D Beyond link on its page. The character must be Public on D&D Beyond.

**Reuse this on a new project**
1. When you depend on an unofficial data source, store the last good copy and show its age; never let a failed fetch wipe it.
2. Save real sample responses as test files, so tests run offline and catch format changes.
3. Strip anything private before it's stored, not just before it's shown.

## 2026-10-16 — People and access levels

**What we set up**
- **Manage › People**: add someone by Google email and choose Player, Reviewer or Admin; tick DM for whoever runs the game. Remove someone and they're signed out on their next click.
- The Railway variables still work as a safety net. You're an "owner" through ADMIN_EMAILS, so nobody (including you) can accidentally lock you out from the app.
- **Character numbers double-checked** against D&D Beyond's own sheet, value by value, for all four characters.

**Reuse this on a new project**
1. Start with an allowlist in environment variables (simple, safe), then move day-to-day access into the app once more people need managing, keeping the env list as the owner's backstop.
2. Separate "what you can do" (access level) from "who you are at the table" (DM), so one rule like "the DM never sees notes" can't be undone by giving someone more access.
3. When you recompute someone else's numbers, test against what their own product shows, not against what you think the rules say.
4. With Google sign-in in "testing" mode, every new person must also be added as a test user in Google Cloud.

## 2026-10-16 — Battle, Character and Party

**What we set up**
- **Battle**: your character during play: what you can do, sorted into action, bonus action and reaction, with "See all" for the rest, resources as dots, your Easy-to-forget reminders and the party table. Flip **Game Mode** on to keep it in sync with D&D Beyond every couple of minutes.
- **Character**: the full sheet, reorganized. Advantages show on the saves they change, a Situational tab gathers the "only when…" rules, and rarely needed details are folded away. On your own character, ★ puts things on Battle and **Remind me** adds them to Easy to forget.
- **Party**: everyone side by side, plus the party's spells and magic items pooled for planning.
- **Manage › People › Plays**: say who plays which character.

**Reuse this on a new project**
1. Mock up, get feedback, mock up again, then build: two rounds of mockups changed the design more than any code review would.
2. Let people mark what matters to them (stars, reminders) instead of guessing a perfect default layout.
3. When you poll someone else's service, throttle on the server per item, not per viewer, so more viewers don't mean more traffic.
