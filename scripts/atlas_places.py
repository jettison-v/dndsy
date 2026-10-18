"""Refresh app/data/sword_coast_places.txt: the marker names on AideDD's Sword Coast map.

Only the names are kept (one per line), so place pages know when "Show on map" can
link straight to a marker. Run it if AideDD adds or renames markers:

    uv run python scripts/atlas_places.py
"""

import re
import urllib.request
from pathlib import Path

SOURCE = "https://www.aidedd.org/atlas/dataR.js"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "sword_coast_places.txt"


def main() -> None:
    text = urllib.request.urlopen(SOURCE, timeout=30).read().decode("utf-8")
    names = sorted({n.strip() for n in re.findall(r'name1:\s*"([^"]+)",\s*color:', text) if n.strip()}, key=str.lower)
    OUT.write_text("\n".join(names) + "\n")
    print(f"{len(names)} places written to {OUT}")


if __name__ == "__main__":
    main()
