# /// script
# requires-python = ">=3.12"
# dependencies = ["pdfplumber==0.11.10"]
# ///
"""Build app/data/srd/ from the official System Reference Document 5.2.1 PDF.

The SRD is Wizards of the Coast's free 2024 rules content under CC-BY-4.0 (attribution in
app/data/srd/README.md). This reads the PDF itself, not a conversion: its fonts mark every part
(a stat block's name is GillSans-SemiBold 15pt, its fields Optima-Bold, an action's name
Optima-BoldItalic…), so each part lands in its field. Out come four files, one per kind, in the
shapes app/rules_data.py checks: monsters.json (every stat block in Monsters and Animals, plus
creatures a magic item makes), spells.json, magic_items.json and rules_glossary.json (the Rules
Glossary; conditions are its [Condition] entries).

    uv run scripts/srd_import.py              # download the PDF to private/srd/ if needed, rebuild
    uv run scripts/srd_import.py --compare    # also list differences from Open5e's conversion

--compare fetches Open5e's srd-2024 data (a well-kept conversion) and reports where its numbers
differ from ours, as a check on this reader; where they differ, the PDF is right.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "private" / "srd"
OUT = ROOT / "app" / "data" / "srd"
PDF_URL = "https://media.dndbeyond.com/compendium-images/srd/5.2/SRD_CC_v5.2.1.pdf"
PDF = CACHE / "SRD_CC_v5.2.1.pdf"
SOURCE = "SRD 5.2.1"

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
DAMAGE_TYPES = ("Acid", "Bludgeoning", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Piercing", "Poison",
                "Psychic", "Radiant", "Slashing", "Thunder")
CONDITIONS = ("Blinded", "Charmed", "Deafened", "Exhaustion", "Frightened", "Grappled", "Incapacitated", "Invisible",
              "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious")
SCHOOLS = ("Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy", "Transmutation")
ITEM_CATEGORIES = ("Armor", "Potion", "Ring", "Rod", "Scroll", "Staff", "Wand", "Weapon", "Wondrous Item")
SECTIONS = ("Traits", "Actions", "Bonus Actions", "Reactions", "Legendary Actions")
CR_VALUES = {"1/8": 0.125, "1/4": 0.25, "1/2": 0.5}
NOTES: list[str] = []  # things worth a look, printed at the end
# Misprints in the PDF that the stat block itself shows to be wrong, put right here (and only these)
CORRECTIONS = {
    ("Young White Dragon", "saves", "int"): (-2, ("the SAVE column prints “2” beside a −2 modifier; the dragon "
                                                 "isn't proficient in Intelligence saves")),
}


# ------------------------------------------------------------------ reading the PDF


@dataclass
class Line:
    page: int
    col: int  # 0 = left column (or the whole page width), 1 = right
    base: float  # baseline, from the top of the page
    spans: list  # [[font, size, text, x]] in reading order; a span after a wide gap starts with a tab
    x: float = 0  # where the line's first letter is: a paragraph's first line is indented

    @property
    def text(self) -> str:
        return "".join(s[2] for s in self.spans)

    @property
    def first(self) -> list:
        """The first span with something in it."""
        return next((s for s in self.spans if s[2].strip()), ["", 0, "", 0])

    def is_(self, font: str, size: float | None = None) -> bool:
        f = self.first
        return f[0] == font and (size is None or abs(f[1] - size) < 0.3)

    def cells(self) -> list[tuple[float, str]]:
        """A table row's cells: (x, text), split at the wide gaps."""
        out: list[list] = []
        for _, _, t, x in self.spans:
            if not out or t.startswith("\t"):
                out.append([x, ""])
            out[-1][1] += t
        return [(x, re.sub(r"\s+", " ", t).strip()) for x, t in out if t.strip()]


TABLE_HEAD = ("GillSans-SemiBold", 9.2)


def _columns(page, chars: list[dict]) -> list[int]:
    """Each letter's column. A table set across both columns (its header row has letters on both sides of
    the middle) belongs to the left column's flow, header to last row, so its rows stay whole."""
    mid = page.width / 2 - 10
    base = [round(page.height - c["matrix"][5], 1) for c in chars]
    col = [0 if c["x0"] < mid else 1 for c in chars]
    is_table = [c["fontname"].split("+")[-1].startswith("GillSans") and c["size"] < 11 for c in chars]
    heads = sorted({b for c, b in zip(chars, base) if (c["fontname"].split("+")[-1], round(c["size"], 1)) == TABLE_HEAD})
    for h in heads:
        row = [k for k, b in enumerate(base) if abs(b - h) < 1.6
               and (chars[k]["fontname"].split("+")[-1], round(chars[k]["size"], 1)) == TABLE_HEAD]
        if not ({col[k] for k in row} == {0, 1} and min(chars[k]["x0"] for k in row if col[k] == 1) - mid < 80):
            continue  # not across the middle (two tables side by side have a header each, far apart)
        end, last = h, h
        for b in sorted({b for k, b in enumerate(base) if b > h and is_table[k]}):
            if b - last > 20:
                break
            end = last = b
        for k, b in enumerate(base):
            if h - 1.6 <= b <= end + 1.6 and is_table[k]:
                col[k] = 0
    return col


