"""A standing rule (Brett, Nov 13: "The tool should be able to be translated with no impact to any portion of it.
Referencing text is fragile and should not be done."): nothing finds, checks or decides by the words people see.
Every piece a test or the code refers to has a marker (`data-*`, an id) or a key in the data; tests read those
(tests/menu.py, tests/browser/pages.py).

The references older than the rule are counted here and may only go down: a new one fails this test, and converting
one means lowering its count below (the test says so when a count can go down). BASELINE is the work left."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# What counts as finding or deciding by text, per place
KINDS = {
    # a browser test finding or checking something by its words
    "browser tests": (["tests/browser/*.py"], r"has_text=|get_by_text\(|:has-text\(|text=\"|textContent(?:\.trim\(\))?\.(?:includes|startsWith)|inner_text\(\)|text_content\(\)"),
    # a server test checking a page's words ('>Needs you<' in page)
    "server tests": (["tests/*.py"], r"[\"']>[A-Z][a-z][^<\"']{2,40}<"),
    # the app deciding by a display label (a roll named "Initiative", a page labelled "Sessions")
    "app logic": (["app/*.py", "app/templates/*.html"], r"\blabel\s*==\s*[\"']|\.label\s*==|label\.startswith\([\"']|selectattr\(\"label\""),
    # app.js deciding by what an element says
    "app.js": (["app/static/app.js"], r"textContent\s*(?:===|==|!==)|(?:textContent|innerText)\.(?:includes|startsWith|indexOf|match)\("),
}
SELF = {"tests/test_no_text_refs.py"}

# The work left (Nov 13). Lower a number when you convert some; never raise it.
BASELINE = {"browser tests": 123, "server tests": 90, "app logic": 10, "app.js": 1}


def count(kind: str) -> tuple[int, dict[str, int]]:
    globs, pattern = KINDS[kind]
    per = {}
    for g in globs:
        for p in sorted(ROOT.glob(g)):
            rel = p.relative_to(ROOT).as_posix()
            if rel in SELF:
                continue
            n = len(re.findall(pattern, p.read_text()))
            if n:
                per[rel] = n
    return sum(per.values()), per


def test_no_new_reference_to_display_text():
    """Each kind's count may only go down (A standing rule, Brett Nov 13)."""
    over, under = [], []
    for kind in KINDS:
        n, per = count(kind)
        if n > BASELINE[kind]:
            worst = ", ".join(f"{f} {c}" for f, c in sorted(per.items(), key=lambda x: -x[1])[:5])
            over.append(f"{kind}: {n} references to display text, {BASELINE[kind]} allowed ({worst}). Give the thing a marker or key and use it.")
        elif n < BASELINE[kind]:
            under.append(f"{kind}: {n} now, lower BASELINE from {BASELINE[kind]} to {n}")
    assert not over, "\n".join(over)
    assert not under, "Good: fewer references to text. " + "; ".join(under)
