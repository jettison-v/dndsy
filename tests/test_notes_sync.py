import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_notes, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.gdocs import doc_id_from_url, html_to_text, parse_export
from app.importer import import_bundle
from app.main import app
from app.models import NoteSnapshot, NoteSource
from app.notes_sync import store_export, sync_sources

HTML = """<html><head><style>.c1{color:red}</style><title>t</title></head><body>
<h1>Session 17</h1><p>The party met <b>Uni</b>.</p>
<ul><li>First</li><li>Second<ul><li>Nested</li></ul></li></ul>
<p><img src="images/image1.png"></p>
<table><tr><td>A</td><td>B</td></tr></table></body></html>"""


def make_zip(html=HTML, images={"images/image1.png": b"\x89PNG fake"}):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Notes.html", html)
        for name, data in images.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_doc_id_from_url():
    url = "https://docs.google.com/document/d/1OLwxN8HOXO2E5VlpTcxH0Dm8cYZXYBftlIWowGQm3wg/edit?tab=t.0#heading=h.x"
    assert doc_id_from_url(url) == "1OLwxN8HOXO2E5VlpTcxH0Dm8cYZXYBftlIWowGQm3wg"
    assert doc_id_from_url("not a link") is None


def test_html_to_text_keeps_structure():
    text = html_to_text(HTML)
    assert "# Session 17" in text
    assert "The party met Uni." in text
    assert "- First" in text and "  - Nested" in text
    assert "[image: images/image1.png]" in text
    assert "color:red" not in text


def test_parse_export_collects_images():
    doc = parse_export(make_zip())
    assert doc.images["images/image1.png"] == ("image/png", b"\x89PNG fake")


