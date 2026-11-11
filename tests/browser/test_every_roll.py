"""Every roll button plays its plan (Brett, Nov 10: rolls have to be right, driven by askdnd's own data, including rolls
nobody wrote a test for; and the window's place solid, "one of the most annoying UI elements for a player when it's
wrong"). For each of the party's saved sheets (Cole, Big C, No Name, Trah, each in turn as Cole's place at the table),
on Battle, Sheet, the Spell Book and Table rolls' Roll, every roll button is pressed and the roll card played along the
path a player takes most (Damage for an Unarmed Strike, the level it opens at, the first effect, then damage on a hit).

For every one: what's sent to Table rolls is what the button's plan says (app/roll_plan.py `button`: the kind, the
label, the bonus, a spell's dice and count at the level it's cast at), there's no error on the page, and the card is
wholly on screen, beside its button without covering it, and doesn't move from one step to the next.

No hand-picked cases: a new spell, character or button is covered the day it's on a sheet. Whether a plan matches the
rules is the plan's own tests (tests/test_roll_plan.py, the roll audit); this checks the card does what the plan says."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.table_setup import char

PARTY = ["cole", "big_c", "no_name", "trah"]
ROOT_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ddb"

# In the page: every POST to /rolls is noted (and still made), so each roll's own words can be compared with its plan
RECORD = """() => {
  if (window.__sent) return;
  window.__sent = [];
  const real = window.fetch;
  window.fetch = (url, opts) => {
    if (String(url).endsWith('/rolls') && opts && opts.method === 'POST') {
      const d = {};
      for (const [k, v] of new URLSearchParams(opts.body)) (d[k] = d[k] || []).push(v);
      window.__sent.push(d);
      (window.__all = window.__all || []).push(d);  // (every roll this page sent, across buttons)
      return real(url, opts).then(r => { if (!r.ok) r.clone().text().then(t => { d.refused = r.status + ' ' + t.slice(0, 200); }); return r; });
    }
    return real(url, opts);
  };
}"""

# One button, played: open its card, then press on (the first of: Damage, Roll, Roll to hit, Roll damage) until it's
# done, checking the card's place at every step. Returns what was noted.
PLAY = """async ([sel, i]) => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const btn = document.querySelectorAll(sel)[i];
  if (!btn) return { gone: true };
  btn.scrollIntoView({ block: 'center' });
  await wait(30);
  const anchor = btn.getBoundingClientRect(), plan = JSON.parse(btn.dataset.plan || 'null');
  const ctx = JSON.parse((btn.closest('[data-roll-char]') || btn.closest('[data-roll-ctx]') || document.querySelector('[data-roll-ctx]') || { dataset: {} }).dataset.rollCtx || '{}');
  window.__sent.length = 0;
  btn.click();
  const out = { label: btn.dataset.label, kind: btn.dataset.roll, mod: btn.dataset.mod || '', slot: +btn.dataset.slot || 0, plan, ctx, places: [], steps: [] };
  const card = () => document.querySelector('.roll-card');
  for (let t = 0; t < 40 && !card(); t++) await wait(25);
  if (!card()) return { ...out, nocard: true };
  const where = () => { const r = card().getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, vw: innerWidth, vh: innerHeight }; };
  await Promise.all(card().getAnimations().map(a => a.finished.catch(() => null)));  // (its pop-in: 0.14 s)
  out.anchor = { left: anchor.left, top: anchor.top, right: anchor.right, bottom: anchor.bottom };
  out.places.push(where());
  for (let step = 0; step < 6; step++) {
    const c = card();
    if (!c) break;
    const go = c.querySelector('.rcard-choice[data-choice=damage], [data-roll-hit], [data-roll-single]:not([disabled]), [data-roll-save]:not([disabled]), [data-roll-dmg]');
    if (!go) break;
    out.steps.push(go.textContent.trim().split('\\n')[0]);
    const before = window.__sent.length;
    go.click();
    for (let t = 0; t < 200; t++) {
      await wait(25);
      const k = card();
      if (!k || (!k.querySelector('.rolling') && (go.dataset.choice || window.__sent.length > before))) break;
    }
    if (card()) out.places.push(where());
  }
  await wait(60);  // (a refusal's words arrive just after)
  out.sent = window.__sent.slice();
  out.text = card() ? card().innerText : '';
  document.querySelectorAll('.roll-card .rp-x').forEach(x => x.click());
  return out;
}"""


def _as(browser_db, server, name: str):
    """Cole's place at the table, holding `name`'s saved sheet."""
    from app import characters

    data = json.loads((ROOT_FIXTURES / f"{name}.json").read_text())["data"]
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        characters.refresh(db, char(db, "Cole"), lambda _id: data)
        db.commit()
    engine.dispose()


def _expected(r: dict, phone: bool = False) -> list[str]:
    """What's wrong with one played button, in words (empty when it played its plan)."""
    p, name = r["plan"], f"{r['label']} ({r['kind']})"
    if r.get("nocard"):
        return [f"{name}: no roll card opened"]
    bad = []
    if phone:  # (from the bottom, within thumb reach, and staying there: it grows upward)
        for at in r["places"]:
            if at["left"] < 7 or at["top"] < 7 or at["right"] > at["vw"] - 7 or abs(at["bottom"] - (at["vh"] - 8)) > 2:
                bad.append(f"{name}: on a phone the card isn't at the bottom, wholly on screen ({at})")
                break
        r = {**r, "places": r["places"][:1], "anchor": {"top": -1, "bottom": -1, "left": 0, "right": 0}}
    # the card's place: on screen, not over its button, and still at each step (only moved up, as far as it had to)
    first = r["places"][0]
    for at in r["places"]:
        if at["left"] < 7 or at["top"] < 7 or at["right"] > at["vw"] - 7 or at["bottom"] > at["vh"] - 7:
            bad.append(f"{name}: the card isn't wholly on screen ({at})")
            break
    a = r["anchor"]
    if a["bottom"] > 0 and a["top"] < first["vh"] and not (first["right"] <= a["left"] or first["left"] >= a["right"] or first["bottom"] <= a["top"] or first["top"] >= a["bottom"]):
        bad.append(f"{name}: the card covers its own button")
    for at in r["places"][1:]:
        moved_up_to_fit = at["top"] < first["top"] and abs(at["bottom"] - (at["vh"] - 8)) < 2
        if abs(at["left"] - first["left"]) > 1 or (abs(at["top"] - first["top"]) > 1 and not moved_up_to_fit):
            bad.append(f"{name}: the card moved between steps ({first['left']:.0f},{first['top']:.0f} to {at['left']:.0f},{at['top']:.0f})")
            break
    for x in r["sent"]:
        if x.get("refused"):
            bad.append(f"{name}: askdnd refused the roll ({x['refused']}): sent {x}")
    if not r["sent"]:
        return bad + [f"{name}: nothing was rolled ({r['steps']}; the card says: {r['text'][:200]!r})"]
    s = r["sent"][0]
    one = lambda k: (s.get(k) or [""])[0]  # noqa: E731
    play, rolls = p["play"], p.get("rolls")
    level = 0
    if rolls:
        level = r["slot"] if r["slot"] >= rolls["base"] else next((x for x in r["ctx"].get("slots") or [] if x >= rolls["base"]), rolls["base"])
        if rolls["levels"] and level not in rolls["levels"]:
            level = rolls["base"]
    eff = rolls["effects"][0] if rolls and rolls.get("effects") else None
    at = eff["at"].get(str(level)) if eff else None
    want_kind = {"attack": "attack", "d20": p["roll"], "death": "death"}.get(play) or (eff["kind"] if at else p["roll"])
    if one("kind") != want_kind:
        bad.append(f"{name}: sent kind {one('kind')!r}, its plan says {want_kind!r}")
    if play in ("attack", "d20") and one("mod") != r["mod"]:
        bad.append(f"{name}: sent the bonus {one('mod')!r}, the button says {r['mod']!r}")
    if play in ("attack", "d20") and r["mod"] and int(r["mod"].replace("+", "")) != p["bonus"]:
        bad.append(f"{name}: its plan's bonus {p['bonus']} isn't the button's {r['mod']}")
    if at and play == "attack" and s.get("dmg_part", []) != at["parts"]:
        bad.append(f"{name}: sent damage {s.get('dmg_part')}, its plan says {at['parts']} at level {level}")
    if at and play in ("single", "save") and (s.get("part", []) != at["parts"] or int(one("count") or 1) != at["count"]):
        bad.append(f"{name}: sent {one('count')} × {s.get('part')}, its plan says {at['count']} × {at['parts']} at level {level}")
    if rolls and int(one("level") or 0) != level:
        bad.append(f"{name}: sent level {one('level') or 0}, it opened at {level}")
    if not at and play in ("single", "save") and p.get("dmg") and one("dmg") != p["dmg"]:
        bad.append(f"{name}: sent dice {one('dmg')!r}, its plan says {p['dmg']!r}")
    return bad


