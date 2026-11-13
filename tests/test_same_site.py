"""Changes come only from askdnd's own pages (app/same_site.py, foundations F2): a change made with the sign-in cookie
from another site's page is refused; the extension's key and requests without the cookie are left to their route."""

from app.same_site import from_elsewhere

ROUTE = "/errors/page"  # a change anyone signed in may send: its own answer (400 for an empty body) shows it got through


def test_another_sites_page_cant_change_anything_with_your_cookie(player):
    assert player.post(ROUTE, content=b"[]", headers={"Origin": "https://elsewhere.example"}).status_code == 403
    assert player.post(ROUTE, content=b"[]", headers={"Origin": "null"}).status_code == 403  # a sandboxed frame
    assert player.post(ROUTE, content=b"[]", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_askdnds_own_pages_and_other_proof_get_through(player):
    assert player.post(ROUTE, content=b"[]", headers={"Origin": "http://testserver"}).status_code == 400
    assert player.post(ROUTE, content=b"[]", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 400
    assert player.post(ROUTE, content=b"[]").status_code == 400  # (no Origin: a script, the Processor)
    assert player.post(ROUTE, content=b"[]", headers={"Origin": "chrome-extension://abc", "X-Askdnd-Bridge": "k"}).status_code == 400
    player.cookies.clear()  # signed out: no cookie to misuse, the route decides
    assert player.post(ROUTE, content=b"[]", headers={"Origin": "https://elsewhere.example"}).status_code == 401


def test_reading_is_never_refused_by_it(player):
    assert player.get("/health", headers={"Origin": "https://elsewhere.example", "Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_the_rule_on_its_own():
    cookie = {b"cookie": b"x=1; askdnd_session=abc", b"host": b"askdnd.ai"}
    assert from_elsewhere({**cookie, b"origin": b"https://evil.example"})
    assert not from_elsewhere({**cookie, b"origin": b"https://askdnd.ai"})
    assert not from_elsewhere({b"host": b"askdnd.ai", b"origin": b"https://evil.example"})
    assert not from_elsewhere({**cookie, b"origin": b"https://evil.example", b"authorization": b"Bearer t"})