def extract_lines(pdf_path: Path) -> list[Line]:
    """Every line of text, page by page, left column then right (cached next to the PDF)."""
    cached = pdf_path.with_suffix(".lines.json")
    if cached.exists() and cached.stat().st_mtime > pdf_path.stat().st_mtime and cached.stat().st_mtime > Path(__file__).stat().st_mtime:
        return [Line(*x) for x in json.loads(cached.read_text())]
    import pdfplumber

    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            rows: dict[tuple[int, float], list] = {}
            for ch, col in zip(page.chars, _columns(page, page.chars)):
                if col == 1 and ch["x0"] < MARGIN[1] - 8 and not ch["text"].isalnum():
                    continue  # stray punctuation in the gutter between the columns
                rows.setdefault((col, round(page.height - ch["matrix"][5], 1)), []).append(ch)
            merged: list[list] = []
            for key in sorted(rows):  # letters a hair above or below the line (small caps) join it
                if merged and merged[-1][0][0] == key[0] and abs(merged[-1][0][1] - key[1]) < 1.6:
                    merged[-1][1].extend(rows[key])
                else:
                    merged.append([key, list(rows[key])])
            for (col, base), chars in merged:
                chars.sort(key=lambda c: c["x0"])
                spans: list[list] = []
                prev = None  # the last letter that isn't a space
                for ch in chars:
                    font, size, t = ch["fontname"].split("+")[-1], round(ch["size"], 1), ch["text"]
                    gap = prev is not None and t != " " and ch["x0"] - prev["x1"] > (2.5 if spans[-1][2][-1:] != " " else 6)
                    if gap or not spans or spans[-1][0] != font or abs(spans[-1][1] - size) >= 0.3:
                        spans.append([font, size, "\t" if gap else "", None])
                    spans[-1][2] += t
                    if t != " ":
                        spans[-1][3] = spans[-1][3] if spans[-1][3] is not None else round(ch["x0"], 1)
                        prev = ch
                spans = [[f, s, t, x if x is not None else 0] for f, s, t, x in spans]
                xs = [sp[3] for sp in spans if sp[2].strip()]
                if xs:
                    out.append(Line(pno, col, base, spans, xs[0]))
    cached.write_text(json.dumps([[x.page, x.col, x.base, x.spans, x.x] for x in out], ensure_ascii=False))
    return out


def body_lines(lines: list[Line]) -> list[Line]:
    """Without the running footer (page number and document title)."""
    return [x for x in lines if x.base < 740]


# ------------------------------------------------------------------ text


class Words:
    """Which line-end hyphens are the word's own ("15-foot-long") and which only split it ("suc-ceed"):
    a word the PDF also prints whole, unbroken, decides."""

    def __init__(self, lines: list[Line]):
        self.whole: set[str] = set()
        self.hyphenated: set[str] = set()
        for x in lines:
            for w in re.findall(r"[A-Za-z’'-]+", x.text):
                (self.hyphenated if "-" in w.strip("-") else self.whole).add(w.lower().strip("-"))

    def join(self, left: str, right: str) -> str:
        """`left` ends with a hyphen at the end of a line, `right` is the next line."""
        a = re.search(r"([A-Za-z’'-]*)-$", left).group(1)
        b = re.match(r"[A-Za-z’']*", right).group(0)
        if not b or not b[0].islower():
            return left + right  # "Fire-" + "Breathing", or a dash before a number
        if (a + b).lower() in self.whole:
            return left[:-1] + right
        if f"{a}-{b}".lower() in self.hyphenated or re.search(r"\d|-", a):
            return left + right
        return left[:-1] + right


def small_caps(spans: list) -> str:
    """A heading set in small caps ("A" + "cid" + " S" + "plASh"): the smaller letters are lowercase."""
    big = max(s[1] for s in spans if s[2].strip())
    return "".join(s[2] if abs(s[1] - big) < 0.3 else s[2].lower() for s in spans).replace("\t", " ")


def heading(line: Line) -> str:
    text = small_caps(line.spans) if "SC700" in line.first[0] else line.text
    return re.sub(r"\s+", " ", text).strip()


BOLD = ("Cambria-BoldItalic", "Cambria-Bold", "Optima-BoldItalic", "Optima-Bold", "GillSans-Bold")
TABLE_FONTS = ("GillSans", "GillSans-SemiBold", "GillSans-Bold", "GillSans-Italic", "GillSans-Light")
MARGIN = (63.0, 313.5)  # where each column's text starts


