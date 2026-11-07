"""The roadmap's table of documents, written from docs/library.json, the one list of every page made for askdnd (the
same list Manage › askdnd › Documents shows; app/documents.py).

    uv run python scripts/library.py          # rewrite the table in docs/roadmap.html, then republish the roadmap

Add a new page to docs/library.json first (tests/test_documents.py fails on a page in docs/ it doesn't list), then run
this; tests/test_documents.py also fails when the roadmap's table and the list disagree.
"""

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "docs" / "library.json"
ROADMAP = ROOT / "docs" / "roadmap.html"
KIND_ORDER = ("guide", "plan", "design", "earlier")
TABLE = re.compile(r'(<section id="documents">.*?<tbody>\n)(.*?)(      </tbody>)', re.S)


def chip(status: str) -> str:
    s = status.lower()
    if s.startswith(("superseded", "earlier", "not built")):
        return "s-parked"
    if s.startswith(("current", "paused", "for you", "approved", "running")):
        return "s-todo"
    return "s-done"


def rows() -> str:
    """One row per document, guides first, then plans, designs and earlier ones, in the list's own order within each."""
    entries = json.loads(LIBRARY.read_text())
    out = []
    for kind in KIND_ORDER:
        for e in (x for x in entries if x["kind"] == kind):
            title = html.escape(e["title"])
            name = f'<a href="{html.escape(e["link"])}">{title}</a>' if e["link"] else title
            what = html.escape(e["what"]) + (f' Source <code>{html.escape(e["source"])}</code>.' if e["source"] else "")
            out.append(f'        <tr><td>{name}</td><td><span class="chip {chip(e["status"])}">{html.escape(e["status"])}</span></td>'
                       f'<td>{html.escape(e["date"])}</td><td class="what">{what}</td></tr>\n')
    return "".join(out)


def written(page: str) -> str:
    """The roadmap with its table of documents written from the list."""
    if not TABLE.search(page):
        raise SystemExit("docs/roadmap.html has no table of documents (<section id=\"documents\"> … <tbody>).")
    return TABLE.sub(lambda m: m.group(1) + rows() + m.group(3), page, count=1)


def main() -> None:
    page = ROADMAP.read_text()
    new = written(page)
    if new == page:
        print("The roadmap's table already matches docs/library.json.")
        return
    ROADMAP.write_text(new)
    print("Wrote the roadmap's table of documents from docs/library.json; republish the roadmap.", file=sys.stderr)


if __name__ == "__main__":
    main()
