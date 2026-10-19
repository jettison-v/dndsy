from app.templating import _static


def test_static_urls_carry_a_content_hash():
    url = _static("app.css")
    assert url.startswith("/static/app.css?v=") and len(url.split("?v=")[1]) == 10
    assert _static("app.css") == url


def test_missing_static_file_still_gets_a_plain_url():
    assert _static("nope.css") == "/static/nope.css"
