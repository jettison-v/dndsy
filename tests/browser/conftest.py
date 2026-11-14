"""Browser tests (VTT 0.8, docs/plans/2026-10-22-vtt-roadmap.md): a real askdnd server and real Chromium pages,
several people at once, through the table's core flows. Server tests can't see what pages do, or what they do to each
other live; these do.

- The server runs as its own process on a free port, on its own database (the test database's name + `_browser`),
  seeded with the test bundle: Cole (played by player@), Trah (other@), the DM (dm@) and an admin (admin@).
- Everyone signs in with the local-only dev sign-in (`/dev/login?as=`); each person is a separate browser context,
  so their cookies don't mix.
- D&D Beyond is never called: the server's outbound requests go to a dead proxy, and Cole's sheet comes from the test
  fixture.

Run with the rest (`uv run pytest`). They need Playwright's Chromium and WebKit (`uv run playwright install chromium
webkit`): without them they skip on a laptop and fail on GitHub, like the database.
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


def _listening() -> socket.socket:
    """A socket already listening on a free port, handed to the server as it starts. Picking a free port and letting the
    server bind it later left a gap: another session's server could take the port meanwhile, and the tests would then
    talk to that server (Nov 2: setup errors and odd failures, only while other sessions ran tests too)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(128)
    return s


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
    import app.models
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
    sock = _listening()
    port = sock.getsockname()[1]
    env = {**os.environ, "DATABASE_URL": database_url, "APP_ENV": "development", "SESSION_SECRET": "browser-tests",
           "FILE_STORAGE": str(tmp_path_factory.mktemp("files")),
           "DEV_LOGIN_EMAIL": PEOPLE["admin"], "ADMIN_EMAILS": PEOPLE["admin"], "ALLOWED_EMAILS": ",".join(PEOPLE.values()),
           "AUTO_DRAFT": "0", "UNWATCHED_SECONDS": "0", "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",  # never D&D Beyond
           "NO_PROXY": "127.0.0.1,localhost", **getattr(request.module, "SERVER_ENV", {})}
    # Its log goes to a file: a pipe nobody reads fills after ~64 KB of request lines, and the server then stops answering
    # mid-file (Nov 2: failures only in slow runs, which make more requests)
    log = tmp_path_factory.mktemp("server") / "askdnd.log"
    with log.open("w") as out:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--fd", str(sock.fileno())], pass_fds=[sock.fileno()],
                                cwd=ROOT, env=env, stdout=out, stderr=subprocess.STDOUT)
    sock.close()  # (the server has its own copy)
    base = f"http://127.0.0.1:{port}"
    end = time.monotonic() + 60  # (a machine busy with other tests can take a while to start it)
    while True:
        try:
            with urllib.request.urlopen(base + "/login", timeout=2):
                break
        except Exception:
            if proc.poll() is not None or time.monotonic() > end:
                proc.kill()
                pytest.fail("askdnd didn't start:\n" + log.read_text())
            time.sleep(0.2)
    yield {"base": base, **ids}
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


# The before-and-after pictures (test_pictures.py, foundation F7) run only for scripts/visual_compare.py
collect_ignore = [] if os.getenv("VISUAL_OUT") else ["test_pictures.py"]


@pytest.fixture(scope="module")  # per file: torn down before the server tests run
def playwright():
    """One Playwright per file, for every browser in it: a second one started beside it fails ("Sync API inside the
    asyncio loop"), as test_extension.py's own did."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


def _launch(kind):
    from playwright.sync_api import Error

    try:
        return kind.launch()
    except Error:
        if os.getenv("CI"):
            raise
        pytest.skip(f"Playwright's {kind.name} isn't installed (uv run playwright install {kind.name})")


@pytest.fixture(scope="module")
def chromium(playwright):
    browser = _launch(playwright.chromium)
    yield browser
    browser.close()


@pytest.fixture(scope="module")
def webkit(playwright):
    """Safari's engine: Brett plays on an iPhone, and every browser there is WebKit underneath."""
    browser = _launch(playwright.webkit)
    yield browser
    browser.close()


# Waiting for something on a page by polling it from here (Nov 13): Playwright's own wait_for_function evaluates its text
# inside the page, which askdnd's Content Security Policy refuses (no text evaluated as code); page.evaluate goes through
# the browser's debugging connection, which the policy doesn't govern. Same arguments, same timeout error.
def _wait_for_function(self, expression, arg=None, timeout=None, polling=None):
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    end = time.monotonic() + (timeout if timeout is not None else 10000) / 1000
    pause = polling / 1000 if isinstance(polling, (int, float)) else 0.05
    while True:
        try:
            value = self.evaluate(expression, arg)
        except PlaywrightError as e:  # (the page moved on while asked: ask again)
            if "context was destroyed" not in str(e) and "navigat" not in str(e).lower():
                raise
            value = None
        if value:
            return value
        if time.monotonic() > end:
            raise PlaywrightTimeout(f"wait_for_function: not true within {timeout or 10000}ms: {expression[:120]}")
        time.sleep(pause)


def _patch_waits():
    from playwright.sync_api import Frame, Page

    Page.wait_for_function = _wait_for_function
    Frame.wait_for_function = _wait_for_function


_patch_waits()


