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

## 2026-10-16 — Feedback round: spells, features, inventory, drag and drop

**What changed**
- **Spells tab is now a spell planner**: see what's prepared vs. everything your class could prepare, shortlist spells with ♥, filter and search, and see "Prepared 10 of 10" at a glance.
- **Features**: what you can use is on top; rules that just change your numbers are folded away.
- **Inventory**: battle items and equipped gear on top; everything else folded and sorted by type.
- **Battle**: drag options to reorder a column; remove reminders with ×.
- **People**: tidy columns.

**Reuse this on a new project**
1. Ship, use it, collect a list of small annoyances, then fix them in one focused round, small commits per item.
2. When a third-party site loads data in pieces, look for the extra public calls it makes (here: class spell lists) rather than guessing.

## 2026-10-16 — Denser Character page with a details panel

**What changed**
- Every tab is a dense list (two columns on a laptop). Each row says what the thing does, with its numbers at a glance; click it for the full details in the side panel.
- "What it does" uses D&D Beyond's own short text, with formulas like "half your Druid level" worked out for you.
- As admin, you can move things to a different group right from the side panel; it applies to everyone.
- Easy to forget can be reordered; Situational folds what's already counted; Circle Magic noise is folded into one line.

**Reuse this on a new project**
1. Optimize for the screen people actually use (here a laptop next to Zoom): dense lists, details on demand in a side panel.
2. Give the admin an in-app "this is in the wrong group" control instead of collecting feedback by typing; save it as data you can learn from.

## 2026-10-16 — Manage › Characters, Game Mode banner, core rules only

**What changed**
- **Manage › Characters** (admin): D&D Beyond links and Refresh all live here now, plus a list of every regrouping correction with Undo.
- **Game Mode banner** on every page while it's on.
- **Core rules only**: Forgotten Realms extras are gone; the spell planner offers only 2024 core spells.
- Bell icon for reminders, Heroic Inspiration badge, gear is clickable and can be regrouped.

**Reuse this on a new project**
1. Keep admin-only setup (links, data sources) on an admin page, not on the pages everyone reads.
2. When a mode changes what the app does in the background (like Game Mode), show it everywhere until it's turned off.

## 2026-10-17 — Pictures, custom items, the DM's own corrections

**What changed**
- **Pictures.** Characters show their D&D Beyond portrait. The DM (and reviewers) can add a picture to any person, place, faction, item or quest from its page; it shows on the page, in the side panel and on the Campaign list.
- **Custom and changed items** are tagged in Inventory, with what changed in the side panel. Players' item notes still never leave D&D Beyond.
- **The DM's corrections skip review**, because the DM controls the story.

**Reuse this on a new project**
1. For a handful of user-uploaded images, storing resized copies in the database is simpler than setting up file storage (S3). Move to S3 when there are many or they're large.
2. Always re-encode uploaded images on the server (here with Pillow): it checks they're really images, shrinks them, and removes hidden location data from phone photos.
3. Decide per role who needs review. Here the DM is trusted with the story; everyone else's suggestions wait for a reviewer.

## 2026-10-18 — Back to local development

**What changed**
- All the cloud-session work (characters, Battle, Party, Campaign tabs, pictures, suggestions inbox, About/FAQ) is on `main` and deployed to beta.
- The README has a "Switching between cloud sessions and this Mac" section with the four commands to catch a local copy up.

**Reuse this on a new project**
1. Treat GitHub as the hand-off point: push before switching machines or sessions, pull after. Never keep work only in one place.
2. After pulling, always run the same three steps: install packages (`uv sync`), apply database changes (`alembic upgrade head`), run the tests. That covers almost every "it worked over there" problem.
3. Keep local and production data separate; a local database is for trying things, not a copy of the real one.

## 2026-10-18 — Campaign map

**What changed**
- A **Map** tab shows AideDD's interactive Sword Coast map inside askdnd, with a button to open it full screen.
- Places in the campaign record that are on the map (Waterdeep, Star Mounts, Oakhurst…) have **Show on map**, which opens the Map tab centered on that place.

**Reuse this on a new project**
1. Before copying someone else's content into your app, check whether you can **embed or link** it instead. Embedding keeps their features and avoids hosting copyrighted images.
2. Check that a site allows embedding (no `X-Frame-Options` or `frame-ancestors` block) and whether it has **deep links** (here `…/sword-coast@Waterdeep`). Those two facts decide how tight the integration can be.
3. Keep a small local list of the outside site's names (here, map markers) with a script to refresh it, so your pages don't depend on that site being up to render.

## 2026-10-18 — Wild Shape planner and notes

