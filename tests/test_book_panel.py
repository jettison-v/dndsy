"""A rule book's side panel (issue 117, Brett's picks on docs/mockups/rule-books/, Nov 27): pressing a book on Backstage ›
Rule books opens what it is, what askdnd takes from it, where you meet it, what it leaves out and which campaigns have it
on; its cover is his upload through the one Picture window, drawn until he adds one, and only admins ever see it."""

from sqlalchemy import select

from app.models import BookEntry, Campaign, EntityPicture
from tests.test_pictures import png
from tests.test_suggestions import HX


def _monsters(db, n=2):
    db.add_all([BookEntry(book="mm-2024", kind="monster", key=f"hound-{i}", name=f"Hound {i}", data={"name": f"Hound {i}"}) for i in range(n)])
    db.flush()


def test_pressing_a_book_opens_what_askdnd_takes_from_it(admin, db):
    _monsters(db)
    db.add(Campaign(slug="vtt", name="VTT test", is_test=True, books=["phb-2024"]))
    db.commit()
    page = admin.get("/manage/books").text
    assert 'data-panel-url="/manage/books/mm-2024"' in page and 'data-book="mm-2024"' in page  # (a drawn cover beside its name)
    panel = admin.get("/manage/books/mm-2024").text
    assert 'data-book-panel="mm-2024"' in panel and "2</b><span>monsters" in panel
    assert "Wild Shape" in panel and "What it leaves out" in panel and "Add a cover…" in panel
    assert 'data-campaign="vtt"' in panel and "/c/vtt/manage/settings?tab=books" in panel  # (switched there: Brett's pick K1)
    empty = admin.get("/manage/books/dmg-2024").text
    assert "Nothing taken yet" in empty and "Upload…" in empty
    assert admin.get("/manage/books/no-such-book").status_code == 404


def test_a_standing_rule_a_books_panel_and_cover_are_for_admins_only(admin, dm, player, db):
    """A standing rule (Brett, the data strategy, 2026-10-27: a book's content is private, never public; Rule books is
    admins only): its panel, its cover's Picture window and the cover itself answer no one else."""
    _monsters(db)
    db.commit()
    for who in (dm, player):
        assert who.get("/manage/books/mm-2024").status_code in (302, 303, 403, 404)
        assert who.get("/pictures?for=book:mm-2024").status_code == 404
        r = who.post("/pictures/upload", data={"for": "book:mm-2024"}, files={"file": ("c.png", png(600, 800), "image/png")}, headers=HX)
        assert r.status_code == 404
    assert db.scalar(select(EntityPicture)) is None


def test_the_cover_is_uploaded_never_drawn_and_shown_in_place_of_the_drawn_one(admin, dm, db):
    window = admin.get("/pictures?for=book:mm-2024").text
    assert "Upload" in window and "Describe it" not in window  # (its publisher's art: never drawn)
    assert admin.post("/pictures/draw", data={"for": "book:mm-2024", "words": "a cover"}).status_code == 404
    r = admin.post("/pictures/upload", data={"for": "book:mm-2024"}, files={"file": ("c.png", png(600, 800), "image/png")}, headers=HX)
    assert r.status_code == 200
    pic = db.scalar(select(EntityPicture).where(EntityPicture.book == "mm-2024"))
    assert pic is not None and pic.file_key.startswith("tool/")  # (the tool's own file: no campaign's)
    assert admin.get("/manage/books/mm-2024/cover").status_code == 200
    assert dm.get("/manage/books/mm-2024/cover").status_code == 404
    panel = admin.get("/manage/books/mm-2024").text
    assert 'class="book-cover photo"' in panel and "/manage/books/mm-2024/cover" in panel and "Change the cover…" in panel
