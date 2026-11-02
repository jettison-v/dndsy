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

## 2026-10-22: Data organization step 1, characters separate from campaigns

**What was set up.** A database change (an Alembic migration) that reshapes existing data, not just adds to it:
characters got their own name, and their link to a campaign moved into a new table, `campaign_characters`
(campaign, character, its story page, joined, left, Wild Shape keeps). The migration copies today's four characters
across in one go, and can be undone (`alembic downgrade`), which puts every value back where it was. Nothing on
screen changes; it's groundwork for roles per campaign and a second campaign.

**How it was checked.** A test builds the database as it was before, fills it with production-shaped data, runs
the migration up, down and up again, and compares every value. Then the migration ran on the local copy of beta
(`askdnd_beta`), and the app was clicked through there before pushing. Railway runs the same migration on beta
when it deploys.

**For a new project:**
1. When a migration moves data (not only adds columns), write a test that runs it on realistic rows, both ways.
2. Run it on a copy of production first. A copy made from the nightly backup is the cheapest way to get one.
3. Model "belongs to" links that can change over time as their own rows with dates (joined, left) instead of a
   column you overwrite; history stays answerable.

**Update: the manual backup before deploying, over SSH.** Beta's database has no address outside Railway, so the
backup ran *inside* the beta service: `railway ssh --service askdnd-v2 -- …` runs one command in the live
container. That needed three one-time steps on the Mac: register its public key with Railway
(`railway ssh keys add --key ~/.ssh/id_ed25519.pub --name brett-mac`; importing keys from GitHub failed), accept
Railway's host key on first connect, and unlock the passphrase-protected key once with
`ssh-add --apple-use-keychain ~/.ssh/id_ed25519` so tools can use it without asking. The dump (read-only, about
45 MB) was copied to `private/backups/beta-2026-10-22-before-step1.json.gz` (git ignores it) and checked before
pushing; the temporary copy on Railway was deleted.

**For a new project:** add an SSH key to your hosting account early. "Run one command inside production" is the
fastest way to back up, inspect or fix things when the database isn't reachable from outside, and it's safer than
opening the database to the internet.

## 2026-10-23: Data organization step 2, roles per campaign

**What was set up.** Two kinds of role instead of one access level plus a DM tick. A **tool role** (member or
admin) on the person, for setting up askdnd itself, and a **campaign role** (DM, reviewer or player) per campaign,
for running a table. A migration moved today's people across: Mary's Reviewer access and DM tick became "DM in
Main campaign", everyone else who can sign in became a player there, and Brett stays admin. Manage › People now
groups people by role and shows a chart of what each role can do, drawn from the same rules the app checks. The
same manual backup over Railway SSH was taken before deploying.

**For a new project:**
1. Separate "what you can do in the product" (admin, member) from "what you do in a workspace" (owner, editor,
   viewer per project or team). Almost every multi-team app ends up needing both, and splitting them late means a
   migration like this one.
2. Keep every permission rule in one function and draw any "who can do what" chart from it, so the help text can't
   drift from the code.

## 2026-10-23: Data organization step 3, tool corrections and house rules

**What was set up.** Two kinds of change to what askdnd knows, kept apart. **Tool corrections** (renamed from
sheet corrections) fix how askdnd reads D&D Beyond and apply everywhere; they now have a Why column. **House rules**
are a DM's rulings for one campaign, on a new page, Manage › House rules. Both are rows that point at what they
change, so askdnd's audited rules data in the code is never edited, and removing a row brings back the rule
underneath. A database table was renamed in the same migration (`sheet_overrides` → `tool_corrections`), with its
id counter and constraints renamed too so the names stay consistent.

**For a new project:**
1. Keep "the product's knowledge" (shipped in code, reviewed, the same for every customer) apart from
   "a customer's settings" (in the database, per workspace). Overrides should point at what they override, never
   copy and edit it.
2. Work out the effective value in one place, in a fixed order (default → global fix → local override), so every
   screen agrees.

## 2026-10-23: Data organization step 4, more than one campaign (step 10 done)

**What was set up.** askdnd can now hold several campaigns. Story pages have the campaign in their address
(`beta.askdnd.ai/c/main/sessions`), a small piece of code in front of the app reads that part of the address,
and every page works in any campaign without being written twice. Old links still work: they open the campaign
you were in last. Admins create campaigns and move characters on Manage › Campaigns; each person sees only the
campaigns they have a role in. The monthly Claude limit moved to a tool-wide setting, since one Anthropic account
pays for everything.