**What changed**
- Character › **Wild Shape** (druids): the Beasts you can learn now, your known forms, and a ♥ shortlist, with pictures. Clicking a form shows it with your own stats carried over, as battle cards.
- **Battle** has Wild Shape buttons: pick a known form and the page shows that form's options and numbers; Normal switches back.
- Shortlisted spells and forms, and reminders, can have a short **note** saying why.
- Place cards on Campaign › Places have **Show on map**.
- One database change (notes, and which form a character is in). Beta applies it automatically when it deploys.

**Reuse this on a new project**
1. Look for openly licensed data before copying from a book. The 2024 rules have a free version (the SRD, CC-BY-4.0) that can be stored in your repo as long as you credit it.
2. Store **links** to pictures hosted elsewhere rather than copies, and hide them gracefully if they stop loading.
3. Keep rules logic in one plain module with its own tests (here `app/wild_shape.py`), so the pages stay simple and the rules can be checked without a browser.

## 2026-10-18 — Manage cleanup and player notes

**What changed**
- **Manage** has an overview page with a card per area showing what needs attention, a menu grouped Table / Party / Admin, and the same tab bar on every Manage page. Review is now **Recaps**; Import is **Data**; Notes sync is the **Campaign doc** page under Recaps.
- **Player notes** on the Character page (Battle combos, Leveling strategy, Personal quests, General notes) replace syncing each player's Google Doc. Combos also show on Battle.
- One database change (the player notes table). Beta applies it automatically when it deploys.

**Reuse this on a new project**
1. Admin pages pile up as you build. Every so often, list them, group them by who uses them and how often, and give them one shared header. An overview page that says "what needs me?" saves opening each one.
2. Syncing outside documents is handy to start, but structured forms inside the app scale better: everyone writes in the same shape, and the app can link and reuse what they write.
3. Move existing content over with an import file kept out of git (`private/`), so you can review it locally before loading it into production.

## 2026-10-18 — Safer imports and a clear access chart

**What changed**
- **Manage › Data** now shows a preview of every import: what's new, what would change (old and new side by side) and what's already the same. Nothing is saved until you press **Import these changes**; **Cancel** throws it away. You can keep the current descriptions and import only what's new.
- **Manage › People** has a chart of what Player, Reviewer and Admin can do, what ticking DM changes, and what askdnd doesn't do for anyone. Each person's row says in one line what their access allows.

**Reuse this on a new project**
1. Any upload that overwrites data should show a preview first. The easy way to build one: run the real import inside a database transaction, compare before and after, then roll it back.
2. Keep permission rules in one function that both the app and its help text use, so the explanation can never disagree with what actually happens.

## 2026-10-19 — Version history and backups

**What changed**
- askdnd now keeps a **history of every change** to the campaign record, characters, people and players' notes: the old value, the new value, who changed it and how. It's stored in the app's database on Railway (in the cloud), and **Manage › History** can restore any earlier version. **Manage › Data** can undo a whole import.
- History only covers changes from 2026-10-19 on. For anything older, the safety net is Railway's own database backups (see below).

**Reuse this on a new project**
1. Decide early what must never be lost, and record changes to it automatically at the database level (a hook on every save), not page by page, so new pages are covered without anyone remembering.
2. Keep two layers: in-app history for "undo that one change", and whole-database backups for "something went badly wrong". Turn backups on from day one; they can't recover what happened before they existed.
3. Make bulk operations (imports) undoable as a unit.

## 2026-10-19 — Nightly backups to S3

**What was set up**
- A second Railway service, **askdnd-backup**, built from the same GitHub repo. Instead of running the website, its start command is `python scripts/backup_db.py`, and a **cron schedule** (`0 10 * * *`, daily at 10:00 UTC) runs it once a night. It copies the whole database into one compressed file in S3 (`askdnd-ai/v2/backups/askdnd-YYYY-MM-DD.json.gz`) and deletes copies older than 30 days.
- A new AWS user, **askdnd-v2-backups**, whose key can only read and write `v2/backups/` in the bucket (checked: listing the whole bucket is refused). Its keys were set with `scripts/set-secret.sh … --service askdnd-backup`, so they never appeared on screen.
- The first backup (45 MB, 480 rows) was downloaded and restored into a scratch database to prove it works.
- Railway's own Postgres "point-in-time recovery" exists (`railway postgres pitr`) but is off; it needs Railway storage and may cost extra. Optional later.

**Reuse this on a new project**
1. Give each job its own cloud key with the narrowest permission that works ("least privilege"), and test that it's refused outside its area.
2. Scheduled work (backups, reports) can be its own small service on a cron schedule, built from the same code, so it never slows the website.
3. A backup only counts once you've restored it. Do a test restore right after setting it up, and again now and then.
4. Never paste keys into chat or files that get committed; use a helper that reads them hidden and stores them straight into the host's settings.

