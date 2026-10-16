"""Turn known names in text into links to entity pages (opened in a peek panel).

Matching is case-sensitive on purpose: the characters Anger and Sadness get
linked, the ordinary words "anger" and "sadness" don't. Longest names win, so
"The Lich Queen's cult" isn't split into "The Lich Queen" + "'s cult".
"""

import html as htmllib
import re
from dataclasses import dataclass

from markupsafe import Markup, escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Entity, EntityAlias, Status

APOSTROPHES = "(?:'|’|&#39;|&#x27;)"
TAG = re.compile(r"(<[^>]+>)")
MIN_LENGTH = 3


@dataclass
class Linker:
    pattern: re.Pattern | None
    targets: dict[str, int]  # matched text (normalized apostrophes) -> entity id

    def _replace(self, m: re.Match) -> str:
        key = re.sub(APOSTROPHES, "'", m.group("name"))
        entity_id = self.targets.get(key)
        if entity_id is None:
            return m.group(0)
        return f'<a class="ent" href="/campaign/{entity_id}" data-entity="{entity_id}">{m.group(0)}</a>'

    def html(self, html: str | Markup) -> Markup:
        """Link names in already-safe HTML, skipping tags and existing links."""
        if not self.pattern or not html:
            return Markup(html or "")
        out, in_link = [], 0
        for part in TAG.split(str(html)):
            if part.startswith("<"):
                lower = part.lower()
                if lower.startswith("<a ") or lower == "<a>":
                    in_link += 1
                elif lower.startswith("</a"):
                    in_link = max(0, in_link - 1)
                out.append(part)
            elif in_link:
                out.append(part)
            else:
                out.append(self.pattern.sub(self._replace, part))
        return Markup("".join(out))

    def text(self, text: str | None) -> Markup:
        """Escape plain text, then link names in it."""
        return self.html(escape(text or ""))


_cache: dict[tuple, Linker] = {}


def entity_linker(db: Session, campaign_id: int, exclude_id: int | None = None, include_drafts: bool = False) -> Linker:
    """A Linker for this campaign's published entities (names and capitalized aliases)."""
    stamp = db.execute(
        select(func.count(Entity.id), func.max(Entity.updated_at)).where(Entity.campaign_id == campaign_id)
    ).one()
    alias_stamp = db.scalar(
        select(func.count(EntityAlias.id)).join(Entity).where(Entity.campaign_id == campaign_id)
    )
    key = (campaign_id, exclude_id, include_drafts, tuple(stamp), alias_stamp)
    if key in _cache:
        return _cache[key]

    targets: dict[str, int] = {}
    query = select(Entity).where(Entity.campaign_id == campaign_id)
    if not include_drafts:
        query = query.where(Entity.status == Status.PUBLISHED)
    for e in db.scalars(query):
        if e.id == exclude_id:
            continue
        candidates = [e.name] + [a.alias for a in e.aliases if a.alias != a.alias.lower()]  # skip "the cult"-style descriptions
        candidates += [c[4:] for c in candidates if c.startswith("The ")]  # "the Lich Queen", "Lich Queen"
        for text in candidates:
            text = htmllib.unescape(text.strip()).replace("’", "'")
            if len(text) >= MIN_LENGTH and text not in targets:
                targets[text] = e.id
    if not targets:
        linker = Linker(None, {})
    else:
        parts = []
        for name in sorted(targets, key=len, reverse=True):
            parts.append(re.escape(name).replace("'", APOSTROPHES).replace("\\'", APOSTROPHES))
        # Possessives are part of the link: "Cole's" links as one word.
        pattern = re.compile(r"(?<![\w&#])(?P<name>" + "|".join(parts) + r")(?:" + APOSTROPHES + r"s)?(?![\w])")
        linker = Linker(pattern, targets)
    if len(_cache) > 50:
        _cache.clear()
    _cache[key] = linker
    return linker
