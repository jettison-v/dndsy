# DnDsy (askdnd.ai)

RAG assistant for the D&D 2024 ruleset ("5.5e"). Users ask rules questions; the app retrieves from indexed official PDFs and answers with page-level source attribution. Live at askdnd.ai. Solo personal project, built in 2025 with Cursor; being revived and modernized after ~a year dormant.

## Stack
- Python 3.11.9 (pyenv) · Flask 3 + Gunicorn/gevent · server-rendered Jinja templates + vanilla JS (`static/js`, Marked.js)
- Vector DB: Qdrant Cloud · Files: AWS S3 bucket `askdnd-ai` (source PDFs, page images, links, metadata, processing history)
- LLM: OpenAI only (`llm_providers/openai.py`). An Anthropic provider is stubbed/commented out in `llm_providers/__init__.py`.
- Embeddings: sentence-transformers `all-MiniLM-L6-v2` (pages, haystack stores) and OpenAI `text-embedding-3-small` (semantic store)
- Hosting: Railway, Docker build from `docker/Dockerfile` (see `railway.json`)

## Layout
- `app.py` — the real app: all Flask routes (chat via `/api/chat` streaming, login, admin panel APIs). Large (~1.5k lines).
- `llm.py` — RAG orchestration; `ask_dndsy()` is the core entry point.
- `config.py` — central config; `vector_store/` — four store implementations (`pdf_pages_store`, `semantic_store` [default, hybrid vector+BM25], `haystack/qdrant_store`, `haystack/memory_store`) behind a factory in `__init__.py`.
- `data_ingestion/processor.py` — PDF → images, structure analysis, links, metadata, embeddings, indexing. Driven by `scripts/manage_vector_stores.py`.
- `templates/` + `static/` — desktop and separate `mobile/` variants.
- `main.py` — stale FastAPI stub; FastAPI is not in requirements. Ignore it (candidate for deletion).

## Commands
```bash
source .venv/bin/activate            # venv is .venv (README says venv/ — outdated)
pip install -r requirements.txt      # requirements.in is the source; requirements.txt is compiled
flask run                            # http://localhost:5000, log in with APP_PASSWORD
pytest                               # see Testing notes
python -m scripts.manage_vector_stores --store semantic --cache-behavior use   # ⚠️ see Guardrails
docker compose -f docker/docker-compose.yml up --build app                     # app + local Qdrant
```

## Guardrails (important)
- **Local `.env` points at PRODUCTION** (`ENV=production`, prod S3 bucket, Qdrant Cloud). Anything that writes to S3 or Qdrant from this machine hits the live site. Never run `manage_vector_stores` (especially `--cache-behavior rebuild`, which deletes collections), admin process/upload/delete endpoints, or tests marked as external without asking first. Rebuilding also costs OpenAI embedding spend.
- For safe experimentation prefer `ENV=development` (adds `dev-` S3 prefix) and/or local Qdrant via docker-compose.
- **Pushing to `main` likely deploys to askdnd.ai** (Railway auto-deploys from the connected branch; `.github/workflows/deploy.yml` is a placeholder that skips tests and deploy). Work on feature branches; don't push or merge to `main` unless asked.
- Never print, log, or commit `.env` contents or secrets.

## Testing notes
- pytest config in `pytest.ini`; fixtures in `tests/conftest.py` (`client`, `authenticated_client`).
- Many tests hit real services (Qdrant Cloud, OpenAI). Markers are declared (`unit`, `integration`, `api`, `vector_store`, `slow`, `external`) but only `api` is actually applied, so `-m "not external"` does not filter much yet. Prefer running specific files, e.g. `pytest tests/test_app.py`.
- CI does not run tests.

## Known state / tech debt
- Models are hard-coded in several places (`app.py`, `config.py`, `llm_providers/openai.py`): gpt-4.1 family + o4-mini (2025-era). Centralize before upgrading.
- Dependencies are pinned to early-2025 versions (langchain 0.1.x, transformers 4.36, openai 1.70). Upgrades will need care, especially langchain.
- Four parallel vector-store implementations is likely more than needed; `semantic` is the production default.
- README is long and partly outdated (mentions `runtime.txt`, 3.11.7, `venv/`, files that no longer exist). Treat the code as the source of truth.

## Working style
- Plan before multi-file changes; keep diffs focused; commit in small, descriptive commits.
- When touching retrieval/answer quality, describe how to verify it (a few sample rules questions and the expected sources).
