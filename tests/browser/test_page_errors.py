"""What goes wrong in a page comes home (app.js "page errors", app/errors.py): a JavaScript error, and something the
Content Security Policy blocked, which raises no error of its own."""

import json


def test_a_blocked_picture_comes_home_with_its_rule_and_only_its_origin(people, server):
    player = people("player")
    player.open("/c/main/campaign")
    with player.page.expect_request("**/errors/page") as sent:
        player.page.evaluate("""() => { const i = document.createElement('img');
            i.src = 'https://elsewhere.example/a/secret.png?who=me'; document.body.append(i); }""")
    got = json.loads(sent.value.post_data)
    assert got["message"] == "Blocked by the page's rules: img-src https://elsewhere.example"
    assert "secret" not in sent.value.post_data and "who=me" not in sent.value.post_data
    player.csp.clear()  # (blocked on purpose: the fixture fails a test on any other block)