## 2026-10-19 — Tests before every deploy (CI) and job alerts

**What was set up**
- **GitHub Actions** (`.github/workflows/tests.yml`): every push to `main` runs the full test suite on GitHub's computers, with its own throwaway Postgres. You can see each run on the repo's **Actions** tab.
- **Railway "Wait for CI"**: Railway waits for that test run and only deploys beta if it passes. (A setting on each Railway service; see below.)
- **Job alerts**: the nightly backup records each run; the Manage overview turns red if one fails or a night is missed, and also when D&D Beyond copies fail or get stale.

**Reuse this on a new project**
1. Set up CI (tests on every push) early, and make the host wait for it. It's the cheapest protection against shipping a broken change.
2. Make CI fail loudly when something it needs is missing (here, the database), so "all skipped" can never look like "all passed".
3. Any scheduled job should leave a trace (a row with time and result) and something should look at it. A job nobody checks can be broken for weeks.

## 2026-10-19 — Tidy-ups: lint, automatic cache-busting, spending limit

**What was set up**
- **Lint in CI**: `ruff` checks for unused and undefined names on every push, next to the tests. It caught a real mistake while the D&D Beyond file was being split.
- **Automatic cache-busting**: the CSS and JS links end in a fingerprint of the file's contents, so browsers fetch the new version after each deploy. No more hand-edited `?v=51` numbers.
- **Leftovers removed with a safe migration**: an old unused table and flag were dropped, with any old rows copied to their replacement first.
- **Monthly spending limit inside the app**: Manage › Usage. It sits on top of the Anthropic Console's limit and explains itself instead of failing mid-draft.

**Reuse this on a new project**
1. Add a linter to CI from day one. It's free and catches mistakes tests miss.
2. Let the build fingerprint static files (a hash in the URL) rather than numbering them by hand; stale-cache bugs disappear.
3. When removing a database table, write the migration so it moves any remaining data first. You can't always check production by hand.
4. Put spending caps in two places: the provider's hard limit, and a friendlier one in your app that says what happened and how to change it.

## 2026-10-20 — Shared table rolls (a new table, live updates by polling)

**What was set up**
- **A new database table** (`table_rolls`), added with an Alembic migration like every other change to the database. Railway runs migrations when it deploys, so beta gets the table automatically.
- **Rolls made on the server**: the browser only says "Cole rolled a Wis save"; askdnd's server rolls the dice and decides who may see the result. Hidden numbers never leave the server for people who shouldn't see them.
- **Live updates by polling**: while Game Mode is on, each open page asks "anything new since roll #42?" every 3 seconds. Nothing new costs almost nothing (an empty answer).
- **Previewing as two people locally**: `/dev/login?as=<email>` signs in as another allowed person on your own Mac only. Browsers keep cookies per address, so one tab on `localhost:8000` and another on `127.0.0.1:8000` can be two different people.

**Reuse this on a new project**
1. Anything that must be fair or private (dice, scores, secrets) belongs on the server. The browser is the user's: whatever it computes or receives, they can see or change.
2. Decide visibility in one function and test it for each kind of viewer; send each person only what they may see, not everything with some of it hidden on screen.
3. Polling every few seconds is a fine first version of "live" for a handful of users. Reach for WebSockets only when polling is visibly too slow or too heavy.
4. For testing "two people at once" on one computer, use two addresses for the same local server (localhost and 127.0.0.1): each gets its own sign-in.


## 2026-10-22: Responding to a hosting provider's security incident (Railway)

**What happened.** On 2026-10-21 Railway paused all builds, then disclosed that an attacker may have read customers' environment variables, which is where askdnd's secrets live. Railway's advice: replace ("rotate") every secret stored there, and check logs for unusual activity.

