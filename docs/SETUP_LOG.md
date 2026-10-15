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