def _play_all(page, sel: str, reopen=None, phone: bool = False) -> tuple[int, list[str]]:
    n = page.locator(sel).count()
    bad = []
    for i in range(n):
        if reopen:
            reopen()
        r = page.evaluate(PLAY, [sel, i])
        if r.get("gone"):
            continue
        bad += _expected(r, phone)
    return n, bad


SIZES = {"laptop": (1440, 900), "small laptop": (1280, 800), "phone": (375, 812)}


@pytest.mark.parametrize(("name", "size"), [(n, "laptop") for n in PARTY] + [("cole", "small laptop"), ("cole", "phone")])
def test_every_roll_button_plays_its_plan(people, server, browser_db, name, size):
    _as(browser_db, server, name)
    player = people("player")
    page = player.page
    w, h = SIZES[size]
    page.set_viewport_size({"width": w, "height": h})
    phone = size == "phone"
    if phone:  # (the page decides it's a phone by its width, as it loads)
        page.reload()
    player.open(f"/characters/{server['cole']}/battle")
    page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
    played, bad = 0, []
    for path, scope in ((f"/characters/{server['cole']}/battle", "main"), (f"/characters/{server['cole']}", "main")):
        player.open(path)
        page.evaluate(RECORD)
        n, b = _play_all(page, f"{scope} [data-roll][data-plan]", phone=phone)
        played, bad = played + n, bad + b

    # the Spell Book (a large window of its own)
    player.open(f"/characters/{server['cole']}/battle")
    page.evaluate(RECORD)
    if page.locator(".spellbook-btn").count():
        def book():
            if not page.locator(".sb-actions").count():
                page.locator(".spellbook-btn").first.click()
                page.locator(".sb-actions").first.wait_for()
        book()
        n, b = _play_all(page, ".sb-actions [data-roll][data-plan]", book, phone)
        played, bad = played + n, bad + b

    # Table rolls' Roll: each pick closes the window behind it, so it's opened again for the next
    player.open(f"/characters/{server['cole']}/battle")
    page.evaluate(RECORD)

    def board():
        if not page.locator("#peek.open .roll-board .rc").count():
            page.evaluate("document.querySelector('[data-rs-roll]').click()")
            page.locator("#peek.open .roll-board .rc").first.wait_for()
    board()
    n, b = _play_all(page, "#peek.open .roll-board .rc[data-plan]", board, phone)
    played, bad = played + n, bad + b

    # Table rolls' follow-ups (Roll damage, Reroll, + a die) on the rolls just made: each opens the card on its roll
    player.open(f"/characters/{server['cole']}/battle")
    page.evaluate(RECORD)
    if page.evaluate("document.body.classList.contains('rolls-closed')"):
        page.evaluate("document.querySelector('.rs-edge, .rs-toggle').click()")
    for _ in range(3):  # (an attack rolled and closed before its damage: Table rolls offers its follow-ups; a natural 1 offers none)
        page.locator("main [data-roll=attack][data-plan]").first.evaluate("b => b.click()")
        card = page.locator(".roll-card")
        if card.locator('[data-choice="damage"]').count():
            card.locator('[data-choice="damage"]').click()
        card.locator("[data-roll-hit]").click()
        card.locator(".rcard-result:not(.rolling)").wait_for(timeout=15000)
        page.keyboard.press("Escape")
        if page.locator('#roll-log .roll-follow[data-follow="damage"]').count():
            break
    page.locator("#roll-log .roll-follow").first.wait_for(state="attached", timeout=10000)
    for action in ("damage", "reroll", "bonus"):
        button = page.locator(f'#roll-log .roll-follow[data-follow="{action}"]')
        if not button.count():
            continue
        page.evaluate("window.__sent.length = 0")
        button.first.evaluate("b => b.click()")
        page.locator(".roll-card").wait_for()
        if action == "bonus":
            page.locator(".roll-card [data-add]").first.click()
        page.locator(".roll-card .rcard-result:not(.rolling)").wait_for(timeout=15000)
        sent = page.evaluate("window.__sent")
        if not sent or sent[0].get("action") != [action] or sent[0].get("refused"):
            bad.append(f"Table rolls' {action}: sent {sent}")
        played += 1
        page.keyboard.press("Escape")

    # What's offered under the to-hit once it's seen (Guided Strike's +10, Favored by the Gods' +2d4): each pressed once,
    # on an attack of its own, and sent as an added roll with its name (Brett's Roll Audit comment, Nov 10)
    attack = "main [data-roll=attack][data-plan]"
    pills = page.evaluate(f"""() => {{ const p = JSON.parse(document.querySelector('{attack}')?.dataset.plan || '{{}}');
        return (p.modifiers || []).filter(m => ['after_fail', 'after_roll'].includes(m.when) && (m.to || []).includes('attack')).map(m => [m.name, m.short || m.name]); }}""")
    for full, short in pills:
        for _ in range(4):  # (a natural 20 offers nothing for a miss: roll again)
            page.evaluate("window.__sent.length = 0")
            page.locator(attack).first.evaluate("b => b.click()")
            card = page.locator(".roll-card")
            if card.locator('[data-choice="damage"]').count():
                card.locator('[data-choice="damage"]').click()
            card.locator("[data-roll-hit]").click()
            card.locator(".rcard-result:not(.rolling)").wait_for(timeout=15000)
            pill = card.locator(f'[data-after="{full}"]')
            if pill.count():
                pill.click()
                page.wait_for_function("window.__sent.some(x => (x.action || [])[0] === 'bonus')", timeout=15000)
                sent = page.evaluate("window.__sent.find(x => (x.action || [])[0] === 'bonus')")
                if not any(e.startswith(short + ":+") for e in sent.get("extra", [])) or sent.get("refused"):
                    bad.append(f"{full}: sent {sent}")
                played += 1
                page.keyboard.press("Escape")
                break
            page.keyboard.press("Escape")
        else:
            bad.append(f"{full}: never offered after four to-hit rolls")

    # Riders on a hit that do something (docs/mockups/rider-actions/, Nov 10): each pressed once on an attack that has it,
    # then Roll damage; what's sent is what the rider says (its dice in the damage, Force, rolled twice, its save)
    riders = page.evaluate(f"""() => {{ const seen = {{}};
        document.querySelectorAll('{attack}').forEach((b, i) => (JSON.parse(b.dataset.plan || '{{}}').riders || [])
          .filter(r => r.act && r.when === 'hit' && !(r.name in seen)).forEach(r => {{ seen[r.name] = [i, r.name, r.act]; }}));
        return Object.values(seen); }}""")
    for i, rider, act in riders:
        for _ in range(6):  # (a natural 1 has no damage: roll again)
            page.evaluate("window.__sent.length = 0")
            page.locator(attack).nth(i).evaluate("b => b.click()")
            card = page.locator(".roll-card")
            if card.locator('[data-choice="damage"]').count():
                card.locator('[data-choice="damage"]').click()
            card.locator("[data-roll-hit]").click()
            card.locator(".rcard-result:not(.rolling)").wait_for(timeout=15000)
            pill = card.locator(f'[data-ride="{rider}"]')
            if not pill.count():
                page.keyboard.press("Escape")
                continue
            pill.click()
            card.locator("[data-roll-dmg]").click()
            want = "save" if act["kind"] == "save" else "damage"
            page.wait_for_function(f"window.__sent.some(x => (x.action || [])[0] === '{want}')", timeout=15000)
            page.wait_for_timeout(300)
            sent = page.evaluate("window.__sent")
            dmg = next((x for x in sent if x.get("action") == ["damage"]), {})
            ok = dmg and not any(x.get("refused") for x in sent)
            if act["kind"] == "dice":
                ok = ok and any(e.startswith(rider) for e in dmg.get("extra", []))
            if act.get("type"):
                ok = ok and dmg.get("as_type") == [act["type"]]
            if act.get("twice"):
                ok = ok and dmg.get("twice") == ["1"]
            if act["kind"] == "save":
                ok = ok and any(x.get("action") == ["save"] and x.get("label") == [f"{rider}: {act['save']} save"] for x in sent)
            if not ok:
                bad.append(f"rider {rider}: sent {sent}")
            played += 1
            page.keyboard.press("Escape")
            break
        else:
            bad.append(f"rider {rider}: never offered after six to-hit rolls")

    assert played > 40, f"only {played} roll buttons found for {name}"
    assert not bad, f"{name}: {len(bad)} of {played} roll buttons didn't play their plan:\n" + "\n".join(bad[:40])
    assert player.errors == []