class Person:
    """One person at the table: their own browser context, signed in, with the dice animation off (the numbers are the
    same; the tests don't wait for dice to land), in the table's time zone (Pacific).
    `errors` collects the page's JavaScript errors."""

    def __init__(self, browser, server, who: str, **device):
        self.server, self.errors, self.csp = server, [], []  # (csp: what the Content Security Policy blocked)
        self.who, self.allowed = who, []  # (allowed: errors this test causes on purpose, by a part of their words)
        self.context = browser.new_context(**{"viewport": {"width": 1400, "height": 900}, **device}, timezone_id="America/Los_Angeles")
        webkit = browser.browser_type.name == "webkit"
        self.context.set_default_timeout(20_000 if webkit else 10_000)  # a page that's working answers well within this (WebKit is slower)
        self.context.add_init_script("localStorage.setItem('askdnd.rollsAnim', 'off'); if (!sessionStorage.getItem('fresh')) { sessionStorage.setItem('fresh', '1'); localStorage.setItem('askdnd.rollsSide', 'open'); }")
        # Outside sites a page frames (Campaign › Map's atlas) get a stand-in: the tests never depend on another site,
        # which may answer GitHub's machines differently (aidedd.org refused to be framed there, Nov 13)
        self.context.route("https://www.aidedd.org/**", lambda route: route.fulfill(status=200, content_type="text/html", body="<p>atlas</p>"))
        # Anything the Content Security Policy blocks (app/main.py CSP) is said on the console, and fails the test at its end
        self.context.add_init_script("document.addEventListener('securitypolicyviolation', e => console.error('CSP blocked: ' + e.violatedDirective + ' ' + (e.blockedURI || 'inline')))")
        self.page = self.context.new_page()
        self.page.on("console", lambda m: m.text.startswith("CSP blocked:") and self.csp.append(m.text))
        # Each error says where it came from on the test's output (shown when a test fails), so a failure on GitHub's
        # machines that never happens locally still says what it was (Nov 13: WebKit on Linux, never on a Mac)
        def note(source, text, ignored=False):
            print(f"[{who} {'ignored ' if ignored else ''}{source}] {text}")
            if not ignored:
                self.errors.append(text)
        # The console's "Failed to load resource" doesn't say which: record the failing address instead
        # (Safari's engine says a request cut short by leaving the page failed to send, which htmx reports; a real failure
        # still shows as its response below)
        cut_short = ("htmx:sendError", "htmx:afterRequest") if webkit else ()
        # (and WebKit logs a fetch of askdnd's own it cancelled, leaving a page mid-load, as "access control checks":
        # seen once tests ran side by side, Nov 13; askdnd only fetches its own address, so it's never a real one)
        # (its words vary: "Fetch API cannot load <address> …", or the address alone, Nov 13 on /search/index)
        own = server["base"].split("://", 1)[-1]
        cancelled = (lambda t: "due to access control checks" in t and own in t and "Error" not in t) if webkit else (lambda t: False)
        self.page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and m.text not in cut_short
                     and note("console", m.text, ignored=cancelled(m.text)))
        # An error the page didn't catch is a bug real browsers hit too, so it's never ignored, with one exception seen on
        # GitHub's Linux WebKit (Nov 13, tagged runs of #334): the engine's own line about a fetch it cancelled arrives as
        # a page error. It's not one: it has no error type (Safari's real fetch failure is "TypeError: Load failed"), the
        # fetch it names catches its own failure (app.js "Search" load()), and Sentry has none from people's Safari.
        def page_error(e):
            stack = (getattr(e, "stack", "") or "").replace(server["base"], "")
            if stack and not cancelled(str(e)):
                print(f"[{who} pageerror stack] {stack[:1500]}")  # (where in app.js: the line says what broke)
            note("pageerror", str(e), ignored=cancelled(str(e)))
        self.page.on("pageerror", page_error)
        self.page.on("response", lambda r: r.status >= 400 and note("response", f"{r.status} {r.url.replace(server['base'], '')}"))
        # (a fresh browser's first page, WebKit's especially, can take longer: Nov 2, 10 seconds ran out on a busy machine)
        self.page.goto(f"{server['base']}/dev/login?as={PEOPLE[who]}", timeout=30_000)

    def allow(self, *parts: str):
        """This test causes these errors on purpose (a refusal it checks, an error it throws): each by a part of its words."""
        self.allowed.extend(parts)

    def unexpected(self) -> list[str]:
        return [e for e in self.errors if not any(a in e for a in self.allowed)]

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
    blocked = [x for p in made for x in p.csp]
    # Every test, whatever it checks, fails on an error a page didn't mean to show (Brett, Nov 13: robust means no new
    # bug anyone missed): an error the page didn't catch, an error on the console, an answer of 400 or more. A test
    # that causes one on purpose says so with person.allow(...).
    errors = [f"{p.who}: {e}" for p in made for e in p.unexpected()]
    for p in made:
        p.context.close()
    assert not blocked, "The Content Security Policy blocked something a page needs:\n" + "\n".join(sorted(set(blocked)))
    assert not errors, "A page had an error this test didn't expect (person.allow(...) if it's on purpose):\n" + "\n".join(errors)




def pytest_collection_modifyitems(config, items):
    """A browser test that fails is tried once more before it fails the run (Brett, Nov 9: a timing miss on GitHub's
    shared machines meant re-running the whole job, 5 minutes or more, for nothing). Browser tests only: the server
    tests have never flaked and stay strict. Every second try is listed on the run's summary page ("passed only on a
    second try", .github/workflows/tests.yml), so a flaky test is seen and fixed at its cause, not hidden."""
    here = Path(__file__).parent
    for item in items:
        if Path(str(item.fspath)).is_relative_to(here):
            item.add_marker(pytest.mark.flaky(reruns=1, reruns_delay=2))


def pytest_runtest_logreport(report):
    """A test that failed and is being tried again says why first (Nov 13: a retry that passed hid the first failure's
    words, so a flaky test couldn't be fixed at its cause): its failure, as it would have printed, in the run's output."""
    if report.outcome == "rerun" and report.longreprtext:
        import sys

        sys.__stdout__.write(f"\n=== {report.nodeid} failed on its first try:\n{report.longreprtext[-3000:]}\n=== (trying it again)\n")
        sys.__stdout__.flush()
