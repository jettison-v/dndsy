"""The one item window (Brett, Nov 20: issue 44 and The Work Pages, docs/mockups/work-pages/): any single item (a check,
a question or decision, a change to try on your Mac, a note, an issue, an idea, a Roadmap step) opens in a panel at the
page's right, from any of For you, Feedback and Development, read and acted on there. ↑ ↓ walk the list it was opened from
(`?from=`); after a press it moves on to the next one, or stays for a conversation (app.js "the item window"). A link
to a group (a plan, a Product Area) goes to its page instead. Admins only, as the pages it opens from."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.fft import feedback_page, taxonomy, testing_page, views, work_page
from app.templating import templates

router = APIRouter()
KINDS = {"c": "Check", "q": "Question", "l": "On your Mac", "n": "Note", "i": "Issue", "d": "Idea", "r": "Roadmap item", "a": "Plan"}


def _list(db: Session, frm: str, device: str) -> list[str]:
    """The keys of the list an item was opened from, in its order (empty when unknown: no ↑ ↓)."""
    parts = frm.split(":")
    if parts[0] == "foryou":
        return testing_page.listed_keys(db, "foryou", device)
    if parts[0] in ("checks", "round", "plan"):  # (Work's Checks, a plan's Test round and Issues)
        return work_page.listed_keys(db, frm)
    if parts[0] == "feedback" and len(parts) == 6:
        tab, chip, area, pa, feature = parts[1:]
        if tab in dict(feedback_page.TABS):
            return feedback_page.listed_keys(db, tab, chip, int(area) if area.isdigit() else 0, pa, feature)
    return []


def _home(picked: dict, frm: str) -> tuple[str, str]:
    """Where the item lives as a page: Open in … (its old address, which opens it in this window there). Nothing when
    that's the page the window was opened on (issue 58, Brett, Nov 20: "This button is recursive")."""
    k = picked["kind"]
    if k in ("note", "issue", "idea"):
        name, href = "Feedback", f"/manage/feedback?tab={feedback_page.tab_of(picked)}&open={picked['key']}"
    elif k == "roadmap":  # (Brett, Nov 20: "the navigation is circular and you never actually get to the roadmap item")
        name, href = "the Roadmap", f"/manage/roadmap/{picked['it'].id}"
    elif k == "plan":  # (a plan opens in the window from the Board and Your order; its page stays for a link: M1)
        name, href = "its page", f"/manage/work/{picked['a'].id}"
    elif k == "check":  # (a check lives in Development's Checks, wherever it was opened from)
        name, href = "Development", f"/manage/work?tab=checks&open={picked['key']}"
    else:  # (a question or a try on your Mac lives only in For you)
        name, href = "For you", f"/manage/for-you?open={picked['key']}"
    return ("", "") if name == _page_of(frm) else (name, href)


def _page_of(frm: str) -> str:
    """The page a window was opened on, named as _home names it ("" when unknown)."""
    first = frm.split(":", 1)[0]
    return {"foryou": "For you", "feedback": "Feedback", "checks": "Development"}.get(first, "")  # (from a plan's page: where it lives)


@router.get("/manage/item/{key}", response_class=HTMLResponse)
def item(request: Request, key: str, frm: str = Query("", alias="from"), db: Session = Depends(get_db)):
    user, denied = testing_page._admin(request)
    if denied:
        return denied
    device = testing_page.device_of(request)
    me = views.person(db, user)
    picked = (feedback_page.picked_of(db, key, me["id"]) if key[:1] in ("n", "i", "d")
              else testing_page._picked(db, key, device) if key[:1] in KINDS else None)
    if picked is None:
        return HTMLResponse("This one isn't here any more.", status_code=404)
    picked["key"] = key
    keys = _list(db, frm, device)
    at = keys.index(key) if key in keys else -1
    prev = keys[at - 1] if at > 0 else ""
    nxt = keys[at + 1] if 0 <= at < len(keys) - 1 else ""
    page_name, page_href = _home(picked, frm)
    db.commit()  # (an issue opened is seen)
    return templates.TemplateResponse(request, "_fft_item.html", {
        "key": key, "picked": picked, "kind_label": KINDS[key[:1]], "number": key[1:], "frm": frm,
        "prev": prev, "next": nxt, "at": at + 1, "of": len(keys), "page_name": page_name, "page_href": page_href,
        # (what the readers used from their pages: Feedback's words and the tab a press lands on; Testing's device)
        "tab": feedback_page.tab_of(picked) if picked["kind"] in ("note", "issue", "idea") else "",
        "kind_said": views.KIND_SAID, "closed_word": views.CLOSED_WORD, "issue_word": views.ISSUE_WORD, "me_id": me["id"], "taxonomy": taxonomy.areas(),
        "device": device, "device_said": testing_page.DEVICE_SAID, "check_words": views.CHECK_WORD})
