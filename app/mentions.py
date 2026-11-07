"""Finding the World entries a piece of the story names, by their names (Brett, Nov 6): Listen's pictures (app/narration.py),
a new entry accepted from a draft linking the session's key moments that name it (app/review.py), and the one-time pass
that linked published key moments to entries made after them (migration e2b8c4d6f1a3).

Only proper names count, an entry's own and its other names with a capital past a leading "the" or "a" ("Lillippi",
"Pirate Captain", "the Lich Queen"), never a description like "the captain", which would match every captain in the
story. A longer name claims its words first, so "Captain Trager Grill" isn't also "Captain Captain".
"""

import re
from collections.abc import Callable, Hashable, Iterable


def proper(name: str) -> bool:
    words = re.sub(r"^(the|a|an)\s+", "", (name or "").strip(), flags=re.I).split()
    return len((name or "").strip()) >= 3 and any(w[:1].isupper() for w in words)


def finder(names: Iterable[tuple[str, Hashable]]) -> Callable[[str], list]:
    """A function giving, for a text, the keys of the names it mentions, in the order it first mentions them.
    `names`: (a name, its entry's key) for every name to look for; descriptions are left out here."""
    patterns = sorted(((re.compile(r"(?<!\w)" + re.escape(n.strip()) + r"(?!\w)", re.I), k) for n, k in names if proper(n)),
                      key=lambda x: -len(x[0].pattern))

    def find(text: str) -> list:
        found, taken = {}, []
        for pattern, key in patterns:
            for m in pattern.finditer(text or ""):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.setdefault(key, m.start())
        return sorted(found, key=found.get)

    return find