ZAP = 990001


def _made_up_creature() -> dict:
    """A familiar-like creature on Cole's sheet, in D&D Beyond's shape, with made-up words (tests/test_creatures.py)."""
    from tests.test_creatures import made_up

    return made_up(cid=ZAP)


def _setup(browser_db, server, what: str) -> list[tuple[str, str, str]]:
    """Cole's place at the table set up for `what`; returns (who, page, roll buttons) to play."""
    from app import characters, rules_data
    from app.models import Campaign, Character, Place, Token

    data = json.loads((ROOT_FIXTURES / "cole.json").read_text())["data"]
    if what == "creature":
        data = {**data, "creatures": [*data.get("creatures", []), _made_up_creature()]}
    engine = create_engine(browser_db[0])
    out = []
    with Session(engine) as db:
        cole = char(db, "Cole")
        characters.refresh(db, cole, lambda _id: data)
        campaign = db.get(Campaign, cole.campaign_id)
        campaign.vtt_pieces = ["sync", "labs", "creatures", "vtt", "vtt_table"]
        cid = cole.id
        if what == "forms":
            forms = [c["definition"]["name"] for c in data.get("creatures") or [] if c.get("groupId") == 4 or "Wild Shape" in str(c.get("group"))]
            forms = forms or [c["name"] for c in characters.character_summary(cole).get("creatures") or [] if c.get("group") == "Wild Shape form"]
            out = [("player", f"/characters/{cid}/battle", form) for form in forms]
        elif what == "creature":
            out = [("player", f"/characters/{cid}/battle?creature={ZAP}", "")]
        else:  # the DM's rolls as a creature on askdnd's table (a token's side panel)
            p = Place(campaign_id=campaign.id, name="Test room", position=1, map_w=700, map_h=490, map_key=None,
                      grid={"size": 70, "x": 0, "y": 0}, fog={"on": False, "shown": []})
            db.add(p)
            db.flush()
            campaign.shown_place_id = p.id
            for name in ("Goblin Warrior", "Bandit Captain", "Brown Bear"):
                e = rules_data.find("monster", name, db, campaign.id)
                if not e:
                    continue
                t = Token(campaign_id=campaign.id, place_id=p.id, kind="monster", name=e["name"],
                          monster={"key": e["key"], "name": e["name"], "source": e.get("source", "")},
                          hp={"current": int(e.get("hp") or 1), "max": int(e.get("hp") or 1), "temp": 0}, x=0, y=0, size=1)
                db.add(t)
                db.flush()
                out.append(("dm", f"/c/{campaign.slug}/table/tokens/{t.id}", e["name"]))
        db.commit()
        db.expire_all()
        assert db.get(Character, cid)
    engine.dispose()
    return out


