"""Package the askdnd bridge for the Chrome Web Store (roadmap step 4, 2026-10-28).

    uv run python -m scripts.build_extension

Writes private/extension/askdnd-bridge-<version>.zip (private/ is never committed). The store's copy is the folder in
extension/askdnd-bridge/ without localhost: the folder itself also works with askdnd on your own computer (Load
unpacked), the store's only with askdnd's own sites. Upload the zip on the developer dashboard
(https://chrome.google.com/webstore/devconsole), then raise the version in manifest.json before the next upload: the
store refuses a version it already has.
"""

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "extension" / "askdnd-bridge"
OUT = ROOT / "private" / "extension"
LEAVE_OUT = {"README.md"}  # (for whoever builds it, not for Chrome)


def store_manifest(manifest: dict) -> dict:
    """The manifest without anything for askdnd on your own computer."""
    local = lambda pattern: pattern.startswith(("http://localhost", "http://127.0.0.1"))
    out = json.loads(json.dumps(manifest))
    out["host_permissions"] = [p for p in out["host_permissions"] if not local(p)]
    for cs in out["content_scripts"]:
        cs["matches"] = [p for p in cs["matches"] if not local(p)]
    out["content_scripts"] = [cs for cs in out["content_scripts"] if cs["matches"]]
    return out


def files(manifest: dict) -> list[Path]:
    """Every file the package holds; each one the manifest names must be there."""
    named = {*manifest.get("icons", {}).values(), manifest["background"]["service_worker"]}
    named |= {f for cs in manifest["content_scripts"] for f in cs["js"]}
    named |= {f for w in manifest.get("web_accessible_resources", []) for f in w["resources"]}
    missing = [f for f in named if not (SRC / f).is_file()]
    if missing:
        raise SystemExit(f"manifest.json names files that aren't there: {', '.join(sorted(missing))}")
    return sorted(p for p in SRC.rglob("*") if p.is_file() and p.name not in LEAVE_OUT and not p.name.startswith("."))


def build() -> Path:
    manifest = json.loads((SRC / "manifest.json").read_text())
    store = store_manifest(manifest)
    OUT.mkdir(parents=True, exist_ok=True)
    zip_path = OUT / f"askdnd-bridge-{manifest['version']}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files(manifest):
            rel = p.relative_to(SRC).as_posix()
            z.writestr(rel, json.dumps(store, indent=2) + "\n" if rel == "manifest.json" else p.read_bytes())
    return zip_path


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
    sys.exit(0)
