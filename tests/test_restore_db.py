"""scripts/restore_db.py's guards: a backup never lands on beta's database by accident, and --into-staging only works
on staging's own server (Nov 6, the staging environment)."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "restore_db.py"


def run(monkeypatch, *args: str, env: dict | None = None) -> str:
    spec = importlib.util.spec_from_file_location("restore_db", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["restore_db.py", *args])
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit) as stop:
        mod.main()
    return str(stop.value)


def test_a_railway_database_needs_saying_so(monkeypatch):
    assert "looks like the Railway database" in run(monkeypatch, "--into", "postgresql://x@postgres.railway.internal/db", "--file", "x")


def test_into_staging_refuses_anywhere_but_staging(monkeypatch):
    assert "only on staging's own server" in run(monkeypatch, "--into-staging", "--file", "x")
    assert "only on staging's own server" in run(monkeypatch, "--into-staging", "--file", "x", env={"RAILWAY_ENVIRONMENT_NAME": "production"})