**What we did first (the two that can cost money or expose data):**
- **Anthropic API key.** Made a new key in the askdnd workspace, saved it with `scripts/set-secret.sh ANTHROPIC_API_KEY --clipboard` (local `.env` and Railway at once, never on screen), checked it with a free call that lists models, then disabled the old key. Usage looked normal.
- **AWS backup key** (user `askdnd-v2-backups`). Made a new access key and saved both halves to the `askdnd-backup` service straight from the clipboard. Checked that it can read `v2/backups/` and is still refused everywhere else, then deactivated the old key. The old key's "Last used" was the nightly 10:00 UTC backup, as expected.
- The Railway command line had been signed out by the incident; `railway login --browserless` signed it back in (approve the code in a browser where you're already signed in).

**Still to do once Railway builds are back** (each needs a redeploy to take effect, and changing them sooner would only break beta): a new `SESSION_SECRET` (signs everyone out), a new Google client secret, a new `UPLOAD_TOKEN` (also in the Mac's local `.env`), the Postgres password if Railway offers a reset, and the **legacy service's** keys (askdnd.ai) at each provider. Until the backup service redeploys, the nightly backup will fail, because it still has the old, now-deactivated key; the three existing backups are untouched.

**Same on a new project:**
1. Keep a list of every secret, where it lives and where to rotate it, so an incident is a checklist, not a scramble.
2. Rotate first what can cost money or expose data (AI keys, cloud storage keys). Give each key the smallest permission that works, so a leak stays small.
3. Use spending caps (the Anthropic prepaid balance) so a leaked key has a ceiling.
4. Save new secrets from the clipboard with a script, test them with a harmless call, then turn the old ones off.

**Update, later on 2026-10-22.** Builds came back. `SESSION_SECRET` and `UPLOAD_TOKEN` were rotated (generated on the Mac and piped straight into `scripts/set-secret.sh`, so no one ever saw them), and an empty commit pushed to `main` redeployed beta and the backup service. Still open: the Google client secret, the Postgres password and the legacy keys (roadmap step 12).

## 2026-10-22: Reviewing a big change side by side (branch + second local server)

**Why.** The design system's visual passes change how every page looks. Brett wants to compare old and new before they reach beta, on the same data, with everything clickable.

**What we set up:**
- A **branch**, `design-system`: a parallel line of commits. `main` (and so beta) stays as it is until the branch is merged.
- A **worktree**: a second folder, `~/Code/dndsy-design`, with the branch checked out (`git worktree add -b design-system ../dndsy-design main`). Two folders, one repository: no copying, and each folder can run its own server.
- **Two local servers** in `.claude/launch.json`: `web` (the current look, from `main`, port 8000) and `web-new` (the branch, port 8001). Both read the same `.env`, so the same local database and the same sign-in.
- Compare by opening the same page on `localhost:8000` and `localhost:8001` side by side.
- When Brett approves, the branch is merged into `main` and deploys to beta as usual. Fixes made on `main` in the meantime get merged into the branch so the two don't drift.

**Same on a new project:**
1. Do large or risky changes on a branch; keep `main` deployable.
2. For a visual review, run old and new side by side on the **same data**. Comparing local to the live site mixes up data differences with design differences.
3. A worktree avoids switching branches back and forth in one folder (and restarting servers each time).
4. Hosting services can also deploy a branch to its own temporary address ("preview environments"). Worth it with more reviewers; it needs its own database copy.

**Update, later on 2026-10-22: merging the branch.** Brett approved steps 3 and 4 side by side, so `design-system` was merged into `main` (a "fast-forward": `main` simply moved up to the branch's last commit, because the branch already contained everything on `main`). Pushing `main` ran the tests and deployed beta; Railway's start command (`alembic upgrade head`) added the new database column for "Got it" on the way. Then the worktree folder and the branch were removed, since everything in them is now on `main`. To review the next big change the same way: `git worktree add -b <name> ../dndsy-design main`, then start `web-new` from `.claude/launch.json` (it runs from `../dndsy-design` on port 8001).

## 2026-10-22: A local copy of beta's data, for testing on real data

**What was set up.** `scripts/pull_beta.sh` copies beta's data into a local database (`askdnd_beta`) from the
newest nightly backup in S3, and the local app now uses it (one `DATABASE_URL` line in `.env`; remove it to go
back to the old `askdnd_dev`). Beta is never touched: the backup is downloaded with the backup service's own key,
which `railway run --service askdnd-backup` lends to that single command without showing it. The file lands in
`private/backups/`, which git ignores.

**How it restores.** The backup was made before today's database changes, two of which also rearrange existing
data. So the script builds the database as it was when the backup was made, loads the backup, then applies every
change since (`alembic upgrade head`). The restore tool learned to load into whatever version the database is at,
which is also what a real disaster recovery from an older backup needs.

**Automatic drafting is off locally** (`AUTO_DRAFT`, on in production): publishing a session on the copy doesn't
start a real Claude draft. Set `AUTO_DRAFT=1` in `.env` to test it on purpose.

**Found on the way:** the newest backup in S3 was Oct 21. The Oct 22 run failed because the backup service still
had the deactivated AWS key until today's redeploy (see above), so tonight's should be the first good one since.
Roadmap step 12 checks it.

**For a new project:**
1. Test on a copy of real data, never on production. A copy made from the nightly backup gets you real data and
   proves the backups restore, in one go.
2. Keep restore scripts able to take an older backup: build the schema at the backup's version, load, then migrate.
3. Turn off anything that spends money or sends messages by default outside production.