**For a new project:**
1. Put the workspace (team, project, campaign) in the address from the start (`/c/<name>/…`, like GitHub's
   `/<owner>/<repo>`). Links then say where they point, and adding a second workspace later is far easier.
2. One "current workspace" function that every page asks, instead of each page deciding, makes the switch a
   small change.
3. Store "what I opened last" per person, not per browser, so it follows them between devices.

## 2026-10-23: Finishing the Railway incident cleanup (roadmap step 12)

- **Google client secret.** Brett added a second secret to askdnd's web client in Google Cloud Console (Google
  Auth Platform › Clients) and copied it. `scripts/set-secret.sh GOOGLE_CLIENT_SECRET --clipboard` saved it to Railway
  and the local `.env` without showing it; `railway redeploy --service askdnd-v2` put it into effect. Brett signed in
  from a private window, then disabled the old secret. Google lets a client have two secrets at once, which is what
  makes this a no-downtime swap.
- **Database password: checked first.** The legacy service has no database settings, so only beta and the backup
  service use this Postgres. It also has no public address (no TCP proxy), so the leaked password couldn't be used
  from outside Railway's private network. That lowers the urgency; it gets rotated after a fresh backup.
- **Legacy keys** are Brett's (legacy is never touched from here): its AWS key first, then OpenAI, Qdrant,
  `SECRET_KEY` and `APP_PASSWORD`.

**For a new project:**
1. Rotate with an overlap when the provider allows two keys at once (Google client secrets, most API keys): add the
   new one, deploy, test, then disable the old one.
2. Before rotating a database password, check who uses the database and whether it's reachable from the internet at
   all. A database with no public address is much less exposed by a leaked password.

## 2026-10-23: The first pull request (Manage layout)

This is the first change built the new way (agreed in the VTT roadmap): on its own short **branch**, opened as a
**pull request** (PR), checked by GitHub Actions, and merged by Brett. Until now changes went straight onto `main`,
which deploys beta right away.

- **Why a branch and a PR.** The work happens off to the side, so `main` (and beta) keep working while it's
  unfinished. The PR is one page on GitHub showing everything that will change, the tests' result, and a place to
  comment. Nothing reaches beta until someone presses **Merge**.
- **How to review one.** Open the PR link. The description has a short review guide: what changed, what to try.
  The **Checks** section must be green (ruff and pytest ran on GitHub). **Files changed** shows every line, but the
  guide is enough; you don't need to read code.
- **How to merge.** Press **Merge pull request** (then **Confirm**). That puts the branch onto `main`, and Railway
  deploys beta as usual (it waits for the checks). Not on game night.
- **Keeping it current.** If `main` moved on while the PR was open (another session merged something), the branch is
  brought up to date first, so what you tested is what lands.

**For a new project:**
1. Work on short branches and merge through pull requests from day one, even alone: `main` stays deployable and every
   change has one page explaining it.
2. Make CI (lint and tests) run on every PR and require it before deploying, so a red check stops a bad merge.
3. Write the PR description for the person who merges: what changed, how to try it, what's not done.

## 2026-10-23: The database password, and the Railway cleanup is done

The last open item from the Railway incident. Brett had already rotated the legacy service's keys that mattered.

- **A fresh backup first.** The nightly backup was 10 hours old, so a new one was made inside beta (`railway ssh` runs
  a command in the live app) and saved to `private/backups/` on the Mac (git ignores it).
- **One setting feeds everything.** Railway's Postgres builds its address from `POSTGRES_PASSWORD`, and beta and the
  backup service only *point to* that address (`${{Postgres.DATABASE_URL}}`), so changing it in one place updates both.
- **Two steps that must both happen.** The database itself keeps its password (the setting only matters when the
  database is first created), so the password was changed inside the database (`ALTER USER`, sent through
  `railway ssh`), then the same value saved to Railway, then beta and the backup service redeployed. The value was
  generated on the Mac and piped through; no one saw it.
- **A hiccup.** One redeploy failed on Railway's side (its build machine dropped the connection); trying again worked.
  Beta kept serving the old version meanwhile, so nobody noticed.
- **Checked:** beta's startup step talks to the database (it couldn't have started with the old password), pages load,
  and a fresh connection from inside Railway works.

