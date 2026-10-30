"""A time of day in the reader's own time zone (templating.py `clock`, app.js "clocks"; Brett, 2026-10-29: the bridge
page said 1:22 AM at 6:22 PM). The server writes UTC, which it keeps; the page rewrites it, however it arrives."""


def test_a_time_shows_in_the_readers_own_zone_even_when_it_arrives_later(people, server):
    admin = people("admin")  # (Pacific, as the table)
    page = admin.open("/help")
    page.evaluate("""document.querySelector('main').insertAdjacentHTML('beforeend',
        '<time id="t1" datetime="2026-10-30T01:22:00+00:00" data-clock="time">1:22 AM UTC</time>'
        + '<time id="t2" datetime="2025-03-02T17:05:00+00:00" data-clock="date">Mar 2, 2025, 5:05 PM UTC</time>')""")
    page.wait_for_function("document.getElementById('t1').textContent === '6:22 PM'")
    assert page.locator("#t2").inner_text() == "Mar 2, 2025, 9:05 AM"  # another year says which
    assert admin.errors == []