def _form(browser_db, form: str):
    from app.models import Character

    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        ch = char(db, "Cole")
        db.get(Character, ch.id).wild_shape = form
        db.commit()
    engine.dispose()


@pytest.mark.parametrize("what", ["forms", "creature", "token"])
def test_every_roll_beyond_the_sheet_plays_its_plan(people, server, browser_db, what):
    """Brett, Nov 10 ("what's left to fully complete rolls"): the rolls that aren't the character's own sheet play their
    plans the same way: Cole in each of his Wild Shape forms, a creature of his on its own Battle, and the DM's rolls as a
    creature on askdnd's table (its side panel's saves and actions, sent with the token, so Table rolls says it's the
    creature's)."""
    todo = _setup(browser_db, server, what)
    assert todo, f"nothing set up for {what}"
    who = people(todo[0][0])
    page = who.page
    page.set_viewport_size({"width": 1440, "height": 900})
    played, bad = 0, []
    for _, path, label in todo:
        if what == "forms":
            _form(browser_db, label)
        if what == "token":
            who.open(path.rsplit("/table/", 1)[0] + "/table")
            page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
            page.evaluate(RECORD)
            sel = "#peek.open .tk-panel [data-roll][data-plan]"

            def panel(path=path):
                if not page.locator(".tk-panel").count():
                    page.evaluate("p => window.askdndPanel(p)", path)
                    page.locator(".tk-panel").first.wait_for(timeout=8000)
            panel()
            n, b = _play_all(page, sel, panel)
            sent_tokens = page.evaluate("(window.__all || []).filter(x => !x.action).map(x => (x.token || [''])[0])")  # (a follow-up is its attack's)
            if any(t != path.rsplit("/", 1)[1] for t in sent_tokens):
                b.append(f"{label}: a roll wasn't sent as the creature's (token {sent_tokens})")
        else:
            who.open(path)
            page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
            page.evaluate(RECORD)
            n, b = _play_all(page, "#battle-body [data-roll][data-plan]")
            if what == "creature":
                whos = page.evaluate("(window.__all || []).filter(x => !x.action).map(x => (x.who || [''])[0])")
                if any(w != "Homunculus Servant" for w in whos):
                    b.append(f"a creature's roll wasn't sent as its (who {whos})")
        if not n:
            bad.append(f"{what} {label or path}: no roll buttons")
        played, bad = played + n, bad + [f"{label}: {x}" for x in b]
    assert not bad, f"{what}: {len(bad)} of {played} roll buttons didn't play their plan:\n" + "\n".join(bad[:40])
    assert who.errors == []