**For a new project:**
1. Keep one source for each secret and have other services *reference* it, so rotating means one change, not several.
2. Take a backup right before touching a database's credentials, and know how you'd get back in if something breaks
   (here: from inside Railway the database doesn't need the password).
3. If a deploy fails, read its log before assuming your change broke it; it may be the host.

## 2026-10-23: The VTT switch and a test campaign (VTT 0.1)

How askdnd grows into a virtual tabletop without the table seeing unfinished work, on **one site** and **one `main`
branch**.

- **A switch per campaign, in the database.** Each VTT piece is listed in the code (`app/vtt.py`) and shows only where
  a campaign has it on. This kind of switch is often called a **feature flag**: code ships early, hidden, and is turned
  on per group of people. Turning one off again is a click, not a redeploy.
- **A test campaign** (tagged **Test** everywhere) sees every piece, finished or not; Brett and the DM try things there.
  The table's campaign gets a piece only when its DM or an admin switches it on in Manage › Settings.
- **Test copies of characters.** VTT pieces will change things during play (hit points, slots), so the test campaign
  uses copies that share the D&D Beyond sheet but keep their own state. The real characters are never touched.
- **A database change done safely.** The new columns were *added* (never removed or renamed), with defaults, so the
  running app and the new code both work during the deploy; Railway runs the migration before starting the new version.

**For a new project:**
1. Use feature flags instead of long-lived branches when building something big inside a live app: merge small pieces
   to `main` often, hidden, and switch them on when ready.
2. Keep a test space with realistic data (here a test campaign with copies of real characters) instead of testing on
   the real thing.
3. Make database changes "add first, remove later", so a deploy never breaks the version still running.

## 2026-10-23: A third-party library, vendored (the 3D dice)

The thrown dice use an open-source library (@3d-dice/dice-box-threejs, MIT license) with its textures and sounds,
about 3 MB.

- **Vendored, not loaded from a CDN.** The files are copied into `app/static/vendor/dice-box-threejs-0.0.12/`, so
  askdnd serves them itself: a game night never depends on someone else's server, and the version can't change
  under us. The folder name carries the version, so an upgrade is a new folder.
- **Checked on the way in.** Each downloaded file was compared with the checksum the package registry publishes, so
  what's in the repo is exactly what the authors released. The library's LICENSE file is kept next to it (MIT asks
  for that).
- **Loaded only when needed.** Pages don't download it until the first roll or the dice picker.

**For a new project:**
1. Check a library's license before using it (MIT, BSD and Apache are friendly), and keep its LICENSE file.
2. Pin an exact version; vendor the files when the app must keep working even if the CDN or the package disappears.
3. Verify downloads against published checksums.

## 2026-10-24: Deploy failures, and making deploys sturdier

Brett saw failed deploys and asked whether the VTT switch made deploying too complicated. It didn't: the switch is a
setting in the database, and deploying works exactly as before (merge → GitHub's tests → Railway builds → beta).

- **What failed.** On 2026-10-23, 3 of about 26 deploys failed, all with Railway's build machines dropping the
  connection ("build daemon returned an error"), before our code even ran. Each time beta kept running the previous
  version, so nobody saw a broken site; a rebuild fixed it. GitHub shows those as red "deployment failed" marks.
- **Fewer builds.** The nightly backup service was rebuilding on every merge, though it only runs one script. It now
  has **watch paths**: it rebuilds only when a file the backup uses changes. Half the builds means half the chances to
  hit a Railway glitch. The list lives in the repo (`BACKUP_WATCH` in `scripts/deploy_check.py`, which copies it to
  Railway with `--set-backup-watch`), and a test checks every file the backup script loads is on it.
- **A road not taken.** Railway's settings files ("config as code") turned out to be deprecated. Their replacement
  describes the *whole project* in one file, and anything left out gets deleted, including the legacy askdnd.ai
  service we must never touch. Too much risk for one setting, so we set just the watch paths through Railway's API.
- **Retrying the right failures.** `scripts/deploy_check.py` follows a merge to beta: it waits for the tests, then for
  each service's deploy, and if Railway's build machine failed it builds again from source (twice at most). If the
  failure is ours (a bad package, a crash on start) it prints the end of the log and stops instead of retrying.
- **Why it beat a separate VTT branch or environment.** A second branch or preview site would mean twice the deploys
  and twice the places for this to happen; the switch keeps one pipeline.

**For a new project:**
1. Read the failure log before blaming your change: "build daemon", "buildkit" and similar mean the host failed.
2. Give each service watch paths, so a change rebuilds only what it affects.
3. Keep host settings in the repo where you safely can (versioned, reviewed, testable), but read what a tool manages
   before adopting it: "the whole project in one file" also means "delete what isn't in the file".
4. Retry only failures you've identified as the host's; retrying your own errors just hides them.

## 2026-10-24: A live connection to every page (WebSockets)

Until now each page asked the server "anything new?" every few seconds (polling). Now each page keeps one open
connection, a **WebSocket**, and the server tells it the moment something changes at its table: a roll shows up on
everyone's screen in a few hundredths of a second instead of up to 3 seconds.

- **What travels on it.** Only "what changed" ("a roll", "Cole's sheet"), never the roll itself. The page then fetches
  it the normal way, so the rules about who may see a DM-only roll stay in one place.
- **Hosting.** Railway and Cloudflare both pass WebSockets through with no settings to change (Cloudflare's proxy
  supports them by default). Proxies do close connections that stay quiet, so each page sends a tiny "ping" every 25
  seconds.
- **Deploys.** A deploy restarts the app, which drops every connection; pages reconnect on their own (waiting a little
  longer each try) and catch up on anything they missed. Slow polling stays on as a safety net.
- **Ready for more than one copy.** Each copy of the app keeps its own pages' connections, so copies need a shared
  channel to tell each other about changes. Postgres has one built in (LISTEN/NOTIFY): every copy listens, and a change
  on any copy reaches every page. No new service to run or pay for. It also covers a deploy, when the old and new copies
  overlap for a moment.

**For a new project:**
1. Start with polling; switch to WebSockets when "a few seconds late" starts to matter.
2. Send "something changed" on the socket and let the page fetch the details: one place enforces permissions.
3. Keep polling as a slow fallback and reconnect with growing waits, so a dropped connection costs speed, not data.
4. Build the shared channel from day one (Postgres LISTEN/NOTIFY if you already have Postgres): adding a second copy of
   the app later then needs no rewrite.

## 2026-10-24: Browser tests

Until now every automated test talked to the server directly. That can't see what happens *in a page*: the roll
window's Enter key stopped working after a click and no test noticed. Now a second kind of test drives real browser
pages.

- **Playwright** (from Microsoft) controls a real Chrome-like browser (Chromium) with no window. The tests start askdnd
  itself on a spare port with its own throwaway database, sign several people in at once (each in a separate
  "context", like separate browsers), click, press keys and read what each person sees.
- **What they cover:** the main pages load with no errors; the roll window's keys; a player's roll reaching the DM's
  screen in under 1.5 seconds; a DM-only roll's number staying hidden from other players.
- **On GitHub** the checks install the browser first (about 30 seconds), then run these with the rest. A pull request
  that breaks one of these flows can't merge.
- **Proved, not assumed:** with the Enter-key bug put back, the test fails.

**For a new project:**
1. Server tests check rules and data; browser tests check what people actually do. You want a few of the second kind
   for the flows that matter most, not hundreds.
2. Give the test server its own database and block it from calling outside services, so tests are repeatable and free.
3. When you fix a bug a test should have caught, add the test and check it fails with the bug put back.

## 2026-10-24: Error reporting (Sentry)

Until now, if something broke on beta, we found out when someone at the table hit it. Now errors report themselves.

- **Sentry** (sentry.io) collects errors and emails Brett the first time each new one happens. It's the standard tool;
  the free Developer plan covers a table our size. Brett created the account and project; the project's address (its
  "DSN") is a secret, set on Railway only (`scripts/set-secret.sh SENTRY_DSN --clipboard --railway-only`), so testing
  on a laptop never alerts him. A deliberate test error sent from beta arrived in Sentry as the first issue.
- **What it sees:** the error, the page and the line of code. Not notes, recaps, transcripts, form contents, emails or
  names. That's switched off in Sentry's settings and scrubbed again before sending, and a test checks it.
- **Errors in the browser** (a button that throws, for example) are sent back to askdnd, which forwards them, so no
  outside script runs in players' browsers.
- **The nightly backup** reports its failures the same way.

**For a new project:**
1. Add error reporting before real people use it; the free tiers are enough to start.
2. Decide what must never leave your app, and turn it off in the reporting tool's settings, not just in your code.
3. Send a test error once it's set up, so you know the alert actually reaches you.

## 2026-10-24: Working in parallel

To move faster without cutting corners, independent pieces with little design (file storage, rules data, faster
checks) run as separate Claude sessions, each in its own copy of the code (a git "worktree"), each ending in a pull
request Brett approves. Lesson learned on day one: they also need their own **test databases**, because two test runs
on one database block each other.

## 2026-10-24: Faster checks (same tests)

Every merge waited about 4 minutes for GitHub's checks before Railway even started building. Now it's about 1 minute,
with the same 454 tests and the same rule: Railway deploys only when every check passes.

- **Measured first.** The time wasn't the browser download or a few broken tests: it was 450 ordinary tests run one
  at a time, and one thing inside them. Tests turned off a small memory of "who has which role" that the real app
  keeps, so every page reloaded it from the database dozens of times. The link checker (which opens about 300 pages
  as each kind of person) spent most of its minute doing that.
- **Two jobs side by side.** GitHub now runs "Server tests" and "Browser tests" at the same time, on separate machines.
  You wait for the slower one, not both added together. They show as two checks on a pull request.
- **Parallel tests** (pytest-xdist): the server tests are split across the machine's processors. Each "worker" gets
  its own test database (askdnd_test_gw0, _gw1, …) so they never trip over each other. Locally, `uv run pytest` does
  the same on your Mac's cores: about 25 seconds instead of 100.
- **One test database per copy of the code.** Each folder (the main one, each session's worktree) now tests on its own
  database named after the folder (askdnd_test_dndsy, …), made automatically. Several sessions testing at once on the
  Mac no longer block each other on one shared database.
- **Cached browser**: the test copy of Chromium is saved between runs and downloaded again only when Playwright is
  upgraded.
- **Safety net kept:** on GitHub, a test that skips (because something is missing, like the database or the browser)
  now fails the run, so nothing quietly stops being tested.
- **Railway's build** (1–3 minutes) is unchanged: the slow parts are on Railway's side (it reinstalls packages and
  pushes the finished image every time), and the settings that could change that would also apply to the backup
  service.

| | Before | After |
|---|---|---|
| GitHub checks, whole run | 2.5–4.5 min | about 1 min |
| Tests (on GitHub) | 2:20–3:40, one at a time | 32 s server + 24 s browser, side by side |
| Browser install | 20–24 s | about 11 s (cached) |
| Railway build | 1–3 min | unchanged |

**For a new project:**
1. Time each step before changing anything; the slow part is often not the one you'd guess.
2. Split checks into jobs that run side by side, and make sure your deploy waits for all of them.
3. Run tests in parallel early, giving each worker its own database; it's much harder to add once tests depend on
   each other.
4. Make your test settings match production's where you can: here, a cache the tests had switched off was the main
   cost.

## 2026-10-24: Openly licensed game data (the SRD)

askdnd now keeps the free part of the 2024 rules, the System Reference Document 5.2.1, as data: every monster, spell,
magic item and condition. It's published by Wizards of the Coast under **CC-BY-4.0**, a license that lets anyone copy
and reuse it, even in a public repository, as long as they credit it.

- **The license's own wording.** The SRD's first page gives the exact sentence to include and asks for no other credit
  to Wizards. It's on Help › About word for word and in `app/data/srd/README.md`; other places just say "SRD 5.2.1".
- **From the original, not a copy of a copy.** A script reads Wizards' PDF itself (the fonts show which text is a
  monster's name, a field or an action) and writes one JSON file per kind. A free conversion (Open5e) is used only as a
  second opinion: a check lists every number where the two disagree, and each was settled by looking at the PDF.
  That turned up several mistakes in the conversion, and a few misreadings in our script, fixed before saving.
- **Public and private kept apart.** What's openly licensed lives in the repo; anything from the books Brett bought, or
  a DM's own creations, goes in the database, per campaign. The app reads both as one list.
- **Checked when loaded.** Each kind has a schema (the fields it must have and their types). A file or database row
  that doesn't fit fails loudly instead of showing up wrong on a page.

**For a new project:**
1. Read the license before using "free" data, and copy its attribution exactly where it asks.
2. Prefer the publisher's own file; use a community version as a cross-check, not the source.
3. Keep a script that rebuilds the data from the source instead of editing the data by hand.
4. Decide early what may be public (licensed data, code) and what must stay private (purchased content, user data).

## 2026-10-24: File storage (VTT 0.5)

Pictures were stored inside the database. That's fine for a handful, but maps, handouts, tokens and music won't fit,
so askdnd now has proper file storage.

- **Where files live.** Amazon S3, in the same bucket as before but only under `v2/files/` (legacy uses the rest of the
  bucket and is never touched). On the Mac and in tests, files go to a folder instead (`private/files/`, never
  committed), so nothing local ever writes to the real bucket.
- **Names that never change.** Each file is named by a fingerprint of its contents (a "content hash") inside its
  campaign's folder: `v2/files/<campaign>/<fingerprint>.webp`. The same picture uploaded twice is stored once, and a
  name always means the same bytes, so browsers can keep a copy for good and load pages faster.
- **Still private.** There are no public links to the bucket. Pictures are served through askdnd, which checks who's
  asking first, exactly as before.
- **Limits.** Only listed kinds of files (pictures for now) and up to 20 MB each.
- **Moving the old pictures, safely.** Add before you remove: (1) a new column for each picture's storage name;
  (2) askdnd writes pictures to both places and reads storage first, falling back to the database; (3) a script copies
  every existing picture and checks each copy byte for byte; (4) only after that's checked on beta does a later change
  remove the database copies. At every step beta keeps working, and undoing a step loses nothing.
- **Backups.** The nightly backup is of the database, so it no longer contains the pictures. Instead the database
  lists every file, and after each backup the job checks they're all there and only deletes a file once nothing has
  used it for 35 days. Backups are kept 30 days, so any backup can still be restored with all its pictures.
- **Keys.** The website gets its own AWS user (`askdnd-v2-files`) that can read and write `v2/files/` but not delete.
  The backup job's user can also list and delete there, because it's the one that tidies up.

**For a new project:**
1. Keep files (uploads, images, audio) in object storage like S3, not the database, and serve them through your app
   when they're private. Use a local folder for development so tests never touch the real bucket.
2. Name files by their content hash: duplicates disappear, and you can cache them forever.
3. When moving data, add the new place first, write to both, copy the old data with a script that checks every copy,
   and remove the old place in a separate, later change.
4. A database backup doesn't cover files. Decide how files are protected: here, nothing is deleted until every kept
   backup is past needing it, and the backup job checks the files are there.
5. Give the website only the permissions it needs (no delete), and let one scheduled job do the cleanup.

## 2026-10-26: A map of the stack

askdnd now has one picture of all its moving parts: `docs/stack.html` (also published as a private page). It shows
how a change travels (Mac → GitHub → Railway), how the table reaches the site (Cloudflare), the five outside services
the site calls, and, by color, who can change each piece: Claude from the terminal, Brett in a dashboard, or both.

- **Claude's reach is the command-line tools signed in on this Mac** (`gh`, `railway`), not the dashboards. AWS,
  Google Cloud, Cloudflare, Anthropic and Sentry stay Brett's; that's deliberate, since whoever holds the master
  login can make any key, and keeping that with a person keeps every app key narrow.
- **Connections (MCP servers)** let Claude use a service directly. Worth adding only where the CLI falls short: Sentry
  (read and resolve errors without screenshots), which Brett connected the same day, signing in with his Sentry
  account so no key was pasted anywhere. Railway and GitHub are already covered by their CLIs.

**For a new project:**
1. Draw the stack early and keep it in the repo: every service, the arrows between them, and who holds each login.
2. List every secret's name, which service uses it, and where it's made, never its value.
3. Give an assistant the narrowest access that does the job: CLIs or connections for daily work, account-level
   dashboards (billing, IAM, DNS) kept with a person.

## 2026-10-26: Checking every screen width

Two resizing bugs reached beta in one day, because every browser test ran at one window size. Now:

- **A width check on every pull request.** A browser test opens each main page (as a player and as an admin, with
  deliberately long names) at phone, tablet, laptop and wide widths, plus each tab, the menus and the side panel, and
  fails if anything scrolls sideways, spills out of its box, breaks a button onto two lines, or covers text. Its first
  runs found real problems on Sheet, Battle, Party, Help and two Manage pages.
- **A sweep at the end of each phase.** The same check over every page of a copy of real data, as each role, with a
  screenshot of each page at each width to look over for what can't be measured (cramped, hard to read).
- **Rules written down.** The design notes now say, for each part of a page, what gives way first as the room runs out.

**For a new project:**
1. Test layouts at several widths from the start, not just desktop and phone; the in-between widths break most.
2. Check measurable things (sideways scrolling, text spilling, wrapping) automatically; save human review for taste.
3. Use long, realistic names in test data; short placeholders hide layout bugs.
4. Let a component respond to its own space (container queries), not only the screen's, when it sits beside others.

## 2026-10-26: Artifacts live in the repo

**What:** every page Claude published on claude.ai for askdnd (plans, explorations, before-and-after comparisons) now
has its source in `docs/artifacts/`, with an index (`docs/artifacts/README.md`) linking each one. CLAUDE.md tells
every future session to save new pages there.

**Why:** a page that lives only in one service is one account change away from gone. In git, it's on GitHub, on
your Mac and in every copy of the repo, next to the code it describes. Screenshots of real pages stayed out, because
the repo is public and they show the campaign.

**For a new project:**
1. Keep the source of every planning page and diagram in the repo from day one, and link the hosted copy from it.
2. Decide early what may go in a public repo; screenshots of real data usually can't.

## 2026-10-26: Try changes locally before deploying

**What:** a user-visible change is tried on the local server first, on the local copy of beta's data, from a link that
signs you in and opens the page (`http://localhost:8000/dev/login?next=/characters/1/battle`). It's merged and
deployed once it looks right.

**Why:** a beta deploy takes several minutes (tests on GitHub, then Railway's build), so each round of "still broken"
cost one. Locally a fix is a page reload away. The local copy can't show what only the cloud does: Google sign-in,
Railway's settings, pictures in S3, Sentry, the deploy itself, or several people on different devices.

**For a new project:**
1. Keep a local copy of real (or realistic) data and a one-click local sign-in that only works on your own computer.
2. Review on local first; use the hosted environment for what only it can show.

## 2026-10-27: The D&D Beyond bridge only runs during the game
- **What:** the bridge (local proof, branch `ddb-bridge-proof`) now sleeps unless the table is playing or testing. It wakes on Game Mode, a change made through askdnd, or the check. It sleeps after 30 minutes idle, on Game Mode off, or after 6 hours at most. Asleep, it reads nothing from D&D Beyond.
- **Why:** a tool that talks to someone else's service should use it only while it's needed and say plainly who it is. Brett accepts D&D Beyond's terms risk knowingly and tells the table.
- **Reuse on a new project:** anything that polls another service gets an "awake" switch with an idle timeout *and* a hard cap, so a forgotten tab can't keep it running. And every hand-off between two programs needs a "got it" reply: without one, a message to a stale tab looks like it was delivered. Count unanswered hand-offs as failed tries and give up loudly after a few.

## 2026-10-27: Merging a feature "dark"
- **What:** the D&D Beyond bridge merged into `main` switched off. It runs only on a computer with `DDB_BRIDGE=1` in `.env`, and the code refuses to turn it on in production, so beta looks exactly the same; beta's database just gains four empty tables.
- **Why:** one branch, kept current with everything else, instead of a long-lived side branch that drifts. Turning it on for the table becomes a settings change plus installing the extension, not a big merge.
- **Reuse on a new project:** guard unfinished features with an environment variable that's off by default and can't be switched on in production by accident. Merge early, show late. Its timers live on an admin page rather than in code, so they can be tuned without a deploy.

## 2026-10-27: Pictures live only in S3 (VTT 0.5 finished)
- **What:** a read-only check compared every picture still in beta's database with its copy in S3, byte for byte (84 note images, all identical; all 28 stored files present). Then askdnd stopped writing and reading the database copies, and a last change dropped them.
- **Why in three steps:** each is safe on its own. The check changes nothing; the second step leaves the old copies in place, so undoing it loses nothing; only the third deletes, and it refuses to run if any picture lacks its S3 copy. The backups from before it still hold the old copies for 30 days.
- **Reuse on a new project:** when moving data from one place to another, add the new place, copy, *verify with a separate read-only check*, switch reads over, and only then delete the old copy, as its own step that someone approves. Write the verification as a script you keep, not a one-off command, so you can show the numbers.

## 2026-10-28: Publishing a Chrome extension (the askdnd bridge)

- **What:** a Chrome Web Store developer account (Brett's Google account, publisher name "askdnd", $5 once), and the
  bridge packaged for it: `scripts/build_extension.py` makes the zip, the listing text is in
  `extension/askdnd-bridge/README.md`, and Help › About's bridge section is its privacy policy. The listing is
  **unlisted**: only people with the link find it, and Chrome keeps everyone's copy up to date on its own.
- **Why the store, not "Load unpacked":** an unpacked extension needs Developer mode, never updates itself, and Chrome
  nags about it at every start. Through the store, a new version reaches the whole table after Google's review.
- **One folder, two copies:** the repo's folder works with askdnd on your own computer and on beta (for trying
  changes); the store's copy is the same files with localhost taken out of its permissions, which reviewers look at.
- **Switched on per campaign:** beta may run the bridge (`DDB_BRIDGE=1`), but each campaign switches it on itself
  (a VTT piece), so it reaches the table only when you decide, after telling them the risk.
- **Reuse on a new project:** register the developer account early (review can take days), keep the listing text and
  the privacy page in the repo next to the code, publish unlisted until you're sure, and raise the version for every
  upload: the store refuses one it already has.

## 2026-10-29: Keeping the branch list tidy

- **What:** 102 branches on GitHub and 97 on this computer were deleted: every one whose work was already in `main`
  (each pull request keeps its own history, so nothing is lost), plus three mockup branches whose work had reached
  `main` another way. Kept: `main`, `legacy` (the old app, never touched) and four 2025 branches from the old app.
  GitHub now deletes a branch by itself when its pull request merges (repo Settings › General › Pull Requests ›
  Automatically delete head branches).
- **Why:** a branch list that holds only work in progress answers "what isn't merged yet?" at a glance. Today it
  turned up one mockup whose source had never reached `main`.
- **Not deleted:** branches still open in another session's working folder (`.claude/worktrees/`); git won't delete
  a branch that a folder has checked out. They go when those folders are cleaned up.
- **Reuse on a new project:** turn on automatic branch deletion on day one, and before deleting a branch by hand,
  check that `main` has its work (`git log main..branch` shows nothing).

## 2026-10-30: A test table that runs itself (Mac Mini)

- **What:** three real Chrome windows on the always-on Mac Mini, each signed in as a test person on real D&D Beyond and beta with the askdnd bridge. A script (`scripts/real_table.py`) acts like those people and reports what happened.
- **Why:** several people, several browsers and a real third-party site are slow to test by hand. The first run confirmed one fix on the real site and found a timing problem that made-up test data had missed.
- **Copies, not the originals:** Chrome blocks scripts from its normal profile folder, so each seat is a copy in its own folder on the Mini. A cleaned-up copy left out a folder the extension needs, so copy everything but page caches.
- **Reuse on a new project:** test accounts that could be flagged are never your real ones; an always-on machine suits slow real-world checks; keep them apart from the everyday tests, which must stay fast and need no accounts.


## 2026-11-02: Tests you can trust, every night

- **A canary:** a small check that runs by itself on a schedule and warns you before anyone else notices, like the canary miners took underground. Every night at 4:00 the Mac Mini opens the three test seats, runs part 1 of the live test against beta on the real D&D Beyond, and closes them. If anything misses, Sentry emails you, the same way the app's own errors arrive. It catches what the everyday tests can't: D&D Beyond changing its site, or timing that only shows on the real thing. A job like this on a Mac is a launchd "LaunchAgent" (a small settings file that says what to run and when); on Linux it would be cron.
- **Why flaky tests matter here:** GitHub runs the tests on every push, and Railway waits for them before deploying beta. A test that fails at random either blocks a good deploy or teaches everyone to press "run again" until it passes, and then a real failure gets waved through too. Today's flakes weren't bad luck: two test runs at the same time (two Claude sessions in one folder) used the same test database and wiped each other's tables. Each run now claims its database with a lock, and a second run steps aside to its own. Two smaller ones went too: a test server could lose its port to another program, and its log, written to a pipe nobody read, could fill up and freeze it.
- **Why test in Safari's engine:** on an iPhone every browser (Safari, and Chrome too) uses Apple's WebKit underneath, and it draws some things differently from Chrome's engine (fonts, form fields, a few layout details). The layout check now also opens every page as an iPhone and an iPad in WebKit, so a page that breaks only on your phone is caught before it ships.
- **What the live test found:** the Temporary Hit Points window wouldn't let you set them until you clicked "Take" yourself, and a Short Rest's Hit Point Die could take over 30 seconds to reach D&D Beyond. Both are fixed, with tests.
- **Reuse on a new project:** give each test run its own database (or a lock on it), never let a background process write to a pipe nothing reads, run a nightly check against the real outside services you depend on and send its failures where your other alerts go, and test in the browser engine your users actually have.
