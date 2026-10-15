"""Remember model answers per prompt so a rerun skips finished blocks.

Stored under transcripts/ (git-ignored) because prompts contain transcript text.
"""

import hashlib
import json
from pathlib import Path


class Cache(dict):
    def __init__(self, path: Path):
        self.path = path
        super().__init__(json.loads(path.read_text()) if path.exists() else {})

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self))
        tmp.replace(self.path)
