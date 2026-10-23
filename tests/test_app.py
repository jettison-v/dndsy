from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_public():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_home_redirects_to_login_when_signed_out():
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page():
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign in with Google" in response.text


def test_about_and_faq_are_open_to_anyone():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    about, faq = c.get("/help?tab=about"), c.get("/help")  # Help: the FAQ and About as tabs (2026-10-23)
    assert c.get("/faq", follow_redirects=False).status_code == 404 and c.get("/about").status_code == 404  # one address each
    assert about.status_code == 200 and "Ground rules" in about.text and "never shown to the DM" in about.text
    assert faq.status_code == 200 and "Who sees my suggestion" in faq.text and "every 2.5 minutes" in faq.text
    assert 'href="/help"' in c.get("/login").text
