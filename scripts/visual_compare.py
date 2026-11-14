"""Before and after: every main page on main against this branch (foundation F7, docs/plans/2026-11-13-engineering-practices.md).

    uv run python scripts/visual_compare.py                  # origin/main against what's checked out here
    uv run python scripts/visual_compare.py --base <ref>     # against another commit
    uv run python scripts/visual_compare.py --only-compare A B   # two folders of pictures already taken

It checks out the base in a folder of its own (private/visual/base-src), copies this branch's tests into it so both
sides are drawn the same way, and runs tests/browser/test_pictures.py on each side: the same seeded data, widths and
clock. Then it compares the pictures pixel by pixel and writes private/visual/report.html: only the pages that changed,
before, after, and the change in red. The pictures show the party's sheets: they stay in private/ (never committed).
"""

import argparse
import html
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "private" / "visual"
TOLERANCE = 24  # per colour channel: anti-aliasing and font smoothing differ by a little, a real change by a lot
CHANGED = 0.0005  # share of a page's pixels that must differ before it counts as changed


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("  $", " ".join(cmd), f"(in {cwd.name})", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def pictures(src: Path, out: Path, db: str) -> None:
    """Draw every page of the checkout at `src` into `out`."""
    if out.exists():
        shutil.rmtree(out)
    env = {**os.environ, "VISUAL_OUT": str(out), "TEST_DATABASE_URL": f"postgresql+psycopg://localhost/{db}"}
    run(["uv", "run", "pytest", "-q", "tests/browser/test_pictures.py", "-n", "2", "-p", "no:cacheprovider"], src, env)


def base_checkout(ref: str) -> Path:
    """The base commit in a folder of its own, with this branch's tests (the same harness on both sides)."""
    src = WORK / "base-src"
    run(["git", "fetch", "-q", "origin"], ROOT)
    if src.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(src)], cwd=ROOT)
    run(["git", "worktree", "add", "-q", "--detach", str(src), ref], ROOT)
    shutil.rmtree(src / "tests")
    shutil.copytree(ROOT / "tests", src / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    for secret in (".env",):  # (the saved sheets' key: the tests unlock them themselves)
        if (ROOT / secret).exists():
            (src / secret).symlink_to(ROOT / secret)
    return src


def difference(a: Path, b: Path, out: Path) -> float:
    """The share of pixels that differ (1.0 when the page changed size), with the change drawn in red over the after."""
    before, after = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    w, h = max(before.width, after.width), max(before.height, after.height)
    pad = lambda im: im if im.size == (w, h) else Image.new("RGB", (w, h), "white").paste(im) or _pasted(im, w, h)
    before, after = pad(before), pad(after)
    diff = ImageChops.difference(before, after).convert("L").point(lambda v: 255 if v > TOLERANCE else 0)
    changed = diff.histogram()[255] / (w * h)
    if changed:
        faded = Image.blend(after, Image.new("RGB", (w, h), "white"), 0.6)
        faded.paste(Image.new("RGB", (w, h), (220, 30, 30)), mask=diff)
        faded.save(out)
    return changed


def _pasted(im: Image.Image, w: int, h: int) -> Image.Image:
    canvas = Image.new("RGB", (w, h), "white")
    canvas.paste(im)
    return canvas


def report(before: Path, after: Path) -> Path:
    diffs = WORK / "diffs"
    if diffs.exists():
        shutil.rmtree(diffs)
    diffs.mkdir(parents=True)
    names = sorted({p.name for p in before.glob("*.png")} | {p.name for p in after.glob("*.png")})
    rows, same = [], 0
    for n in names:
        a, b = before / n, after / n
        if not a.exists() or not b.exists():
            rows.append((n, "new page" if b.exists() else "page gone", None))
            continue
        share = difference(a, b, diffs / n)
        if share > CHANGED:
            rows.append((n, f"{share:.2%} of the page changed", diffs / n))
        else:
            same += 1
            (diffs / n).unlink(missing_ok=True)
    rel = lambda p: os.path.relpath(p, WORK)
    body = "".join(
        f"<section><h2>{html.escape(n)}</h2><p>{html.escape(what)}</p><div class=row>"
        + (f"<figure><figcaption>Before</figcaption><img src='{rel(before / n)}'></figure>" if (before / n).exists() else "")
        + (f"<figure><figcaption>After</figcaption><img src='{rel(after / n)}'></figure>" if (after / n).exists() else "")
        + (f"<figure><figcaption>What changed (red)</figcaption><img src='{rel(d)}'></figure>" if d else "")
        + "</div></section>"
        for n, what, d in rows)
    page = WORK / "report.html"
    page.write_text(f"""<!doctype html><meta charset=utf-8><title>Before and after</title>
<style>body{{font:14px system-ui;margin:16px;background:#f6f4ef}} .row{{display:flex;gap:12px;align-items:flex-start}}
figure{{margin:0;flex:1;min-width:0}} img{{width:100%;border:1px solid #ccc;background:#fff}} h2{{font-size:15px;margin:24px 0 4px}}</style>
<h1>Before and after</h1><p>{len(rows)} of {len(names)} pictures changed; {same} the same.</p>{body or '<p>Nothing changed.</p>'}""")
    print(f"\n{len(rows)} of {len(names)} pictures changed, {same} the same. Report: {page}")
    for n, what, _ in rows:
        print(f"  {n}: {what}")
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--only-compare", nargs=2, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.only_compare:
        report(Path(args.only_compare[0]), Path(args.only_compare[1]))
        return 0
    print(f"Before: {args.base}")
    src = base_checkout(args.base)
    pictures(src, WORK / "before", "askdnd_test_visual_before")
    print("After: this checkout")
    pictures(ROOT, WORK / "after", "askdnd_test_visual_after")
    report(WORK / "before", WORK / "after")
    return 0


if __name__ == "__main__":
    sys.exit(main())
