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