def source(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    from app.models import Campaign

    s = NoteSource(campaign_id=db.scalar(select(Campaign)).id, google_doc_id="x" * 30)
    db.add(s)
    db.flush()
    return s


def test_snapshot_only_when_content_changes(db):
    s = source(db)
    assert store_export(db, s, parse_export(make_zip()), "Notes")
    assert not store_export(db, s, parse_export(make_zip()))
    assert store_export(db, s, parse_export(make_zip(images={"images/image1.png": b"new picture"})))
    assert len(s.snapshots) == 2
    assert s.title == "Notes"


def test_one_failing_doc_does_not_stop_others(db):
    good, bad = source(db), None
    from app.models import NoteSource as NS

    bad = NS(campaign_id=good.campaign_id, google_doc_id="y" * 30, title="Bad")
    db.add(bad)
    db.flush()

    def fetch(doc_id):
        if doc_id.startswith("y"):
            raise ValueError("boom")
        return "Good doc", parse_export(make_zip())

    results = sync_sources(db, [good, bad], fetch)
    assert results["Good doc"].startswith("updated")
    assert results["Bad"] == "failed: boom"


@pytest.fixture
def admin_client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    client.get("/auth/callback", follow_redirects=False)
    yield client
    app.dependency_overrides.clear()


def test_notes_page_admin_only(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "player@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    client.get("/auth/callback", follow_redirects=False)
    assert client.get("/c/main/manage/sessions/doc").status_code in (403, 404)
    app.dependency_overrides.clear()


def para(text, nesting=None, style="NORMAL_TEXT", obj=None):
    elements = [{"textRun": {"content": text + "\n"}}]
    if obj:
        elements.insert(0, {"inlineObjectElement": {"inlineObjectId": obj}})
    p = {"elements": elements, "paragraphStyle": {"namedStyleType": style}}
    if nesting is not None:
        p["bullet"] = {"nestingLevel": nesting}
    return {"paragraph": p}


DOCS_JSON = {
    "title": "DnD Notes",
    "tabs": [
        {
            "tabProperties": {"title": "Notes"},
            "documentTab": {
                "body": {"content": [
                    para("Session 17", style="HEADING_6"),
                    para("Top bullet", nesting=0),
                    para("Nested bullet", nesting=1),
                    para("", obj="kix.img"),
                    para("Family Tree", obj="kix.drawing"),
                ]},
                "inlineObjects": {
                    "kix.img": {"inlineObjectProperties": {"embeddedObject": {"imageProperties": {"contentUri": "https://img.example/1"}}}},
                    "kix.drawing": {"inlineObjectProperties": {"embeddedObject": {"embeddedDrawingProperties": {}}}},
                },
            },
            "childTabs": [{"tabProperties": {"title": "Wild Shape"}, "documentTab": {"body": {"content": [para("Lion", nesting=0)]}}}],
        }
    ],
}


def test_docs_json_keeps_nesting_tabs_and_objects():
    from app.gdocs import docs_json_to_text

    text, objects = docs_json_to_text(DOCS_JSON)
    assert "- Top bullet\n  - Nested bullet" in text
    assert "## Wild Shape" in text and "- Lion" in text
    assert [o["kind"] for o in objects] == ["image", "drawing"]
    assert "[image: obj-1]" in text and "[image: obj-2]" in text


def test_table_keeps_merged_cells_and_cell_bullets():
    from app.gdocs import docs_json_to_text

    def cell(*paras, colspan=1):
        return {"tableCellStyle": {"columnSpan": colspan, "rowSpan": 1}, "content": list(paras)}

    empty = cell()
    doc = {"tabs": [{"tabProperties": {"title": "Wild Shape"}, "documentTab": {"body": {"content": [
        {"table": {"tableRows": [
            {"tableCells": [cell(para("When"), colspan=3), empty, empty]},
            {"tableCells": [cell(para("Pros"), colspan=2), empty, cell(para("Cons"))]},
            {"tableCells": [cell(para("Pack Tactics", nesting=0), para("Multiattack", nesting=0), colspan=2), empty, cell(para("Low <save>"))]},
        ]}}
    ]}}}]}
    text, _ = docs_json_to_text(doc)
    assert '<tr><th colspan="3">When</th></tr>' in text
    assert '<tr><th colspan="2">Pros</th><th>Cons</th></tr>' in text
    assert "• Pack Tactics<br>• Multiattack" in text
    assert "Low &lt;save&gt;" in text  # cell text is escaped


def test_links_become_clickable_in_text_and_tables():
    from app.gdocs import docs_json_to_text
    from app.render import markdown_to_html

    linked = {"textRun": {"content": "Cole sheet", "textStyle": {"link": {"url": "https://www.dndbeyond.com/characters/1"}}}}
    plain = {"textRun": {"content": " map: https://example.com/map?a=1&b=2\n"}}
    p = {"paragraph": {"elements": [linked, plain], "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}}
    cell = {"tableCellStyle": {"columnSpan": 1}, "content": [p]}
    doc = {"tabs": [{"tabProperties": {"title": "T"}, "documentTab": {"body": {"content": [p, {"table": {"tableRows": [{"tableCells": [cell]}]}}]}}}]}
    text, _ = docs_json_to_text(doc)
    assert "[Cole sheet](https://www.dndbeyond.com/characters/1)" in text
    html = markdown_to_html(text, lambda n: None)
    assert html.count('href="https://www.dndbeyond.com/characters/1"') == 2  # paragraph + table cell
    assert html.count('href="https://example.com/map?a=1&amp;b=2"') == 2
    assert 'target="_blank"' in html


def test_render_is_sanitized_and_swaps_images():
    from app.render import markdown_to_html

    md = "# Title\n\n- a\n  - b\n\n<table><tr><td colspan=\"2\">x</td></tr></table>\n\n[image: obj-1] <script>alert(1)</script>"
    html = markdown_to_html(md, lambda n: "/img/1" if n == "obj-1" else None)
    assert "<h1>Title</h1>" in html
    assert "<ul>" in html and html.count("<ul>") == 2  # nested list
    assert '<td colspan="2">x</td>' in html
    assert '<img src="/img/1"' in html
    assert "<script>" not in html


def test_shrink_image_limits_size():
    from PIL import Image

    from app.gdocs import MAX_IMAGE_SIDE, shrink_image

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (120, 30, 200)).save(buf, "PNG")
    ctype, data = shrink_image("image/png", buf.getvalue())
    assert max(Image.open(io.BytesIO(data)).size) == MAX_IMAGE_SIDE
    assert len(data) < len(buf.getvalue())


class Resp:
    def __init__(self, status=200, content=b"", json_data=None, ctype="image/png"):
        self.status_code, self.content, self._json, self.text = status, content, json_data, ""
        self.headers = {"content-type": ctype}

    def json(self):
        return self._json


def test_add_source_and_sync(admin_client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    url = "https://docs.google.com/document/d/" + "a" * 44 + "/edit"
    admin_client.post("/manage/sessions/doc/sources", data={"url": url})
    assert db.scalar(select(NoteSource)).google_doc_id == "a" * 44

    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": f"openid email {admin_notes.DRIVE_READONLY}"}

    export_html = '<p><img src="images/image1.png"></p><p><img src="images/image2.png">Family Tree</p>'
    export_zip = make_zip(html=export_html, images={"images/image1.png": b"one", "images/image2.png": b"tree"})

    async def fake_get(url, token=None, timeout=None):
        if "docs.googleapis.com" in url:
            return Resp(json_data=DOCS_JSON)
        if "img.example" in url:
            return Resp(content=b"photo")
        if "export" in url:
            return Resp(content=export_zip)
        return Resp(status=404)

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    monkeypatch.setattr(admin_notes.oauth.google_drive, "get", fake_get)
    page = admin_client.get("/admin/notes/callback")
    assert "<b>DnD Notes</b>: updated" in page.text
    assert "2 images" in page.text
    snap = db.scalar(select(NoteSnapshot))
    assert {i.name: i.data for i in snap.images} == {"obj-1": b"photo", "obj-2": b"tree"}
    view = admin_client.get(f"/c/main/manage/sessions/doc/snapshots/{snap.id}").text
    assert "/manage/sessions/doc/images/" in view
    assert view.count("<ul>") >= 2  # nested bullet list


def test_sync_rejects_missing_drive_scope(admin_client, db, monkeypatch):
    from tests.roles import set_role

    set_role(db, "admin@example.com", "player")  # in a campaign, so the doc page has its address to come back to
    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": "openid email"}

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    assert "read-only Drive access" in admin_client.get("/admin/notes/callback").text


def test_google_errors_explained_and_shown_in_red(admin_client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    admin_client.post("/manage/sessions/doc/sources", data={"url": "https://docs.google.com/document/d/" + "b" * 44 + "/edit"})

    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": admin_notes.DRIVE_READONLY}

    async def fake_get(url, token=None, timeout=None):
        return Resp(status=403, json_data={"error": {"code": 403, "message": "API not used", "errors": [{"reason": "accessNotConfigured"}]}})

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    monkeypatch.setattr(admin_notes.oauth.google_drive, "get", fake_get)
    page = admin_client.get("/admin/notes/callback").text
    assert "Sync failed." in page
    assert 'flash bad' in page
    assert "isn&#39;t turned on for your Google Cloud project" in page
    assert db.scalar(select(NoteSource)).last_synced_at is None