def is_table(line: Line) -> bool:
    f = line.first
    return f[0] in TABLE_FONTS and f[1] < 11 and not f[2].lstrip().startswith("•")


def table_start(line: Line) -> bool:
    """A table's title (SemiBold 10.5) or header row (SemiBold 9.2)."""
    f = line.first
    return f[0] == "GillSans-SemiBold" and (abs(f[1] - 10.5) < 0.3 or abs(f[1] - 9.2) < 0.3)


def indented(line: Line, prev: Line | None, nxt: Line | None) -> bool:
    """A paragraph's first line is indented from the line before it (or from the column's edge, at the top
    of a column). A block that is indented as a whole (the Ivory Goats under a Figurine) isn't: the line
    after it is indented as far."""
    same = prev and (prev.page, prev.col) == (line.page, line.col)
    edge = prev.x if same else MARGIN[line.col]
    if prev and not re.search(r"[.:!?”)]\s*$", prev.text):
        return False  # the sentence goes on: a hanging indent ("Grovel. The target…" set in under it)
    if nxt and (nxt.page, nxt.col) == (line.page, line.col) and nxt.x > line.x - 3:
        return False
    return 5 <= line.x - edge < 14


@dataclass
class Table:
    title: str
    head: list[str]
    rows: list[list[str]]

    def markdown(self) -> str:
        out = ([f"**{self.title}**", ""] if self.title else []) + ["| " + " | ".join(self.head) + " |", "|" + "---|" * len(self.head)]
        return "\n".join(out + ["| " + " | ".join(c.replace("|", "/") for c in r) + " |" for r in self.rows])


class Text:
    """Lines of running text to a small Markdown: paragraphs apart by a blank line, a run-in heading in
    bold ("**Audible Alarm.** The alarm…"), bullets as "- ", tables as pipe tables with a bold title."""

    def __init__(self, words: Words):
        self.words = words

    def __call__(self, lines: list[Line]) -> str:
        blocks: list = []  # finished paragraphs (str) and tables
        para = ""
        i = 0

        def flush():
            nonlocal para
            if para.strip():
                blocks.append(re.sub(r"[ \t]+", " ", para).strip())
            para = ""

        while i < len(lines):
            x = lines[i]
            f = x.first
            raw = x.text.replace("\t", " ")
            if table_start(x):
                flush()
                j = i + 1
                while j < len(lines) and is_table(lines[j]) and not (j > i + 1 and lines[j].first[1] > 10):
                    j += 1
                t = self.table(lines[i:j])
                prev = blocks[-1] if blocks else None
                if isinstance(prev, Table) and not t.title and t.head == prev.head:
                    prev.rows += t.rows  # the table goes on in the next column, its header repeated
                elif t.head:
                    blocks.append(t)
                i = j
                continue
            if f[2].lstrip().startswith("•"):
                flush()
                para = "- " + raw.strip().lstrip("•").strip()
            elif f[0] in BOLD and f[2].strip().endswith((".", ":")) and (x.spans[0] is f or not x.spans[0][2].strip()):
                flush()
                label = f[2].strip()
                para = f"**{label}**{raw.strip()[len(label):]}"
                if label.endswith(":") and f[0] == "Optima-Bold":
                    para = "- " + para  # a monster's spell list ("At Will: …")
            elif indented(x, lines[i - 1] if i else None, lines[i + 1] if i + 1 < len(lines) else None) and not para.startswith("- "):
                flush()
                para = raw.strip()
            elif not para:
                para = raw.strip()
            elif para.rstrip().endswith("-") and not para.rstrip().endswith(" -"):
                para = self.words.join(para.rstrip(), raw.strip())
            elif para.rstrip().endswith("—"):
                para = para.rstrip() + raw.strip()
            else:
                para = para.rstrip() + " " + raw.strip()
            i += 1
        flush()
        out = ""
        for k, b in enumerate(blocks):
            b = b.markdown() if isinstance(b, Table) else b
            tight = k and isinstance(blocks[k - 1], str) and blocks[k - 1].startswith("- ") and b.startswith("- ")
            out += ("\n" if tight else "\n\n" if k else "") + b
        return out

    def table(self, lines: list[Line]) -> Table:
        """A table: an optional title (SemiBold 10.5), header rows (SemiBold 9.2; a two-line header is put
        together by where its words are), then rows. A line set close under the one before (12.5pt
        rather than a row's 15pt) is a wrapped cell: its words join the cells above them. A table set in
        two halves side by side (its header twice over) is put back into one."""
        title = ""
        if lines and lines[0].first[0] == "GillSans-SemiBold" and lines[0].first[1] > 10:
            title, lines = heading(lines[0]), lines[1:]
        heads, edge = [], 0.0
        while lines and (lines[0].first[0], lines[0].first[1]) == TABLE_HEAD:
            heads.append(lines[0].cells())
            edge = MARGIN[lines[0].col]  # x is measured from the column's edge, so a table that goes on in
            # the other column (header repeated) lines up
            lines = lines[1:]
        if not heads:  # a title with no table under it
            heads = [[(0.0, "")]]
        cols = max(heads, key=len)
        xs = [x - edge for x, _ in cols]
        names = [t for _, t in cols]
        for other in heads:
            if other is not cols:
                for x, t in other:
                    k = min(range(len(xs)), key=lambda n: abs(xs[n] - (x - edge)))
                    names[k] = f"{t} {names[k]}"

        def column(x: float) -> int:
            return max([n for n, cx in enumerate(xs) if cx <= x + 6] or [0])

        rows: list[list[str]] = []
        prev = None
        for x in lines:
            cells = x.cells()
            wrapped = prev is not None and x.col == prev.col and x.base - prev.base < 13.5 and rows
            if not wrapped:
                rows.append([""] * len(xs))
            for cx, t in cells:
                k = column(cx - MARGIN[x.col])
                cell = rows[-1][k]
                rows[-1][k] = self.words.join(cell, t) if cell.endswith("-") else f"{cell} {t}".strip()
            prev = x
        n = len(names)
        if n % 2 == 0 and n >= 2 and names[: n // 2] == names[n // 2:]:
            half = n // 2
            rows = [r[:half] for r in rows] + [r[half:] for r in rows if any(r[half:])]
            names = names[:half]
        return Table(title, names if any(names) else [], [r for r in rows if any(r)])


def follows(chunk: list[Line], k: int, like) -> tuple[int, str]:
    """The text of the lines from k on that are `like` and set close under each other (a wrapped line),
    and where they stop."""
    out = ""
    start = k
    while k < len(chunk) and like(chunk[k]) and (k == start or (chunk[k].col == chunk[k - 1].col and chunk[k].base - chunk[k - 1].base < 14)):
        out += " " + chunk[k].text
        k += 1
    return k, re.sub(r"\s+", " ", out).strip()


def titled(part: list[Line], like, then=lambda x: True) -> list[tuple[int, str, int]]:
    """(where, name, where its text starts) for each heading: lines that are `like` (a long name wraps to a
    second line) followed by a line that is `then`."""
    out, i = [], 0
    while i < len(part):
        if not like(part[i]):
            i += 1
            continue
        j = i + 1
        while j < len(part) and like(part[j]) and part[j].col == part[j - 1].col and part[j].base - part[j - 1].base < 16:
            j += 1
        if j < len(part) and then(part[j]):
            out.append((i, " ".join(heading(x) for x in part[i:j]), j))
        i = j
    return out


def chunks(part: list[Line], heads: list[tuple[int, str, int]]):
    """(name, the lines after its heading up to the next heading)."""
    for n, (_, name, body) in enumerate(heads):
        yield name, part[body:heads[n + 1][0] if n + 1 < len(heads) else len(part)]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("’", "").replace("'", "")).strip("-")


