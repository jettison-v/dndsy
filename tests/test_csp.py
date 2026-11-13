"""A standing rule (the engineering practices, Nov 13; docs/plans/2026-11-13-engineering-practices.md): askdnd's pages
run only askdnd's own script files, under a Content Security Policy that says so (app/main.py CSP). Nothing written into
a page runs: no inline <script>, no on…= handler, no htmx text evaluated as code (hx-on, hx-vals="js:…", a trigger's
[condition]). A marker and app.js do the job instead (early.js, data-confirm, data-reset-after, data-hide-broken)."""

import re
from pathlib import Path

from app.main import CSP

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_the_policy_runs_only_askdnds_own_scripts():
    rules = dict(r.split(" ", 1) for r in CSP.split("; "))
    assert rules["script-src"] == "'self'" and "unsafe-eval" not in CSP and rules["object-src"] == "'none'"
    assert rules["frame-ancestors"] == "'self'" and rules["base-uri"] == "'self'"


def test_every_page_says_so(admin):
    for path in ("/c/main/campaign", "/party", "/help"):
        assert admin.get(path).headers["content-security-policy"] == CSP


def test_nothing_written_into_a_page_runs():
    found = []
    for p in sorted(TEMPLATES.rglob("*.html")):
        if "email" in p.parts:  # (emails: no scripts at all)
            continue
        s = p.read_text()
        for pattern, what in ((r"<script(?![^>]*\bsrc=)(?![^>]*type=\"application/(?:ld\+)?json\")[^>]*>", "an inline <script>"),
                              (r"\son[a-z]+\s*=\s*[\"']", "an on…= handler"),
                              (r"\shx-on[:\-]", "hx-on (evaluated)"),
                              (r"hx-vals=\"js:", "hx-vals=\"js:…\" (evaluated)"),
                              (r"hx-trigger=\"[^\"]*\[", "a trigger's [condition] (evaluated)")):
            for m in re.finditer(pattern, s):
                found.append(f"{p.relative_to(TEMPLATES)}: {what} near {s[m.start():m.start() + 60]!r}")
    assert not found, "\n".join(found)
