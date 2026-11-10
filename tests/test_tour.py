"""The new-player tour and Help › What askdnd adds (app/tour.py): each person's stops, with their own character's
pages; the stops' targets exist in the templates; Help shows every group with Show me. Walking the tour in a real
browser is tests/browser/test_tour.py."""

import re
from pathlib import Path

from app import tour
from app.player_notes import KINDS
from tests.test_table_rolls import char, table  # noqa: F401

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


def test_signed_in_only(table):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/tour").status_code == 401


def test_a_player_tours_their_own_character(table, db):  # noqa: F811
    stops = table["player"].get("/tour").json()["stops"]
    cole = char(db, "Cole").id
    urls = {s["url"] for s in stops}
    assert {f"/characters/{cole}/battle", f"/characters/{cole}", f"/characters/{cole}/plan", "/c/main/", "/c/main/campaign",
            "/party", None} == urls
    assert [s["group"] for s in stops][:2] == ["previously", "memory"] and stops[-1]["group"] == "help"
    assert all(s["title"] and s["what"] and s["why"] for s in stops)


def test_without_a_character_the_tour_leaves_out_character_pages(table):  # noqa: F811
    groups = [s["group"] for s in table["dm"].get("/tour").json()["stops"]]
    assert groups == ["previously", "memory", "rolling", "rolling", "dice", "live", "party", "help"]  # (Table rolls, Search and Your dice: anyone)


def test_every_stop_has_a_target_in_the_templates():
    """Every attribute and class a stop names is made somewhere: a template, or app.js (the side panel's .peek)."""
    html = "\n".join(p.read_text() for p in TEMPLATES.glob("*.html"))
    js = (TEMPLATES.parent / "static" / "app.js").read_text()
    for s in tour.STOPS:
        opens = [s["open"]] if isinstance(s.get("open"), str) else s.get("open") or []
        for sel in [s["at"], *opens]:
            for attr, value in re.findall(r'\[([\w-]+)(?:="([^"]*)")?\]', sel):
                if attr == "data-tab" and value in ("t-combo", "t-leveling", "t-quest", "t-general"):
                    assert value[2:] in KINDS and 'data-tab="t-{{ kind }}"' in html  # Plan's note tabs, one per kind
                elif value:
                    assert f'{attr}="{value}"' in html or f'{attr}="{{{{' in html and attr == "data-econ-col", sel
                else:
                    assert attr in html, sel
            for cls in re.findall(r"\.([\w-]+)", sel):
                assert re.search(rf'class="[^"]*\b{cls}\b', html) or f"'{cls}'" in js or f"'{cls} " in js, (cls, sel)


def test_the_words_are_plain_with_bold_names_only():
    for s in tour.STOPS:
        for text in (s["what"], s["why"]):
            assert set(re.findall(r"</?(\w+)", text)) <= {"b"}, text


def test_help_shows_what_askdnd_adds_with_show_me(table):  # noqa: F811
    html = table["player"].get("/help?tab=adds").text
    assert 'aria-selected="true" data-tab="t-adds"' in html
    keys = {k for _, groups in tour.SECTIONS for k, _, _ in groups if k}
    assert keys <= {s["group"] for s in tour.STOPS}
    for k in keys:
        assert f'data-tour-start="{k}"' in html
    assert table["player"].get("/help?tab=faq").text.count('id="t-adds" class="adds" hidden') == 1
    assert table["player"].get("/help").text.count('id="t-adds" class="adds" hidden') == 0  # a first visit starts here