def section(lines: list[Line], start: str, end: str) -> list[Line]:
    """The lines from the heading `start` (18pt or larger) up to the next big heading `end`."""
    big = [i for i, x in enumerate(lines) if x.first[0] == "GillSans-SemiBold" and x.first[1] >= 18]
    a = next(i for i in big if heading(lines[i]) == start)
    b = next(i for i in big if i > a and heading(lines[i]) == end) if end else len(lines)
    return lines[a + 1:b]


# ------------------------------------------------------------------ stat blocks

STAT_FONTS = ("Optima-Regular", "Optima-Bold", "Optima-Italic", "Optima-BoldItalic", "GillSans-SemiBold-SC700", "GillSans-Bold-SC700")


def in_stat_block(line: Line) -> bool:
    f = line.first
    return f[0] in STAT_FONTS or (f[0] == "GillSans" and (f[1] in (6.0, 9.8) or heading(line) in SECTIONS)) or \
        (f[0] in ("GillSans-SemiBold", "GillSans-Bold") and f[1] == 9.8)


def split_blocks(lines: list[Line]) -> list[tuple[int, int]]:
    """(start, end) of every stat block: a 15pt name and an italic type line, then stat block fonts."""
    out = []
    for i, x in enumerate(lines):
        if x.is_("GillSans-SemiBold", 15.0) and i + 1 < len(lines) and lines[i + 1].is_("Optima-Italic", 9.0):
            j = i + 1
            while j < len(lines) and in_stat_block(lines[j]):
                j += 1
            out.append((i, j))
    return out


def _num(s: str) -> int:
    return int(s.replace("−", "-").replace("–", "-").replace(",", "").replace("+", ""))


