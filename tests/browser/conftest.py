"""Browser tests (VTT 0.8, docs/plans/2026-10-22-vtt-roadmap.md): a real askdnd server and real Chromium pages,
several people at once, through the table's core flows. Server tests can't see what pages do, or what they do to each
other live; these do.

- The server runs as its own process on a free port, on its own database (the test database's name + `_browser`),
  seeded with the test bundle: Cole (played by player@), Trah (other@), the DM (dm@) and an admin (admin@).
- Everyone signs in with the local-only dev sign-in (`/dev/login?as=`); each person is a separate browser context,
  so their cookies don't mix.
- D&D Beyond is never called: the server's outbound requests go to a dead proxy, and Cole's sheet comes from the test
  fixture.

Run with the rest (`uv run pytest`). They need Playwright's Chromium (`uv run playwright install chromium`): without
it they skip on a laptop and fail on GitHub, like the database.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
PEOPLE = {"player": "player@example.com", "other": "other@example.com", "dm": "dm@example.com", "admin": "admin@example.com"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")  # per file: torn down before the server tests run
def browser_db():
    """A database of its own (the server can't see the other tests' uncommitted rows), seeded and committed."""
    from tests.conftest import TEST_DATABASE_URL

    url = make_url(TEST_DATABASE_URL)
    url = url.set(database=f"{url.database}_browser")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except Exception:
        if os.getenv("CI"):
            raise
        pytest.skip("local test database not available (brew services start postgresql@18)")
    import app.models  # noqa: F401
    from app import characters
    from app.db import Base
    from app.importer import import_bundle
    from tests.roles import set_role
    from tests.table_setup import BUNDLE, char, fake_fetch, owned_by

    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        import_bundle(db, BUNDLE)
        cole, trah = char(db, "Cole"), char(db, "Trah")
        owned_by(db, cole, PEOPLE["player"])
        owned_by(db, trah, PEOPLE["other"])
        set_role(db, PEOPLE["dm"])
        characters.refresh(db, cole, fake_fetch)
        db.commit()
        ids = {"cole": cole.id, "campaign": cole.campaign_id}
    engine.dispose()
    yield url.render_as_string(hide_password=False), ids
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="module")  # per file: torn down before the server tests run
def server(browser_db, tmp_path_factory, request):
    """askdnd itself, as it runs on beta (uvicorn, its startup and the Postgres listener), on a free port. A test file's
    SERVER_ENV adds to its settings (the bridge, for test_extension.py)."""
    database_url, ids = browser_db
    port = _free_port()
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "development", "SESSION_SECRET": "browser-tests",
           "FILE_STORAGE": str(tmp_path_factory.mktemp("files")),
           "DEV_LOGIN_EMAIL": PEOPLE["admin"], "ADMIN_EMAILS": PEOPLE["admin"], "ALLOWED_EMAILS": ",".join(PEOPLE.values()),
           "AUTO_DRAFT": "0", "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",  # never D&D Beyond
           "NO_PROXY": "127.0.0.1,localhost", **getattr(request.module, "SERVER_ENV", {})}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    end = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(base + "/login", timeout=2):
                break
        except Exception:
            if proc.poll() is not None or time.monotonic() > end:
                proc.kill()
                pytest.fail("askdnd didn't start:\n" + (proc.stdout.read() if proc.stdout else ""))
            time.sleep(0.2)
    yield {"base": base, **ids}
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")  # per file: torn down before the server tests run
def chromium():
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Error:
            if os.getenv("CI"):
                raise
            pytest.skip("Playwright's Chromium isn't installed (uv run playwright install chromium)")
        yield browser
        browser.close()


class Person:
    """One person at the table: their own browser context, signed in, with the dice animation off (the numbers are the
    same; the tests don't wait for dice to land), in the table's time zone (Pacific).
    `errors` collects the page's JavaScript errors."""

    def __init__(self, chromium, server, who: str):
        self.server, self.errors = server, []
        self.context = chromium.new_context(viewport={"width": 1400, "height": 900}, timezone_id="America/Los_Angeles")
        self.context.set_default_timeout(10_000)  # a page that's working answers well within this
        self.context.add_init_script("localStorage.setItem('askdnd.rollsAnim', 'off'); if (!sessionStorage.getItem('fresh')) { sessionStorage.setItem('fresh', '1'); localStorage.setItem('askdnd.rollsSide', 'open'); }")
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        # The console's "Failed to load resource" doesn't say which: record the failing address instead
        self.page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and self.errors.append(m.text))
        self.page.on("response", lambda r: r.status >= 400 and self.errors.append(f"{r.status} {r.url.replace(server['base'], '')}"))
        self.page.goto(f"{server['base']}/dev/login?as={PEOPLE[who]}")

    def open(self, path: str):
        self.page.goto(self.server["base"] + path)
        return self.page

    def live(self):
        """Wait until the page's live connection to the table is up."""
        self.page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=5000)


@pytest.fixture
def people(chromium, server):
    """people("player", "dm") → a signed-in Person for each."""
    made = []

    def make(*who):
        out = [Person(chromium, server, w) for w in who]
        made.extend(out)
        return out if len(out) > 1 else out[0]

    yield make
    for p in made:
        p.context.close()