def test_what_adds_to_a_spells_damage_is_pressed_and_rolled(people, server, browser_db):
    """A modifier to a spell's damage (Trah's Dragon-Touched Focus, marked Chromatic): a pill above Roll damage on a
    save spell, sent with the damage when pressed (Brett, Nov 10: what's left to complete rolls)."""
    _as(browser_db, server, "trah")
    data = json.loads((ROOT_FIXTURES / "trah.json").read_text())["data"]
    focus = next(i for i in data["inventory"] if "Dragon-Touched" in i["definition"]["name"])
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        char(db, "Cole").item_choices = {str(focus["id"]): "Chromatic"}
        db.commit()
    engine.dispose()
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 1440, "height": 900})
    player.open(f"/characters/{server['cole']}/battle")
    page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
    page.evaluate(RECORD)
    page.locator(".spellbook-btn").first.click()
    page.locator('.sb-actions [data-roll][data-label="Burning Hands"]').first.evaluate("b => b.click()")
    card = page.locator(".roll-card")
    pill = card.locator('[data-on="Dragon-Touched Focus: Chromatic"]')
    pill.wait_for(timeout=5000)
    pill.click()
    assert "1d6" in card.locator("[data-roll-save]").inner_text()
    card.locator("[data-roll-save]").click()
    page.wait_for_function("window.__sent.length > 0", timeout=15000)
    sent = page.evaluate("window.__sent[0]")
    assert "Dragon-Touched Focus:+1d6" in sent.get("extra", []) and not sent.get("refused"), sent
    assert player.errors == []