def _list(s: str) -> list[str]:
    return [p.strip() for p in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+", s) if p.strip()]


def type_line(s: str) -> dict:
    """"Large Swarm of Tiny Beasts, Unaligned" / "Huge Dragon (Chromatic), Chaotic Evil"."""
    s = re.sub(r"\s+", " ", s).strip()
    sizes = "|".join(SIZES)
    m = re.match(rf"((?:{sizes})(?:,? or (?:{sizes}|Smaller))*) (.+), ([^,]+)$", s)
    if not m:
        raise ValueError(f"type line: {s!r}")
    size, kind, alignment = m.groups()
    out = {"size": size, "type": kind, "tags": [], "swarm_of": "", "alignment": alignment}
    sw = re.match(rf"Swarm of ({sizes}) (\w+?)s?$", kind)
    if sw:
        out["swarm_of"], out["type"] = sw.group(1), sw.group(2).rstrip("s")
    tm = re.match(r"(\w+) \(([^)]+)\)$", kind)
    if tm and "," not in kind:
        out["type"], out["tags"] = tm.group(1), [t.strip() for t in tm.group(2).split(",")]
    return out


def fields(lines: list[Line]) -> tuple[dict[str, str], dict, dict]:
    """The stat block's header: {"AC": "17", "Initiative": "+7 (17)", "HP": …}, ability scores and saves."""
    out: dict[str, str] = {}
    scores, saves = {}, {}
    last = None
    for x in lines:
        f = x.first
        if "SC700" in f[0] or (f[0] == "GillSans-Bold" and f[1] == 9.8):
            t = re.sub(r"[\s\t]+", "", "".join(s[2] for s in x.spans))
            for ab, score, _mod, save in re.findall(r"(?i)(str|dex|con|int|wis|cha)(\d+)([+−-]\d+)([+−-]?\d+)", t):
                scores[ab.lower()], saves[ab.lower()] = int(score), _num(save)
            continue
        if f[0] == "GillSans":
            continue  # the MOD / SAVE column titles
        if f[0] == "Optima-Bold":
            label = None
            for font, _, t, _ in x.spans:  # "AC 17  Initiative +7 (17)" has two labels on one line
                if font == "Optima-Bold" and t.strip():
                    label = t.strip()
                    out[label] = ""
                elif label:
                    out[label] += t
            last = label
        elif last:
            out[last] += " " + x.text
    return {k: re.sub(r"\s+", " ", v).strip() for k, v in out.items()}, scores, saves


def speed(s: str) -> tuple[dict[str, int], bool, str]:
    """"10 ft., Fly 90 ft. (hover)": the speeds, hover, and what holds only sometimes ("40 ft. (bear form
    only)", "Climb or Fly 20 ft. (GM’s choice)"), as printed."""
    out, note = {}, []
    for part in re.split(r",\s*(?![^()]*\))", s):
        m = re.fullmatch(r"\s*(Burrow|Climb|Fly|Swim)?\s*(\d+) ft\.(?: \(hover\))?\s*", part)
        if m and (m.group(1) or "walk").lower() not in out:
            out[(m.group(1) or "walk").lower()] = int(m.group(2))
        else:
            note.append(part.strip())
    return out, "(hover)" in s, ", ".join(note)


def senses(s: str) -> tuple[dict[str, int], int, str]:
    """"Blindsight 30 ft. (blind beyond this radius), Darkvision 60 ft.; Passive Perception 10"."""
    found = {m.group(1).lower(): int(m.group(2)) for m in re.finditer(r"(Blindsight|Darkvision|Tremorsense|Truesight) (\d+) ft\.", s)}
    pp = re.search(r"Passive Perception (\d+)", s)
    note = "; ".join(re.findall(r"\(([^)]*)\)", s.split("Passive Perception")[0]))
    return found, int(pp.group(1)) if pp else 10, note


def challenge(s: str) -> dict:
    """"10 (XP 5,900, or 7,200 in lair; PB +4)" / "1/2 (XP 100; PB +2)"."""
    s = re.sub(r"\(([\d,]+) XP", r"(XP \1", s)  # one stat block prints "(700 XP; PB +2)"
    m = re.match(r"([\d/]+) \(XP ([\d,]+)(?:, or ([\d,]+) in lair)?; PB \+(\d+)\)", s)
    if not m:
        raise ValueError(f"CR: {s!r}")
    label, xp, lair, pb = m.groups()
    return {"cr": CR_VALUES.get(label) or float(label), "cr_label": label, "xp": _num(xp),
            "xp_lair": _num(lair) if lair else None, "pb": int(pb)}


def entries(lines: list[Line], text: Text) -> tuple[dict[str, list[dict]], str]:
    """Traits, Actions…: each entry is a bold-italic name and its text. Also the Legendary Actions intro."""
    out: dict[str, list[dict]] = {}
    intro = []
    cur, buf, name = None, [], None

    def done():
        if name is not None:
            out[cur].append({"name": name, "text": text(buf)})

    for x in lines:
        h = heading(x)
        if x.is_("GillSans", 12.0) and h in SECTIONS:
            done()
            cur, name, buf = h, None, []
            out[cur] = []
            continue
        if cur is None:
            continue
        f = x.first
        if f[0] == "Optima-BoldItalic" and (x.spans[0] is f or not x.spans[0][2].strip()):
            done()
            name = f[2].strip().rstrip(".").strip()
            # the name's closing period is sometimes a span of its own ("Bite" then ". Melee Attack Roll…")
            rest = re.sub(r"^\s*\.", "", x.text.replace("\t", " ").strip()[len(f[2].strip()):])
            buf = [Line(x.page, x.col, x.base, [["Optima-Regular", 9.5, rest, MARGIN[x.col]]], MARGIN[x.col])]
        elif x.is_("Optima-Italic", 9.0) and name is None and cur == "Legendary Actions":
            intro.append(x)
        elif name is not None:
            buf.append(x)
    done()
    return out, text(intro)


def stat_block(lines: list[Line], text: Text) -> dict:
    name = heading(lines[0])
    kind = type_line(lines[1].text)
    head_end = next((i for i, x in enumerate(lines) if x.is_("GillSans", 12.0) and heading(x) in SECTIONS), len(lines))
    f, scores, saves = fields(lines[2:head_end])
    secs, legendary = entries(lines[head_end:], text)
    return {"name": name, **kind, "fields": f, "abilities": scores, "saves": saves, "sections": secs, "legendary_uses": legendary}


def monster(raw: dict, section_name: str, group: str) -> dict:
    """A real creature's stat block, every number as a number."""
    f = dict(raw["fields"])
    ac = re.fullmatch(r"(\d+)", f.pop("AC"))
    init = re.match(r"([+−-]\d+)", f.pop("Initiative", "+0"))
    hp = re.match(r"(\d+)(?: \(([^)]+)\))?", f.pop("HP"))
    spd, hover, speed_note = speed(f.pop("Speed"))
    sn, pp, note = senses(f.pop("Senses", ""))
    resist, vuln, immune, cond_immune = [], [], [], []
    for label, target in (("Resistances", resist), ("Vulnerabilities", vuln)):
        if label in f:
            target += _list(f.pop(label))
    if "Immunities" in f:
        for part in _list(f.pop("Immunities").replace(";", ",")):
            (immune if part in DAMAGE_TYPES else cond_immune).append(part)
    unknown = [x for x in resist + vuln + immune if x not in DAMAGE_TYPES] + [x for x in cond_immune if x not in CONDITIONS]
    if unknown:  # e.g. the Half-Dragon's "Damage type chosen for the Draconic Origin trait below"
        NOTES.append(f"{raw['name']}: not a damage type or condition: {unknown}")
    skills = {m.group(1): _num(m.group(2)) for m in re.finditer(r"([A-Z][A-Za-z ]+?) ([+−-]\d+)", f.pop("Skills", ""))}
    gear = _list(f.pop("Gear", ""))
    languages = f.pop("Languages", "None")
    cr = challenge(f.pop("CR"))
    if f:
        raise ValueError(f"{raw['name']}: fields not read {list(f)}")
    for (who, field, key), (value, why) in CORRECTIONS.items():
        if who == raw["name"]:
            NOTES.append(f"{who}: {field}.{key} {raw[field][key]} corrected to {value} ({why})")
            raw[field][key] = value
    secs = raw["sections"]
    return {
        "key": slug(raw["name"]), "name": raw["name"], "size": raw["size"], "type": raw["type"], "tags": raw["tags"],
        "swarm_of": raw["swarm_of"], "alignment": raw["alignment"],
        "ac": int(ac.group(1)), "initiative": _num(init.group(1)),
        "hp": int(hp.group(1)), "hit_dice": hp.group(2) or "", "speed": spd, "hover": hover, "speed_note": speed_note,
        "abilities": raw["abilities"], "saves": raw["saves"], "skills": skills,
        "resistances": resist, "vulnerabilities": vuln, "immunities": immune, "condition_immunities": cond_immune,
        "gear": gear, "senses": sn, "senses_note": note, "passive_perception": pp, "languages": languages, **cr,
        "traits": secs.get("Traits", []), "actions": secs.get("Actions", []), "bonus_actions": secs.get("Bonus Actions", []),
        "reactions": secs.get("Reactions", []), "legendary_actions": secs.get("Legendary Actions", []),
        "legendary_uses": raw["legendary_uses"], "section": section_name, "group": group if group != raw["name"] else "",
        "source": SOURCE,
    }


def summoned(raw: dict) -> dict:
    """A creature a spell makes: its numbers depend on the spell ("10 (Medium or smaller), 20 (Large)…"),
    so the header stays as printed."""
    secs = raw["sections"]
    return {"name": raw["name"], "size": raw["size"], "type": raw["type"], "alignment": raw["alignment"],
            "fields": raw["fields"], "abilities": raw["abilities"], "saves": raw["saves"],
            "traits": secs.get("Traits", []), "actions": secs.get("Actions", []), "bonus_actions": secs.get("Bonus Actions", []),
            "reactions": secs.get("Reactions", [])}


def without_blocks(lines: list[Line]) -> tuple[list[Line], list[list[Line]]]:
    """Running text with the stat blocks in it taken out, and the stat blocks."""
    blocks = split_blocks(lines)
    keep, cut = [], []
    pos = 0
    for a, b in blocks:
        keep += lines[pos:a]
        cut.append(lines[a:b])
        pos = b
    return keep + lines[pos:], cut


# ------------------------------------------------------------------ the four kinds


def monsters(lines: list[Line], text: Text) -> list[dict]:
    part = section(lines, "Monsters A–Z", None)
    animals_at = next(i for i, x in enumerate(part) if x.first[1] >= 26 and heading(x) == "Animals")
    out = []
    group = ""
    blocks = split_blocks(part)
    starts = dict(blocks)
    for i, x in enumerate(part):
        if x.is_("GillSans-SemiBold", 18.0):
            group = heading(x)
        if i in starts:
            out.append(monster(stat_block(part[i:starts[i]], text), "Animals" if i > animals_at else "Monsters",
                               "" if i > animals_at else group))
    return out


def spells(lines: list[Line], text: Text) -> list[dict]:
    part = section(lines, "Spell Descriptions", "Rules Glossary")
    heads = titled(part, lambda x: x.is_("GillSans-SemiBold", 12.0) or x.is_("GillSans-SemiBold-SC700", 12.0),
                   lambda x: x.is_("Cambria-Italic", 10.0))
    out = []
    for name, chunk in chunks(part, heads):
        k, kind = follows(chunk, 0, lambda x: x.is_("Cambria-Italic", 10.0))
        info: dict[str, str] = {}
        last = None
        while k < len(chunk):  # Casting Time, Range, Components, Duration; a long one wraps
            x = chunk[k]
            m = re.match(r"[\s,]*(Casting Time|Range|Components?|Duration):(.*)", x.text.replace("\t", " "))  # one has a stray ", "
            if m:
                last = m.group(1)
                info[last] = m.group(2)
            elif last and x.col == chunk[k - 1].col and x.base - chunk[k - 1].base < 13:
                left = info[last].rstrip()
                info[last] = text.words.join(left, x.text.strip()) if left.endswith("-") else f"{left} {x.text}"
            else:
                break
            k += 1
        # one spell prints "Component:"
        info = {{"Component": "Components"}.get(a, a): re.sub(r"\s+", " ", b).strip() for a, b in info.items()}
        rest, blocks = without_blocks(chunk[k:])
        desc, higher, upgrade = [], [], []
        target = desc
        for x in rest:
            h = x.first[2].strip()
            if x.first[0] == "Cambria-BoldItalic" and h in ("Using a Higher-Level Spell Slot.", "Cantrip Upgrade."):
                target = higher if h.startswith("Using") else upgrade
                x = Line(x.page, x.col, x.base, [["Cambria", 10.0, x.text.replace("\t", " ").strip()[len(h):], MARGIN[x.col]]], MARGIN[x.col])
            target.append(x)
        out.append(spell(name, kind, info, text(desc), text(higher), text(upgrade),
                         [summoned(stat_block(b, text)) for b in blocks]))
    return out


def spell(name: str, kind: str, info: dict, desc: str, higher: str, upgrade: str, creatures: list) -> dict:
    """"Level 2 Evocation (Wizard)" / "Evocation Cantrip (Sorcerer, Wizard)"."""
    m = re.match(r"Level (\d) (\w+) \(([^)]+)\)$", kind) or re.match(r"(\w+) Cantrip \(([^)]+)\)$", kind)
    if not m:
        raise ValueError(f"{name}: spell line {kind!r}")
    level, school, classes = (int(m.group(1)), m.group(2), m.group(3)) if kind.startswith("Level") else (0, m.group(1), m.group(2))
    if school not in SCHOOLS:
        raise ValueError(f"{name}: school {school!r}")
    if "Components" not in info:
        raise ValueError(f"{name}: no Components in {info} ({kind})")
    comps = info.pop("Components")
    cm = re.match(r"([VSM, ]+?)(?: \((.*)\))?$", comps)
    if not cm:
        raise ValueError(f"{name}: components {comps!r}")
    casting = info.pop("Casting Time")
    ritual = casting.endswith(" or Ritual")
    duration = info.pop("Duration")
    rng = info.pop("Range")
    if info:
        raise ValueError(f"{name}: fields not read {list(info)}")
    return {
        "key": slug(name), "name": name, "level": level, "school": school, "classes": _list(classes),
        "casting_time": casting.removesuffix(" or Ritual"), "ritual": ritual, "range": rng,
        "components": [c.strip() for c in cm.group(1).split(",") if c.strip()], "material": cm.group(2) or "",
        "duration": duration, "concentration": duration.startswith("Concentration"),
        "text": desc, "higher_levels": higher, "cantrip_upgrade": upgrade, "creatures": creatures, "source": SOURCE,
    }


def magic_items(lines: list[Line], text: Text) -> tuple[list[dict], list[dict]]:
    """The items, and the creatures they make that are monsters in their own right (the Figurine of
    Wondrous Power's Giant Fly). A creature whose numbers are its summoner's stays with its item."""
    part = section(lines, "Magic Items A–Z", "Monsters")
    heads = titled(part, lambda x: x.is_("GillSans-SemiBold", 12.0),
                   lambda x: x.is_("Cambria-Italic", 10.0) and re.match(rf"({'|'.join(ITEM_CATEGORIES)})\b", x.text.strip()))
    items, creatures = [], []
    for name, chunk in chunks(part, heads):
        k, kind = follows(chunk, 0, lambda x: x.is_("Cambria-Italic", 10.0))
        rest, blocks = without_blocks(chunk[k:])
        raw = [stat_block(b, text) for b in blocks]
        made = [monster(r, "Magic Items", name) for r in raw if not r["fields"]["CR"].startswith("None")]
        creatures += made
        items.append(magic_item(name, kind, text(rest), [c["key"] for c in made],
                                [summoned(r) for r in raw if r["fields"]["CR"].startswith("None")]))
    return items, creatures


def magic_item(name: str, kind: str, desc: str, monster_keys: list[str], creatures: list[dict]) -> dict:
    """"Armor (Plate Armor), Legendary (Requires Attunement)" / "Wondrous Item, Rare (Requires Attunement by a Wizard)"."""
    m = re.match(rf"({'|'.join(ITEM_CATEGORIES)})(?: \(([^)]+)\))?, (.+)$", kind)
    if not m:
        raise ValueError(f"{name}: item line {kind!r}")
    category, base, rest = m.groups()
    att = re.search(r"\s*\(Requires Attunement( [^)]*)?\)\s*$", rest)
    rarity = rest[:att.start()] if att else rest
    return {"key": slug(name), "name": name, "category": category, "base": base or "", "rarity": rarity.strip(),
            "attunement": bool(att), "attunement_by": (att.group(1) or "").strip() if att else "",
            "text": desc, "monsters": monster_keys, "creatures": creatures, "source": SOURCE}


def glossary(lines: list[Line], text: Text) -> list[dict]:
    part = section(lines, "Rules Definitions", "Gameplay Toolbox")
    out = []
    for h, chunk in chunks(part, titled(part, lambda x: x.is_("GillSans-SemiBold", 12.0))):
        m = re.match(r"(.+?)(?: \[([^\]]+)\])?$", h)
        out.append({"key": slug(m.group(1)), "name": m.group(1), "tag": m.group(2) or "", "text": text(chunk), "source": SOURCE})
    return out


# ------------------------------------------------------------------ out


def plain(v):
    """Apostrophes as typed (’ → '), so "Will-o'-Wisp" finds the Will-o’-Wisp; everything else as printed"""
    if isinstance(v, str):  # and a dice expression's minus as a minus: one Jackal prints "1d4 – 1" with a dash
        return re.sub(r"(\d+d\d+) – (\d)", r"\1 − \2", v.replace("’", "'"))
    if isinstance(v, list):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return v


def write(name: str, rows: list[dict], sha: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = plain(rows)
    data = {"source": {"title": "System Reference Document 5.2.1", "version": "5.2.1", "license": "CC-BY-4.0",
                       "url": PDF_URL, "sha256": sha, "made_by": "scripts/srd_import.py"},
            name: rows}
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(rows):4} {name}")


def download() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {PDF_URL}")
    req = urllib.request.Request(PDF_URL, headers={"User-Agent": "askdnd (private table companion)"})
    PDF.write_bytes(urllib.request.urlopen(req, timeout=120).read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, default=PDF)
    ap.add_argument("--compare", action="store_true", help="list differences from Open5e's conversion")
    args = ap.parse_args()
    if args.pdf == PDF and not PDF.exists():
        download()
    sha = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
    lines = body_lines(extract_lines(args.pdf))
    text = Text(Words(lines))
    items, item_creatures = magic_items(lines, text)
    mons = monsters(lines, text) + item_creatures
    sp = spells(lines, text)
    gl = glossary(lines, text)
    for name, rows in (("monsters", mons), ("spells", sp), ("magic_items", items), ("rules_glossary", gl)):
        keys = [r["key"] for r in rows]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            sys.exit(f"{name}: the same key twice: {sorted(dupes)}")
        write(name, rows, sha)
    for n in NOTES:
        print("note:", n)
    if args.compare:
        import srd_compare

        srd_compare.report(mons, sp, items)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
