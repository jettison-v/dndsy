# askdnd v2

A companion app for one D&D 2024 table: pre-session recaps, character briefings and (later) rules answers.

- Product: [docs/BRIEF.md](docs/BRIEF.md)
- Architecture and build plan: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Decisions: [docs/DECISIONS.md](docs/DECISIONS.md)
- Setup log: [docs/SETUP_LOG.md](docs/SETUP_LOG.md)

## Run locally

Requires [uv](https://docs.astral.sh/uv/) and Postgres 18 (Homebrew):

```bash
brew install postgresql@18 && brew services start postgresql@18
/opt/homebrew/opt/postgresql@18/bin/createdb askdnd_dev
/opt/homebrew/opt/postgresql@18/bin/createdb askdnd_test
```

Then:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --env-file .env
```

Secrets live in `.env` locally and Railway variables in production (see `.env.example`). Set one in both places with:

```bash
scripts/set-secret.sh NAME
```

Then open http://localhost:8000 (health check at `/health`).

## Switching between cloud sessions and this Mac

Work done in a Claude cloud session is pushed to `main` on GitHub (which also deploys beta). Before working
locally again, bring your copy up to date:

```bash
git checkout main && git pull       # get the latest code
uv sync                             # install any new packages
uv run alembic upgrade head         # apply new database changes to askdnd_dev
uv run pytest -q                    # check everything passes
```

Your local database (`askdnd_dev`) is separate from beta's, so it has its own people, characters and story.
Character data added by newer versions (item notes, the Background tab, portraits) appears after
**Manage › Characters › Refresh all** locally. Before going back to the cloud, commit and push from here.



Install the double-click app once (re-run after moving the repo):

```bash
scripts/install-processor-app.sh
```

Then open **askdnd Processor** from Applications (or the Dock): drop in a MacWhisper
*Segments* `.json` export, click **Filter**, review the cuts, and **Save**. It runs at
http://127.0.0.1:8765 only; raw transcripts never leave the Mac. Logs:
`~/Library/Logs/askdnd-processor.log`.

## Database changes

Edit `app/models.py`, then generate and apply a migration:

```bash
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

Railway applies migrations automatically on deploy (see `Procfile`).

## Test

```bash
uv run pytest
```

D&D Beyond parsing is tested against saved public character sheets in `tests/fixtures/ddb/`
(tests never call D&D Beyond). To add or update one (player notes are stripped):

```bash
uv run python -m scripts.ddb_fixture 75423618 cole
```

The legacy (v1) app is on the `legacy` branch and the `v1-legacy` tag.
