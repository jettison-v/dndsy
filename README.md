# askdnd v2

A companion app for one D&D 2024 table: pre-session recaps, character briefings and (later) rules answers.

- Product: [docs/BRIEF.md](docs/BRIEF.md)
- Architecture and build plan: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Decisions: [docs/DECISIONS.md](docs/DECISIONS.md)
- Setup log: [docs/SETUP_LOG.md](docs/SETUP_LOG.md)

## Run locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload --env-file .env
```

Secrets live in `.env` locally and Railway variables in production (see `.env.example`). Set one in both places with:

```bash
scripts/set-secret.sh NAME
```

Then open http://localhost:8000 (health check at `/health`).

## Test

```bash
uv run pytest
```

The legacy (v1) app is on the `legacy` branch and the `v1-legacy` tag.
