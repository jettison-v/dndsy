// askdnd: small page behaviors. Server-rendered pages; HTMX handles partial updates.

// Feedback for Claude's window, or its Point at (Brett, Nov 9: "clicking Point at closes all modals"): a click or Escape
// there belongs to it, so whatever is open on the page (the roll window, a side panel, a picker) stays open to point at.
const feedbackBusy = e => !!(e && e.target && e.target.closest && e.target.closest('#fb-win')) || document.body.classList.contains('fb-pointing');

(function () {
  const $ = (s, el = document) => el.querySelector(s);

  // ---------------------------------------------------------------- page errors
  // (VTT 0.9, app/errors.py) A JavaScript error in one of askdnd's own scripts goes home to askdnd, which passes it to
  // Sentry. Errors from browser extensions and other sites' scripts are left out; each error is sent once per page,
  // at most five per page.
  const sentErrors = new Set();
  const PAGE_V = (/[?&]v=(\w+)/.exec((document.currentScript || {}).src || '') || [])[1] || '';  // this app.js's version: a tab opened before a deploy shows as old
  function reportError(message, source, line, column, stack) {
    (window.askdndErrors = window.askdndErrors || []).push({ message: String(message).slice(0, 300), at: new Date().toISOString() });  // (a note for Claude carries them)
    if (!document.body || !document.body.dataset.dice) return;  // signed in (the server checks too)
    if (!source || new URL(source, location.href).origin !== location.origin) return;
    const key = message + '|' + source + '|' + line;
    if (sentErrors.has(key) || sentErrors.size >= 5) return;
    sentErrors.add(key);
    const body = JSON.stringify({ message, source, line, column, stack: String(stack || '').slice(0, 2000), page: location.pathname, v: PAGE_V });
    try { navigator.sendBeacon('/errors/page', new Blob([body], { type: 'application/json' })); } catch (e) { /* never break the page over it */ }
  }
  addEventListener('error', e => { if (e.error || e.message) reportError(e.message, e.filename, e.lineno, e.colno, e.error && e.error.stack); });
  // Something the Content Security Policy blocked (app/main.py SAFE_HEADERS) raises no error of its own, so it comes home
  // the same way: the rule it broke and only the origin of what it blocked (never a path or query). Blocks a browser
  // extension caused are its own business.
  document.addEventListener('securitypolicyviolation', e => {
    const ext = /^(chrome|moz|safari(-web)?)-extension:/;
    if (ext.test(e.blockedURI || '') || ext.test(e.sourceFile || '')) return;
    let what = e.blockedURI || '';
    try { what = /^https?:/.test(what) ? new URL(what).origin : what; } catch (err) { /* keep the word (inline, eval) */ }
    reportError('Blocked by the page\'s rules: ' + e.effectiveDirective + ' ' + what, location.href, e.lineNumber || 0, e.columnNumber || 0, '');
  });
  addEventListener('unhandledrejection', e => {
    const r = e.reason || {}, at = /(https?:\/\/[^\s)]+?):(\d+):(\d+)/.exec(String(r.stack || ''));
    reportError('Unhandled: ' + (r.message || String(r)).slice(0, 300), at ? at[1] : '', at ? +at[2] : 0, at ? +at[3] : 0, r.stack);
  });

  // ---------------------------------------------------------------- clocks
  // A time of day in the reader's own time zone (templating.py `clock`): the server writes it in UTC, as it doesn't
  // know the reader's, and this rewrites every <time data-clock> in the browser's own, however it reached the page.
  function clocks(root) {
    const year = new Date().getFullYear();
    (root.matches && root.matches('time[data-clock]') ? [root] : [...root.querySelectorAll('time[data-clock]')]).forEach(t => {
      const d = new Date(t.getAttribute('datetime'));
      if (isNaN(d)) return;
      const o = { hour: 'numeric', minute: '2-digit' };
      // ('when': the time alone today, Yesterday and the time, else the day and the time; a conversation's lines, issue 32)
      const day = n => new Date(Date.now() - n * 864e5).toDateString(), ago = t.dataset.clock === 'when' ? [0, 1].find(n => d.toDateString() === day(n)) : undefined;
      if (t.dataset.clock === 'date' || (t.dataset.clock === 'when' && ago === undefined)) Object.assign(o, { month: 'short', day: 'numeric' }, d.getFullYear() !== year ? { year: 'numeric' } : {});
      t.textContent = (ago === 1 ? 'Yesterday, ' : '') + d.toLocaleString([], o);
      t.title = d.toLocaleString([], { dateStyle: 'full', timeStyle: 'short' });
    });
  }
  clocks(document);
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) clocks(n); })))
    .observe(document.body, { childList: true, subtree: true });

  // ---------------------------------------------------------------- corner cards
  // (Brett, 2026-10-29; docs/mockups/temporary-items.html) Everything you read and dismiss, in one place: bottom right,
  // the newest at the bottom, three at most (one on a phone). Its kind gives its icon, colour and how long it stays:
  // done 4 seconds, for your information and someone's roll 6, refused 10, an error until closed; one with a button
  // (Undo, Keep going) 20. Hovering a card keeps it. The server says which kind (web.notice: its text alone is "done").
  const CARD = { ok: ['✓', 4000], info: ['i', 6000], roll: ['', 6000], warn: ['!', 10000], error: ['✕', 0], heal: ['+', 0] };
  // (a round's card, app/fft/testing_page.py, sits at the foot of the screen too: its height is kept in --cc-h so the corner
  // cards stack just above it where they share a corner, never over it; Brett's round, Nov 18, issue 28)
  const ccSlot = document.getElementById('check-card');
  if (ccSlot && window.ResizeObserver) new ResizeObserver(() => document.documentElement.style.setProperty('--cc-h', ccSlot.offsetHeight + 'px')).observe(ccSlot);
  function card(content, { kind = 'ok', action, actions, icon, stay } = {}) {
    const box = $('#cards');
    if (!box || !content) return null;
    const [mark, ms] = CARD[kind] || CARD.ok, el = document.createElement('div');
    el.className = 'card k-' + kind;
    el.setAttribute('role', kind === 'warn' || kind === 'error' ? 'alert' : 'status');
    const ic = icon || Object.assign(document.createElement('i'), { className: 'card-ic', textContent: mark });
    const tx = document.createElement('div');
    tx.className = 'card-tx';
    tx.append(content);
    el.append(ic, tx);
    const close = () => { clearTimeout(el._hide); el.classList.add('out'); setTimeout(() => el.remove(), 250); };
    // Its buttons in a row of their own under the text (Brett, 2026-10-29: beside it they squeezed the words); `node`
    // is a ready button that keeps the card open (a roll: the save it asks for, then Saved: end it)
    const acts = actions || (action ? [action] : []);
    const x = Object.assign(document.createElement('button'), { type: 'button', className: 'card-x', textContent: '✕' });
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', close);
    el.append(x);
    if (acts.length) {
      const row = Object.assign(document.createElement('span'), { className: 'card-acts' });
      acts.forEach(a => {
        if (a.node) return row.append(a.node);
        const b = Object.assign(document.createElement('button'), { type: 'button', className: 'card-act', textContent: a.label });
        b.addEventListener('click', () => { close(); a.run(); });
        row.append(b);
      });
      el.append(row);
    }
    // (a card following a change to D&D Beyond stays until it's settled: followChange)
    const wait = stay ? 0 : acts.length ? 20000 : ms, start = () => { if (wait && !el._following) el._hide = setTimeout(close, wait); };
    el._close = close;
    el.addEventListener('mouseenter', () => clearTimeout(el._hide));
    el.addEventListener('mouseleave', start);
    start();
    box.append(el);
    const most = matchMedia('(max-width: 900px)').matches ? 1 : 3;
    while (box.children.length > most) {  // (the oldest goes first; a healing card waiting for an answer last, and it comes back)
      const old = [...box.children].find(c => c !== el && !c.classList.contains('k-heal')) || box.firstElementChild;
      if (old.classList.contains('k-heal') && window.askdndHeals) setTimeout(window.askdndHeals, (wait || 6000) + 400);
      old.remove();
    }
    if (waitingFollow && Date.now() - waitingFollow.at < 1500) followChange(el, waitingFollow.d);  // (its change came first)
    waitingFollow = null;
    lastCard = { el, at: Date.now() };
    return el;
  }
  // ---- following a change (Bridge Review, Nov 3): the card saying a change for D&D Beyond was made stays with it, "On
  // its way", "Trying again (2 of 3)", until D&D Beyond has it (✓ On D&D Beyond), or says it didn't go through, with Try
  // again and Undo. The change is web.deliver_now's `upto`; app/ddb_bridge.py `follow` says how it stands.
  let lastCard = null, waitingFollow = null;
  function followChange(el, d) {
    if (!el || el._following || !d || !d.upto || !d.character) return;
    el._following = true;
    clearTimeout(el._hide);
    el.classList.add('following');
    const ic = el.querySelector('.card-ic'), sub = Object.assign(document.createElement('small'), { className: 'card-sub', textContent: 'On its way to D&D Beyond' });
    el.querySelector('.card-tx').append(sub);
    if (ic) ic.textContent = '↻';
    const settle = (ms) => { el._following = false; el.classList.remove('following'); el._hide = setTimeout(el._close, ms); };
    const told = () => {  // the page shows its new copy, and the extension makes it now
      document.body.dispatchEvent(new CustomEvent('characterChanged', { detail: { character: d.character } }));
      document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: { ddbId: d.ddbId } }));
    };
    const end = Date.now() + 120000;
    const tick = async () => {
      if (!el.isConnected) return;
      let s = null;
      try { const r = await fetch('/bridge/follow/' + d.character + '?upto=' + d.upto, { headers: { Accept: 'application/json' } }); if (r.ok) s = await r.json(); } catch (e) { /* offline: ask again */ }
      if (s && s.state === 'done') {
        el.className = 'card k-ok'; if (ic) ic.textContent = '✓'; sub.textContent = 'On D&D Beyond';
        return settle(4000);
      }
      if (s && s.state === 'failed') {
        el.className = 'card k-warn'; el.setAttribute('role', 'alert'); if (ic) ic.textContent = '!';
        sub.textContent = (s.failed || []).length ? "Didn't go through" + (s.error ? ': ' + s.error : '') : s.says;
        const ids = (s.failed || []).map(f => f.id), postEach = (path, then) => () => Promise.all(ids.map(id => fetch(path + id, { method: 'POST', headers: { Accept: 'application/json' } }))).then(then);
        const row = Object.assign(document.createElement('span'), { className: 'card-acts card-follow-acts' });
        [['Try again', postEach('/bridge/retry/', () => { row.remove(); el.className = 'card k-ok following'; if (ic) ic.textContent = '↻'; sub.textContent = 'Trying again'; el._following = true; clearTimeout(el._hide); told(); setTimeout(tick, 1500); })],
         ['Undo', postEach('/bridge/dismiss/', () => { row.remove(); sub.textContent = 'Undone in askdnd'; told(); settle(4000); })]].forEach(([label, run]) => {
          const b = Object.assign(document.createElement('button'), { type: 'button', className: 'card-act', textContent: label });
          b.addEventListener('click', run);
          row.append(b);
        });
        el.querySelector('.card-follow-acts')?.remove();
        if (ids.length) el.append(row);  // (none: it waits on another sheet's change, whose buttons are in the Live window)
        el._following = false; el.classList.remove('following');  // (stays until closed: it needs you)
        return;
      }
      if (s && s.says !== sub.textContent && sub.textContent !== 'On its way to D&D Beyond') window.postMessage({ askdndBridge: 'deliver', ddbId: String(d.ddbId) }, location.origin);  // (moved on: one that waited for another may go now)
      if (s) sub.textContent = s.says;
      if (Date.now() > end) { sub.textContent = 'Still on its way: the Live pill has it'; return settle(10000); }
      el._tick = setTimeout(tick, 1500);
    };
    setTimeout(tick, 800);
  }
  // A message: its text, or {text, kind} from the server (web.notice); action: {label, run}, a button on the card
  function toast(message, action, kind) {
    // (an Undo the server offers with what it did, web.notice's `undo`: a POST to that address of askdnd's own; Feedback's
    // approvals, for a minute)
    let undoTo = null;
    try { undoTo = message && typeof message === 'object' && typeof message.undo === 'string' ? new URL(message.undo, location.origin) : null; } catch (e) { undoTo = null; }
    if (undoTo && undoTo.origin === location.origin) {  // (a form posted as a page: the server answers with where to go and what it did)
      action = { label: 'Undo', run: () => {
        const f = Object.assign(document.createElement('form'), { method: 'post', action: undoTo.pathname + undoTo.search });
        (document.querySelector('main') || document.body).append(f); f.requestSubmit();  // (in main: it redraws in place too)
      } };
    }
    if (message && typeof message === 'object') { kind = message.kind; message = message.text; }
    if (message) card(document.createTextNode(message), { kind: kind || 'ok', action });
  }
  window.askdndToast = toast;
  window.askdndCard = card;
  // Healing for you (app/heals.py; Brett chose A on Healing and Costs, Nov 14): healing someone gave a character you
  // play waits as a green corner card that stays until you answer, on every askdnd page you have open. Apply heals
  // through the hit points window's own route; Not now hides it until your next page. Gone everywhere once applied or
  // undone (the live connection's "rolls").
  (() => {
    if (!$('#cards') || !document.querySelector('[data-door]')) return;  // (signed in: the menu bar's doors)
    const shown = new Map(), later = new Set();
    const line = (tag, text) => Object.assign(document.createElement(tag), { textContent: text });
    function apply(h) {
      fetch('/characters/' + h.for + '/hp/apply', { method: 'POST', headers: { 'X-Requested-With': 'fetch' },
                                                     body: new URLSearchParams({ mode: 'heal', amount: String(h.amount), type: '', roll: String(h.id) }) })
        .then(r => {
          if (!r.ok) return r.json().catch(() => ({})).then(j => { throw new Error(j.detail || "askdnd couldn't apply it"); });
          const t = r.headers.get('HX-Trigger');  // (what the window's own Apply says: its corner card, the sheet's new copy)
          if (t) { try { Object.entries(JSON.parse(t)).forEach(([k, v]) => document.body.dispatchEvent(new CustomEvent(k, { detail: v }))); } catch (err) { /* nothing more to say */ } }
          shown.delete(h.id);
        })
        .catch(err => { toast(h.name + ': ' + err.message, null, 'warn'); shown.delete(h.id); setTimeout(check, 500); });
    }
    function check() {
      fetch('/heals/waiting', { headers: { 'X-Requested-With': 'fetch' } }).then(r => (r.ok ? r.json() : { heals: [] })).then(j => {
        const ids = new Set(j.heals.map(h => h.id));
        shown.forEach((el, id) => { if (!ids.has(id)) { if (el._close) el._close(); shown.delete(id); } });
        j.heals.forEach(h => {
          if (later.has(h.id) || (shown.get(h.id) && shown.get(h.id).isConnected)) return;
          const text = document.createElement('span');
          text.append(line('b', h.from + ' heals ' + h.name + ' ' + h.amount), document.createElement('br'), line('small', h.label + (h.hp ? ' · ' + h.hp : '')));
          const el = card(text, { kind: 'heal', stay: true, actions: [{ label: 'Apply ' + h.amount, run: () => apply(h) }, { label: 'Not now', run: () => later.add(h.id) }] });
          if (el) { el.dataset.heal = h.id; shown.set(h.id, el); }
        });
      }).catch(() => { /* the next page or roll asks again */ });
    }
    window.askdndHeals = check;
    check();
    document.addEventListener('askdnd:live', e => { if (e.detail.type === 'rolls' || e.detail.type === 'resync') check(); });
  })();
  // A change's corner card: the one just shown, or the next one (web.changed sends the change before its message)
  window.askdndFollow = d => {
    if (lastCard && lastCard.el.isConnected && Date.now() - lastCard.at < 1500) followChange(lastCard.el, d);
    else waitingFollow = { d, at: Date.now() };
  };

  // Server can trigger a toast with the HX-Trigger header: {"toast": "Saved"}
  document.body.addEventListener('toast', e => toast(e.detail && typeof e.detail === 'object' && 'value' in e.detail ? e.detail.value : e.detail));  // (htmx hands a plain message on as {value}; a fetch may hand on the message itself)

  // The switch (_settings.html; the UI review's pick 1, Nov 16): a setting saves itself the moment it's flipped. Its form
  // is posted here with X-Switch; the route answers 204 and a corner card (web.switched), and the switch flips where it
  // is, or 409 and an amber card, and it stays. A two-way switch (data-choice) saves the pressed choice the same way.
  async function saveSwitch(form, values, done) {
    const body = new URLSearchParams();
    new FormData(form).forEach((v, k) => body.append(k, v));
    Object.entries(values).forEach(([k, v]) => { body.delete(k); if (v !== '') body.set(k, v); });
    let r;
    try { r = await fetch(form.action, { method: 'POST', body, headers: { 'X-Switch': '1' } }); } catch (err) { r = null; }
    let events = {};
    try { events = JSON.parse((r && r.headers.get('HX-Trigger')) || '{}'); } catch (err) { /* no message */ }
    if (events.toast) toast(events.toast);
    if (!r || r.status !== 204) { if (!events.toast) toast("Not saved: try again.", null, 'warn'); return; }  // (only 204 is saved: a sign-in page after a redirect isn't)
    if (events.switchReload) { location.reload(); return; }
    done();
  }
  document.addEventListener('submit', e => {
    const form = e.target;
    if (form.matches('form[data-switch]')) {
      e.preventDefault();
      const btn = form.querySelector('.switch');
      if (!btn || btn.disabled || form.dataset.busy) return;
      const next = btn.getAttribute('aria-checked') !== 'true';
      form.dataset.busy = '1';
      saveSwitch(form, { [form.dataset.switch]: next ? '1' : '' }, () => btn.setAttribute('aria-checked', next ? 'true' : 'false'))
        .finally(() => { delete form.dataset.busy; });
    } else if (form.matches('form[data-choice]')) {
      e.preventDefault();
      const pick = e.submitter;
      if (!pick || pick.getAttribute('aria-pressed') === 'true' || form.dataset.busy) return;
      form.dataset.busy = '1';
      saveSwitch(form, { [form.dataset.choice]: pick.value }, () => form.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', b === pick ? 'true' : 'false')))
        .finally(() => { delete form.dataset.busy; });
    }
  });

  // The add fold (_suggest_form.html add_fold; Key Moments Everywhere, Nov 16): "+ Add what the party learned" opens its
  // form in place with the box ready to type; Cancel or Escape closes it and keeps what's typed; a send that went
  // through empties and closes it (addFoldDone, with its corner card). A form the server redraws comes back closed.
  document.addEventListener('toggle', e => {
    const fold = e.target;
    if (fold.matches && fold.matches('details.add-fold') && fold.open) fold.querySelector('textarea')?.focus();
  }, true);
  // A list's column headings that are floating over its rows (sticky, feedback 73) are marked data-stuck, so they
  // stand apart from the rows passing under them; once a frame, after any scroll (the page's or a window's)
  let headsQueued = false;
  const markHeads = () => {
    headsQueued = false;
    document.querySelectorAll('.ls-head').forEach(h => {
      const stuck = h.checkVisibility() && h.getBoundingClientRect().top - h.parentElement.getBoundingClientRect().top > 1;
      if (stuck !== h.hasAttribute('data-stuck')) h.toggleAttribute('data-stuck', stuck);
    });
  };
  document.addEventListener('scroll', () => { if (!headsQueued) { headsQueued = true; requestAnimationFrame(markHeads); } }, { capture: true, passive: true });
  // Steppers (_form_bits.html stepper): − and + change the number within its min and max, as typing it does
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-stepper] .step');
    if (!b) return;
    const box = b.parentElement.querySelector('input[type=number]');
    const min = box.min === '' ? -Infinity : +box.min, max = box.max === '' ? Infinity : +box.max;
    const next = box.value === '' ? (+box.placeholder || (Number.isFinite(min) ? min : 0)) : +box.value + +b.dataset.step;
    box.value = Math.min(max, Math.max(min, next));
    box.dispatchEvent(new Event('input', { bubbles: true }));
    box.dispatchEvent(new Event('change', { bubbles: true }));
  });

  // Dice pickers (_form_bits.html dice_picker): how many, which die and the damage type write the dice box; typing in
  // the box sets the pickers. The box is the form's field, so what's typed is what's saved.
  const DICE_SAID = /^\s*(\d*)d(\d+)\s*([+-]\s*\d+)?\s*([a-z]+)?\s*$/i;
  const dpSync = dp => {
    const box = dp.querySelector('[data-dp="box"]'), m = box.value.match(DICE_SAID), flat = (box.value.match(/^\s*\+?(\d+)\s*$/) || [])[1];
    if (m && m[1]) dp.querySelector('[data-dp="n"]').value = m[1];
    dp.querySelectorAll('[data-dp-die]').forEach(c => c.setAttribute('aria-pressed', String(!!m && c.dataset.dpDie === m[2])));
    dp.querySelectorAll('[data-dp-flat]').forEach(c => c.setAttribute('aria-pressed', String(!m && c.dataset.dpFlat === flat)));
    dp.querySelectorAll('[data-dp-type]').forEach(c => c.setAttribute('aria-pressed', String(!!m && c.dataset.dpType === (m[4] || '').toLowerCase())));
  };
  const dpWrite = (dp, change) => {
    const box = dp.querySelector('[data-dp="box"]'), m = box.value.match(DICE_SAID) || [];
    const cur = { n: dp.querySelector('[data-dp="n"]').value || '1', die: m[2] || '', mod: (m[3] || '').replace(/\s+/g, ''), type: (m[4] || '').toLowerCase(), ...change };
    if (cur.flat) box.value = '+' + cur.flat;
    else if (cur.die) box.value = `${cur.n}d${cur.die}${cur.mod}${cur.type ? ' ' + cur.type : ''}`;
    else return;
    dpSync(dp);
    box.dispatchEvent(new Event('input', { bubbles: true }));
  };
  document.addEventListener('click', e => {
    const c = e.target.closest('[data-dice-picker] [data-dp-die], [data-dice-picker] [data-dp-flat], [data-dice-picker] [data-dp-type]');
    if (!c) return;
    const dp = c.closest('[data-dice-picker]'), m = dp.querySelector('[data-dp="box"]').value.match(DICE_SAID);
    if (c.dataset.dpDie) dpWrite(dp, { die: c.dataset.dpDie });
    else if (c.dataset.dpFlat) dpWrite(dp, { flat: c.dataset.dpFlat });
    else if (m) dpWrite(dp, { type: c.dataset.dpType });  // (a type needs dice first)
  });
  document.addEventListener('input', e => {
    const dp = e.target.closest && e.target.closest('[data-dice-picker]');
    if (!dp) return;
    if (e.target.matches('[data-dp="box"]')) dpSync(dp);
    else if (e.target.matches('[data-dp="n"]')) dpWrite(dp, {});
  });
  document.querySelectorAll('[data-dice-picker]').forEach(dpSync);

  // The item builder (DM Tools › an item, docs/mockups/item-builder/): what it does in play a piece at a time. Each
  // piece's sentence is written from its own fields; Edit opens its questions; + Add shows the next empty one.
  const hbVal = (p, end) => {
    const el = p.querySelector(`[name$="${end}"]:checked`) || p.querySelector(`[name$="${end}"]:not([type=radio])`);
    return !el ? '' : el.type === 'checkbox' ? (el.checked ? el.value : '') : el.value.trim();
  };
  const HB_TO = { attack: 'attack rolls', save: 'saving throws', check: 'ability checks', damage: 'damage' };
  const hbSays = {
    roll: p => {
      const dice = hbVal(p, '_dice'), how = hbVal(p, '_resolve');
      if (!dice) return 'No dice yet';
      if (how === 'save') return `${dice} · ${hbVal(p, '_save') || 'which'} save DC ${hbVal(p, '_dc') || '?'}, ${hbVal(p, '_half') ? 'half' : 'nothing'} on a success`;
      if (how === 'attack') return `${dice} · an attack roll, on a hit`;
      return { heal: `heals ${dice}`, temp: `${dice} Temporary Hit Points` }[hbVal(p, '_effect')] || dice;
    },
    add: p => {
      const raw = hbVal(p, '_amount');
      if (!raw) return 'Nothing added yet';
      const amt = raw.startsWith('+') || raw.startsWith('-') ? raw : '+' + raw, to = HB_TO[hbVal(p, '_to')] || 'attack rolls', says = hbVal(p, '_says');
      const when = { on_hit: `${amt} on a hit`, on_damage: `${amt} to its damage`, after_fail: `${amt} to ${to}, after a failure` }[hbVal(p, '_when')] || `${amt} to ${to}`;
      return when + (hbVal(p, '_this') ? ' with this item' : '') + (says ? ` (${says})` : '');
    },
    charges: p => {
      const n = hbVal(p, 'charges'), back = hbVal(p, 'charges_back'), regain = hbVal(p, 'charges_regain');
      if (!n) return 'How many?';
      return `${n} charge${n === '1' ? '' : 's'}` + (back ? `, back at ${back}${regain ? ` (${regain})` : ''}` : ", they don't come back");
    },
  };
  const hbDraw = p => {
    const kind = p.dataset.hbPiece, form = p.closest('[data-item-builder]'), how = hbVal(p, '_resolve');
    const said = hbSays[kind](p);
    p.querySelector('[data-hb-line]').textContent = said;
    p.querySelector('[data-hb-says]').textContent = said;
    const called = p.querySelector('[data-hb-called]');
    // its own name when it has one; the kind (A roll, A bonus) when it's only the item's own name (Brett's design review)
    const own = called && called.value.trim(), item = form.querySelector('[data-hb-name]').value.trim();
    p.querySelector('[data-hb-title]').textContent = own && own !== item ? own : p.dataset.hbKind;
    p.querySelectorAll('[data-hb-when]').forEach(r => { r.hidden = r.dataset.hbWhen !== how; });
    p.querySelectorAll('[data-hb-to]').forEach(r => { r.hidden = ['on_hit', 'on_damage'].includes(hbVal(p, '_when')); });
    p.querySelectorAll('[data-hb-regain]').forEach(r => { r.hidden = !hbVal(p, 'charges_back'); });
    const open = p.hasAttribute('data-open'), head = p.querySelector('.hb-head [data-hb-toggle]');
    head.textContent = open ? 'Close' : 'Edit';
    head.setAttribute('aria-expanded', String(open));
  };
  const hbRoom = form => form.querySelectorAll('[data-hb-new]').forEach(b => {
    const left = form.querySelectorAll(`[data-hb-piece="${b.dataset.hbNew}"][hidden]`).length;
    b.disabled = !left;
    const note = b.querySelector('[data-hb-room]');
    if (!note.dataset.said) note.dataset.said = note.textContent;
    note.textContent = left ? note.dataset.said : b.dataset.hbNew === 'charges' ? 'It has them already' : 'As many as askdnd keeps';
  });
  document.querySelectorAll('[data-item-builder]').forEach(form => { form.querySelectorAll('[data-hb-piece]').forEach(hbDraw); hbRoom(form); });
  document.addEventListener('click', e => {
    const form = e.target.closest('[data-item-builder]');
    if (!form) return;
    const toggle = e.target.closest('[data-hb-toggle]'), remove = e.target.closest('[data-hb-remove]'), add = e.target.closest('[data-hb-new]');
    if (toggle) { const p = toggle.closest('[data-hb-piece]'); p.toggleAttribute('data-open'); hbDraw(p); if (!p.hasAttribute('data-open')) p.querySelector('.hb-head [data-hb-toggle]').focus(); }
    else if (remove) {
      const p = remove.closest('[data-hb-piece]');
      p.querySelectorAll('input[type=text], input[type=number]').forEach(i => { i.value = ''; });
      p.querySelectorAll('input[type=checkbox]').forEach(i => { i.checked = false; });
      p.querySelectorAll('[data-dice-picker]').forEach(dpSync);
      p.removeAttribute('data-open');
      p.hidden = true;
      hbDraw(p);
      hbRoom(form);
      form.querySelector('[data-hb-add] > summary').focus();
    } else if (add) {
      const p = form.querySelector(`[data-hb-piece="${add.dataset.hbNew}"][hidden]`);
      if (!p) return;
      p.hidden = false;
      p.setAttribute('data-open', '');
      add.closest('details').open = false;
      hbDraw(p);
      hbRoom(form);
      (p.querySelector('[data-dp="box"], input[name="charges"]') || p.querySelector('input')).focus();
    }
  });
  ['input', 'change'].forEach(t => document.addEventListener(t, e => {
    const form = e.target.closest && e.target.closest('[data-item-builder]');
    if (!form) return;
    const p = e.target.closest('[data-hb-piece]');
    if (p) hbDraw(p);
    else if (e.target.matches('[data-hb-name]')) form.querySelectorAll('[data-hb-piece]').forEach(hbDraw);
  }));

  // The round's card (Testing, app/fft/testing_page.py; Brett's 2A, and his 6A, Nov 17): — folds it to a pill and the pill
  // brings it back; its top bar drags it to any corner, where it settles. Both kept in a cookie (testing_page.card_prefs), so the
  // server draws it as it was left on the next page: never open and then folding (note 85).
  const ccPrefs = cc => { document.cookie = 'askdnd-cc=' + (cc.classList.contains('folded') ? 'folded.' : '') + (cc.dataset.corner || 'br') + '; path=/; max-age=31536000; samesite=lax'; };
  const ccFold = cc => {
    const folded = !cc.classList.contains('folded');
    cc.classList.toggle('folded', folded);
    cc.querySelectorAll('.cc-top, .cc-body').forEach(el => { el.hidden = folded; });
    cc.querySelector('.cc-pill').hidden = !folded;
    ccPrefs(cc);
  };
  document.addEventListener('click', e => {
    const f = e.target.closest('[data-check-card] [data-cc-fold]');
    if (f) ccFold(f.closest('[data-check-card]'));
  });
  document.addEventListener('pointerdown', e => {
    const bar = e.target.closest('[data-check-card] [data-cc-drag]');
    if (!bar || e.button !== 0 || e.target.closest('button, a, input')) return;
    const cc = bar.closest('[data-check-card]'), x0 = e.clientX, y0 = e.clientY;
    let moved = false;
    bar.setPointerCapture(e.pointerId);
    const move = ev => {
      const dx = ev.clientX - x0, dy = ev.clientY - y0;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      cc.classList.add('dragging');
      cc.style.transform = 'translate(' + dx + 'px, ' + dy + 'px)';
    };
    const end = ev => {
      bar.removeEventListener('pointermove', move);
      bar.removeEventListener('pointerup', end);
      bar.removeEventListener('pointercancel', end);
      cc.classList.remove('dragging');
      cc.style.transform = '';
      if (!moved || ev.type === 'pointercancel') return;
      const r = cc.getBoundingClientRect();  // (where it sat; plus how far it was dragged: its middle where it was let go)
      const px = r.left + r.width / 2 + (ev.clientX - x0), py = r.top + r.height / 2 + (ev.clientY - y0);
      cc.dataset.corner = (py < innerHeight / 2 ? 't' : 'b') + (px < innerWidth / 2 ? 'l' : 'r');
      ccPrefs(cc);
    };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
  });

  // The round's card keys (Found, Fixed, Tried, screen 2): P passed, F something's wrong, C can't try; never while typing
  // or with a window open, and only while the card is open
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat || !/^[pfc]$/i.test(e.key)) return;
    const a = document.activeElement;
    if (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) || document.querySelector('dialog[open], .peek.open')) return;
    const b = document.querySelector('[data-fft-card]:not(.folded) [data-key="' + e.key.toLowerCase() + '"]');
    if (b) { e.preventDefault(); b.click(); }
  });

  // An action bar's ⋯ (_admin_bits.html more_menu): a choice in it, a click elsewhere or Escape closes it; a choice that
  // opens more of the menu ([data-show]: Deploys' Paused asks why) keeps it open
  document.addEventListener('click', e => {
    document.querySelectorAll('details.act-more[open]').forEach(d => { if (!d.contains(e.target) || e.target.closest('.act-menu button:not([data-show])')) d.open = false; });
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') document.querySelectorAll('details.act-more[open]').forEach(d => { d.open = false; }); });

  // The walkthrough's ticks (Brett's 3A, Nov 17): only to keep your place, kept on this device for the check you're on
  // and cleared once you're on another
  const ticksKept = () => { try { return JSON.parse(sessionStorage.getItem('askdnd-ticks') || '{}'); } catch (e) { return {}; } };
  const ticksShow = root => root.querySelectorAll('[data-ticks]').forEach(list => {
    const kept = ticksKept()[list.dataset.ticks] || [];
    list.querySelectorAll('[data-tick]').forEach(t => { t.checked = kept.includes(+t.dataset.tick); });
  });
  document.addEventListener('change', e => {
    const t = e.target.closest('[data-tick]');
    if (!t) return;
    const list = t.closest('[data-ticks]');
    const on = [...list.querySelectorAll('[data-tick]')].filter(x => x.checked).map(x => +x.dataset.tick);
    try { sessionStorage.setItem('askdnd-ticks', JSON.stringify({ [list.dataset.ticks]: on })); } catch (err) { /* no storage: ticks last the page */ }
    document.querySelectorAll('[data-ticks="' + list.dataset.ticks + '"] [data-tick="' + t.dataset.tick + '"]').forEach(x => { x.checked = t.checked; });
  });
  ticksShow(document);
  document.addEventListener('htmx:afterSettle', e => { if (e.target.querySelector) ticksShow(e.target); });

  // Key moments' Show fewer (feedback 79): folds the rest away again, keeping the list's top in view
  document.addEventListener('click', e => {
    const less = e.target.closest('[data-km-less]');
    const more = less && less.closest('details.km-more');
    if (!more) return;
    more.open = false;
    const list = more.previousElementSibling || more;
    if (list.getBoundingClientRect().top < 0) list.scrollIntoView({ block: 'start' });
    more.querySelector('summary').focus({ preventScroll: true });
  });
  document.addEventListener('click', e => {
    const cancel = e.target.closest('[data-fold-cancel]');
    const fold = cancel && cancel.closest('details.add-fold');
    if (fold) { fold.open = false; fold.querySelector('summary').focus(); }
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const fold = e.target.closest && e.target.closest('details.add-fold[open]');
    if (!fold) return;
    e.preventDefault(); e.stopPropagation();  // (only the fold: a side panel or window around it stays open)
    fold.open = false; fold.querySelector('summary').focus();
  }, true);
  document.addEventListener('addFoldDone', e => {
    const fold = e.target.closest && e.target.closest('details.add-fold');
    if (!fold) return;
    fold.querySelector('form').reset(); fold.open = false;
  });

  document.addEventListener('click', e => {
    // Menus (campaign, Party, Live, Manage, account, phone More). A click elsewhere closes
    // them; clicks inside a [data-keep-open] menu (the Live popover's switch) don't.
    const opener = e.target.closest('[data-menu]');
    document.querySelectorAll('.menu[id]').forEach(m => {  // (only menus a [data-menu] opens: a <details> menu opens on its own)
      if ((!opener || m.id !== opener.dataset.menu) && !(m.hasAttribute('data-keep-open') && m.contains(e.target))) m.hidden = true;
    });
    if (opener) {
      const m = document.getElementById(opener.dataset.menu);
      if (m) { m.hidden = !m.hidden; opener.setAttribute('aria-expanded', m.hidden ? 'false' : 'true'); }
    }
    // Read/edit toggles: data-show="id" reveals #id and hides data-hide targets
    const show = e.target.closest('[data-show]');
    const target = show && document.getElementById(show.dataset.show);  // (only a toggle with something to show: a link stays a link)
    if (target) {
      e.preventDefault();
      (show.dataset.hide || '').split(' ').filter(Boolean).forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
      target.hidden = false;
      const field = target.querySelector('textarea, input[type=text]') || target.querySelector('select');  // (else its picker: then Escape, inside it, is its Cancel)
      if (field) field.focus();
    }
    const cancel = e.target.closest('[data-cancel]');
    if (cancel) {
      e.preventDefault();
      const form = document.getElementById(cancel.dataset.cancel);
      form.hidden = true;
      (cancel.dataset.restore || '').split(' ').filter(Boolean).forEach(id => { const el = document.getElementById(id); if (el) el.hidden = false; });
      const toggle = document.querySelector(`[data-show="${CSS.escape(form.id)}"]`);  // (back to what opened it, for the keyboard)
      if (toggle && (!toggle.checkVisibility || toggle.checkVisibility())) toggle.focus();
    }
  });
  // A folded form (Change…, Rename…, Decline with why…): Escape inside it is its Cancel (Brett's round, Nov 18: only
  // Save closed Change…). Caught first, so it closes the form and not the window or page around it.
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const form = e.target.closest && e.target.closest('form.fb-fold:not([hidden])');
    const cancel = form && form.querySelector('[data-cancel]');
    if (!cancel) return;
    e.preventDefault();
    e.stopPropagation();
    cancel.click();
  }, true);

  // @-mentions: in any textarea (or input[data-mention]), typing "@" and a few
  // letters suggests entity names (incl. aliases and known misspellings);
  // choosing one inserts the canonical name in place of "@letters".
  const mention = { box: null, field: null, start: 0, items: [], active: 0, timer: null, seq: 0 };
  const TRIGGER = /(?:^|[\s(["'\u201c\u2018])@([\p{L}\p{N}'\u2019-][\p{L}\p{N}'\u2019 -]{0,39})$/u;
  const isMentionField = el => el && (el.tagName === 'TEXTAREA' || (el.tagName === 'INPUT' && el.hasAttribute('data-mention')));

  function closeMention() {
    clearTimeout(mention.timer);
    mention.seq++;
    if (mention.box) mention.box.hidden = true;
    if (mention.field) {
      mention.field.setAttribute('aria-expanded', 'false');
      mention.field.removeAttribute('aria-activedescendant');
    }
    mention.items = [];
  }

  function mentionBox() {
    if (!mention.box) {
      const box = document.createElement('div');
      box.className = 'mention-box';
      box.id = 'mention-box';
      box.setAttribute('role', 'listbox');
      box.setAttribute('aria-label', 'Names');
      box.hidden = true;
      box.addEventListener('mousedown', e => {
        const opt = e.target.closest('[role=option]');
        e.preventDefault(); // keep focus in the text box
        if (opt) chooseMention(Number(opt.dataset.i));
      });
      document.body.appendChild(box);
      mention.box = box;
    }
    return mention.box;
  }

  function renderMention() {
    const box = mentionBox();
    box.replaceChildren(...mention.items.map((item, i) => {
      const opt = document.createElement('div');
      opt.className = 'mention-opt';
      opt.id = 'mention-opt-' + i;
      opt.dataset.i = i;
      opt.setAttribute('role', 'option');
      opt.setAttribute('aria-selected', i === mention.active ? 'true' : 'false');
      opt.textContent = item.name;
      const small = document.createElement('small');
      small.textContent = [item.kind, item.via && 'matches \u201c' + item.via + '\u201d'].filter(Boolean).join(' \u00b7 ');
      opt.appendChild(small);
      return opt;
    }));
    const f = mention.field, r = f.getBoundingClientRect();
    box.style.left = (window.scrollX + r.left) + 'px';
    box.style.top = (window.scrollY + r.bottom + 4) + 'px';
    box.style.width = Math.min(Math.max(r.width, 240), 360) + 'px';
    box.hidden = false;
    f.setAttribute('aria-expanded', 'true');
    f.setAttribute('aria-activedescendant', 'mention-opt-' + mention.active);
  }

  function chooseMention(i) {
    const item = mention.items[i], f = mention.field;
    if (!item || !f) return;
    const end = f.selectionStart, after = f.value.slice(end);
    const insert = item.name + (/^[\s.,;:!?)\]'"\u2019]/.test(after) ? '' : ' ');
    f.value = f.value.slice(0, mention.start) + insert + after;
    const caret = mention.start + insert.length;
    f.setSelectionRange(caret, caret);
    closeMention();
    f.focus();
    f.dispatchEvent(new CustomEvent('askdnd:mention', { bubbles: true, detail: { name: item.name } }));  // (Describe it: its picture to go by)
  }

  document.addEventListener('input', e => {
    const f = e.target;
    if (!isMentionField(f)) return;
    const before = f.value.slice(0, f.selectionStart);
    const m = TRIGGER.exec(before);
    if (!m) { if (mention.field === f) closeMention(); return; }
    mention.field = f;
    mention.start = before.length - m[1].length - 1;
    f.setAttribute('aria-autocomplete', 'list');
    f.setAttribute('aria-controls', 'mention-box');
    clearTimeout(mention.timer);
    const seq = ++mention.seq;
    mention.timer = setTimeout(() => {
      fetch('/campaign/mentions?q=' + encodeURIComponent(m[1]), { headers: { Accept: 'application/json' } })
        .then(r => (r.ok ? r.json() : []))
        .then(items => {
          if (seq !== mention.seq) return; // a newer keystroke won
          if (!items.length) { closeMention(); return; }
          mention.items = items;
          mention.active = 0;
          renderMention();
        })
        .catch(closeMention);
    }, 120);
  });

  document.addEventListener('keydown', e => {
    if (!mention.items.length || e.target !== mention.field || mention.box.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = mention.items.length;
      mention.active = (mention.active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
      renderMention();
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      chooseMention(mention.active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeMention();
    }
  }, true);

  document.addEventListener('focusout', e => { if (e.target === mention.field) setTimeout(closeMention, 100); });
  window.addEventListener('resize', closeMention);
  document.body.addEventListener('htmx:beforeSwap', closeMention);

  // Peek panel: clicking a name (a link to an entry, /c/<campaign>/campaign?open=<id>) opens a summary in a
  // right-hand pane on desktop or a bottom sheet on phones. Cmd/Ctrl/Shift-click,
  // links marked data-no-peek and links in the panel's footer open the full page as usual.
  // An entry's address, /c/<campaign>/campaign?open=<id> (2026-10-23; a glossary term's is its Reader's, ?tab=glossary&term=<id>)
  const ENTITY_URL = /^(?:\/c\/[a-z0-9-]+)?\/campaign\?open=(\d+)$/;
  // Two layers: the base panel (a side panel, or a centered modal such as the Spell Book) and a
  // top side panel that slides in from the modal's own right edge, inside it (Brett, 2026-10-21:
  // a spell's details open inside the Spell Book). Each layer keeps its own "← Back" history.
  const layers = {};
  let lastFocus = null;

  function peekPanel(name = 'base') {
    if (layers[name] && layers[name].panel.isConnected) return layers[name];
    const backdrop = document.createElement('div');
    backdrop.className = 'peek-backdrop' + (name === 'top' ? ' top' : '');
    backdrop.hidden = true;
    const panel = document.createElement('aside');
    panel.className = 'peek' + (name === 'top' ? ' top' : '');
    panel.id = name === 'top' ? 'peek-top' : 'peek';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');
    panel.hidden = true;
    const layer = { name, panel, backdrop, history: [], focus: null };
    backdrop.addEventListener('click', () => closeLayer(layer));
    (name === 'top' ? layers.base.panel : document.body).append(backdrop, panel);  // the top layer lives inside the modal
    layers[name] = layer;
    return layer;
  }
  const isOpen = l => l && l.panel.isConnected && !l.panel.hidden && l.panel.classList.contains('open');

  function closeLayer(layer) {
    if (!layer || layer.panel.hidden) return;
    if (layer.name === 'base' && layers.top) closeLayer(layers.top);
    layer.panel.classList.remove('open');
    layer.backdrop.hidden = true;
    layer.history = [];
    setTimeout(() => { if (!layer.panel.classList.contains('open')) layer.panel.hidden = true; }, 180);
    const f = layer.name === 'top' ? layer.focus : lastFocus;
    if (f && f.isConnected) f.focus();
  }
  // Escape and "close" take off the topmost layer first.
  function closePeek() { if (isOpen(layers.top)) closeLayer(layers.top); else closeLayer(layers.base); }

  function openPeek(id, opener) { openPanel('/campaign/' + id + '/peek', opener, opener && opener.getAttribute('href')); }
  // A link to an entry (/campaign/45) lands on /campaign?open=45: show the Campaign page with its panel open
  // (Brett, 2026-10-22: entries live in the side panel; no full page)
  // The Campaign page's Reader already shows the entry it was asked for: then ?open= is that entry's address.
  { const id = /^(\/c\/[^/]+)?\/campaign$/.test(location.pathname) && new URLSearchParams(location.search).get('open');
    const shown = document.getElementById('reader-article');
    if (id && /^\d+$/.test(id) && !(shown && shown.dataset.readerId === id) && !document.getElementById('quest-' + id)) { history.replaceState(null, '', location.pathname + location.hash); openPanel('/campaign/' + id + '/peek', null, null); } }

  // Any element with data-panel-url opens that fragment in a side panel (Battle: "See all", an
  // option's details). data-modal-url opens a centered modal; data-modal-size="large" makes it wide, "full" nearly the whole window
  // (a Wild Shape form, the Spell Book). A side panel opened from inside a modal goes on the top
  // layer. Opening something from inside a panel remembers what was there, so "← Back" returns to it.
  function openPanel(url, opener, fallback, modal, back) {
    const base = layers.base;
    const fromModal = !modal && opener && isOpen(base) && base.panel.classList.contains('modal') && base.panel.contains(opener);
    const fromTop = opener && isOpen(layers.top) && layers.top.panel.contains(opener);
    const layer = back ? back.layer : peekPanel(fromModal || fromTop ? 'top' : 'base');
    const { panel, backdrop } = layer;
    if (layer.name === 'base' && !back && layers.top) closeLayer(layers.top);
    const inside = isOpen(layer) && opener && panel.contains(opener);
    if (back && back.nodes && !back.stale) {  // returning: the window comes back as it was left, what was typed in it too
      panel.replaceChildren(...back.nodes);
      panel.dataset.url = back.url;
      panel.classList.toggle('modal', !!back.modal);
      panel.classList.toggle('large', back.modal === 'large' || back.modal === 'full');
      panel.classList.toggle('full', back.modal === 'full');
      backdrop.classList.toggle('dim', !!back.modal);
      const body = panel.querySelector('.peek-body');
      if (body) body.scrollTop = back.scroll;
      if (back.title) panel.setAttribute('aria-label', back.title);
      panel.focus({ preventScroll: true });
      return;
    }
    if (back) { /* returning to a window that changed something since: drawn again */ }
    else if (inside && panel.dataset.url) {
      const title = panel.querySelector('#peek-title');
      // (its own nodes are kept, not a copy, when something was typed or picked in it: those words, picks and their
      // handlers come back as they were, Brett, Nov 17; any other window is fetched fresh, so Back never shows one that
      // changed meanwhile, by someone else or another page; the review of #417)
      const typed = [...panel.querySelectorAll('input, textarea, select')].some(f => (f.type === 'checkbox' || f.type === 'radio') ? f.checked !== f.defaultChecked
        : f.tagName === 'SELECT' ? [...f.options].some(o => o.selected !== o.defaultSelected) : f.type !== 'hidden' && f.value !== f.defaultValue);
      layer.history.push({ url: panel.dataset.url, modal: panel.classList.contains('full') ? 'full' : panel.classList.contains('large') ? 'large' : panel.classList.contains('modal'), scroll: (panel.querySelector('.peek-body') || {}).scrollTop || 0,
                           title: title ? title.textContent.trim() : '', layer, nodes: typed ? [...panel.childNodes] : null });
    } else layer.history = [];
    if (!inside && !back) { if (layer.name === 'top') layer.focus = opener; else lastFocus = opener; }
    panel.classList.toggle('modal', !!modal);
    panel.classList.toggle('large', modal === 'large' || modal === 'full');
    panel.classList.toggle('full', modal === 'full');  // (nearly the whole window: a mockup to look at)
    backdrop.classList.toggle('dim', !!modal);
    fetch(url, { headers: { 'HX-Request': 'true' } })
      .then(r => (r.ok ? r.text() : Promise.reject(r.status)))
      .then(html => {
        panel.innerHTML = html;
        panel.dataset.url = url;
        const title = panel.querySelector('#peek-title');
        if (title) panel.setAttribute('aria-label', title.textContent.trim());
        addBack(layer);
        panel.hidden = false;
        backdrop.hidden = false;
        void panel.offsetWidth; // let the browser place it off-screen first, then slide in
        panel.classList.add('open');
        panel.scrollTop = 0;
        const body = panel.querySelector('.peek-body');
        if (body) body.scrollTop = back ? back.scroll : 0;
        if (window.htmx) htmx.process(panel);  // forms inside the panel (suggestions, edits)
        panel.tabIndex = -1;
        panel.focus({ preventScroll: true });  // focus the dialog itself, so no focus ring sits on ✕
        panel.dispatchEvent(new CustomEvent('panel:loaded', { bubbles: true }));
      })
      .catch(() => { if (fallback) location.href = fallback; });
  }
  function addBack(layer) {  // "← Back" to what the layer showed before
    const prev = layer.history[layer.history.length - 1], head = layer.panel.querySelector('.peek-head > div');
    if (!prev || !head) return;
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn link peek-back';
    b.textContent = '← Back' + (prev.title ? ' to ' + prev.title : '');
    b.addEventListener('click', () => {
      const p = layer.history.pop();
      openPanel(p.url, null, null, p.modal, p);
    });
    head.prepend(b);
  }
  // A window that changes something (an htmx post inside it) leaves the windows behind it out of date: Back draws them again
  document.addEventListener('htmx:beforeRequest', e => {
    const verb = ((e.detail && e.detail.requestConfig && e.detail.requestConfig.verb) || 'get').toLowerCase();
    if (verb === 'get') return;
    Object.values(layers).forEach(l => { if (l && l.panel.contains(e.target)) l.history.forEach(h => { h.stale = true; }); });
  });
  window.askdndPanel = openPanel;
  // Close the layer holding `el` (Table rolls' Roll window, behind the roll it just opened), without a click: a click
  // elsewhere closes the roll window
  window.askdndClosePanel = el => { const layer = Object.values(layers).find(l => l && l.panel === (el.closest && el.closest('.peek'))); if (layer) closeLayer(layer); };
  // ✕ closes its own layer. Delegated, so it still works after part of a panel is swapped in
  // (Wild Shape's "Kept in a form" boxes re-render the whole window).
  document.addEventListener('click', e => {
    const x = e.target.closest('.peek-close'); if (!x) return;
    const layer = Object.values(layers).find(l => l && l.panel === x.closest('.peek'));  // the innermost (the top layer sits inside a modal)
    if (layer) closeLayer(layer);
  });

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-panel-url], [data-modal-url]');
    if (!t) return;
    // A pop-up, form or button of its own inside the row: the row stays put; a link of its own goes where it says. Only
    // what's inside the row counts: a button that sits in an open <details> list (Apply to… in Table rolls) still opens
    // its window (Brett, Nov 13: picking a name there did nothing). A row in a <summary> is the details' toggle.
    const own = e.target.closest('button[hx-post], form, [data-roll], [data-use-url], details, a[data-no-peek], .ft-init button, .ft-init input');
    if ((own && (own === t || t.contains(own))) || t.closest('summary')) return;
    e.preventDefault();
    if (t.dataset.modalUrl) openPanel(t.dataset.modalUrl, t, t.getAttribute('href'), ['large', 'full'].includes(t.dataset.modalSize) ? t.dataset.modalSize : true);
    else openPanel(t.dataset.panelUrl, t, t.getAttribute('href'));
  });
  document.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('[data-roll], [data-use-url]')) return;
    const t = e.target.closest && e.target.closest('[data-panel-url][tabindex], [data-modal-url][tabindex]');
    if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); t.click(); }
  });

  // Tabs (Character page): buttons with data-tab show #id and hide their siblings' panels.
  function selectTab(b) {
    b.closest('[role=tablist]').querySelectorAll('[role=tab]').forEach(x => {
      x.setAttribute('aria-selected', x === b ? 'true' : 'false');
      const p = document.getElementById(x.dataset.tab); if (p) p.hidden = x !== b;
    });
    const panel = document.getElementById(b.dataset.tab);
    if (panel) panel.dispatchEvent(new CustomEvent('tab:shown', { bubbles: true }));
    return panel;
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('[role=tab][data-tab]');
    if (!b) return;
    const list = b.closest('[role=tablist]'), panel = selectTab(b);
    // If the tabs are stuck at the top (scrolled down), start the new tab from its top.
    const offset = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--stick-top')) || 0;
    if (panel && list.getBoundingClientRect().top <= offset + 1) {
      const top = panel.getBoundingClientRect().top + window.scrollY - offset - list.offsetHeight - 8;
      if (top < window.scrollY) window.scrollTo({top});
    }
  });

  document.addEventListener('click', e => {
    const a = e.target.closest('a');
    if (!a || a.hasAttribute('data-no-peek') || a.closest('.peek-foot') || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    const m = ENTITY_URL.exec(a.getAttribute('href') || a.getAttribute('xlink:href') || '');  // SVG links use xlink:href
    if (!m) return;
    e.preventDefault();
    const ref = m[1];
    // On the Campaign page, a name opens that entry in the Reader (World) instead
    const item = !a.closest('.peek') && document.querySelector('#reader [data-rd-id="' + ref + '"]');
    if (item) {
      const tab = item.closest('[id^="t-"]'), btn = tab && tab.hidden && document.querySelector('[role=tab][data-tab="' + tab.id + '"]');
      if (btn) btn.click();
      item.click();
      return;
    }
    openPeek(ref, a);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !feedbackBusy(e) && !(e.target.closest && e.target.closest('#search-box'))) closePeek(); });

  // Party in a fight: Cards or Rows (party.html), one choice per device
  function ptView() {
    const box = document.querySelector('[data-pt-view-default]');
    if (!box) { document.body.classList.remove('pt-rows'); return; }
    let v = null; try { v = localStorage.getItem('askdnd-party-view'); } catch (err) { /* private window */ }
    v = v || box.dataset.ptViewDefault;
    document.body.classList.toggle('pt-rows', v === 'rows');
    box.querySelectorAll('[data-pt-view]').forEach(b => b.setAttribute('aria-pressed', b.dataset.ptView === v ? 'true' : 'false'));
  }
  ptView();
  document.body.addEventListener('htmx:afterSettle', ptView);
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-pt-view]'); if (!b) return;
    try { localStorage.setItem('askdnd-party-view', b.dataset.ptView); } catch (err) { /* private window */ }
    ptView();
  });

  // Battle's Resources: whole names while they fit on one line, every short name once they don't (Brett, 2026-11-01).
  // Measured with the short names off, each time the row's width changes or a new copy arrives. Phones stack them.
  function fitRes() {
    // Party's cards too (Brett, 2026-11-02): resources by their whole names while every card's fit on one line, else
    // short on every card, decided once for the grid (the UI review, Nov 16: never short on one card, whole beside it).
    // They arrive short (party.html), so a card never grows and then shrinks as the page loads.
    const cards = [...document.querySelectorAll('.pt-res')];
    cards.forEach(r => r.classList.remove('short'));
    const tooLong = cards.some(r => r.offsetHeight > (r.firstElementChild?.offsetHeight || 24) * 1.5);
    if (tooLong) cards.forEach(r => r.classList.add('short'));
    const row = document.querySelector('.battlebar > .res-row:not(.slots)');
    if (!row) return;
    row.classList.remove('short');
    if (matchMedia('(max-width: 640px)').matches) return;
    const line = row.querySelector('.res-insp')?.offsetHeight || 28;
    if (row.offsetHeight > line * 1.5) row.classList.add('short');
  }
  let resWidth = 0;
  const resWatch = window.ResizeObserver && new ResizeObserver(([e]) => {
    if (e.contentRect.width !== resWidth) { resWidth = e.contentRect.width; requestAnimationFrame(fitRes); }
  });
  function watchRes() {
    const bar = document.querySelector('.battlebar, .pt-cards');
    if (bar && resWatch) { resWatch.disconnect(); resWatch.observe(bar); }
    fitRes();
  }
  document.addEventListener('askdnd:swapped', watchRes);  // (a new copy of the page, from a live change)
  watchRes();
  document.fonts?.ready.then(fitRes);
  document.body.addEventListener('htmx:afterSettle', watchRes);
  // On a phone, Battle's longer rows fold to one line that opens (data-fold): Resources, Wild Shape's forms and the spell
  // bar's pinned spells (feedback 29, Nov 7); one choice each per device, for every character (body.fold-<key>)
  const FOLDS = ['res', 'ws', 'sb'];
  const stored = k => { try { return localStorage.getItem('askdnd-fold-' + k) === '1' || (k === 'res' && localStorage.getItem('askdnd-res-open') === '1'); } catch (err) { return false; } };
  FOLDS.forEach(k => document.body.classList.toggle('fold-' + k, stored(k)));
  const marks = () => FOLDS.forEach(k => document.querySelectorAll('[data-fold="' + k + '"]')
    .forEach(x => x.setAttribute('aria-expanded', document.body.classList.contains('fold-' + k) ? 'true' : 'false')));
  marks();
  document.addEventListener('askdnd:swapped', marks);  // (a new copy of the page: its buttons say how they stand)
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-fold]'); if (!b) return;
    const k = b.dataset.fold, open = document.body.classList.toggle('fold-' + k);
    marks();
    try { localStorage.setItem('askdnd-fold-' + k, open ? '1' : '0'); if (k === 'res') localStorage.removeItem('askdnd-res-open'); } catch (err) { /* private window */ }
  });

  // Busy buttons: a normal (non-HTMX) form shows that it's working once submitted —
  // its submit button is disabled, gets a spinner and, if it has data-busy, a new
  // label ("Refreshing…"). This also stops double submits. HTMX requests get the
  // same look from the htmx-request class (see app.css).
  document.addEventListener('submit', e => {
    const form = e.target;
    if (e.defaultPrevented || form.hasAttribute('hx-post') || form.hasAttribute('hx-get') || form.method.toLowerCase() !== 'post') return;
    const btn = e.submitter || form.querySelector('button[type=submit], button:not([type])');
    if (!btn) return;
    if (btn.name) {  // a disabled button isn't submitted, so keep its name/value
      const keep = document.createElement('input');
      keep.type = 'hidden'; keep.name = btn.name; keep.value = btn.value; keep.dataset.kept = '';
      form.appendChild(keep);
    }
    setTimeout(() => {  // after the browser has collected the form data
      btn.dataset.label = btn.textContent;
      if (btn.dataset.busy) btn.textContent = btn.dataset.busy;
      btn.classList.add('busy');
      btn.disabled = true;
      const note = form.dataset.busyNote && document.getElementById(form.dataset.busyNote);
      if (note) note.hidden = false;
    }, 0);
  });
  // One press, one change (the outside review's W1, Nov 10): HTMX queues a second request from the same element while
  // the first is on its way and sends it after, so a double press of Apply took the damage twice. A press (a submit or
  // a click) that would change something is dropped while that element's last one hasn't answered; typing (input,
  // change) still queues, so a preview always ends on what was typed last.
  const inFlight = new WeakSet();
  document.addEventListener('htmx:confirm', e => {
    const d = e.detail, t = d.triggeringEvent && d.triggeringEvent.type;
    if (d.verb === 'get' || (t !== 'submit' && t !== 'click')) return;
    if (inFlight.has(d.elt)) e.preventDefault();
  });
  document.addEventListener('htmx:beforeRequest', e => { if (e.detail.requestConfig && e.detail.requestConfig.verb !== 'get') inFlight.add(e.detail.elt); });
  document.addEventListener('htmx:afterRequest', e => inFlight.delete(e.detail.elt));
  // Coming back with the browser's Back button shows the page as it was left: undo busy states.
  window.addEventListener('pageshow', () => document.querySelectorAll('button.busy').forEach(b => {
    b.classList.remove('busy'); b.disabled = false; if (b.dataset.label) b.textContent = b.dataset.label;
  }));
  // A press redraws in place (the Live UI Audit, Brett, Nov 19: "only what changed redraws, and nothing needs a
  // refresh"; issue 40, the page flashing on the freeze and lanes). A plain form in the page's main or a side panel that changes
  // something is sent in the background; when askdnd answers with this same page (a redirect back here, or a page drawn
  // for the answer), its new copy goes in through swapMain, as a change from elsewhere does: scroll, tabs and what was
  // open stay, the corner card says what happened, the address follows. An answer that is another page loads it as
  // before, its card carried over. Refused: its words in a card, nothing redrawn. Opt out with data-reload on the form
  // (or a box around it) where the change reaches outside main: the menu bar, the page's settings on body.
  function unbusy(form) {
    form.querySelectorAll('input[data-kept]').forEach(i => i.remove());
    form.querySelectorAll('button.busy').forEach(b => { b.classList.remove('busy'); b.disabled = false; if (b.dataset.label) b.textContent = b.dataset.label; });
  }
  window.addEventListener('submit', e => {  // (on window: after every page's own handler has had its say)
    const form = e.target, main = document.querySelector('main');
    const by = e.submitter, method = ((by && by.getAttribute('formmethod')) || form.method).toLowerCase();  // (a button may send it elsewhere: Suggestions' Dismiss)
    if (e.defaultPrevented || !(form instanceof HTMLFormElement) || method !== 'post' || form.hasAttribute('hx-post')) return;
    const target = (by && by.getAttribute('formtarget')) || form.target;
    const panel = form.closest('aside.peek');  // (a side panel's press too, batch 3: it closes as the reload closed it)
    if (!main || !(main.contains(form) || panel) || form.closest('[data-reload]') || (target && target !== '_self')) return;
    const to = new URL((by && by.hasAttribute('formaction') && by.formAction) || form.action, location.href);
    if (to.origin !== location.origin) return;
    e.preventDefault();
    const root = document.documentElement;  // (data-pressing while it's on its way: tests wait for the outcome on it, never an address)
    root.dataset.pressing = String((+root.dataset.pressing || 0) + 1);
    const done = () => { const n = (+root.dataset.pressing || 1) - 1; if (n > 0) root.dataset.pressing = String(n); else delete root.dataset.pressing; };
    fetch(to.href, { method: 'POST', body: new FormData(form), credentials: 'same-origin' })
      .then(r => r.text().then(html => [r, html]))
      .then(([r, html]) => {
        if (!r.ok) {
          unbusy(form);
          let words = '';
          try { words = JSON.parse(html).detail; } catch (err) { /* not askdnd's words */ }
          toast(typeof words === 'string' && words ? words : 'Not done: try again.', null, 'warn');
          return;
        }
        const url = new URL(r.url), page = (r.headers.get('content-type') || '').includes('text/html');
        const doc = page ? new DOMParser().parseFromString(html, 'text/html') : null, said = doc && doc.body.dataset.toast;
        if (!doc || !doc.querySelector('main') || (r.redirected && url.pathname !== location.pathname)) {
          if (said) { try { sessionStorage.setItem('askdnd-card', said); } catch (err) { /* no storage */ } }
          location.assign(r.redirected ? url.href : location.href);
          return;
        }
        const same = !r.redirected || url.search === location.search;  // (another view of this page: its tab is the answer's)
        if (r.redirected) history.replaceState(history.state, '', url.pathname + url.search);
        if (panel) closeLayer(layers.base);  // (done in the panel: it closes, the page under it redraws)
        swapMain(doc, same);
        if (doc.title) document.title = doc.title;
        if (said) { try { toast(JSON.parse(said)); } catch (err) { /* not a message */ } }
        document.dispatchEvent(new CustomEvent('askdnd:changed'));
      })
      .catch(() => { unbusy(form); toast('Not done: askdnd can\'t be reached. Try again.', null, 'warn'); })
      .finally(done);
  });

  // At the table (body.at-table; docs/mockups/table-without-modes.html): every few minutes, while the tab is visible, the
  // page asks the server to keep the party fresh (throttled per character, however many pages ask). askdnd reads the
  // party from D&D Beyond (the character on screen, or your own, first) and the Live pill comes back. Whatever changed
  // reaches the pages showing it through the live connection, like every change (showInPlace below); while that's down,
  // this page asks for its new copy itself.
  function freshen() {
    const pill = document.getElementById('live-pill');
    if (!window.htmx || !pill) return;
    htmx.ajax('POST', '/live/sync' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-pill', swap: 'outerHTML' })
      .then(() => { liveWindowAgain(); document.dispatchEvent(new Event('askdnd:pill')); if (!live.up) showInPlace(); });
  }
  // Someone else's character changed (a read found it): only the pill catches up, reading nothing from D&D Beyond
  // (Sentry ASKDND-V2-7, Nov 6: asking /live/sync here had every open page re-read the party on every change)
  function pillAgain() {
    const pill = document.getElementById('live-pill');
    if (!window.htmx || !pill) return;
    htmx.ajax('GET', '/live/pill' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-pill', swap: 'outerHTML' })
      .then(() => { liveWindowAgain(); document.dispatchEvent(new Event('askdnd:pill')); });
  }
  // The Live window, while it's open, says what the pill says (Bridge Review, Nov 3: an open window said "Not connected"
  // under a pill saying Connected): it's fetched again whenever the pill is
  function liveWindowAgain() {
    const menu = document.getElementById('live-menu'), pill = document.getElementById('live-pill');
    if (!window.htmx || !menu || menu.hidden || !pill) return;
    htmx.ajax('GET', '/live' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-menu', swap: 'innerHTML' });
  }
  // The connection band (_conn_band.html; Brett chose B, Nov 13): under the menu bar while your sheet's connection is
  // worse than it was tonight. It comes and goes with the pill (the server sends it beside the pill; showInPlace copies
  // it). Not now hides it on this computer for 30 minutes, for that state only: worse again (amber to red, another
  // character) is a new key, so it shows at once.
  const LATER = 'askdnd.band.later', LATER_MS = 30 * 60 * 1000;
  function bandApply() {
    const b = document.getElementById('conn-band');
    if (!b) return;
    let later = null;
    try { later = JSON.parse(localStorage.getItem(LATER) || 'null'); } catch (e) { later = null; }
    b.classList.toggle('later', !!(b.dataset.bandKey && later && later.key === b.dataset.bandKey && Date.now() < later.until));
  }
  document.addEventListener('click', e => {
    if (e.target.closest('[data-band-later]')) {
      const b = document.getElementById('conn-band');
      try { localStorage.setItem(LATER, JSON.stringify({ key: b.dataset.bandKey, until: Date.now() + LATER_MS })); } catch (err) { /* private window */ }
      b.classList.add('later');
    } else if (e.target.closest('[data-band-live]')) {
      const pill = document.getElementById('live-pill');
      if (pill) pill.click();
    }
  });
  document.body.addEventListener('htmx:afterSettle', bandApply);  // (an out-of-band swap from the pill's answer)
  bandApply();
  // ?live=1 opens it (the panel beside a D&D Beyond sheet links here: each change's Try again and Undo are in it)
  if (new URLSearchParams(location.search).get('live')) {
    const url = new URL(location.href);
    url.searchParams.delete('live');
    history.replaceState(history.state, '', url);
    addEventListener('load', () => { const pill = document.getElementById('live-pill'); if (pill) pill.click(); });
  }
  if (document.body.classList.contains('at-table')) {
    const pill = document.getElementById('live-pill');
    if (pill) setInterval(() => { if (document.visibilityState === 'visible') freshen(); }, (Number(pill.dataset.every) || 150) * 1000);
  }
  // A button the server refused (403, 409: a sheet that can't be reached…) says why, the same way everywhere: the
  // message askdnd answered with (FastAPI's {"detail": …})
  document.body.addEventListener('htmx:responseError', e => {
    try { const d = JSON.parse(e.detail.xhr.responseText).detail; if (typeof d === 'string' && d) toast(d, null, 'warn'); } catch (err) { /* not a message */ }
  });
  // A page shows a new copy in one way, whatever brought it (the bridge hearing a sheet save, a turn in the fight, Refresh now,
  // a reconnect, your own change): the page and each open side panel fetch themselves again and are swapped in
  // together before the next paint, with the Live pill, keeping the tabs, each list's search and the scroll, so
  // nothing flashes. Someone else's change waits while you're in the middle of something (typing, a side panel, a
  // roll, the tour); your own (`now`) doesn't. Lists set themselves up as they appear; the rest is set up again here
  // (a panel as when it opened: panel:loaded). A button's own answer, such as a pin's or Wild Shape's, still swaps
  // just the box it changed.
  const PARTY = /^(\/c\/[^/]+)?\/(party|table)$/;  // (and askdnd's table: everyone on it)
  let showWait = null, showing = false, again = false, againNow = false;
  function showsAny(ids) {  // ids: character ids as text, or '*' for any
    const page = document.querySelector('main[data-character]');
    const mine = document.querySelector('[data-cond-dots]');  // your character's button in the menu bar shows its conditions
    return PARTY.test(location.pathname) || !!(page && (ids.includes('*') || ids.includes(page.dataset.character)))
      || !!(mine && ids.includes(mine.dataset.character));
  }
  function busyHere() {
    const a = document.activeElement;
    // (on askdnd's table a side panel stays open through a fight, so the map keeps moving beside it)
    const table = /^(\/c\/[^/]+)?\/table$/.test(location.pathname);
    return !!(document.querySelector((table ? '' : '.peek.open, ') + '.roll-win, .tour-card, dialog[open], details.conc-pop[open], details.cond-pill[open], #tmap.dragging') ||
              (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))));
  }
  // A field that saves as you type (a note in a side panel): the box holding it isn't swapped while you're in it
  const typingIn = box => { const a = document.activeElement; return !!(a && box.contains(a) && a.closest('form[hx-trigger*="input"]')); };
  function keepState(box, view = true) {  // what the person had in a box (the page's main, a side panel); returns what puts it back
    // (view false: the new copy is another view of the page, its own tab chosen by askdnd's answer, Feedback's
    // Approve going on to the issue's tab: the tab the person was on doesn't come back)
    const scroller = () => box.matches('main') ? document.scrollingElement : box.querySelector('.peek-body');
    const y = (scroller() || {}).scrollTop || 0;
    const a = document.activeElement, form = a && box.contains(a) && a.name && a.closest('form');
    const field = form && ('form[' + (form.getAttribute('hx-post') ? 'hx-post="' + form.getAttribute('hx-post') : 'action="' + form.getAttribute('action')) + '"] [name="' + a.name + '"]');
    const tabs = view ? [...box.querySelectorAll('[role=tab][data-tab][aria-selected=true]')].map(t => t.dataset.tab) : [];
    const searches = [...box.querySelectorAll('[data-list]')].map(r => [r.dataset.list, (r.querySelector('[data-ls-search]') || {}).value || '']).filter(([, q]) => q);
    // A pop-up you opened (a condition's pill, + Condition, Concentration) stays open in the new copy, if it's still
    // there (Nov 9: your own change landing on D&D Beyond closed the Exhaustion pill you had just opened)
    const POPS = 'details.cond-pill, details.conc-pop', pops = [...box.querySelectorAll(POPS)];
    const opened = pops.filter(d => d.open).map(d => d.classList.contains('cond-add') ? ['add'] : d.dataset.mark ? ['mark', d.dataset.mark] : ['at', pops.indexOf(d)]);
    return () => {
      const now = [...box.querySelectorAll(POPS)];
      opened.forEach(([how, k]) => {
        const d = how === 'add' ? now.find(x => x.classList.contains('cond-add')) : how === 'mark' ? now.find(x => x.dataset.mark === k) : now[k];
        if (d) d.open = true;
      });
      tabs.forEach(id => { const t = box.querySelector('[role=tab][data-tab="' + id + '"]'); if (t) selectTab(t); });
      if (window.htmx) htmx.process(box);
      const sc = scroller(); if (sc) sc.scrollTop = y;
      const back = field && box.querySelector(field); if (back) back.focus({ preventScroll: true });  // where you were
      queueMicrotask(() => searches.forEach(([key, q]) => {  // after the lists have set themselves up
        const input = box.querySelector('[data-list="' + key + '"] [data-ls-search]');
        if (input) { input.value = q; input.dispatchEvent(new Event('input', { bubbles: true })); }
      }));
    };
  }
  // The change mark (Brett, 2026-10-28): a number that changed while the page showed its new copy glows for a moment with
  // the change ("−11"), whatever brought it (D&D Beyond, someone else's screen, your own). Numbers are named on the page
  // ([data-mark]: its first <b>; pips by their place), compared before and after the swap.
  function marksIn(box) {
    const out = new Map();
    box.querySelectorAll('[data-mark]').forEach(el => { const b = el.querySelector('b'); if (b) out.set(el.dataset.mark, b.textContent.trim()); });
    box.querySelectorAll('.pips').forEach((el, i) => out.set('pips#' + i, String(el.querySelectorAll('.pip:not(.used)').length)));
    return out;
  }
  function showMarks(box, before) {
    const num = v => /^[−-]?\d+$/.test(v) ? parseInt(v.replace('−', '-'), 10) : null;
    const one = (el, was, now) => {
      if (was === undefined || was === now) return;
      // (a number going back because askdnd's change didn't go through isn't a gain or a loss: Bridge Review, Nov 3)
      if (el.closest('[data-sync="failed"]')) return;
      el.classList.remove('marked'); void el.offsetWidth; el.classList.add('marked');
      clearTimeout(el._marked); el._marked = setTimeout(() => el.classList.remove('marked'), 2600);
      const a = num(was), b = num(now);
      if (a === null || b === null) return;
      const d = document.createElement('span');
      d.className = 'mark-delta ' + (b > a ? 'up' : 'down');
      d.textContent = (b > a ? '+' : '−') + Math.abs(b - a);
      const value = el.matches('.pips') ? el : el.querySelector('b');
      value.after(d);  // right after the number, so it never covers the label
      setTimeout(() => d.remove(), 2600);
    };
    // (D&D Beyond confirming a change shown already is quiet: its mark just goes; Brett, 2026-10-29)
    box.querySelectorAll('[data-mark]').forEach(el => { const b = el.querySelector('b'); if (b) one(el, before.get(el.dataset.mark), b.textContent.trim()); });
    box.querySelectorAll('.pips').forEach((el, i) => one(el, before.get('pips#' + i), String(el.querySelectorAll('.pip:not(.used)').length)));
  }
  function swapMain(html, view = true) {
    const doc = typeof html === 'string' ? new DOMParser().parseFromString(html, 'text/html') : html, here = document.querySelector('main'), there = doc.querySelector('main');
    if (!here || !there) return;
    const restore = keepState(here, view), before = marksIn(here);
    [...here.attributes].forEach(a => { if (!there.hasAttribute(a.name)) here.removeAttribute(a.name); });
    [...there.attributes].forEach(a => here.setAttribute(a.name, a.value));
    // What's the same in both stays as it is ([data-keep]: askdnd's table map's picture, so it never flashes)
    const keep = new Map([...here.querySelectorAll('[data-keep]')].map(n => [n.dataset.keep, n]));
    here.replaceChildren(...[...there.childNodes].map(n => document.importNode(n, true)));
    here.querySelectorAll('[data-keep]').forEach(n => { const old = keep.get(n.dataset.keep); if (old) n.replaceWith(old); });
    // Parts drawn outside main that follow it ([data-with-main]: askdnd's table's windows), unless one is open
    document.querySelectorAll('[data-with-main]').forEach(n => {
      const now = doc.getElementById(n.id);
      if (now && !n.querySelector('dialog[open]')) n.replaceWith(document.importNode(now, true));
    });
    const pill = document.getElementById('live-pill'), newPill = doc.getElementById('live-pill');
    if (pill && newPill) { pill.className = newPill.className; pill.title = newPill.title; pill.innerHTML = newPill.innerHTML; Object.assign(pill.dataset, newPill.dataset); liveWindowAgain(); }
    const band = document.getElementById('conn-band'), newBand = doc.getElementById('conn-band');  // (the connection band beside it)
    if (band && newBand) { band.replaceWith(document.importNode(newBand, true)); bandApply(); }
    document.dispatchEvent(new Event('askdnd:pill'));
    // Your character's conditions on its menu bar button, outside main
    const dots = doc.querySelectorAll('[data-cond-dots]');
    document.querySelectorAll('[data-cond-dots]').forEach((d, i) => { if (dots[i]) { d.innerHTML = dots[i].innerHTML; if (dots[i].title) d.title = dots[i].title; else d.removeAttribute('title'); } });
    // The fight and its reminders, as the page is drawn now
    const b = document.body;
    ['fight', 'reminders'].forEach(k => { if (doc.body.dataset[k] !== undefined) b.dataset[k] = doc.body.dataset[k]; else delete b.dataset[k]; });
    showReminders();  // (a condition's reminder, as the fight moved on)
    document.dispatchEvent(new CustomEvent('askdnd:fight'));
    restore();
    document.dispatchEvent(new CustomEvent('askdnd:swapped'));
    if (window.askdndNotesInit) window.askdndNotesInit(here);
    sortSetup(); econSetup(); condArrive();
    showMarks(here, before);
  }
  function swapPanel(layer, html) {
    const panel = layer.panel, restore = keepState(panel), before = marksIn(panel);
    const top = layer.name === 'base' && layers.top ? [layers.top.backdrop, layers.top.panel].filter(n => n.parentNode === panel) : [];  // (the top layer lives inside the modal)
    const t = document.createElement('template');
    t.innerHTML = html;
    panel.replaceChildren(...t.content.childNodes, ...top);
    addBack(layer);
    restore();
    showMarks(panel, before);
    panel.dispatchEvent(new CustomEvent('panel:loaded', { bubbles: true }));
  }
  function showInPlace(now) {
    // (one asked for while another is on its way follows it, at once only if one of those asking said so: a change
    // landing from elsewhere never inherits your own change's "at once" and closes what you opened, Nov 9)
    if (showing) { again = true; againNow = againNow || !!now; return; }
    clearTimeout(showWait); showWait = null;
    const later = () => { showWait = setTimeout(() => showInPlace(), 2000); };
    if (!now && (busyHere() || document.visibilityState !== 'visible')) return later();
    showing = true;
    const get = url => fetch(url, { headers: { 'HX-Request': 'true' } }).then(r => r.ok ? r.text() : Promise.reject(r.status));
    const open = ['base', 'top'].map(n => layers[n]).filter(l => isOpen(l) && l.panel.dataset.url);
    const asked = location.pathname + location.search;
    Promise.all([get(asked), ...open.map(l => get(l.panel.dataset.url))])
      .then(([page, ...panels]) => {
        showing = false;
        const queued = again, queuedNow = againNow;
        again = againNow = false;
        // (the page moved on meanwhile, a press answered with another view of it: this copy is of the old one, so
        // it's dropped and the new address asked for; Feedback's Approve, the Live UI Audit, Nov 19)
        if (asked !== location.pathname + location.search) return showInPlace(queuedNow);
        if (!now && busyHere()) return queuedNow ? showInPlace(true) : later();
        const main = document.querySelector('main');
        if (main && !typingIn(main)) swapMain(page);  // (askdnd:swapped measures Resources again)
        open.forEach((l, i) => { if (isOpen(l) && l.panel.dataset.url && !typingIn(l.panel)) swapPanel(l, panels[i]); });
        if (queued) showInPlace(queuedNow);
      })
      .catch(() => { showing = false; });
  }
  // After "Refresh now" or "Refresh everyone"
  document.body.addEventListener('liveRefreshed', e => {
    if (showsAny(((e.detail && e.detail.ids) || []).map(String))) showInPlace(true);
  });
  // ---------------------------------------------------------------- live connection
  // (VTT 0.3, app/realtime.py) One WebSocket per page to its campaign's table. askdnd says what changed ("rolls", or
  // "character" with its id) and the page asks for it the usual way; each message goes out as a document event
  // `askdnd:live` (Table rolls listen for "rolls"). Reconnects on its own with growing waits, then sends "resync":
  // anything may have changed meanwhile. While it's down, polling carries on. Refused (4403): it stops.
  const live = window.askdndLive = { up: false };
  (function connectLive(wait) {
    const c = document.body.dataset.campaign;
    if (!c || !window.WebSocket) return;
    const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/live/connect?c=' + c);
    let ping = null, was = live.seen;
    ws.onopen = () => {
      live.up = live.seen = true; wait = 1;
      ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 25000);  // proxies close quiet connections
      if (was) document.dispatchEvent(new CustomEvent('askdnd:live', { detail: { type: 'resync' } }));  // catch up after a gap
    };
    ws.onmessage = e => { try { document.dispatchEvent(new CustomEvent('askdnd:live', { detail: JSON.parse(e.data) })); } catch (err) { /* not ours */ } };
    ws.onclose = ev => {
      live.up = false; clearInterval(ping);
      // 4403: refused. Otherwise try again, a little later each time and spread out, so a deploy's reconnects don't all land at once
      if (ev.code !== 4403) setTimeout(() => connectLive(Math.min(wait * 2, 30)), wait * (500 + Math.random() * 1000));
    };
  })(1);
  // Someone's character changed (a read of D&D Beyond found something new: the bridge hearing their sheet save, Game
  // Mode, a page opening), or the connection came back ("resync": anything may have changed): a page showing them
  // shows the new copy; the Live pill on any other page catches up. A burst ("Refresh
  // everyone") is taken once.
  let liveTick = null, liveIds = new Set();
  document.addEventListener('askdnd:live', e => {
    const t = e.detail.type;
    if (t === 'game') { showInPlace(); return; }
    if (t === 'fft') {  // (Found, Fixed, Tried changed: Feedback, Testing and Notes you sent show their new copy; a round's card too)
      // (never over something half done: words typed but not sent, a fold opened, a row being dragged; the next change catches up)
      const drafting = [...document.querySelectorAll('main textarea, main input[type=text], main input[type=search]')].some(el => el.value !== el.defaultValue)
        || document.querySelector('main .fb-fold:not([hidden]), main .sortable-chosen, main details.act-more[open]');
      if (document.querySelector('[data-fft-page], [data-fft-yours]') && !drafting) showInPlace();
      const slot = document.getElementById('check-card');
      if (slot && window.htmx && !slot.contains(document.activeElement)) htmx.ajax('GET', '/manage/testing/card?at=' + encodeURIComponent(location.pathname), { target: slot, swap: 'innerHTML' });
      return;
    }
    if (t === 'table') { if (/^(\/c\/[^/]+)?\/table$/.test(location.pathname)) showInPlace(); return; }  // (askdnd's table: a place, a token, a scene)
    if (t === 'deliver') { window.postMessage({ askdndBridge: 'deliver', ddbId: String(e.detail.ddb) }, location.origin); return; }  // (a change another one waited for may go now: ddb_bridge._release)  // the fight moved on: every page, once it isn't in the way of a pop-up
    if (t !== 'character' && t !== 'resync') return;
    liveIds.add(t === 'resync' ? '*' : String(e.detail.id));
    clearTimeout(liveTick);
    liveTick = setTimeout(() => {
      const ids = [...liveIds];
      liveIds = new Set();
      if (showsAny(ids)) showInPlace();
      else pillAgain();
    }, 400);
  });
  // You changed something of a character's (a pin, bookmark, reminder or note: character_pages, player_notes):
  // the page and its open panels show their new copy at once. A form that's done with its window closes it first.
  document.body.addEventListener('closePanel', () => closePeek());
  // A scene of the DM's to read or write in (app/scene_notes.py: a new one opens to write in, a saved one to read)
  document.body.addEventListener('openScene', e => { const url = e.detail && (e.detail.value || e.detail); if (typeof url === 'string') openPanel(url, null, null); });
  // Something on askdnd's table changed (a place, a token, the fight): this page shows its new copy at once
  document.body.addEventListener('tableChanged', () => showInPlace(true));
  document.body.addEventListener('characterChanged', () => showInPlace(true));
  // Pop-ups made of <details> (Concentration, conditions, + Condition): a click anywhere else closes them
  document.addEventListener('click', e => {
    document.querySelectorAll('details.conc-pop[open], details.cond-pill[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; });
    // The badges by the name (Brett, 2026-10-29): one says what its condition does on hover or focus, or a tap on phones
    const badge = e.target.closest('.cond-badge');
    document.querySelectorAll('.cond-badge[aria-expanded="true"]').forEach(x => { if (x !== badge) x.setAttribute('aria-expanded', 'false'); });
    if (badge) badge.setAttribute('aria-expanded', String(badge.getAttribute('aria-expanded') !== 'true'));
  });
  // A condition that starts makes its badge pop in and Battle's edge flash once, however it arrived (its pill, D&D
  // Beyond, someone else's screen); after that nothing moves, so it never pulls your eye mid-turn. Opening the page doesn't.
  const condsWere = {};
  function condArrive() {
    const page = document.querySelector('main[data-character]');
    if (!page) return;
    const badges = [...page.querySelectorAll('.char-head .cond-badge')];
    const now = badges.map(x => x.dataset.name), was = condsWere[page.dataset.character];
    condsWere[page.dataset.character] = now;
    const fresh = was ? now.filter(n => !was.includes(n)) : [];
    if (!fresh.length) return;
    badges.forEach(x => { if (fresh.includes(x.dataset.name)) x.classList.add('new'); });
    const halo = page.querySelector('.cond-halo');
    if (halo) halo.classList.add('starting');
  }
  condArrive();

  // How long a condition lasts (Brett, 2026-10-29; docs/mockups/turn-conditions.html): + Condition's Lasts shows only
  // the fields its choice needs, and they go with the chip picked (hx-include)
  document.addEventListener('change', e => {
    const sel = e.target.closest('[data-lasts]');
    if (!sel) return;
    const kind = sel.value === 'minute' ? 'rounds-fixed' : sel.value;
    sel.closest('[data-lasts-form]').querySelectorAll('[data-lasts-for]').forEach(f => { f.hidden = !f.dataset.lastsFor.split(' ').includes(kind); });
  });
  // Its reminders (app/fight.py follow): a condition that ran out, a save due at the end of a turn (said as it begins), Concentration's time
  // up, each a corner card for that character's player (with what to do) and the DM (to know). They come with the page
  // (body data-reminders, drawn again whenever the fight moves on); each shows once in this browser, and only while
  // it's fresh. Nothing ends by itself: the player ends it, keeps it (the DM ruled it lasts), or rolls the save.
  const SEEN = 'askdnd.reminders', FRESH_MS = 3 * 60 * 1000;
  const DEATH_SAYS = { down: 'warn', massive: 'warn', out: 'warn', stable: 'ok' };
  const seenGet = k => { try { return sessionStorage.getItem(k); } catch (e) { return null; } };
  const seenSet = (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* private window */ } };
  const escText = v => { const d = document.createElement('div'); d.textContent = v == null ? '' : v; return d.innerHTML; };
  function act(url, data) {
    return fetch(url, { method: 'POST', headers: { 'HX-Request': 'true', 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams(data) })
      .then(r => r.ok ? showInPlace(true) : r.json().then(j => toast(j.detail || 'Not done', null, 'warn'), () => toast('Not done', null, 'warn')));
  }
  function showReminders() {
    let list = [];
    try { list = JSON.parse(document.body.dataset.reminders || '[]'); } catch (e) { return; }
    const key = SEEN + ':' + (document.body.dataset.campaign || ''), seen = +(seenGet(key) || 0);
    let top = seen;
    for (const r of list) {
      if (r.id <= seen) continue;
      top = Math.max(top, r.id);
      if (Date.now() - Date.parse(r.at) > FRESH_MS) continue;
      const base = '/characters/' + r.character;
      const t = document.createElement('span');
      const said = DEATH_SAYS[r.kind];  // death saves (app/death_saves.py): what happened, the same for the player and the DM
      if (said) {
        t.innerHTML = '<b>' + escText(r.who) + '</b>: ' + escText(r.text) + '.';
        card(t, { kind: said, stay: said !== 'ok' });
        continue;
      }
      if (r.kind === 'reach') {  // left a creature's reach (app/tokens.py): the same words for the player and the DM
        t.innerHTML = escText(r.text) + '.';
        card(t, { kind: 'info' });
        continue;
      }
      if (!r.mine) {  // the DM: to know
        t.innerHTML = '<b>' + escText(r.who) + '</b>: ' + escText(r.text) + (r.kind === 'save' || r.kind === 'death' ? ' (their roll)' : '');
        card(t, { kind: 'info' });
        continue;
      }
      if (r.kind === 'death') {
        t.innerHTML = '<b>Your turn:</b> ' + escText(r.text) + '.';
        const roll = Object.assign(document.createElement('button'), { type: 'button', className: 'card-act main', textContent: 'Roll your death save' });
        Object.assign(roll.dataset, { roll: 'death', label: 'Death save', rollChar: r.character });
        card(t, { kind: 'warn', stay: true, actions: [{ node: roll }] });
      } else if (r.kind === 'save') {
        t.innerHTML = '<b>Your turn:</b> ' + escText(r.text) + '.';
        const roll = Object.assign(document.createElement('button'), { type: 'button', className: 'card-act main', textContent: 'Roll the save' });
        Object.assign(roll.dataset, { roll: 'save', label: r.ability + ' save (' + r.name + '), DC ' + r.dc, mod: (r.mod || '+0').replace('−', '-'), rollChar: r.character });
        card(t, { kind: 'warn', stay: true, actions: [{ node: roll }, { label: 'Saved: end it', run: () => act(base + '/conditions/end', { name: r.name }) }] });
      } else if (r.kind === 'creature') {  // one of your creatures' turn (app/fight.py creature_turns; Your creatures, slice 3)
        t.innerHTML = '<b>' + escText(r.text) + '.</b>';
        card(t, { kind: 'info', stay: true, actions: [{ label: 'Its Battle', run: () => { location.href = base + '/battle?creature=' + encodeURIComponent(r.creature); } }] });
      } else if (r.kind === 'conc') {
        t.innerHTML = '<b>' + escText(r.text) + '.</b>';
        card(t, { kind: 'warn', stay: true, actions: [{ label: 'End it', run: () => act(base + '/concentration/end', {}) },
                                                      { label: 'Keep', run: () => act(base + '/conditions/keep', { name: 'Concentration' }) }] });
      } else {
        t.innerHTML = '<b>' + escText(r.text) + '.</b>';
        card(t, { kind: 'warn', stay: true, actions: [{ label: 'End it', run: () => act(base + '/conditions/end', { name: r.name }) },
                                                      { label: 'Keep', run: () => act(base + '/conditions/keep', { name: r.name }) }] });
      }
    }
    if (top > seen) seenSet(key, String(top));
  }
  showReminders();
  // Icon buttons say what they do (Brett, 2026-10-22): a label on hover or keyboard focus, or a long press on
  // phones. The text is the button's data-tip, aria-label or title; the native title is held back while
  // the label shows so the two don't stack.
  const TIP_SEL = '.pick:not(.static), .pick.static[title], .peek-close, [data-tip]';
  let tipEl = null, tipFor = null, tipTimer = null;
  const tipText = el => el.dataset.tip || el.getAttribute('aria-label') || el.dataset.title || el.getAttribute('title') || '';
  function tipShow(el) {
    const text = tipText(el); if (!text) return;
    if (el.hasAttribute('title')) { el.dataset.title = el.getAttribute('title'); el.removeAttribute('title'); }
    tipEl = tipEl || Object.assign(document.createElement('div'), { className: 'icon-tip', role: 'tooltip' });
    tipEl.textContent = text; document.body.appendChild(tipEl); tipFor = el;
    const r = el.getBoundingClientRect(), w = tipEl.offsetWidth;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
    tipEl.style.top = (r.top > 40 ? r.top - tipEl.offsetHeight - 6 : r.bottom + 6) + 'px';
  }
  function tipHide() {
    clearTimeout(tipTimer);
    if (tipFor && tipFor.dataset.title) { tipFor.setAttribute('title', tipFor.dataset.title); delete tipFor.dataset.title; }
    if (tipEl) tipEl.remove(); tipFor = null;
  }
  document.addEventListener('mouseover', e => {
    const el = e.target.closest && e.target.closest(TIP_SEL);
    if (el === tipFor) return;
    tipHide(); if (el) tipTimer = setTimeout(() => tipShow(el), 250);
  });
  document.addEventListener('focusin', e => { const el = e.target.closest && e.target.closest(TIP_SEL); tipHide(); if (el && el.matches(':focus-visible')) tipShow(el); });
  document.addEventListener('focusout', tipHide);
  document.addEventListener('touchstart', e => {
    const el = e.target.closest && e.target.closest(TIP_SEL); tipHide();
    if (el) tipTimer = setTimeout(() => tipShow(el), 450);
  }, { passive: true });
  document.addEventListener('touchend', () => { clearTimeout(tipTimer); setTimeout(tipHide, 1200); }, { passive: true });
  document.addEventListener('click', tipHide, true);
  window.addEventListener('scroll', tipHide, true);
  // Long lines in summary cards (Sheet › Wild Shape's "In a form"…) show one line; a click shows the rest (Brett, 2026-10-22)
  document.addEventListener('click', e => {
    const c = e.target.closest('.clamp'); if (!c || e.target.closest('a, button')) return;
    const open = c.classList.toggle('open'); c.setAttribute('aria-expanded', open ? 'true' : 'false'); c.title = open ? 'Show less' : 'Show all';
  });
  // (Battle's See all and + Add panels use the shared list engine below, "Lists": feedback 67, Nov 16)
  // FAQ search: only the answers containing every word typed, opened; sections with none hide (Brett, 2026-10-22)
  const faqBox = document.getElementById('faq-search');
  if (faqBox) faqBox.addEventListener('input', () => {
    const words = faqBox.value.toLowerCase().split(/\s+/).filter(Boolean);
    let any = false;
    document.querySelectorAll('details.faq').forEach(d => {
      const hit = !words.length || words.every(w => d.textContent.toLowerCase().includes(w));
      d.hidden = !hit; d.open = !!words.length && hit; any = any || hit;
    });
    document.querySelectorAll('.help .section').forEach(s => { s.hidden = !!words.length && !s.querySelector('details.faq:not([hidden])'); });
    document.getElementById('faq-none').hidden = any;
  });
  // FAQ: a link to one answer (/help#<id>) opens it
  const openFaq = () => { const d = location.hash.length > 1 && document.getElementById(location.hash.slice(1)); if (d && d.matches('details.faq')) { d.open = true; d.scrollIntoView({ block: 'start' }); } };
  openFaq(); window.addEventListener('hashchange', openFaq);
  // Lists' "Full notes": each row's note in full instead of one line, remembered per list. Plan's tabs re-render
  // their lists after a save, so it's applied again after every swap.
  const notesOf = box => box.closest('[data-list], [data-notes-list]');
  const notesKey = box => 'askdnd:notes-full:' + (notesOf(box).dataset.list || notesOf(box).dataset.notesList);
  const applyNotes = box => notesOf(box).classList.toggle('ls-notes-full', box.checked);
  const initNotes = root => root.querySelectorAll('[data-ls-notes]').forEach(box => {
    try { box.checked = localStorage.getItem(notesKey(box)) === '1'; } catch (_) { /* storage blocked */ }
    applyNotes(box);
  });
  document.addEventListener('change', e => {
    const box = e.target.closest && e.target.closest('[data-ls-notes]'); if (!box) return;
    applyNotes(box);
    try { localStorage.setItem(notesKey(box), box.checked ? '1' : '0'); } catch (_) { /* storage blocked */ }
  });
  initNotes(document);
  window.askdndNotesInit = initNotes;
  document.body.addEventListener('htmx:afterSwap', e => initNotes(e.detail.target));
  document.addEventListener('panel:loaded', e => initNotes(e.target));
  // Notes editor (Brett, 2026-10-22: most players won't know Markdown). The textarea[data-rich] stays the
  // form field; an editable area with formatting buttons takes its place on screen and writes Markdown back
  // into it on every change (Turndown), so a note nobody edits is saved exactly as it was. Without Turndown
  // the plain textarea stays.
  document.addEventListener('panel:loaded', e => e.target.querySelectorAll('textarea[data-rich]').forEach(richNotes));
  function richNotes(ta) {
    if (!window.TurndownService || ta._rich) return;
    ta._rich = true;
    const td = new TurndownService({ headingStyle: 'atx', bulletListMarker: '-', emDelimiter: '*', strongDelimiter: '**' });
    td.addRule('listItem', {  // "- item", not Turndown's "-   item"
      filter: 'li',
      replacement(content, node, options) {
        content = content.replace(/^\n+/, '').replace(/\n+$/, '\n').replace(/\n/gm, '\n  ');
        const list = node.parentNode;
        const prefix = list.nodeName === 'OL' ? (Number(list.getAttribute('start') || 1) + [...list.children].indexOf(node)) + '. ' : options.bulletListMarker + ' ';
        return prefix + content + (node.nextSibling && !/\n$/.test(content) ? '\n' : '');
      },
    });
    const area = document.createElement('div');
    area.className = 'rich-area';
    area.contentEditable = 'true';
    area.setAttribute('role', 'textbox'); area.setAttribute('aria-multiline', 'true'); area.setAttribute('aria-label', 'Note');
    area.dataset.placeholder = 'Write anything.';
    const src = ta.parentElement.querySelector('template.rich-src');
    area.innerHTML = src ? src.innerHTML.trim() : '';
    const bar = document.createElement('div');
    bar.className = 'rich-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', 'Formatting');
    const blockOf = () => {
      for (let n = getSelection().anchorNode; n && n !== area; n = n.parentNode) if (n.nodeType === 1 && /^(H\d|P|LI|DIV)$/.test(n.tagName)) return n.tagName;
      return '';
    };
    const sync = () => { ta.value = td.turndown(area.innerHTML).trim(); };
    const state = () => bar.querySelectorAll('button').forEach(b => {
      let on = false;
      try { on = b.dataset.cmd === 'heading' ? /^H\d$/.test(blockOf()) : document.queryCommandState(b.dataset.cmd); } catch (_) { /* not supported */ }
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    [['B', 'bold', 'Bold (Ctrl/⌘+B)'], ['I', 'italic', 'Italic (Ctrl/⌘+I)'], ['Heading', 'heading', 'Heading'],
     ['• List', 'insertUnorderedList', 'Bulleted list'], ['1. List', 'insertOrderedList', 'Numbered list']].forEach(([label, cmd, title]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = label; b.title = title; b.dataset.cmd = cmd;
      b.style.fontWeight = cmd === 'bold' ? '700' : ''; b.style.fontStyle = cmd === 'italic' ? 'italic' : '';
      b.addEventListener('mousedown', ev => ev.preventDefault());  // keep the selection in the note
      b.addEventListener('click', () => {
        area.focus();
        if (cmd === 'heading') document.execCommand('formatBlock', false, /^H\d$/.test(blockOf()) ? 'p' : 'h3');
        else document.execCommand(cmd);
        sync(); state();
      });
      bar.appendChild(b);
    });
    area.addEventListener('focus', () => document.execCommand('defaultParagraphSeparator', false, 'p'));
    area.addEventListener('input', sync);
    area.addEventListener('keyup', state);
    area.addEventListener('mouseup', state);
    area.addEventListener('paste', ev => {  // paste as plain text: no fonts or colors from other sites
      ev.preventDefault();
      document.execCommand('insertText', false, ev.clipboardData.getData('text/plain'));
    });
    ta.hidden = true;
    ta.after(bar, area);
  }
  // A swap that re-renders a whole panel or window (Wild Shape's "Kept in a form" boxes) keeps its scroll position
  document.body.addEventListener('htmx:beforeSwap', e => {
    const t = e.detail.target, body = t && t.matches && t.matches('.peek') && t.querySelector('.peek-body');
    if (body) t._keepScroll = body.scrollTop;
  });
  document.body.addEventListener('htmx:afterSwap', e => {
    const t = e.detail.target;
    if (t && t._keepScroll !== undefined) { const body = t.querySelector('.peek-body'); if (body) body.scrollTop = t._keepScroll; delete t._keepScroll; }
  });
  document.body.addEventListener('htmx:afterSettle', e => {
    const ids = [e.target.id, e.detail.target && e.detail.target.id];
    if (ids.includes('battle-body')) { sortSetup(); econSetup(); condArrive(); }
  });

  // Phones (Battle): Action / Bonus / Reaction as tabs over the three columns. The choice is
  // kept while the page swaps in a new body.
  let econShown = 'action';
  function econSetup() {
    const econ = document.querySelector('.econ[data-econ-show]');
    if (!econ) return;
    econ.dataset.econShow = econShown;
    document.querySelectorAll('[data-econ]').forEach(b => b.setAttribute('aria-selected', b.dataset.econ === econShown ? 'true' : 'false'));
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-econ]');
    if (!b) return;
    econShown = b.dataset.econ;
    econSetup();
  });

  // Drag and drop to reorder a Battle column (the character's own player only).
  function sortSetup() {
    if (!window.Sortable) return;
    document.querySelectorAll('[data-sort-column]').forEach(list => {
      if (list._sortable) return;
      // (only the list's own rows: a list inside a row, Where it stands' areas inside its items, keeps its own order; a
      // list may name its handle, data-sort-handle, so dragging an inner row never drags the outer one)
      const rows = () => [...list.children].filter(el => el.matches(list.dataset.sortItem || '.move'));
      list._sortable = Sortable.create(list, {
        draggable: list.dataset.sortItem || '.move', animation: 150, delay: 180, delayOnTouchOnly: true, ghostClass: 'drag-ghost',
        ...(list.dataset.sortHandle ? { handle: list.dataset.sortHandle } : {}),
        onEnd: () => {
          const body = new URLSearchParams({ column: list.dataset.sortColumn });
          rows().forEach(m => { const k = m.dataset.key || (m.querySelector('[data-key]') || m).dataset.key; if (k) body.append('keys', k); });
          rows().forEach((m, i) => { const n = m.querySelector('[data-sort-n]'); if (n) n.textContent = i + (+list.dataset.sortFrom || 1); });  // (numbered rows: Where it stands' items)
          fetch(list.dataset.sortUrl, { method: 'POST', body }).then(r => { if (!r.ok) toast("Couldn't save the order", null, 'error'); });
        },
      });
    });
  }
  window.addEventListener('load', sortSetup);

  // Star and Remind me buttons sit inside <summary>: don't open/close the row when pressed.
  document.addEventListener('click', e => { if (e.target.closest('summary .pick')) e.preventDefault(); }, true);


  // Repeating rows in forms (a combo's turns, a level plan's levels): [data-repeat] holds
  // the rows, a <template> for a new one, and add/remove buttons.
  document.addEventListener('click', e => {
    const add = e.target.closest('[data-repeat-add]'), rm = e.target.closest('[data-repeat-remove]');
    if (add) {
      const box = add.closest('[data-repeat]'), tpl = box.querySelector(':scope > template');
      const row = tpl.content.firstElementChild.cloneNode(true);
      box.insertBefore(row, tpl);
      const first = row.querySelector('input, textarea'); if (first) first.focus();
    } else if (rm) {
      const box = rm.closest('[data-repeat]'), rows = box.querySelectorAll(':scope > .repeat-row');
      const row = rm.closest('.repeat-row');
      if (rows.length > 1) row.remove(); else row.querySelectorAll('input, textarea').forEach(i => { i.value = ''; });
    }
  });

  // Rule terms: side-panel descriptions underline terms like "Unarmed Strike" (dotted, quiet).
  // Hover shows a short definition; a click or tap (or Enter) pins it; Escape or a click
  // elsewhere closes it. Definitions load once, on first use. Admins can turn a term's
  // underline on or off for every description from the pop-up.
  let termData = null, termTip = null, termFor = null, termPinned = false, termTimer = null;
  function termsLoad() {
    if (!termData) termData = fetch('/rules/terms.json', {credentials: 'same-origin'}).then(r => r.ok ? r.json() : {terms: {}});
    return termData;
  }
  function termPlace() {
    if (!termTip || !termFor) return;
    const r = termFor.getBoundingClientRect(), w = Math.min(340, window.innerWidth - 16);
    termTip.style.width = w + 'px';
    termTip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
    const h = termTip.offsetHeight, below = r.bottom + 6;
    termTip.style.top = (below + h > window.innerHeight - 8 && r.top - h - 6 > 8 ? r.top - h - 6 : below) + 'px';
  }
  function termHide() {
    clearTimeout(termTimer);
    if (termTip) termTip.remove();
    if (termFor) termFor.classList.remove('open');
    termTip = termFor = null; termPinned = false;
  }
  async function termShow(el, pin) {
    const data = await termsLoad(), t = data.terms && data.terms[el.dataset.term];
    if (!t || !el.isConnected) return;
    if (termFor !== el) {
      termHide();
      termTip = document.createElement('div');
      termTip.className = 'term-tip'; termTip.setAttribute('role', 'dialog'); termTip.setAttribute('aria-label', t.name);
      const add = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls; n.textContent = text; termTip.appendChild(n); return n; };
      add('div', 'term-kind', t.kind);
      add('div', 'term-name', t.name);
      add('p', 'term-text', t.text);
      add('div', 'term-where', t.where + '. The DM makes the call at the table.');
      if (data.admin) {
        const row = add('div', 'term-admin', 'Admin · underline everywhere: ');
        [['on', 'Yes'], ['off', 'No']].forEach(([v, label]) => {
          const b = document.createElement('button');
          b.type = 'button'; b.className = 'ov-opt' + ((data.on || []).includes(el.dataset.term) === (v === 'on') ? ' on' : '');
          b.textContent = label; b.dataset.value = v;
          row.appendChild(b);
        });
      }
      termTip.dataset.slug = el.dataset.term;
      document.body.appendChild(termTip);
      termFor = el; el.classList.add('open');
    }
    if (pin) termPinned = true;
    termPlace();
  }
  document.addEventListener('mouseover', e => {
    const el = e.target.closest && e.target.closest('.term');
    if (el && !termPinned) { clearTimeout(termTimer); termTimer = setTimeout(() => termShow(el, false), 650); }
    else if (e.target.closest && e.target.closest('.term-tip')) clearTimeout(termTimer);
  });
  document.addEventListener('mouseout', e => {
    const from = e.target.closest && e.target.closest('.term, .term-tip'), to = e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.term, .term-tip');
    if (from && !to && !termPinned) { clearTimeout(termTimer); termTimer = setTimeout(termHide, 200); }
  });
  document.addEventListener('click', e => {
    const el = e.target.closest('.term');
    if (el) { e.preventDefault(); if (termFor === el && termPinned) termHide(); else termShow(el, true); return; }
    const b = e.target.closest('.term-tip .term-admin button');
    if (b) {
      const slug = termTip.dataset.slug, body = new URLSearchParams({value: b.dataset.value});
      fetch('/rules/terms/' + slug + '/underline', {method: 'POST', body, credentials: 'same-origin'}).then(r => r.json()).then(res => {
        if (!('on' in res)) return toast(res.error || 'Not saved', null, 'error');
        termsLoad().then(d => { d.on = (d.on || []).filter(x => x !== slug); if (res.on) d.on.push(slug); });
        termTip.querySelectorAll('.term-admin button').forEach(x => x.classList.toggle('on', (x.dataset.value === 'on') === res.on));
        toast(res.on ? 'Underlined in every description' : 'No longer underlined');
      });
      return;
    }
    if (termTip && !e.target.closest('.term-tip') && !feedbackBusy(e)) termHide();
  });
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('.term');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
    else if (e.key === 'Escape' && termTip) { e.stopImmediatePropagation(); const f = termFor; termHide(); if (f) f.focus(); }
  }, true);
  document.addEventListener('scroll', () => { if (termPinned) termPlace(); else if (termTip) termHide(); }, true);
  window.addEventListener('resize', termPlace);

  // A select with data-autosave saves as you pick (Backstage › Table)
  document.addEventListener('change', e => { if (e.target.matches('select[data-autosave]')) e.target.form.requestSubmit(); });
  // A file picker with data-autosubmit sends its form as soon as a file is chosen (entity pictures).
  document.addEventListener('change', e => { if (e.target.matches('input[type=file][data-autosubmit]') && e.target.files.length) e.target.form.requestSubmit(); });

  // Sticky headings sit below the top bar.
  function stickTop() {
    const bar = $('.topbar'), tabs = $('.sheet .tabbar');
    // (exact heights, not rounded: a list's headings under the tabs left a sliver of its rows showing; feedback 73)
    document.documentElement.style.setProperty('--stick-top', (bar ? bar.getBoundingClientRect().height : 0) + 'px');
    if (tabs) document.documentElement.style.setProperty('--tabs-h', tabs.getBoundingClientRect().height + 'px');
  }
  stickTop();
  window.addEventListener('resize', stickTop);
  // The top bar can change height after the first measure (web fonts arriving, the Live pill updating), which
  // left Battle's sticky header in the wrong place until a refresh (Brett, 2026-10-22): measure again then.
  if (window.ResizeObserver) { const ro = new ResizeObserver(stickTop); ['.topbar', '.sheet .tabbar'].forEach(q => { const el = $(q); if (el) ro.observe(el); }); }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(stickTop);
  window.addEventListener('load', stickTop);

  // A link like /campaign#glossary opens that tab (only on arrival; tabs don't change the address).
  if (location.hash) {
    const t = document.querySelector('[role=tab][data-tab="t-' + CSS.escape(location.hash.slice(1)) + '"]');
    if (t) t.click();
  }

  // Flash message from a full page load
  if (document.body.dataset.toast) { try { toast(JSON.parse(document.body.dataset.toast)); } catch (e) { /* not a message */ } }
  try { const said = sessionStorage.getItem('askdnd-said'); if (said) { sessionStorage.removeItem('askdnd-said'); toast(said); } } catch (e) { /* no storage */ }
  try { const carried = sessionStorage.getItem('askdnd-card'); if (carried) { sessionStorage.removeItem('askdnd-card'); if (!document.body.dataset.toast) toast(JSON.parse(carried)); } } catch (e) { /* no storage, or not a message */ }
})();


// Rolls. Anything with data-roll opens the roll window next to it: data-roll is the kind (save,
// check, attack, death, damage, heal, dice), data-label names it, data-mod is the bonus, data-dmg
// the dice, data-adv="1" when Advantage always applies, data-adv-why the reasons, data-note a line
// to show. The window offers Normal / Adv / Dis, who sees it and situational bonuses, then turns
// into the result in place (with a short d20 tumble), with the follow-ups: damage after an attack,
// a reroll, an added die. Shift-click rolls straight away.
// - Your own character (or plain dice): the server rolls (app/table_rolls.py)
//   and the table sees it in the Table rolls sidebar; others' rolls arrive by polling, and as
//   small notices while the sidebar is collapsed.
// - Otherwise: a private roll in this browser only (crypto random).
(function () {
  const toast = (...a) => window.askdndToast(...a);  // (the corner cards live in the block above)
  const SIDE = 'askdnd.rollsSide', ANIM = 'askdnd.rollsAnim', TO = 'askdnd.rollsTo';
  const WIDE = 1241;  // narrower than this, the sidebar starts closed and opens over the page (1240: the menu bar keeps its room
  // beside an open sidebar from 1241 up, Nov 13; app.css and base.html's first script say the same)
  const D20 = ['save', 'check', 'attack', 'death'];
  const phone = matchMedia('(max-width: 900px)'), calm = matchMedia('(prefers-reduced-motion: reduce)');
  const side = document.getElementById('table-rolls'), log = document.getElementById('roll-log');
  const store = {
    get: (k, s) => { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set: (k, v, s) => { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* private window */ } },
  };
  const people = side && side.querySelector('.rs-people'), edge = document.querySelector('.rs-edge');
  let tipEl = null;
  let to = store.get(TO) || 'table';  // who sees your rolls: the table, until you pick otherwise on this device
  let lastId = 0, loaded = false, win = null;

  const num = s => parseInt(String(s || '0').replace('−', '-'), 10) || 0;
  const signed = n => (n >= 0 ? '+' : '−') + Math.abs(n);
  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  // ---------------------------------------------------------------- Show the Math
  // (Brett chose A, B, D and E, Nov 12; docs/mockups/show-the-math/): a number with dots under it (`.math-n`) opens its
  // parts, each with where it came from, on hover, keyboard focus or a tap. The parts ride on the number's own button
  // (`data-math`: app/roll_math.py's rows, put there by _math.html `math_num` or mathNum here), so its text is the number
  // alone; one pop shows them over everything (fixed, so a window's or panel's edge never cuts it), beside the number.
  const MATH_SRC = { sheet: 'Sheet', rules: '2024 rules', dm: 'Your DM', form: 'The form', block: 'Stat block', ddb: "D&D Beyond's data", read: 'Its words', added: 'Added' };
  function mathBox(m) {  // m: {rows, total, why?, note?, label} as app/roll_math.py makes them
    const n = (r, i) => typeof r.n === 'string' ? r.n : i ? signed(r.n) : String(r.n).replace('-', '−');
    return m.rows.map((r, i) => '<span class="m-row"><span class="m-n">' + esc(n(r, i)) + '</span><span class="m-what">' + esc(r.what)
      + '</span>' + (MATH_SRC[r.src] ? '<span class="src s-' + r.src + '">' + MATH_SRC[r.src] + '</span>' : '<span></span>') + '</span>').join('')
      + '<span class="m-sum"><span>' + esc(m.label || '') + '</span><b>' + esc(String(m.total)) + '</b></span>'
      + (m.why ? '<span class="m-note">' + esc(m.why) + '</span>' : '') + (m.note ? '<span class="m-note">' + esc(m.note) + '</span>' : '');
  }
  function mathNum(text, m, label) {  // a number that opens its parts (carried on it, so its text is the number alone)
    if (!m || !(m.rows || []).length) return esc(String(text));
    const data = JSON.stringify({ ...m, label }).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    return '<button type="button" class="math-n" aria-expanded="false" title="How it adds up" data-math="' + data + '">' + esc(String(text)) + '</button>';
  }
  let mathPop = null, mathFor = null, mathTimer = null;
  function mathShow(el) {
    let m; try { m = JSON.parse(el.dataset.math || 'null'); } catch (err) { m = null; }
    if (!m || !(m.rows || []).length) return;
    mathHide();
    mathPop = Object.assign(document.createElement('div'), { className: 'math-pop', role: 'tooltip', id: 'math-pop', innerHTML: mathBox(m) });
    document.body.appendChild(mathPop); mathFor = el;
    el.setAttribute('aria-expanded', 'true'); el.setAttribute('aria-describedby', 'math-pop');
    const r = el.getBoundingClientRect(), w = mathPop.offsetWidth, h = mathPop.offsetHeight;
    mathPop.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
    mathPop.style.top = (r.bottom + h + 8 < window.innerHeight || r.top < h + 8 ? Math.min(r.bottom + 6, window.innerHeight - h - 8) : r.top - h - 6) + 'px';
  }
  function mathHide() {
    clearTimeout(mathTimer);
    if (mathFor) { mathFor.setAttribute('aria-expanded', 'false'); mathFor.removeAttribute('aria-describedby'); }
    if (mathPop) mathPop.remove();
    mathPop = null; mathFor = null;
  }
  document.addEventListener('mouseover', e => {
    const el = e.target.closest && e.target.closest('.math-n');
    if (el === mathFor || (mathPop && mathPop.contains(e.target))) return;
    clearTimeout(mathTimer);
    if (el) mathTimer = setTimeout(() => mathShow(el), 200);
    else if (mathFor && !mathFor.matches(':focus')) mathTimer = setTimeout(mathHide, 150);
  });
  document.addEventListener('click', e => {
    const el = e.target.closest && e.target.closest('.math-n');
    if (!el) { if (mathPop && !mathPop.contains(e.target)) mathHide(); return; }
    e.preventDefault(); e.stopPropagation();  // (a number's parts, never the roll or the row under it)
    if (mathFor === el) mathHide(); else mathShow(el);
  }, true);
  document.addEventListener('focusin', e => { const el = e.target.closest && e.target.closest('.math-n'); if (el && el.matches(':focus-visible')) mathShow(el); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && mathPop) { e.stopPropagation(); mathHide(); } }, true);
  window.addEventListener('scroll', e => { if (mathPop && !mathPop.contains(e.target)) mathHide(); }, true);
  const atTable = () => document.body.classList.contains('at-table');
  // The animation switch: on or off as chosen on this device; until then, off only if the device asks for less motion
  const animate = () => { const v = store.get(ANIM); return v ? v === 'on' : !calm.matches; };
  // Whether a roll of yours reaches D&D Beyond's Game Log, for the roll window; "" where it never would (the Live pill's
  // data-log: your sheet is connected, closed, or your character isn't in a D&D Beyond game)
  // Said loudly (amber, with the button) when a roll that would have reached it won't: your sheet isn't open on this
  // computer (Brett, Nov 13, docs/mockups/connection-drops/: a player's rolls stopped reaching the DM and nothing told them)
  function logNote() {
    const d = (document.getElementById('live-pill') || { dataset: {} }).dataset, state = d.log;
    const wont = "The DM won't see this roll in D&D Beyond's Game Log: ";
    if (state && document.body.classList.contains('no-bridge')) return phone.matches ? "Not in D&D Beyond's Game Log: that needs Chrome on a computer." : { warn: wont + "the askdnd bridge isn't in this browser." };
    // (past `data-log-until` the sheet hasn't been heard: a closed tab whose word never came, or a pill not redrawn yet)
    if (state === 'on' && Date.now() / 1000 < Number(d.logUntil)) return "Also goes to D&D Beyond's Game Log.";
    if (state === 'on' || state === 'sheet') return phone.matches ? "Not in D&D Beyond's Game Log: that needs Chrome on a computer." : { warn: wont + "your sheet isn't open.", sheet: d.sheet };
    return '';
  }
  // The roll card's line for it: plain, or amber with Open your sheet
  function logLine() {
    const n = logNote();
    if (!n) return '';
    if (typeof n === 'string') return '<p class="rw-note" data-log-note>' + n + '</p>';
    return '<p class="rw-note rw-log-warn" data-log-note><b aria-hidden="true">!</b><span>' + n.warn
      + (n.sheet ? ' <a href="' + n.sheet + '" target="_blank" rel="noopener">Open your sheet ↗</a>' : '') + '</span></p>';
  }  // An open card's line follows the connection as it changes (Brett, Nov 13: the warning shouldn't wait for the card to
  // open again): the pill was drawn again (its own answer, or a page's new copy), or this browser's bridge answered
  const logAgain = () => document.querySelectorAll('[data-log-note]').forEach(n => {
    const now = logLine();
    if (!now) n.remove(); else if (n.outerHTML !== now) n.outerHTML = now;
  });
  document.addEventListener('askdnd:pill', logAgain);
  document.body.addEventListener('htmx:afterSettle', e => { if (e.detail.target && ['live-pill', 'conn-band'].includes(e.detail.target.id)) logAgain(); });

  const KIND_WORDS = { attack: ' to hit', damage: ' damage', heal: ' healing' };  // (the thrown dice's tag)

  // ---------------------------------------------------------------- dice (private rolls; the server rolls table rolls the same way)
  function die(sides) {
    const a = new Uint32Array(1);
    crypto.getRandomValues(a);
    return (a[0] % sides) + 1;
  }
  function parseFormula(expr) {
    let s = String(expr || '').replace(/\s/g, '').replace(/−/g, '-').toLowerCase();
    if (!s) return null;
    if (!'+-'.includes(s[0])) s = '+' + s;
    const re = /([+-])(?:(\d{1,2})d(\d{1,3})|(\d{1,3}))/g;
    const terms = []; let flat = 0, pos = 0, m;
    while ((m = re.exec(s))) {
      if (m.index !== pos) return null;
      pos = re.lastIndex;
      if (m[2]) { if (m[1] === '-' || +m[2] < 1 || +m[2] > 20 || +m[3] < 2 || +m[3] > 100) return null; terms.push([+m[2], +m[3]]); }
      else flat += (m[1] === '-' ? -1 : 1) * +m[4];
    }
    if (pos !== s.length || (!terms.length && flat < 1) || terms.reduce((a, t) => a + t[0], 0) > 40) return null;  // (a plain "3": an Unarmed Strike's damage)
    return { terms, flat };
  }
  const formulaText = (terms, flat) => !terms.length ? String(flat) : terms.map(t => t[0] + 'd' + t[1]).join('+') + (flat ? signed(flat).replace('−', '-') : '');
  function keptOf(dice, mode) { return mode === 'adv' ? Math.max(...dice) : mode === 'dis' ? Math.min(...dice) : dice[0]; }
  function part(p) { return { extras: [], crit: false, ...p, kept_at: p.kept != null && p.dice.length > 1 ? p.dice.indexOf(p.kept) : -1 }; }
  function rollD20(mod, mode) {
    const dice = mode === 'normal' ? [die(20)] : [die(20), die(20)], kept = keptOf(dice, mode);
    return part({ dice, kept, modifier: mod, mode, formula: 'd20' + signed(mod), total: kept + mod });
  }
  function rollFormula(expr, crit, floor) {
    const f = parseFormula(expr);
    if (!f) return null;
    const terms = crit ? f.terms.map(t => [t[0] * 2, t[1]]) : f.terms;
    const dice = terms.flatMap(t => Array.from({ length: t[0] }, () => die(t[1])));
    const total = dice.reduce((a, b) => a + b, 0) + f.flat;
    return part({ dice, kept: null, modifier: f.flat, mode: 'normal', formula: formulaText(terms, f.flat), total: floor ? Math.max(total, 0) : total, crit: !!crit });
  }
  function rollExtras(list, crit) {
    return list.map(x => {
      const m = /^(.+):([+-])(?:(\d+)d(\d+)|(\d+))$/.exec(x);
      if (!m) return null;
      const sign = m[2] === '-' ? -1 : 1;
      if (!m[3]) return { label: m[1], formula: signed(sign * +m[5]), dice: [], total: sign * +m[5] };
      const n = crit ? +m[3] * 2 : +m[3], dice = Array.from({ length: n }, () => die(+m[4]));
      return { label: m[1], formula: m[2] + n + 'd' + m[4], dice, total: sign * dice.reduce((a, b) => a + b, 0) };
    }).filter(Boolean);
  }
  const sum = xs => xs.reduce((a, x) => a + x.total, 0);
  const ascii = n => (n >= 0 ? '+' : '-') + Math.abs(n);
  const title = s => s.charAt(0).toUpperCase() + s.slice(1);

  // A part of a roll as its plan gives it (app/roll_plan.py): "2d6+3 fire", or a fixed "4 spellcasting modifier"
  const PART = /^(?:(\d+)d(\d+)([+-]\d+)?|([+-]?\d+))(?:\s+(.+))?$/;
  function parsePart(p) {
    const m = PART.exec(String(p || '').trim());
    if (!m) return null;
    return m[4] != null ? { n: 0, s: 0, flat: +m[4], kind: m[5] || '' } : { n: +m[1], s: +m[2], flat: +(m[3] || 0), kind: m[5] || '' };
  }

  // Each part, once per instance (3 darts), each on its own line; a critical instance doubles its dice.
  // `once` (a house rule): the first instance's dice count for every instance.
  function rollParts(parts, crits, each, floor, once) {
    const lines = [], first = [];
    crits.forEach((crit, i) => parts.forEach((pt, j) => {
      const p = parsePart(pt), k = crit ? p.n * 2 : p.n;
      const dice = once && i ? first[j].slice() : Array.from({ length: k }, () => die(p.s));
      if (!i) first[j] = dice;
      lines.push({ label: crits.length > 1 && each ? title(each) + ' ' + (i + 1) : '', kind: p.kind, crit,
                   formula: k ? k + 'd' + p.s + (p.flat ? ascii(p.flat) : '') : String(p.flat), dice, total: dice.reduce((a, b) => a + b, 0) + p.flat });
    }));
    const total = sum(lines);
    return part({ dice: lines.flatMap(x => x.dice), kept: null, modifier: 0, mode: 'normal', formula: parts.join(' + '), total: floor ? Math.max(total, 0) : total, parts: lines });
  }
  // A private roll, in the same shape the server sends for table rolls
  function privateRoll(spec) {
    let main;
    if (D20.includes(spec.kind)) {
      const rays = [];
      for (let i = 0; i < (spec.kind === 'attack' ? spec.count || 1 : 1); i++) {  // several rays: an attack roll each
        const r = rollD20(spec.kind === 'death' ? 0 : num(spec.mod), spec.mode);
        r.extras = rollExtras(spec.extras);
        r.total += sum(r.extras);
        rays.push({ ...r, label: title(spec.each || 'attack') + ' ' + (i + 1) });
      }
      main = { ...rays[0], parts: rays.length > 1 ? rays : [] };
    } else {
      main = spec.parts && spec.parts.length ? rollParts(spec.parts, Array(spec.count || 1).fill(false), spec.each, spec.kind !== 'dice', spec.once)
                                               : rollFormula(spec.dmg, false, spec.kind !== 'dice');
      if (!main) return null;
      main.extras = rollExtras(spec.extras);
      main.total += sum(main.extras);
      if (spec.kind !== 'dice') main.total = Math.max(main.total, 0);
    }
    const e = { id: 0, label: spec.label, kind: spec.kind, to: 'private', main, rerolled: null, bonus: null, damage: null,
                dmg: spec.kind === 'attack' ? spec.dmg : '', spec: spec.kind === 'attack' && spec.dmgParts ? { parts: spec.dmgParts, each: spec.each } : null };
    return settle(e, spec.ctx || {});
  }
  function settle(e, ctx) {
    const eff = e.main;
    e.nat = D20.includes(e.kind) && (eff.kept === 20 || eff.kept === 1) ? eff.kept : null;
    e.total = eff.total + (e.bonus ? e.bonus.total : 0);
    e.outcome = e.kind === 'death' ? deathOutcome(e.total, e.nat) : '';
    const d20 = D20.includes(e.kind);
    const rays = (eff.parts || []).filter(x => x.kept != null);
    const dmgLabel = e.spec ? e.spec.parts.join(' + ') + (rays.length > 1 ? ', per ' + (e.spec.each || 'hit') : '') : e.dmg;
    e.can = {
      damage: e.kind === 'attack' && dmgLabel && !e.damage && (e.nat !== 1 || rays.length) ? dmgLabel : '',
      reroll: e.rerolled || e.damage || !d20 || rays.length ? '' : ctx.halfling && eff.kept === 1 ? 'Luck' : ctx.inspiration ? 'Heroic Inspiration' : '',
      bonus: d20 && !e.bonus && !e.damage,
    };
    return e;
  }
  function privateFollow(e, action, opts) {
    if (action === 'damage') {
      const rays = (e.main.parts || []).filter(x => x.kept != null && x.kept !== 1);
      let d;
      if (rays.length && e.spec) {  // a damage roll for each ray that isn't a 1, doubled where it was a 20
        d = rollParts(e.spec.parts, rays.map(r => r.kept === 20), e.spec.each, true);
        d.parts.forEach((ln, i) => { ln.label = rays[Math.floor(i / e.spec.parts.length)].label; });
        d.extras = rays.flatMap(r => rollExtras(opts.extras || [], r.kept === 20).map(x => ({ ...x, label: r.label + ' · ' + x.label })));
        d.crit = rays.some(r => r.kept === 20);
      } else {
        const crit = e.nat === 20, as = opts.asType, retype = p => p.replace(/\s+(acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder)$/i, '') + ' ' + as;
        const once = () => (e.spec || as ? rollParts((e.spec ? e.spec.parts : [e.dmg]).map(p => as ? retype(p) : p), [crit], '', true) : rollFormula(e.dmg, crit, true));
        d = once();
        if (!d) return e;
        if (opts.twice) {  // (Savage Attacker: rolled twice, the higher kept, as the server does)
          const d2 = once();
          if (d2) { const [hi, lo] = d2.total > d.total ? [d2, d] : [d, d2]; d = hi; d.twice = { dice: lo.dice, total: lo.total }; }
        }
        d.extras = rollExtras(opts.extras || [], crit);
        d.crit = crit;
      }
      d.total = Math.max(d.total + sum(d.extras), 0);
      e.damage = d;
    } else if (action === 'reroll') {
      const old = e.main, dice = old.dice.slice();
      dice[dice.indexOf(old.kept)] = die(20);
      const kept = keptOf(dice, old.mode);
      e.rerolled = { ...old, reason: opts.reason };
      e.main = part({ ...old, dice, kept, total: kept + old.modifier + sum(old.extras) });
    } else if (action === 'bonus') {
      if ((opts.extras || []).length) {  // dice a feature adds after the roll (Favored by the Gods' 2d4: the roll card)
        const got = rollExtras(opts.extras);
        e.bonus = { label: opts.label || (opts.extras[0].split(':')[0]), formula: got.map(x => x.formula).join(' ').replace(/^\+/, ''), dice: got.flatMap(x => x.dice || []), total: sum(got) };
      } else {
        const n = die(opts.die);
        e.bonus = { label: opts.label || 'Added die', formula: '1d' + opts.die, dice: [n], total: n };
      }
    }
    return settle(e, opts.ctx || {});
  }
  function deathOutcome(total, nat) {
    return nat === 20 ? 'natural 20: you regain 1 Hit Point' : nat === 1 ? 'natural 1: two failures' : total >= 10 ? 'success' : 'failure';
  }

  // ---------------------------------------------------------------- showing a result
  // One part or instance: "Dart 2 · force 1d4+1: 3 = 4", or a ray's attack roll
  function pline(x) {
    if (x.kept != null) return esc(x.label) + ': d20 ' + x.dice.map((d, i) => (i === x.kept_at ? '<u>' + d + '</u>' : d)).join(' / ') + ' ' + signed(x.modifier) + ' = <b>' + x.total + '</b>';
    if (!x.dice.length) return (x.label ? esc(x.label) + ' · ' : '') + esc(x.kind || 'bonus') + ' ' + signed(x.total);
    return (x.label ? esc(x.label) + ' · ' : '') + (x.kind ? esc(x.kind) + ' ' : '') + esc(x.formula) + ': ' + x.dice.join(' ') + (x.crit ? ' (critical)' : '') + ' = <b>' + x.total + '</b>';
  }
  function dline(p, d20) {
    if (p.parts && p.parts.length > 1) {
      let s = p.parts.map(pline).join('<br>');
      (p.extras || []).forEach(x => { s += '<br>' + esc(x.label) + ' ' + signed(x.total); });
      return s;
    }
    if (!d20 && !p.dice.length && !(p.extras || []).length) return 'flat, no dice to roll';  // (an Unarmed Strike's 3: feedback 25)
    let s = d20 ? 'd20 ' + p.dice.map((d, i) => (i === p.kept_at ? '<u>' + d + '</u>' : d)).join(' / ') + ' ' + signed(p.modifier) + (p.mode === 'adv' ? ' · Adv' : p.mode === 'dis' ? ' · Dis' : '')
                : esc(p.formula) + ': ' + p.dice.join(' ') + (p.modifier ? ' ' + signed(p.modifier) : '');
    (p.extras || []).forEach(x => { s += ' · ' + esc(x.label) + ' ' + signed(x.total) + (x.dice.length ? ' <span class="roll-x">(' + esc(x.formula.replace('-', '\u2212')) + ')</span>' : ''); });
    return s;
  }
  // ---------------------------------------------------------------- Any dice's picker
  // (Table rolls' Roll › Any dice): click a die to add one ("−" then a die subtracts it), plus a flat bonus.
  const DIE_SIDES = [4, 6, 8, 10, 12, 20, 100];
  function pickerHTML(opts) {
    return '<div class="dice-pick"><div class="dp-dice">' + DIE_SIDES.map(d => '<button type="button" class="dp-die" data-add-die="' + d + '">d' + d + '</button>').join('')
      + (opts.minus ? '<button type="button" class="dp-die dp-minus" data-dp-minus aria-pressed="false" title="Subtract the next die">−</button>' : '') + '</div>'
      + '<output class="dp-formula" aria-live="polite"></output>'
      + '<div class="dp-row"><label class="dp-bonus">Bonus <input type="text" inputmode="numeric" class="dp-mod" placeholder="±0" value="' + (opts.bonus || '') + '"></label>'
      + '<button type="button" class="btn small link" data-dp-clear>Clear</button>' + (opts.extra || '') + '</div></div>';
  }
  function wirePicker(root, onChange) {
    const counts = {};  // "+6" / "-4" -> how many
    const out = root.querySelector('.dp-formula'), modIn = root.querySelector('.dp-mod'), minus = root.querySelector('[data-dp-minus]');
    const flat = () => Math.max(-99, Math.min(99, num(modIn.value)));
    const terms = () => Object.keys(counts).filter(k => counts[k]).sort((a, b) => (a[0] === b[0] ? b.slice(1) - a.slice(1) : a[0] === '+' ? -1 : 1))
      .map(k => ({ sign: k[0], n: counts[k], sides: +k.slice(1) }));
    function text() {
      let t = terms().map((x, i) => (x.sign === '-' ? (i ? ' − ' : '−') : i ? ' + ' : '') + x.n + 'd' + x.sides).join('');
      const f = flat();
      if (f) t += (t ? (f > 0 ? ' + ' : ' − ') : (f > 0 ? '+' : '−')) + Math.abs(f);
      return t;
    }
    function show() {
      const t = text();
      out.textContent = t || 'Click dice to add them';
      out.classList.toggle('empty', !t);
      if (onChange) onChange();
    }
    root.addEventListener('click', e => {
      const d = e.target.closest('[data-add-die]');
      if (d) {
        const k = (minus && minus.getAttribute('aria-pressed') === 'true' ? '-' : '+') + d.dataset.addDie;
        counts[k] = Math.min((counts[k] || 0) + 1, 10);
        if (minus) minus.setAttribute('aria-pressed', 'false');
        show();
      }
      if (e.target.closest('[data-dp-minus]')) minus.setAttribute('aria-pressed', minus.getAttribute('aria-pressed') !== 'true');
      if (e.target.closest('[data-dp-clear]')) { Object.keys(counts).forEach(k => delete counts[k]); modIn.value = ''; show(); }
    });
    modIn.addEventListener('input', show);
    show();
    return {
      dice: () => terms().filter(x => x.sign === '+').length > 0,
      formula: () => terms().filter(x => x.sign === '+').map(x => x.n + 'd' + x.sides).join('+') + (flat() ? ascii(flat()) : ''),
      extras: bonusName => terms().map(x => 'Added:' + x.sign + x.n + 'd' + x.sides).concat(flat() ? [(bonusName || 'Bonus') + ':' + ascii(flat())] : []),
      modIn,
    };
  }
  function ctxFor(cid) {
    const el = cid && document.querySelector('[data-roll-char="' + cid + '"], [data-character="' + cid + '"][data-roll-ctx]');
    try { return el ? { ...JSON.parse(el.dataset.rollCtx), ...(el.dataset.spends != null ? { spends: el.dataset.spends } : {}) } : {}; } catch (e) { return {}; }
  }
  function characterOf(el) {
    const holder = el.closest('[data-roll-char]') || el.closest('[data-character]');
    if (holder) return holder.dataset.rollChar || holder.dataset.character;
    const panel = el.closest('.peek');
    const m = panel && /^\/characters\/(\d+)/.exec(panel.dataset.url || '');
    return m ? m[1] : '';
  }
  function seg(name, opts, value) {
    return '<span class="roll-modes" role="group" aria-label="' + name + '">' + opts.map(([v, t]) =>
      '<button type="button" data-' + name.toLowerCase().replace(/\W+/g, '-') + '="' + v + '" aria-pressed="' + (v === value) + '">' + t + '</button>').join('') + '</span>';
  }
  function closeWin() { if (win) { win.remove(); win = null; } }
  // ---------------------------------------------------------------- where a window opens (docs/DESIGN.md › Windows)
  // One rule for every window opened from a button: the roll card, Cast, Use, a rest (Brett, Nov 10: the window's place
  // is "one of the most annoying UI elements for a player when it's wrong"). On a laptop, beside the button's row, to
  // its right, else its left, level with the row; with no room either side, under the button, else over it. Always
  // wholly on screen, 8px in. It's placed once, as it opens, from where its button was then; after that it moves only
  // with its button when the page scrolls, and as far as it must to stay on screen as it grows or shrinks: it never
  // jumps between steps. A window opened from inside another (a Cast window's roll) takes that one's place. On a phone,
  // from the bottom, within thumb reach. tests/browser/test_every_roll.py checks it for every roll button.
  // (a button in a window that has closed is still on the page but drawn nowhere: it measures 0, 0, the screen's corner)
  const drawn = el => !!(el && el.isConnected && el.getClientRects().length);
  const rowOf = el => el.closest('.move, li, tr, .row, .rc, .save-row, .st, .tile') || el;
  function measure(w, anchor) {
    w._anchor = anchor;
    if (!drawn(anchor)) return;
    w._btn = anchor.getBoundingClientRect();
    w._row = rowOf(anchor).getBoundingClientRect();
    w._seen = w._btn;
    w._want = null;
  }
  function place(w) {
    if (!w || !w.isConnected) return;
    const m = 8, pw = w.offsetWidth, ph = Math.max(w.offsetHeight, w._reserve || 0), vw = innerWidth, vh = innerHeight;
    if (phone.matches) { w.style.left = m + 'px'; w.style.top = Math.max(m, vh - w.offsetHeight - m) + 'px'; return; }  // (on a phone it sits on the bottom edge)
    if (!w._want) {
      const r = w._row, b = w._btn;
      if (!r) w._want = { left: (vw - pw) / 2, top: Math.max(m, (vh - ph) / 3) };
      else if (r.right + 12 + pw <= vw - m) w._want = { left: r.right + 12, top: r.top - 8 };
      else if (r.left - 12 - pw >= m) w._want = { left: r.left - 12 - pw, top: r.top - 8 };
      else w._want = { left: b.left, top: b.bottom + 6 + ph <= vh - m ? b.bottom + 6 : b.top - 6 - ph };
    }
    const left = Math.max(m, Math.min(w._want.left, vw - pw - m)), top = Math.max(m, Math.min(w._want.top, vh - ph - m));
    w._want = { left, top };  // (where it is now: a step that's shorter leaves it there, never back down)
    w.style.left = left + 'px';
    w.style.top = top + 'px';
  }
  function openWin(anchor) {
    const prev = win && anchor && win.contains(anchor) ? win : null;  // (opened from inside a window: it takes that one's place)
    const keep = prev && { want: prev._want, anchor: prev._anchor, seen: prev._seen, btn: prev._btn, row: prev._row };
    closeWin();
    win = document.createElement('div');
    win.className = 'roll-win';
    win.setAttribute('role', 'dialog');
    win.setAttribute('aria-label', 'Roll');
    document.body.appendChild(win);
    if (keep) { win._want = keep.want; win._anchor = keep.anchor; win._seen = keep.seen; win._btn = keep.btn; win._row = keep.row; }
    else measure(win, anchor);
    return win;
  }
  addEventListener('resize', () => { if (win) { if (drawn(win._anchor)) measure(win, win._anchor); else win._want = null; place(win); } });
  // (the page scrolled: the window moves with its button; nothing else moves it. A button in a panel or a large window,
  // which scrolls or closes on its own, leaves the window where it opened)
  document.addEventListener('scroll', e => {
    if (!win || win.contains(e.target) || !win._want || !win._seen || !drawn(win._anchor)) return;
    if (win._anchor.closest('#peek, dialog, .modal, [role=dialog]') || !(e.target === document || e.target.contains(win._anchor))) return;
    const now = win._anchor.getBoundingClientRect();
    win._want = { left: win._want.left + now.left - win._seen.left, top: win._want.top + now.top - win._seen.top };
    win._seen = now;
    place(win);
  }, true);

  // ---------------------------------------------------------------- Table rolls' Roll
  // (Brett chose A, Nov 10: docs/mockups/roll-kinds/, his note 58) A window (app/table_rolls.checks) with your
  // character's rolls by ability, as the sheet groups them, then Initiative, a Death save, a Hit Point Die and Any dice.
  // Typing narrows it ("ste" for Stealth, "dex" for everything Dexterity) and Enter rolls the first match; each row is an
  // ordinary roll button, so it opens the roll window (or card) where it was, and the window closes behind it.
  function rbFilter(board, text) {
    const t = text.trim().toLowerCase();
    let first = null;
    board.querySelectorAll('.rc-group').forEach(g => {
      let any = false;
      g.querySelectorAll('.rc').forEach(b => {
        const hit = !t || (b.dataset.find || '').split(' ').some(w => w.startsWith(t)) || (b.dataset.find || '').includes(t);
        b.hidden = !hit; b.classList.remove('first');
        if (hit) { any = true; if (!first) first = b; }
      });
      g.hidden = !any;
    });
    if (first && t) first.classList.add('first');
    const none = board.querySelector('.rb-none');
    if (none) none.hidden = !!first || !t;
    return first;
  }
  const rbClose = el => {  // (then Enter rolls it, as before: the focus goes to the roll window's own button, not back to Roll)
    if (window.askdndClosePanel) window.askdndClosePanel(el);
    const go = document.querySelector('.roll-win [data-go], .roll-card [data-roll-hit]');
    if (go) go.focus({ preventScroll: true });
  };
  document.addEventListener('panel:loaded', e => {
    const board = e.target.querySelector && e.target.querySelector('.roll-board');
    if (!board) return;
    board.querySelectorAll('[data-manual]').forEach(wireManual);
    const q = board.querySelector('.rb-q');
    if (q) q.focus({ preventScroll: true });
  });
  document.addEventListener('input', e => { if (e.target.matches('.rb-q')) rbFilter(e.target.closest('.roll-board'), e.target.value); });
  document.addEventListener('keydown', e => {
    if (!e.target.matches || !e.target.matches('.rb-q')) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (window.askdndClosePanel) window.askdndClosePanel(e.target); return; }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const f = rbFilter(e.target.closest('.roll-board'), e.target.value);
    if (f) f.click();
  });
  document.addEventListener('click', e => {  // a roll chosen: the roll window opens from the same click first, then this window closes
    const b = e.target.closest('.roll-board .rc, .roll-board [data-manual-roll]');
    if (b && !b.disabled) setTimeout(() => rbClose(b));
  });

  // A roll button pressed (anywhere: Battle, Sheet, the Spell Book, Cast's roll, Search, Table rolls' Roll): the roll
  // card plays the plan the button carries (app/roll_plan.py `button`; Any dice's from its box). Shift rolls at once.
  function planOf(el) {
    const src = el.dataset.plan ? el : el.closest('[data-plan]');
    try { return src ? JSON.parse(src.dataset.plan) : null; } catch (err) { return null; }
  }
  function openRoll(el, spec, shift) {
    const plan = planOf(el);
    if (!plan) return toast("That button has no roll plan, so it can't roll. Tell Claude with \\.", null, 'warn');  // (every roll button has one: tests/browser/test_every_roll.py)
    card(el, { ...spec, shift: !!shift }, plan);
  }

  // ---------------------------------------------------------------- Search, like Spotlight
  // (app/search.py; Brett chose A and A, Nov 9: docs/mockups/search/) The menu bar's Search, ⌘F or Ctrl+F (taking over the
  // browser's find; pressed again with the box open, the browser's own find is let through) or ⌘K opens one box over
  // everything this person can find (/search/index, once a page): results as you type, grouped, the best highlighted.
  // Enter does it (rolls through openRoll, Cast and Use through openUse, a page or an entry opens, a rule's words show);
  // ⌘ Enter opens where it lives (its side panel).
  const searchBox = document.getElementById('search-box');
  if (searchBox) {
    const q = document.getElementById('search-q'), list = document.getElementById('search-list'), read = document.getElementById('search-read');
    const GROUPS = ['Your character', 'Checks, saves, skills', 'Rules', 'The story', 'Pages'];
    let index = null, shown = [], at = 0, findFree = 0;
    const mac = [navigator.userAgentData?.platform, navigator.platform, navigator.userAgent].some(x => /Mac|iPhone|iPad/i.test(x || ''));
    const findKey = mac ? '⌘F' : 'Ctrl+F';
    // (once a page, again after the character changes; a failed answer isn't kept: the next keypress asks again)
    const load = () => index || (index = fetch('/search/index', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => { index = null; return { rows: [], failed: true }; }));
    document.addEventListener('askdnd:live', e => { if (['character', 'resync'].includes(e.detail.type)) index = null; });
    document.body.addEventListener('characterChanged', () => { index = null; });
    // Loaded in the background once the page has settled, so the first ⌘F opens with everything there (only in a tab
    // someone is looking at: a tab opened in the background loads it when it's first shown)
    const early = () => { if (document.visibilityState === 'visible') (window.requestIdleCallback || (f => setTimeout(f, 1500)))(() => load(), { timeout: 4000 }); };
    if (document.readyState === 'complete') early(); else addEventListener('load', early, { once: true });
    document.addEventListener('visibilitychange', () => { if (!index) early(); });
    // The name itself, then a word of the name, then the words it's found by; several words match in any order.
    function score(r, t) {
      const n = r.n.toLowerCase();
      if (n === t) return 5;
      if (n.startsWith(t)) return 4;
      const parts = t.split(/\s+/), names = n.split(/[\s:(),·-]+/), all = names.concat((r.find || '').split(/\s+/));
      if (parts.every(p => names.some(w => w.startsWith(p)))) return 3;
      return parts.every(p => all.some(w => w.startsWith(p))) ? 1 : 0;
    }
    function draw(data) {
      const t = q.value.trim().toLowerCase();
      read.hidden = true;
      const rows = data.rows || [];
      const hits = t ? rows.map(r => [r, score(r, t)]).filter(([, sc]) => sc > 0).sort((a, b) => b[1] - a[1]).map(([r]) => r)
                     : rows.filter(r => r.g === 'Your character' && r.a !== 'Open').slice(0, 6);
      // Groups in the order of their best match, so the top hit is first and highlighted (Spotlight's way).
      const order = t ? GROUPS.map((g, k) => [g, Math.max(0, ...rows.filter(r => r.g === g).map(r => score(r, t))), k])
        .sort((a, b) => b[1] - a[1] || a[2] - b[2]).map(([g]) => g) : GROUPS;
      shown = order.flatMap(g => hits.filter(r => r.g === g).slice(0, t ? 8 : 6));
      at = Math.min(at, Math.max(0, shown.length - 1));
      let i = 0;
      list.innerHTML = shown.length ? order.filter(g => shown.some(r => r.g === g)).map(g => '<div class="search-grp">' + (t ? g : 'Your character') + '</div>'
        + shown.filter(r => r.g === g).map(r => { const k = i++; return '<div class="search-res' + (k === at ? ' on' : '') + '" role="option" id="sr-' + k + '" aria-selected="' + (k === at) + '" data-i="' + k + '">'
          + '<b>' + esc(r.n) + '</b><span class="search-act">' + esc(r.a) + ' ↵</span><small>' + esc(r.s || '') + '</small></div>'; }).join('')).join('')
        : '<p class="note search-none">' + (data.failed ? 'Search can\'t reach askdnd right now. Type again in a moment.'
          : t ? 'Nothing by that name. ' + findKey + ' again finds it on this page.' : data.rows ? 'Type a rule, an entry in the story or a page.' : 'Loading…') + '</p>';
      q.setAttribute('aria-activedescendant', shown.length ? 'sr-' + at : '');
      list.querySelector('.on')?.scrollIntoView({ block: 'nearest' });
    }
    const redraw = () => load().then(draw);
    // The box opens under the menu bar's Search, at its left edge, so it seems to grow out of it (Brett chose D, Nov 13; `placeBox`, not `place`: that's the roll card's);
    // where there's no bar to grow from (a phone's magnifier, a bar off screen) it opens in the middle as before
    function placeBox() {
      const bar = document.querySelector('.search-btn'), r = bar && bar.getBoundingClientRect();
      const inView = r && r.width > 120 && r.bottom > 0;
      searchBox.classList.toggle('at-bar', !!inView);
      if (!inView) return;
      const w = Math.min(640, innerWidth - 24);
      searchBox.style.setProperty('--sb-top', Math.round(r.bottom + 6) + 'px');
      searchBox.style.setProperty('--sb-left', Math.round(Math.max(12, Math.min(r.left, innerWidth - w - 12))) + 'px');
    }
    function open() {
      if (searchBox.open) return;
      if (win) closeWin();
      placeBox();
      searchBox.showModal();
      q.value = ''; at = 0; read.hidden = true;
      redraw();
      q.focus();
    }
    function close() { if (searchBox.open) searchBox.close(); }
    // Enter: the thing itself (A); ⌘ Enter or a row with nothing to do: where it lives
    function act(i, where) {
      const r = shown[i];
      if (!r) return;
      if (r.a === 'Read it') { read.hidden = false; read.innerHTML = '<b>' + esc(r.n) + '</b> ' + esc(r.text || ''); return; }
      close();
      if ((where || r.panel_only) && r.panel) return window.askdndPanel ? window.askdndPanel(r.panel) : (location.href = r.panel);
      if (r.roll) {
        load().then(data => {
          // a roll button of the character's own, made for the moment (openRoll reads it as it would one on Battle)
          const holder = document.createElement('div');
          holder.className = 'search-anchor';
          holder.dataset.rollChar = data.character || '';
          holder.dataset.rollCtx = JSON.stringify(data.ctx || {});
          holder.dataset.condAdv = JSON.stringify((data.ctx || {}).condAdv || {});  // (as Battle's own: specFrom)
          if ((data.ctx || {}).hidden) holder.dataset.hidden = data.ctx.hidden;
          const b = document.createElement('button');
          b.type = 'button';
          // (every detail Battle's own button carries, whole: character_views.roll_data makes both)
          Object.entries(r.roll).forEach(([k, v]) => b.setAttribute('data-' + k, v));
          holder.append(b);
          document.body.append(holder);
          openRoll(b, specFrom(b));
          setTimeout(() => holder.remove(), 0);
        });
        return;
      }
      if (r.use) { const b = document.createElement('button'); b.dataset.useUrl = r.use; b.className = 'search-anchor'; document.body.append(b); openUse(b); setTimeout(() => b.remove(), 0); return; }
      if (r.go && /^https?:/.test(r.go)) window.open(r.go, '_blank', 'noopener');  // (D&D Beyond's VTT, as the menu bar's Table ↗)
      else if (r.go) location.href = r.go;
    }
    document.addEventListener('click', e => { if (e.target.closest('[data-search-open]')) { e.preventDefault(); open(); } });
    searchBox.addEventListener('click', e => {
      if (e.target === searchBox) return close();  // (outside the box: its backdrop)
      const row = e.target.closest('[data-i]');
      if (!row) return;
      // (after this click is done: what it opens would otherwise hear the same click as one outside it, and close)
      e.stopPropagation();
      const i = +row.dataset.i, where = mac ? e.metaKey : e.ctrlKey;
      setTimeout(() => act(i, where), 0);
    });
    list.addEventListener('mousemove', e => { const row = e.target.closest('[data-i]'); if (row && +row.dataset.i !== at) { at = +row.dataset.i; list.querySelectorAll('.search-res').forEach(x => { x.classList.toggle('on', +x.dataset.i === at); x.setAttribute('aria-selected', +x.dataset.i === at); }); } });
    q.addEventListener('input', () => { at = 0; redraw(); });
    document.addEventListener('keydown', e => {
      const mod = mac ? e.metaKey : e.ctrlKey;  // (on a Mac, Ctrl+F and Ctrl+K are a text box's own keys)
      const key = (e.key || '').toLowerCase();  // (Caps Lock on)
      if (mod && !e.altKey && !e.shiftKey && (key === 'f' || key === 'k')) {
        if (document.getElementById('fb-win')?.open) return;
        if (key === 'f' && searchBox.open) { close(); findFree = Date.now(); return; }  // (the browser's own find, this time)
        if (key === 'f' && Date.now() - findFree < 5000) return;
        e.preventDefault();
        open();
        return;
      }
      if (!searchBox.open) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        at = Math.max(0, Math.min(shown.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1)));
        load().then(draw);
      } else if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); act(at, mod); }
    }, true);
    // ⌘ on a Mac, Ctrl elsewhere
    if (!mac) document.querySelectorAll('[data-pc]').forEach(k => { k.textContent = k.dataset.pc; });
    window.askdndSearch = { open, close };
  }

  // ---------------------------------------------------------------- the roll card
  // Every roll in askdnd is played here (Brett, Nov 10: one plan, one window; the Roll Card Prototype, Nov 9:
  // docs/mockups/roll-workflow/round-2.html). Each roll button carries its plan, made by the server (app/roll_plan.py
  // `button`: what kind of roll it is, its numbers, a spell's dice at every level, what can be added and when, its
  // notes), and the card plays it as it is: it decides nothing about the rules. What the card knows is the state of the
  // moment: who's rolling, the slots left, Heroic Inspiration, Luck, the conditions' reasons (the page's roll context).
  //   attack: (a choice) → to hit → the result (reroll, after a miss, on a hit) → damage
  //   save:   the targets' save and DC → damage on a failed save, and what a success takes
  //   d20:    a check or a save of your own, Initiative → the result (reroll, after a failure, + a die)
  //   death:  a death save, which marks the sheet → the result
  //   single: healing, Temporary Hit Points, damage or dice → the result
  // A follow-up from Table rolls (Roll damage, Reroll, + a die) opens the card on that roll's result. Each roll goes the
  // usual way (sendRoll): Table rolls, the thrown dice, the Game Log. On a laptop it opens beside the row (place), on a
  // phone from the bottom. tests/browser/test_every_roll.py plays every roll button on the party's pages against its plan.
  const CARD_DICE = [['+1d4', 'd4'], ['+1d6', 'd6'], ['+1d8', 'd8'], ['+1d10', 'd10'], ['+1d12', 'd12'], ['+1', '+1'], ['+2', '+2'], ['-1d4', '−d4'], ['-1', '−1'], ['-2', '−2']];  // (−d4: Bane and the like)
  // Flat damage comes with the attack roll; one that can only be 0 says so first (feedback 25, 26)
  function flatNote(flat, label) {
    if (flat === 0) return '<p class="rw-note rw-warn" data-flat-note><b>0 damage</b> on a hit' + (/^Unarmed Strike\b/.test(label || '') ? ': 1 + your Strength modifier comes to 0' : '') + '. The DM rules.</p>';
    return '<p class="rw-note" data-flat-note>On a hit: <b>' + flat + ' damage</b>, flat, with the roll (no dice to roll).</p>';
  }
  function card(anchor, spec, plan, from) {
    const ctx = ctxFor(spec.cid), play = plan.play;
    const d20 = play === 'd20' || play === 'death', attack = play === 'attack', save = play === 'save', single = play === 'single';
    const cast = plan.rolls || null, effs = cast ? cast.effects : [], grows = !!cast && cast.levels.length > 1;
    const choice = spec.shared ? plan.choice : null;  // (Grapple and Shove go to the table: yours only)
    const mods = play === 'd20' ? ((ctx.mods || {})[plan.mods || plan.roll] || []) : play === 'death' ? [] : (plan.modifiers || []);
    const w = openWin(anchor);
    w.classList.add('roll-card');
    w.setAttribute('aria-label', plan.name);
    const level0 = !cast ? 0 : spec.cast || (spec.slot >= cast.base ? spec.slot : ((ctx.slots || []).find(l => l >= cast.base) || cast.base));
    const st = { step: from ? (from.action === 'bonus' ? 'pick' : 'rolling') : attack ? (choice ? 'choose' : 'attack') : save ? 'save' : single ? 'single' : 'attack', forText: '',
                 mode: spec.adv ? 'adv' : 'normal', pre: {}, added: [], on: {}, adding: false, visOpen: false, entry: from ? from.entry : null,
                 dmg: null, busy: false, hidden: !!spec.endsHidden, level: level0, ev: 0, ride: {}, way: {}, drama: false,
                 pay: (plan.pay || []).map(p => !p.optional && (p.left == null || p.left >= p.n)), paid: false };  // (a cost the rules make a choice starts unpressed)
    // (on by themselves while they last, Radiant Strikes; once a turn, or only sometimes (`pressed: false`, Rage Damage): yours to tick)
    mods.forEach(m => { if ((m.when === 'on_hit' || m.when === 'on_heal') && m.adds && !m.op) st.on[m.name] = m.pressed != null ? !!m.pressed : !m.once && !(m.slot && spec.castFree); });  // (a slot's bonus is off when cast without one)
    mods.forEach(m => { if (m.op === 'max') st.on[m.name] = true; });  // (Supreme Healing: on, yours to press off)
    mods.forEach(m => { if (m.when === 'before' && m.adds && m.pressed) st.pre[m.name] = true; });  // (Aura of Protection: always, unless the DM says)
    const eff = () => effs[st.ev] || null;
    const now = () => (eff() ? eff().at[String(st.level)] : null);  // (the effect's dice at the level it's cast at)
    const dmgText = () => ((now() ? now().text : '') || plan.dmg || '') + dmgModsText();
    // What adds to the damage (Sneak Attack on a hit; Arcane Firearm, a Chromatic focus on a spell's damage): pills, the
    // pressed ones rolled into the damage as extras
    // (and to a spell's healing: Disciple of Life, its amount at the level cast, `adds_at`, from the plan)
    const dmgMods = () => mods.filter(m => m.adds && !m.op && (eff() && eff().kind === 'heal' ? m.when === 'on_heal' : m.when === 'on_hit' || m.when === 'on_damage'));
    // What a spell's healing does that isn't a number added (roll_plan HEAL_OPS): every die at its highest (Supreme
    // Healing, a pill), and healing yourself once it healed someone else (Blessed Healer, a button on the result)
    const healOps = op => (eff() && eff().kind === 'heal' ? mods.filter(m => m.op === op && !(m.slot && spec.castFree)) : []);
    const madds = m => (m.adds_at && m.adds_at[String(st.level)]) || m.adds;
    const dmgExtras = () => dmgMods().filter(m => st.on[m.name]).map(m => (m.short || m.name).slice(0, 40) + ':+' + madds(m).replace(/^\+/, '').split(' ')[0]);
    const dmgModsText = () => (attack ? '' : dmgMods().filter(m => st.on[m.name]).map(m => ' + ' + madds(m)).join(''));
    const dmgPills = () => { const ms = dmgMods(); return ms.length ? '<div class="rcard-group"><span class="rcard-lbl">' + (eff() && eff().kind === 'heal' ? 'Adds to the healing' : 'Adds to the damage') + '</span><div class="rcard-pills">'
      + ms.map(m => pill('data-on="' + esc(m.name) + '"', st.on[m.name], m.short || m.name, madds(m) + (m.once ? ' · once a turn' : '') + (m.slot ? ' · with a slot' : ''))).join('') + '</div></div>' : ''; };
    const healPills = () => (healOps('max').length ? '<div class="rcard-group"><span class="rcard-lbl">The dice</span><div class="rcard-pills">'
      + healOps('max').map(m => pill('data-on="' + esc(m.name) + '"', st.on[m.name], m.short || m.name, m.says || '')).join('') + '</div></div>' : '');
    const steps = () => d20 || single ? ['Roll'] : save ? ['The save', 'Damage'] : [...(choice ? ['Choose'] : []), 'To hit', 'Damage'];
    const at = () => d20 || single ? (st.step === 'done' ? 9 : 0) : save ? ({ save: 0, rolling: 1, saved: 9 })[st.step]
      : ({ choose: 0, attack: choice ? 1 : 0, rolling: choice ? 1 : 0, result: choice ? 1 : 0, damage: choice ? 2 : 1, done: 9 })[st.step];
    const pill = (attr, on, text, small) => '<button type="button" class="chip rcard-pill" ' + attr + ' aria-pressed="' + !!on + '">' + esc(text) + (small ? ' <small>' + esc(small) + '</small>' : '') + '</button>';
    const adder = target => '<div class="rcard-adder" data-adder="' + target + '">' + CARD_DICE.map(([v, t]) => '<button type="button" class="chip" data-add="' + v + '">' + t + '</button>').join('') + '</div>';
    const added = () => st.added.map((a, i) => pill('data-unadd="' + i + '"', true, a.replace(/^Added:/, ''), 'tap to take off')).join('');
    const plus = target => '<button type="button" class="chip rcard-pill rcard-plus" data-adding>+ die or bonus</button></div>' + (st.adding ? adder(target) : '');
    const visLine = () => !spec.shared
      ? '<div class="rcard-vis"><span>Only you see this: you don\'t play this character</span></div>'
      : (st.visOpen
      ? '<div class="rcard-vis rcard-vis-open"><span class="rw-label">Who sees it</span>' + seg('To', [['table', 'The table'], ['dm', 'DM only'], ['self', 'Just you']], to) + '</div>'
      : '<div class="rcard-vis"><span>' + ({ table: 'The table sees this', dm: 'Only the DM sees this', self: 'Only you see this' }[to] || '') + '</span><button type="button" class="btn small link" data-vis-open>Change</button></div>')
      + (to !== 'self' ? logLine() : '');
    // What it does on a hit (or Graze, on a miss): a weapon's mastery and a class's riders, in words (they're yours to use)
    const riders = when => (plan.riders || []).filter(r => r.says && (r.when === 'miss') === (when === 'miss'));
    // Riders on a hit (Brett, Nov 10, docs/mockups/rider-actions/): one with a kind (its plan's `act`) is a choice under
    // On a hit (adds dice, asks for a save, changes the damage); the rest stay words. Its cost is spent once Roll damage is
    // pressed (A: nothing lost by changing your mind), and a save's DC joins this attack's entry in Table rolls (A).
    const acts = () => riders('hit').filter(r => r.act);
    const RIDE_KIND = { dice: 'Adds dice', save: 'Asks for a save', change: 'Changes the damage' };
    function rideDice(r) {  // the dice a pressed rider adds, at the way it's cast (Divine Smite's slot)
      const a = r.act;
      if (a.kind !== 'dice') return [];
      if (!a.rolls) return a.adds ? [a.adds] : [];
      const way = ((a.cast || {}).ways || [])[st.way[r.name] || 0], first = (a.rolls.effects || [])[0] || { at: {} };
      const atLevel = first.at[String(way ? way.level : a.rolls.base)] || first.at[String(a.rolls.base)];
      return atLevel ? atLevel.parts : [];
    }
    function rideRow(r) {
      const a = r.act, on = !!st.ride[r.name];
      let cost = '';
      if (a.cast) cost = (a.cast.time ? esc(a.cast.time) + ' · ' : '') + (a.cast.ways.length ? '<select class="rw-slot" data-ride-way="' + esc(r.name) + '" aria-label="' + esc(r.name) + ': how to cast it">'
        + a.cast.ways.map((way, i) => '<option value="' + i + '"' + (i === (st.way[r.name] || 0) ? ' selected' : '') + '>' + esc(way.label) + '</option>').join('') + '</select>'
        : esc('No slot left: mark it on D&D Beyond'));
      else if (a.spend) cost = esc('1 ' + a.spend.name.replace(/s$/, '') + (a.spend.left != null ? ' (' + a.spend.left + ' left)' : ''));
      if (cost && ctx.spends !== 'play') cost += '<span class="rcard-rider-by-hand">' + (ctx.spends === 'unreached' ? "The D&amp;D Beyond sheet can't be reached: mark it there." : 'Mark it on D&amp;D Beyond.') + '</span>';
      const says = a.kind === 'dice' ? '+' + rideDice(r).join(' + ') + (r.says ? '; ' + r.says : '') : r.says;
      return '<div class="rcard-rider"><div class="rcard-rider-top">' + pill('data-ride="' + esc(r.name) + '"', on, r.name)
        + '<span class="rcard-kind k-' + esc(a.kind) + '">' + RIDE_KIND[a.kind] + '</span></div>'
        + '<span class="rcard-rider-says">' + esc(says) + '</span>' + (cost ? '<span class="rcard-rider-cost">' + cost + '</span>' : '') + '</div>';
    }
    const riderList = when => riders(when).filter(r => !r.act).map(r => '<li><b>' + esc(r.name) + '</b> ' + esc(r.says) + (r.on && r.on !== 'mastery' ? ' <small>(' + esc(r.on) + ')</small>' : '') + '</li>').join('');
    // Before the roll: the plan's own notes, then the moment's (the conditions' reasons, Luck, Heroic Inspiration)
    function notes() {
      const out = (spec.advWhy || '').split('\n').filter(Boolean).map(t => t.startsWith('!dis ') ? '<b>Disadvantage</b> ' + esc(t.slice(5))
        : t.startsWith('!note ') ? '<b>Note</b> ' + esc(t.slice(6)) : '<b>Advantage</b> ' + esc(t.replace(/^advantage\s*/i, '')));
      if (d20 || attack) {
        if (ctx.luck) out.push('<b>Lucky</b> you can spend a Luck Point (' + ctx.luck + ' left) for Advantage');
        if (ctx.inspiration) out.push('<b>Heroic Inspiration</b> you have it: you can reroll after you see the roll');
        if (ctx.halfling) out.push('<b>Luck</b> (Halfling) you can reroll a 1');
      }
      (plan.notes || []).forEach(n => out.push(esc(n)));
      return out.length ? '<ul class="rw-notes">' + out.map(t => '<li>' + t + '</li>').join('') + '</ul>' : '';
    }
    function head() {
      const sub = [play === 'death' || (d20 && plan.bonus == null) ? 'd20' : d20 ? 'd20 ' + signed(plan.bonus) : attack ? (plan.bonus == null ? '' : 'to hit ' + signed(plan.bonus))
        : save ? plan.save.ability + ' save, DC ' + plan.save.dc : '', singleText()].filter(Boolean).join(' · ');
      return '<button type="button" class="rp-x" aria-label="Close">×</button><div class="rcard-head"><b>' + esc(plan.name) + '</b>' + (sub ? '<span class="rcard-sub">' + esc(sub) + '</span>' : '') + '</div>'
        + '<ol class="rcard-rail" aria-label="Steps">' + steps().map((n, i) => '<li class="' + (i < at() ? 'done' : i === at() ? 'now' : '') + '">' + n + '</li>').join('') + '</ol>';
    }
    function singleText() {
      if (d20) return '';
      const base = single && plan.roll === 'dice' && !cast ? spec.dmg || '' : dmgText();
      return single ? [base, ...st.added.map(a => a.replace(/^Added:/, ''))].filter(Boolean).join(' ') : base;
    }
    // Which effect (a spell with a choice of them) and at what level: fixed once it's cast, else the levels the plan has
    function castAt() {
      let h = '';
      if (effs.length > 1) h += '<div class="rw-row rw-evs"><span class="rw-label">Which</span><span class="rw-ev-list">' + effs.map((x, i) =>
        '<button type="button" class="chip" data-card-ev="' + i + '" aria-pressed="' + (i === st.ev) + '">' + esc(x.name) + '</button>').join('') + '</span></div>';
      if (grows && spec.cast) h += '<div class="rw-row"><span class="rw-label">Cast at</span><span>Level ' + spec.cast + ' <small class="note">(' + (spec.castFree ? 'cast without spending a slot' : 'cast: the slot is spent') + ')</small></span></div>';
      else if (grows) h += '<div class="rw-row"><span class="rw-label">Cast at</span><select class="rw-slot" data-card-slot aria-label="Spell slot level">'
        + cast.levels.map(l => '<option value="' + l + '"' + (l === st.level ? ' selected' : '') + '>Level ' + l
          + (ctx.slots && ctx.slots.length && !ctx.slots.includes(l) ? ' (no slot left)' : '') + '</option>').join('') + '</select></div>';
      if (cast && !now()) h += '<p class="rw-note rw-warn">Nothing extra at your level yet.</p>';
      if (now() && now().why) h += '<p class="rw-note math-why" data-why>' + esc(now().why) + '</p>';  // (Show the Math, D: how the dice grew)
      const e = eff();
      if (e && e.repeat) h += '<p class="rw-note">Again: ' + esc(e.repeat) + '</p>';
      if (e && e.note) h += '<p class="rw-note">' + esc(e.note) + '</p>';
      return h;
    }
    function hitLine() {
      const adds = [...mods.filter(m => m.when === 'before' && st.pre[m.name]).map(m => m.adds), ...st.added];
      return (play === 'death' ? 'd20' : 'd20 ' + signed(plan.bonus)) + (adds.length ? ' ' + adds.join(' ').replace(/(^| )(?=\d)/g, '$1+') : '') + (st.mode !== 'normal' ? ' · ' + (st.mode === 'adv' ? 'Advantage' : 'Disadvantage') : '');
    }
    function draw() {
      let h = head();
      if (st.step === 'choose') {
        h += payLine() + '<p class="rcard-q">' + esc(choice.ask) + '</p><div class="rcard-choices">' + choice.options.map(o =>
          '<button type="button" class="rcard-choice" data-choice="' + esc(o.key) + '"><b>' + esc(o.name) + '</b><small>' + esc(o.says) + '</small></button>').join('') + '</div>';
      } else if (st.step === 'single') {
        h += castAt();
        if (plan.roll === 'dice') h += '<div class="rw-row"><span class="rw-label">For</span><input type="text" class="rw-text" data-card-for placeholder="What the DM asked for (optional)" maxlength="60" value="' + esc(st.forText) + '"></div>';
        h += notes() + payLine();
        if (eff() && (eff().kind === 'damage' || eff().kind === 'heal')) h += dmgPills() + healPills();
        h += '<div class="rcard-group"><span class="rcard-lbl">Adds to the roll</span><div class="rcard-pills">' + added() + plus('pre') + '</div>';
        h += '<button type="button" class="btn primary rcard-go" data-roll-single' + (cast && !now() ? ' disabled' : '') + '>' + ({ heal: 'Roll healing', temp: 'Roll Temporary Hit Points', damage: 'Roll damage' }[eff() ? eff().kind : plan.roll] || 'Roll')
          + ' <small>' + esc(singleText()) + '</small></button>' + visLine();
      } else if (st.step === 'save') {
        h += castAt() + notes();
        const ok = { half: ': half damage on a success', none: ': no damage on a success' }[plan.save.success] || '';
        h += '<p class="rcard-q">Each target makes a <b>' + esc(plan.save.ability) + ' save</b> against <b>DC ' + mathNum(plan.save.dc, (plan.math || {}).dc ? { rows: plan.math.dc, total: plan.save.dc } : null, 'Save DC') + '</b>' + ok + '. The DM rolls them.</p>' + dmgPills();
        h += '<button type="button" class="btn primary rcard-go" data-roll-save' + (cast && !now() ? ' disabled' : '') + '>Roll damage <small>' + esc(dmgText()) + '</small></button>' + visLine();
      } else if (st.step === 'saved') {
        const e = st.entry, half = plan.save.success === 'half' ? Math.floor(e.total / 2) : plan.save.success === 'none' ? 0 : null;
        h += '<div class="rcard-result rcard-dmg"><span class="rcard-big">' + mathNum(e.total, (e.math || {}).dmg, 'Damage') + '</span><span class="rcard-what">damage on a failed save</span><span class="rcard-how">' + dline(e.main, false) + '</span></div>'
          + (half != null ? '<p class="rcard-line">On a success: <b>' + (half ? half + '</b> (half)' : 'no damage</b>') + '</p>' : '')
          + '<p class="rw-note">In Table rolls for the DM, who rolls the saves and applies it.</p><div class="rcard-acts"><button type="button" class="btn primary" data-done>Done</button></div>';
      } else if (st.step === 'attack') {
        if (attack) h += castAt();
        // Make it dramatic (Brett chose A, Nov 13, docs/mockups/make-it-dramatic/): an icon at the end of this row, for
        // players to find by pointing at it; pressed, every screen throws this roll big and slow. On every roll of your own
        // character's (Brett, Nov 13: his device remembered Just you, so it never showed): pressed while the roll was
        // Just you or DM only, it goes to the table, said on the card's Who sees it line like any choice there.
        const drama = spec.shared && play !== 'death'
          ? '<button type="button" class="rcard-drama" data-drama aria-pressed="' + st.drama + '" aria-label="Make it dramatic" title="Make it dramatic: the whole table watches this roll in slow motion">🎬</button>' : '';
        h += '<div class="rw-row rw-mode">' + seg('Mode', [['normal', 'Normal'], ['adv', 'Advantage'], ['dis', 'Disadvantage']], st.mode) + drama + '</div>' + notes() + payLine();
        const pre = mods.filter(m => m.when === 'before' && m.adds);
        h += '<div class="rcard-group"><span class="rcard-lbl">Adds to the roll</span><div class="rcard-pills">' + pre.map(m => pill('data-pre="' + esc(m.name) + '"', st.pre[m.name], m.name, m.adds)).join('')
          + added() + plus('pre') + '</div>';
        if (attack && spec.endsHidden) h += '<div class="rcard-pills">' + pill('data-ends-hidden', st.hidden, 'This attack ends Hidden', st.hidden ? 'the DM may rule otherwise' : 'you stay Hidden') + '</div>';
        if (attack && plan.flat != null) h += flatNote(plan.flat, plan.name);
        h += '<button type="button" class="btn primary rcard-go" data-roll-hit>' + (attack ? 'Roll to hit' : 'Roll') + ' <small>' + esc(hitLine()) + '</small></button>' + visLine();
      } else if (st.step === 'result' || st.step === 'rolling') {
        h += st.step === 'rolling' ? '<div class="rcard-result rolling"><span class="rcard-big">…</span><span class="rcard-what">' + (save ? 'Rolling damage' : attack ? 'Rolling to hit' : 'Rolling') + '</span></div>' : resultBox(st.entry, false);
        if (st.step === 'result' && (attack || d20)) {
          const e = st.entry, c = e.can || {};
          const sure = attack && e.nat === 20;  // (a natural 20 hits: nothing for a miss; 2024 PHB)
          // (what can be added once the roll is seen: Guided Strike, before you know if it hits; Favored by the Gods, after a miss)
          const after = sure ? [] : mods.filter(m => (m.when === 'after_fail' || m.when === 'after_roll') && m.adds && (m.to || []).includes(attack ? 'attack' : plan.roll));
          const adjust = (c.reroll ? pill('data-reroll', false, 'Reroll', c.reroll) : '') + (c.bonus ? after.map(m => pill('data-after="' + esc(m.name) + '"', false, m.short || m.name,
            (/^\d/.test(m.adds) ? '+' : '') + m.adds + ' ' + (m.says || (attack ? 'after a miss' : 'after a failure')))).join('') + '<button type="button" class="chip rcard-pill rcard-plus" data-adding>+ a die</button>' : '');
          if (adjust) h += '<div class="rcard-pills rcard-adjust">' + adjust + '</div>' + (st.adding ? adder('bonus') : '');
          // A natural 1 misses whatever the bonus (2024 PHB), and with several rays only those that aren't: when nothing
          // can hit there's no damage to roll (Nov 13: every Eldritch Blast ray rolled a 1, the card offered damage and
          // askdnd refused it), only It misses
          const rayRolls = ((e.main && e.main.parts) || []).filter(x => x.kept != null);
          const allMiss = attack && (rayRolls.length > 1 ? rayRolls.every(x => x.kept === 1) : e.nat === 1);
          if (attack && c.damage && allMiss) {
            h += '<div class="rcard-acts"><button type="button" class="btn" data-missed>It misses</button></div>';
          } else if (attack && c.damage) {
            h += onHit() + '<div class="rcard-acts"><button type="button" class="btn primary rcard-go" data-roll-dmg>Roll ' + (e.nat === 20 ? 'critical ' : '') + 'damage <small>' + esc(c.damage) + dmgAdds() + '</small></button>'
              + (sure ? '' : '<button type="button" class="btn" data-missed>Missed</button>') + '</div>';
          } else {
            h += d20 ? '<div class="rcard-acts"><button type="button" class="btn primary" data-done>Done</button></div>'
              : '<div class="rcard-acts"><button type="button" class="btn" data-missed>' + (e.nat === 1 ? 'It misses' : 'Done') + '</button></div>';
          }
          if (attack && !sure && riderList('miss')) h += '<div class="rcard-group"><span class="rcard-lbl">On a miss</span><ul class="rw-notes" data-riders>' + riderList('miss') + '</ul></div>';
        }
      } else if (st.step === 'damage') {
        const tw = st.dmg && st.dmg.twice;
        h += st.dmg ? resultBox(st.entry, true)
          + (tw ? '<p class="rcard-line">Rolled twice, the higher kept <span class="roll-x">(the other: ' + esc((tw.dice || []).join(' ')) + ' → ' + tw.total + ')</span></p>' : '')
          + ((st.entry && st.entry.saves) || []).map(sv => { const [who, what] = sv.label.split(': ');
            return '<p class="rcard-line rcard-save">' + esc(who) + ': the target makes a <b>' + esc(what || 'save') + ', DC ' + sv.dc + '</b>.' + (spec.shared ? ' The DM rolls it; it\'s in Table rolls.' : '') + '</p>'; }).join('')
          + (riderList('hit') ? '<ul class="rw-notes" data-riders>' + riderList('hit') + '</ul>' : '') + '<p class="rw-note">' + (spec.shared ? 'In Table rolls for the DM, who applies it to an enemy; a character or a creature on askdnd\'s table can be applied there.' : 'Only you see this roll.') + '</p>'
          + '<div class="rcard-acts"><button type="button" class="btn primary" data-done>Done</button></div>'
          : '<div class="rcard-result rolling"><span class="rcard-big">…</span><span class="rcard-what">Rolling damage</span></div>';
      } else if (st.step === 'pick') {  // (+ a die, pressed in Table rolls: which one)
        h += '<p class="rcard-q">Add a die or a bonus to this roll</p>' + adder('bonus');
      } else if (st.step === 'done') {  // (a roll that can go again, a Hit Point Die: its plan's "again" button first)
        h += resultBox(st.entry, false) + '<div class="rcard-acts">' + (plan.again ? '<button type="button" class="btn primary rcard-go" data-again>' + esc(plan.again) + '</button>' : '')
          + '<button type="button" class="btn' + (plan.again ? '' : ' primary') + '" data-done>Done</button></div>';
      }
      w.innerHTML = h;
      if (w._reserve == null) {  // (room kept from the start for the On a hit block a later step adds: the card never moves)
        const more = attack ? onHit() : '';
        let t = null;
        if (more) { t = document.createElement('div'); t.innerHTML = more; w.append(t); }
        w._reserve = more ? w.offsetHeight : 0;
        if (t) t.remove();
      }
      w.classList.toggle('nat20', !!(st.entry && st.entry.nat === 20));
      w.classList.toggle('nat1', !!(st.entry && st.entry.nat === 1));
      place(w);
      const first = w.querySelector('.rcard-go:not([disabled]), .rcard-choice, [data-done], [data-missed]');
      if (first) first.focus({ preventScroll: true });
    }
    function onHit() {  // what you can add once an attack hits: on-hit dice, riders to press, riders in words
      const hitMods = dmgMods(), said = riderList('hit'), rows = acts();
      return hitMods.length || said || rows.length ? '<div class="rcard-group"><span class="rcard-lbl">On a hit</span>'
        + (hitMods.length ? '<div class="rcard-pills">' + hitMods.map(m => pill('data-on="' + esc(m.name) + '"', st.on[m.name], m.name, m.adds + (m.once ? ' · once a turn' : ''))).join('') + '</div>' : '')
        + rows.map(rideRow).join('') + (said ? '<ul class="rw-notes" data-riders>' + said + '</ul>' : '') + '</div>' : '';
    }
    function dmgAdds() {
      const on = acts().filter(r => st.ride[r.name]), type = on.find(r => r.act.type), twice = on.some(r => r.act.twice);
      return dmgMods().filter(m => st.on[m.name]).map(m => ' + ' + madds(m)).join('')
        + on.flatMap(rideDice).map(p => ' + ' + p).join('') + (type ? ' · as ' + type.act.type : '') + (twice ? ' · rolled twice' : '');
    }
    // Roll damage with what's pressed: on-hit dice and riders' dice in it, its type or rolled twice as a rider says; then
    // each save rider's DC into this attack's entry, then each rider's cost (a Focus Point, Divine Smite's slot), with Undo
    function rollDamage() {
      const on = acts().filter(r => st.ride[r.name]), type = on.find(r => r.act.type);
      const extras = [...dmgExtras(),
                      ...on.flatMap(r => rideDice(r).map(p => { const [dice, dtype] = p.split(' '); return (dtype ? r.name + ' (' + dtype + ')' : r.name).slice(0, 40) + ':+' + dice; }))];
      return followUp('damage', { extras, asType: type ? type.act.type : '', twice: on.some(r => r.act.twice) }).then(() => {
        if (!st.dmg) return;
        if (!spec.shared) {  // (a private roll: the save said on the card alone, nothing spent)
          st.entry.saves = on.filter(r => r.act.kind === 'save').map(r => ({ label: r.name + ': ' + r.act.save + ' save', dc: r.act.dc }));
          if (w.isConnected) draw();
          return;
        }
        let chain = Promise.resolve();
        on.filter(r => r.act.kind === 'save').forEach(r => {
          chain = chain.then(() => sendRoll({ ...spec, ctx, via: 'card', follow: 'save', parent: st.entry.id, entry: st.entry, extras: [], label: r.name + ': ' + r.act.save + ' save' })
            .then(e => { st.entry = e; if (w.isConnected) draw(); }, err => toast(r.name + ': ' + err.message, null, 'warn')));
        });
        return chain.then(() => on.forEach(spendRider));
      });
    }
    function spendRider(r) {
      const a = r.act, cid = spec.cid;
      if (ctx.spends !== 'play' || !cid) return;  // (marked by hand on D&D Beyond: the cost line said so)
      let url, data;
      if (a.cast) {
        const way = a.cast.ways[st.way[r.name] || 0];
        if (!way) return;
        url = '/characters/' + cid + '/cast?key=' + encodeURIComponent(a.cast.key); data = { way: way.way };
      } else if (a.spend && a.spend.field) {
        return spendCount(cid, a.spend.field, 1, r.name);
      } else return;
      posted(url, data).then(j => {
        toast(j.text, j.undo ? { label: 'Undo', run: () => posted(j.undoUrl, j.undo).then(u => { toast(u.text); itemChanged(u); }).catch(err => toast(err.message, null, 'warn')) } : null);
        itemChanged(j);
      }).catch(err => toast(r.name + ': ' + err.message, null, 'warn'));
    }
    function resultBox(e, dmg) {
      if (!e || !e.main) return '';
      if (single) {  // (one roll: its number, what it is, and where it goes next)
        const what = { heal: 'healing', temp: 'Temporary Hit Points', damage: 'damage' }[e.kind] || esc(e.label);
        const next = !spec.shared ? 'Only you see this roll.'
          : (e.kind === 'heal' || e.kind === 'temp') && plan.self ? 'In Table rolls, <b>Apply to</b> adds it to your own Hit Points.'
          : e.kind === 'heal' || e.kind === 'temp' ? 'In Table rolls, <b>Apply to</b> gives it to a character.'
          : e.kind === 'damage' ? 'In Table rolls for the DM, who applies it to an enemy; a character or a creature on askdnd\'s table can be applied there.' : '';
        const yours = spec.shared && spec.cid && e.kind === 'heal' ? healOps('self_heal') : [];
        return '<div class="rcard-result' + (e.kind === 'heal' || e.kind === 'temp' ? ' rcard-heal' : e.kind === 'damage' ? ' rcard-dmg' : '') + '"><span class="rcard-big">' + mathNum(e.total, (e.math || {}).dmg, what.replace(/<[^>]+>/g, '')) + '</span><span class="rcard-what">' + what + '</span><span class="rcard-how">' + dline(e.main, false) + '</span></div>'
          + (next ? '<p class="rw-note">' + next + '</p>' : '')
          + yours.map(m => '<div class="rcard-acts"><button type="button" class="btn small" data-self-heal="' + esc(madds(m)) + '" data-self-name="' + esc(m.name) + '"' + (st.selfHealed ? ' disabled' : '') + '>'
            + esc(m.name) + ': you regain ' + esc(madds(m)) + '</button><span class="rw-note">' + esc(m.says || '') + '</span></div>').join('');
      }
      if (e.kind === 'dc') return '<div class="rcard-result"><span class="rcard-big">DC ' + e.total + '</span><span class="rcard-what">' + esc(e.label) + '</span><span class="rcard-how">The target picks Strength or Dexterity; the DM rolls its save. It\'s in Table rolls.</span></div>';
      if (dmg && e.damage) return '<div class="rcard-result rcard-dmg"><span class="rcard-big">' + mathNum(e.damage.total, (e.math || {}).dmg, 'Damage') + '</span><span class="rcard-what">' + (e.damage.crit ? 'critical damage' : 'damage') + '</span><span class="rcard-how">' + dline(e.damage, false) + '</span></div>'
        + '<p class="rcard-line">To hit <b>' + e.total + '</b> · ' + dline(e.main, true) + '</p>';
      const rays = ((e.main && e.main.parts) || []).filter(x => x.kept != null);
      if (rays.length > 1) {  // (one to-hit per ray; the DM says which hit)
        return '<div class="rcard-result"><span class="rcard-big">' + rays.map(x => x.total).join(' · ') + '</span><span class="rcard-what">to hit, one per ' + esc((eff() || {}).each || 'ray') + '</span>'
          + '<span class="rcard-how">' + rays.map(x => esc(x.label) + ': d20 ' + x.kept + (x.kept === 20 ? ' (critical)' : x.kept === 1 ? ' (misses)' : '')).join(' · ') + '</span></div>'
          + '<p class="rw-note">The DM says which hit. Damage rolls for each one that isn\'t a natural 1, doubled for a 20.</p>';
      }
      const flag = e.kind === 'death' ? (e.outcome ? title(e.outcome) : '')
        : e.nat ? 'Natural ' + e.nat + (d20 ? '' : e.nat === 20 ? ': a critical hit, damage dice doubled' : ': it misses, whatever the bonus') : '';
      return '<div class="rcard-result"><span class="rcard-big">' + mathNum(e.total, (e.math || {}).hit, d20 ? (spec.label || plan.name) : 'To hit') + '</span><span class="rcard-what">' + (d20 ? esc(spec.label || plan.name) : 'to hit') + '</span><span class="rcard-how">' + dline(e.main, true) + '</span></div>'
        + (e.rerolled ? '<p class="rcard-line">Rerolled (' + esc(e.rerolled.reason) + '): was <s>' + e.rerolled.total + '</s></p>' : '')
        + (e.bonus ? '<p class="rcard-line">+ ' + esc(e.bonus.label) + ' ' + e.bonus.total + ((e.bonus.dice || []).length ? ' <span class="roll-x">(' + esc(e.bonus.formula) + ')</span>' : '') + '</p>' : '')  // (a plain +10 isn't written twice)
        + (flag ? '<p class="rcard-flag">' + esc(flag) + '</p>' : '')
        + (e.damage && !dmg ? '<p class="' + (e.damage.total ? 'rcard-line' : 'rw-note rw-warn') + '" data-flat-dmg>On a hit: <b>' + e.damage.total + ' damage</b>' + (e.damage.total ? ', flat' : '') + ', with the roll' + (e.damage.total ? '' : '. The DM rules') + '.</p>' : '');
    }
    function go(o) {  // one roll, its journey (sendRoll), then the card draws what came back
      if (st.busy) return Promise.resolve();
      st.busy = true;
      return sendRoll({ ...spec, ctx, ...o, via: 'card' }).then(e => { st.busy = false; return (animate() ? throwMine(e, o.follow).catch(() => stage(e, o.follow)) : Promise.resolve()).then(() => { landed(e.id); return e; }); })
        .catch(err => { st.busy = false; toast((err.said ? err.message : "Couldn't reach askdnd") + ': not rolled.', null, 'warn'); throw err; });
    }
    // How its numbers add up, sent with the roll and kept with it (Show the Math, app/roll_math.py `clean`): the plan's
    // parts, where its dice come from, and how a spell's dice grew at the level it's cast at
    function sentMath() {
      const m = plan.math || {}, out = {};
      if (m.bonus) out.bonus = m.bonus;
      if (m.dmg) out.dmg = m.dmg;
      if (m.dice) out.dice = m.dice;
      if (now() && now().why) out.why = now().why;
      return Object.keys(out).length ? out : null;
    }
    // What's sent for each roll is what the plan says, at the level and effect chosen (tests/browser/test_every_roll.py)
    const dice = () => (now() ? { parts: now().parts, count: now().count, once: !!eff().once, each: eff().each || '' } : {});
    // What making this roll spends (the action widgets, roadmap 8; character_views.pays): Flurry of Blows' Focus Point,
    // Second Wind's use. A pill each, on while there's enough left; spent once the roll is made, through Use one's own
    // count (app/resources.py), so the corner card's Undo is that window's. Marked by hand where askdnd can't spend it.
    function payLine() {
      const pay = spec.shared ? plan.pay || [] : [];
      if (!pay.length) return '';
      const by = ctx.spends === 'play' ? '' : '<span class="rcard-rider-by-hand">' + (ctx.spends === 'unreached' ? "The D&amp;D Beyond sheet can't be reached: mark it there." : 'Mark it on D&amp;D Beyond.') + '</span>';
      return '<div class="rcard-group" data-pays><span class="rcard-lbl">Spends</span><div class="rcard-pills">' + pay.map((p, i) => p.left != null && p.left < p.n
        ? '<span class="chip rcard-pill" aria-disabled="true">' + esc(p.label) + ' <small>none left</small></span>'
        : pill('data-pay="' + i + '"', st.pay[i], p.label, p.left != null ? p.left + ' left' : '')).join('') + '</div>' + by + '</div>';
    }
    function payCost() {
      if (st.paid || !spec.shared || ctx.spends !== 'play' || !spec.cid) return;
      st.paid = true;
      (plan.pay || []).forEach((p, i) => { if (st.pay[i]) spendCount(spec.cid, p.field, p.n, plan.name); });
    }
    function rollHit() {
      const extras = [...mods.filter(m => m.when === 'before' && st.pre[m.name] && m.adds).map(m => m.name + ':+' + m.adds.replace(/^\+/, '')), ...st.added];
      st.step = 'rolling'; st.adding = false; draw();
      const d = dice();
      go({ kind: attack ? 'attack' : plan.roll, mode: st.mode, extras, endsHidden: st.hidden && attack, level: cast ? st.level : 0, riders: (plan.riders || []).map(r => r.name), math: sentMath(), dramatic: st.drama,
           ...(attack && d.parts ? { dmgParts: d.parts, count: d.count || 1, each: d.each } : {}) })
        .then(e => { st.entry = e; st.step = 'result'; if (w.isConnected) draw(); turnUsed(anchor); payCost(); }, () => { st.step = 'attack'; if (w.isConnected) draw(); });
    }
    function rollOne(next) {  // single and save: one roll of the effect at the level chosen
      const d = dice(), was = st.step;
      st.step = 'rolling'; st.adding = false; draw();
      const label = plan.roll === 'dice' && !cast ? (st.forText.trim() || 'Dice') : spec.label + (d.parts && effs.length > 1 ? ' · ' + eff().name : '');
      const adds = eff() && (eff().kind === 'damage' || eff().kind === 'heal') ? dmgExtras() : [];
      return go({ kind: eff() ? eff().kind : plan.roll, label, mode: 'normal', extras: [...(single ? st.added.slice() : []), ...adds], level: cast ? st.level : 0, self: !!plan.self, math: sentMath(),
                  best: healOps('max').some(m => st.on[m.name]), ...d })
        .then(e => { st.entry = e; st.step = next; if (w.isConnected) draw(); if (cast || save) turnUsed(anchor); payCost(); }, () => { st.step = was; if (w.isConnected) draw(); });
    }
    function followUp(action, o) {
      const was = st.step;
      if (action === 'damage') { st.step = 'damage'; st.dmg = null; draw(); }
      return go({ follow: action, parent: st.entry.id, entry: st.entry, extras: [], ...o }).then(e => {
        st.entry = e;
        if (action === 'damage') st.dmg = e.damage;
        st.step = action === 'damage' ? 'damage' : 'result';
        if (w.isConnected) draw();
      }, () => { st.step = was; if (w.isConnected) draw(); });
    }
    w.addEventListener('change', ev => {
      if (ev.target.matches('[data-card-slot]')) { st.level = +ev.target.value; draw(); }
      if (ev.target.matches('[data-ride-way]')) { st.way[ev.target.dataset.rideWay] = +ev.target.value; draw(); }
    });
    w.addEventListener('input', ev => { if (ev.target.matches('[data-card-for]')) st.forText = ev.target.value; });  // (kept as you type, not redrawn)
    w.addEventListener('click', ev => {
      const b = ev.target.closest('button');
      if (!b || st.busy || b.disabled) return;
      if (b.classList.contains('rp-x') || b.hasAttribute('data-done')) return closeWin();
      if (b.hasAttribute('data-missed')) {  // (kept with the roll: it missed; a damage roll marks a hit by itself)
        if (spec.shared && st.entry && st.entry.id && st.entry.kind === 'attack') fetch('/rolls/' + st.entry.id + '/outcome', { method: 'POST', body: new URLSearchParams({ outcome: 'miss' }), headers: { 'X-Requested-With': 'fetch' } }).catch(() => {});
        closeWin(); toast(plan.name + ': missed', null, 'info'); return;
      }
      if (b.dataset.choice) {
        if (b.dataset.choice === 'damage') { st.step = 'attack'; return draw(); }
        st.step = 'rolling'; draw();
        const name = (choice.options.find(x => x.key === b.dataset.choice) || {}).name;
        return go({ kind: 'dc', label: name, mod: '', dmg: '', mode: 'normal', extras: [] }).then(e => { st.entry = e; st.step = 'done'; if (w.isConnected) draw(); payCost(); }, () => { st.step = 'choose'; draw(); });
      }
      if (b.dataset.mode) { st.mode = b.dataset.mode; return draw(); }
      if (b.hasAttribute('data-drama')) { st.drama = !st.drama; if (st.drama && to !== 'table') { to = 'table'; store.set(TO, to); } return draw(); }
      if (b.hasAttribute('data-vis-open')) { st.visOpen = true; return draw(); }
      if (b.hasAttribute('data-ends-hidden')) { st.hidden = !st.hidden; return draw(); }
      if (b.dataset.cardEv != null) { st.ev = +b.dataset.cardEv; return draw(); }
      if (b.dataset.to) { to = b.dataset.to; store.set(TO, to); st.visOpen = false; return draw(); }
      if (b.dataset.pre) { st.pre[b.dataset.pre] = !st.pre[b.dataset.pre]; return draw(); }
      if (b.dataset.selfHeal) {  // (Blessed Healer: your own Hit Points, through the hit points window's own route)
        st.selfHealed = true; draw();
        fetch('/characters/' + spec.cid + '/hp/apply', { method: 'POST', headers: { 'X-Requested-With': 'fetch' },
                                                          body: new URLSearchParams({ mode: 'heal', amount: b.dataset.selfHeal, type: '' }) })
          .then(r => {
            if (!r.ok) return r.json().catch(() => ({})).then(j => { throw new Error(j.detail || "askdnd couldn't heal you"); });
            const t = r.headers.get('HX-Trigger');
            if (t) { try { Object.entries(JSON.parse(t)).forEach(([k, v]) => { if (k !== 'closePanel') document.body.dispatchEvent(new CustomEvent(k, { detail: v })); }); } catch (err) { /* nothing more */ } }
          })
          .catch(err => { st.selfHealed = false; if (w.isConnected) draw(); toast(b.dataset.selfName + ': ' + err.message, null, 'warn'); });
        return;
      }
      if (b.dataset.pay != null) { st.pay[+b.dataset.pay] = !st.pay[+b.dataset.pay]; return draw(); }
      if (b.dataset.on) { st.on[b.dataset.on] = !st.on[b.dataset.on]; return draw(); }
      if (b.dataset.unadd != null) { st.added.splice(+b.dataset.unadd, 1); return draw(); }
      if (b.hasAttribute('data-adding')) { st.adding = !st.adding; return draw(); }
      if (b.dataset.add) {
        const v = b.dataset.add, list = b.closest('[data-adder]').dataset.adder, x = 'Added:' + (v.startsWith('-') ? v : '+' + v.replace(/^\+/, ''));
        st.adding = false;
        if (list === 'bonus') return followUp('bonus', { extras: [x], bonusLabel: 'Added', die: 4 });
        st.added.push(x);
        return draw();
      }
      if (b.hasAttribute('data-roll-hit')) return rollHit();
      if (b.hasAttribute('data-roll-single') || b.hasAttribute('data-again')) return rollOne('done');
      if (b.hasAttribute('data-roll-save')) return rollOne('saved');
      if (b.hasAttribute('data-reroll')) return followUp('reroll', { reason: st.entry.can.reroll });
      if (b.dataset.after) { const m = mods.find(x => x.name === b.dataset.after); return followUp('bonus', { extras: [(m.short || m.name) + ':+' + m.adds], bonusLabel: m.short || m.name, die: 4 }); }
      if (b.dataset.ride) { st.ride[b.dataset.ride] = !st.ride[b.dataset.ride]; return draw(); }
      if (b.hasAttribute('data-roll-dmg')) return rollDamage();
    });
    draw();
    // A follow-up from Table rolls: what was pressed there happens now (damage, a reroll), or + a die opens its dice
    if (from) {
      if (from.action === 'damage') followUp('damage', {});
      else if (from.action === 'reroll') followUp('reroll', { reason: (from.entry.can || {}).reroll || '' });
      return;
    }
    // Cast and roll: the spell is cast, so healing, damage or a save spell's damage rolls now (one effect to roll; a
    // spell with a choice of effects asks Which first). Shift-click: the first roll at once, as it stands.
    const auto = ((spec.cast || spec.used) && (single || save) && effs.length <= 1) || (spec.shift && st.step !== 'choose');
    if (auto) (w.querySelector('[data-roll-single], [data-roll-save], [data-roll-hit]') || { click() {} }).click();
  }

  // ---------------------------------------------------------------- rolling
  // A roll's number waits in Table rolls until its dice land (Brett, 2026-10-29: it showed before the roll was done),
  // however its row arrived (your own answer, the live update, the slow poll): the rolls being thrown, by id
  const LANDING = window.askdndLanding = window.askdndLanding || new Set();
  function markLanding() {
    document.querySelectorAll('#roll-log .roll-item[data-id]').forEach(li => li.classList.toggle('landing', LANDING.has(li.dataset.id)));
  }
  function throwing(id) {
    LANDING.add(String(id)); markLanding();
    setTimeout(() => landed(id), 9000);  // (whatever happens to the throw, the number shows)
  }
  function landed(id) { if (LANDING.delete(String(id))) markLanding(); }
  window.askdndThrowing = { throwing, landed, markLanding };
  // A window whose words couldn't be fetched (Cast, Use, a rest): says so, with Try again
  function useFailed(w, text, retry) {
    if (!w.isConnected) return;
    w.innerHTML = '<button type="button" class="rp-x" aria-label="Close">×</button><p class="rw-note">' + esc(text) + '</p><div class="rcard-acts"><button type="button" class="btn small" data-retry>Try again</button></div>';
    w.querySelector('[data-retry]').onclick = retry;
    place(w);
  }
  // ---------------------------------------------------------------- dice you can see
  // (Brett, 2026-10-23; docs/mockups/dice-on-screen.html, option A) Faceted gem dice drawn with the roll's real
  // values: your own roll tumbles into the middle of the page and lands, with a card saying what it was (click
  // anywhere to skip); someone else's gets a small die in its notice. Gold for d20s, red for damage, green for
  // healing; a natural 20 glows, a natural 1 goes dull. Only with the animation switch on (Table rolls sidebar).
  const pt = (r, deg) => [50 + r * Math.cos(deg * Math.PI / 180), 50 + r * Math.sin(deg * Math.PI / 180)].map(n => n.toFixed(1)).join(',');
  const GEM = {  // each die seen face-on, in a 100×100 box: [points, light] for each face, and where its number sits
    20: { y: 55, faces: [['7,26 50,2 50,24', 'hi'], ['50,2 93,26 50,24', 'hi'], ['7,26 50,24 23,70', 'mid'], ['93,26 77,70 50,24', 'mid'],
      ['7,26 23,70 7,74', 'lo'], ['93,26 93,74 77,70', 'lo'], ['7,74 23,70 50,98', 'lo'], ['93,74 50,98 77,70', 'lo'],
      ['23,70 77,70 50,98', 'lo'], ['50,24 77,70 23,70', 'top']] },
    12: { y: 52, faces: [0, 1, 2, 3, 4].map(i => [[pt(27, -90 + 72 * i), pt(48, -90 + 72 * i), pt(48, -54 + 72 * i), pt(48, -18 + 72 * i), pt(27, -18 + 72 * i)].join(' '),
      ['hi', 'mid', 'lo', 'lo', 'hi'][i]]).concat([[[0, 1, 2, 3, 4].map(i => pt(27, -90 + 72 * i)).join(' '), 'top']]) },
    10: { y: 40, faces: [['50,2 28,52 4,46', 'hi'], ['50,2 96,46 72,52', 'mid'], ['4,46 28,52 50,64 50,98', 'lo'], ['96,46 50,98 50,64 72,52', 'lo'], ['50,2 72,52 50,64 28,52', 'top']] },
    8: { y: 40, faces: [['50,4 6,50 50,62', 'hi'], ['50,4 94,50 50,62', 'mid'], ['6,50 50,96 50,62', 'lo'], ['94,50 50,62 50,96', 'lo'], ['50,4 22,52 78,52', 'top']] },
    6: { y: 50, faces: [['6,6 94,6 80,20 20,20', 'hi'], ['6,6 20,20 20,80 6,94', 'mid'], ['94,6 94,94 80,80 80,20', 'lo'], ['6,94 20,80 80,80 94,94', 'lo'], ['20,20 80,20 80,80 20,80', 'top']] },
    4: { y: 64, faces: [['50,4 4,92 28,78 50,36', 'hi'], ['50,4 50,36 72,78 96,92', 'mid'], ['4,92 96,92 72,78 28,78', 'lo'], ['50,36 72,78 28,78', 'top']] },
  };
  const sidesOf = f => { const s = +((/d(\d+)/.exec(f || '') || [])[1] || 6); return GEM[s] ? s : s === 100 ? 10 : s > 12 ? 20 : s > 6 ? 8 : 6; };
  function gem(sides, value, look, size) {
    const g = GEM[GEM[sides] ? sides : 6], d = document.createElement('div');
    d.className = 'gem ' + look + (size ? ' ' + size : '');
    d.innerHTML = '<span class="gem-shadow"></span><span class="gem-body"><svg viewBox="0 0 100 100" aria-hidden="true">'
      + g.faces.map(([p, t]) => '<polygon class="f-' + t + '" points="' + p + '"/>').join('') + '</svg><b class="gem-n" style="top:' + g.y + '%"></b></span>';
    d._value = value; d._sides = sides;
    return d;
  }
  // Spin a die in: its number flickers while it tumbles, then it lands on its value
  function tumble(d, delay, ms) {
    const n = d.querySelector('.gem-n');
    d.style.setProperty('--delay', delay + 'ms');
    d.classList.add('rolling');
    const t = setInterval(() => { n.textContent = 1 + Math.floor(Math.random() * d._sides); }, 60);
    return new Promise(res => { d._land = () => { clearInterval(t); n.textContent = d._value; d.classList.remove('rolling'); d.classList.add('landed'); res(); };
      d._timer = setTimeout(d._land, ms + delay); });
  }
  function sparks(d) {
    for (let i = 0; i < 10; i++) { const s = document.createElement('i'); s.className = 'gem-spark'; s.style.setProperty('--a', (i * 36) + 'deg'); d.append(s); }
  }
  // Which dice a result shows: the d20s (both, with Advantage; one per ray), or every damage or healing die
  function diceFor(e, focus) {
    const heal = ['heal', 'temp'].includes(e.kind);
    if (focus === 'bonus' && e.bonus) return (e.bonus.dice || []).length ? [{ s: sidesOf(e.bonus.formula), v: e.bonus.dice[0], look: 'gold' }] : [];  // (a plain +10, Guided Strike: no die to throw)
    const p = focus === 'damage' && e.damage ? e.damage : e.main;
    if (p === e.main && D20.includes(e.kind)) {
      const rays = (p.parts || []).filter(x => x.kept != null), src = rays.length > 1 ? rays : [p];
      return src.flatMap(r => [...r.dice.map((v, i) => ({ s: 20, v, look: 'gold', off: r.dice.length > 1 && i !== r.kept_at,
                                                         nat: r.dice.length > 1 && i !== r.kept_at ? null : v === 20 ? 20 : v === 1 ? 1 : null })),
                                ...(r.extras || []).flatMap(x => (x.dice || []).map(v => ({ s: sidesOf(x.formula), v, look: 'gold' })))]);
    }
    const lines = p.parts && p.parts.length ? p.parts : [p], look = heal ? 'jade' : e.kind === 'dice' ? 'gold' : 'ruby';
    return [...lines.flatMap(ln => ln.dice.map(v => ({ s: sidesOf(ln.formula), v, look }))),
            ...(p.extras || []).flatMap(x => (x.dice || []).map(v => ({ s: sidesOf(x.formula), v, look })))];
  }
  let stageEl = null;
  function stageClear() { if (stageEl) { stageEl.querySelectorAll('.gem').forEach(d => { clearTimeout(d._timer); if (d._land) d._land(); }); stageEl.remove(); stageEl = null; } }
  function stage(e, focus) {
    stageClear();
    const all = diceFor(e, focus), dice = all.slice(0, 12);
    if (!dice.length) return Promise.resolve();
    const el = stageEl = document.createElement('div');
    el.className = 'dice-stage';
    el.setAttribute('aria-hidden', 'true');  // the roll window says the same in words
    el.innerHTML = '<div class="ds-dice"></div><div class="ds-card"></div>';
    const box = el.querySelector('.ds-dice');
    const landing = dice.map((x, i) => {
      const d = gem(x.s, x.v, x.look + (x.off ? ' off' : '') + (x.nat === 20 ? ' crit' : x.nat === 1 ? ' fumble' : ''), dice.length > 4 ? 'mid' : '');
      d.style.setProperty('--fx', (180 + 70 * (i % 3)) + 'px'); d.style.setProperty('--fy', (140 - 50 * (i % 4)) + 'px');
      d.style.setProperty('--spin', (540 + 180 * (i % 3)) + 'deg');
      box.append(d);
      return tumble(d, i * 90, 850).then(() => { if (x.nat === 20) sparks(d); });
    });
    document.body.append(el);
    const done = Promise.all(landing).then(() => {
      if (el !== stageEl) return;
      const dmg = focus === 'damage' && e.damage, total = dmg ? e.damage.total : focus === 'bonus' && e.bonus ? e.bonus.total : e.total;
      const what = dmg ? (e.damage.crit ? 'Critical damage' : 'Damage') : e.label + (KIND_WORDS[e.kind] || '');
      el.querySelector('.ds-card').innerHTML = '<span class="ds-what">' + esc(what) + (all.length > dice.length ? ' · ' + all.length + ' dice' : '') + '</span><b class="ds-total' + (!dmg && e.nat === 20 ? ' nat20' : !dmg && e.nat === 1 ? ' nat1' : '') + '">' + total + '</b>'
        + (!dmg && e.nat && e.kind !== 'death' ? '<span class="ds-what">Natural ' + e.nat + '</span>' : '');
      el.classList.add('landed');
      setTimeout(() => { if (el === stageEl) { el.classList.add('gone'); setTimeout(() => { if (el === stageEl) stageClear(); }, 400); } }, 2600);
    });
    return Promise.race([done, new Promise(res => { el._skip = res; })]);
  }
  // ---------------------------------------------------------------- thrown dice
  // (Brett, 2026-10-23; docs/mockups/dice-two-ways.html; app/dice.py) Real 3D dice (@3d-dice/dice-box-threejs, vendored)
  // made to land on askdnd's numbers, in the roller's own set. Your roll: thrown across the page, which dims behind it.
  // Someone else's: thrown like yours, with a tag saying who rolled (Brett, 2026-11-03); for a person who chose the dice
  // tray (Labs, Your dice: data-dice's `tray`), a small tray in the bottom-left corner instead, except on askdnd's table
  // (.table-page), where every roll is thrown across the screen. If the dice can't load (an old browser, no WebGL), the
  // gem stage above stands in.
  const LIB = '/static/vendor/dice-box-threejs-0.0.12/';
  const TYPE_SETS = { fire: 'fire', cold: 'ice', radiant: 'radiant', necrotic: 'necrotic', poison: 'poison', acid: 'acid',
                      thunder: 'thunder', lightning: 'lightning', force: 'force', psychic: 'psychic' };
  let libP = null;
  const lib = () => libP || (libP = import(LIB + 'dice-box-threejs.es.js').then(m => m.default));
  const diceOf = el => { try { return JSON.parse(el.dataset.dice || '{}'); } catch (e) { return {}; } };
  const soundOn = () => store.get('askdnd.diceSound') === 'on';
  // How the dice move and how long they stay in each place (mine, tray, vtt): Backstage › Dice tuning, on every page as
  // body[data-dice-tuning] (app/dice.py); askdnd's own tuning if it's missing
  const TUNE = { drama: { strength: 0.9, gravity: 120, size: 140, shadows: true, light: 0.8, dim: 75, blur: 4, fade_in: 0.4, stay: 4.5, fade_out: 0.5 },
                 mine: { strength: 1.4, gravity: 300, size: 95, shadows: true, light: 0.7, dim: 55, blur: 2, fade_in: 0.2, stay: 3.2, fade_out: 0.3 },
                 tray: { strength: 1, gravity: 400, size: 60, shadows: false, light: 0.7, slide: 0.3, stay: 2.6 },
                 vtt: { strength: 1.4, gravity: 300, size: 95, shadows: true, light: 0.7, dim: 35, blur: 0, fade_in: 0.2, stay: 3.2, fade_out: 0.3 } };
  const tuning = where => { let t = {}; try { t = JSON.parse(document.body.dataset.diceTuning || '{}'); } catch (e) { /* askdnd's own */ } return { ...TUNE[where], ...(t[where] || {}) }; };
  const sleep = s => new Promise(res => { setTimeout(res, s * 1000); });
  // Every die a result shows, with its real sides and value, and the damage type it belongs to
  function throwList(e, focus) {
    const sides = f => +((/d(\d+)/.exec(f || '') || [])[1] || 6);
    if (focus === 'bonus' && e.bonus) return e.bonus.dice.map(v => ({ s: sides(e.bonus.formula), v }));
    const p = focus === 'damage' && e.damage ? e.damage : e.main;
    if (!p) return [];
    // dice added to the roll (Bless's d4, Hunter's Mark's d6) are thrown with it (Brett, 2026-10-29)
    const added = r => (r.extras || []).filter(x => (x.dice || []).length).flatMap(x => x.dice.map(v => ({ s: sides(x.formula), v })));
    if (p === e.main && D20.includes(e.kind)) {
      const rays = (p.parts || []).filter(x => x.kept != null), src = rays.length > 1 ? rays : [p];
      return src.flatMap(r => [...r.dice.map(v => ({ s: 20, v })), ...added(r)]);
    }
    const lines = p.parts && p.parts.length ? p.parts : [p];
    return [...lines.flatMap(ln => ln.dice.map(v => ({ s: sides(ln.formula), v, type: ln.kind }))), ...added(p)];
  }
  // "1d8+2d6@5,4,2": the library merges dice of a size, so each size's values go together, in order
  function notation(list) {
    const order = [], by = {};
    list.slice(0, 20).forEach(d => { if (!by[d.s]) { by[d.s] = []; order.push(d.s); } by[d.s].push(d.v); });
    return order.map(s => by[s].length + 'd' + s).join('+') + '@' + order.flatMap(s => by[s]).join(',');
  }
  function colorset(list, dice) {
    if (dice.by_type !== false) {
      const typed = list.map(d => TYPE_SETS[(d.type || '').toLowerCase()]).filter(Boolean);
      if (typed.length) return typed[0];
    }
    return dice.set || 'white';
  }
  // A dice box in an element of the page, one throw at a time: built again when its tuning's gravity, size or light
  // changes (the library sets those up once), and measured again before each throw (it may have been hidden)
  // Dice thrown across the page are sized to the space they're thrown in (Brett, 2026-10-26: the library draws them
  // a fixed number of points across, small on a big display and big on a phone). Dice tuning's Size is the size at
  // 900 points of room (a 1440×900 window), scaled by the box's shorter side, from 0.55× (phones) to 1.8×.
  const roomFor = host => {
    const squareSide = Math.min(host.clientWidth || innerWidth, host.clientHeight || innerHeight);
    return Math.round(Math.min(1.8, Math.max(0.55, squareSide / 900)) * 20) / 20;  // in steps of 5%, so a small resize doesn't rebuild
  };
  function diceBox(host, opts, tune, relative) {
    if (!host.id) host.id = 'dice-box-' + Math.random().toString(36).slice(2);
    let box = null, built = null, ready = null, queue = Promise.resolve();
    function make(t) {
      // (relative: true, the room the page gives the dice; a number, the width the tuning was made for, so the corner
      // tray's dice grow with it)
      const room = relative === true ? roomFor(host) : relative ? Math.round(Math.min(2, Math.max(1, host.clientWidth / relative)) * 20) / 20 : 1;
      const sig = t ? [t.gravity, t.size, t.shadows, t.light, room].join() : '';
      if (ready && sig === built) return ready;
      built = sig;
      const physics = t ? { gravity_multiplier: t.gravity, baseScale: Math.round(t.size * room), shadows: t.shadows, light_intensity: t.light, strength: t.strength } : {};
      ready = lib().then(DiceBox => { host.innerHTML = ''; box = new DiceBox('#' + host.id, { assetPath: LIB, theme_surface: 'green-felt', theme_colorset: 'white',
        theme_material: 'glass', shadows: true, sounds: false, ...opts, ...physics });
        // A die landing while its material's sounds are still loading (sound() below loads them in the background) made
        // the library look up a list it hadn't made yet and throw mid-roll (Sentry ASKDND-V2-3, 2026-10-29): that hit
        // is silent instead. (Each throw binds box.eventCollide afresh, so this stands in for the library's.)
        const collide = box.eventCollide;
        box.eventCollide = function (ev) {
          if (this.sounds && !(this.sounds_dice.coin && this.sounds_dice[this.sound_dieMaterial] && this.sounds_table[this.surface])) return;
          return collide.call(this, ev);
        };
        // The library draws at one pixel per screen point, so on a Retina screen (2 pixels per point) the dice were
        // drawn at half resolution and stretched, looking soft (Brett, 2026-10-26). Draw at the screen's own
        // resolution, up to 2x: sharper, without the cost of 3x phones or very large screens.
        return box.initialize().then(() => { if (box.renderer) box.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); sound(); (window.askdndDice = window.askdndDice || new Map()).set(host, box); }); });  // (one per place: a rebuilt box replaces its old one, which can then be freed)
      return ready;
    }
    // Sounds (Your dice › Dice sounds, per device). The library loads its sound files only if sound is on when it
    // starts, and its updateConfig can't switch sound on later (it uses Object.apply, not Object.assign), so the
    // dice were silent even with the box ticked (Brett, 2026-10-26). Set it here, and load the files for the dice's
    // material in the background (cached per material; a throw never waits for them).
    function sound() {
      if (!box) return;
      box.sounds = soundOn();
      if (box.sounds) box.loadSounds().catch(() => {});
    }
    make(tune);
    async function go(list, dice, t) {
      await make(t || tune);
      if (t) box.strength = t.strength;
      const c = box.renderer.domElement;
      if (host.clientWidth && (c.clientWidth !== host.clientWidth || c.clientHeight !== host.clientHeight)) box.setDimensions({ x: host.clientWidth, y: host.clientHeight });
      await box.updateConfig({ theme_colorset: colorset(list, dice), theme_material: dice.material || 'glass' });
      sound();
      return box.roll(notation(list));
    }
    return { get ready() { return ready; }, clear: () => box && box.clearDice(),
      throw: (list, dice, before, after, t, until) => (queue = queue.catch(() => {}).then(async () => {
        const late = () => until && (typeof until === 'function' ? until() : Date.now() > until);  // (a time, or a test: a dramatic throw skipped)
        if (late()) return; if (before) await before(); await go(list, dice, t); if (after && !late()) await after(); })) };
  }
  // The page-wide layer: dim, dice, who rolled (others' rolls), and the result card
  let throwEl = null, throwBox = null, throwTimer = null;
  function thrower() {
    if (throwEl) return throwBox;
    throwEl = document.createElement('div');
    throwEl.className = 'dice-throw';
    throwEl.setAttribute('aria-hidden', 'true');  // the roll window and Table rolls say the same in words
    throwEl.innerHTML = '<div class="dt-dim"></div><div class="dt-box"></div><div class="dt-who"></div><div class="dt-card"></div><div class="dt-strip"></div>';
    document.body.append(throwEl);
    throwBox = diceBox(throwEl.querySelector('.dt-box'), {}, tuning('mine'), true);
    return throwBox;
  }
  // The page-wide layer takes this throw's tuning: its fades and the backdrop behind the dice
  function throwTune(t) {
    throwEl._t = t;
    [['--dt-in', t.fade_in + 's'], ['--dt-out', t.fade_out + 's'], ['--dt-dim', t.dim + '%'], ['--dt-blur', t.blur + 'px']].forEach(([k, v]) => throwEl.style.setProperty(k, v));
  }
  function throwDone() { if (!throwEl) return; clearTimeout(throwTimer); throwEl.classList.remove('on', 'landed', 'drama'); throwEl._skip = null;
    throwTimer = setTimeout(() => { if (throwBox && !throwEl.classList.contains('on')) throwBox.clear(); }, ((throwEl._t || TUNE.mine).fade_out + 0.1) * 1000); }
  function throwCard(what, total, nat, sub) {
    throwEl.querySelector('.dt-card').innerHTML = '<span class="ds-what">' + esc(what) + '</span><b class="ds-total' + (nat === 20 ? ' nat20' : nat === 1 ? ' nat1' : '') + '">' + total + '</b>'
      + (sub ? '<span class="ds-what">' + esc(sub) + '</span>' : '');
    throwEl.classList.add('landed');
    clearTimeout(throwTimer);
    throwTimer = setTimeout(throwDone, (throwEl._t || TUNE.mine).stay * 1000);
  }
  // Make it dramatic (Brett chose A and B, Nov 13, docs/mockups/make-it-dramatic/): on every screen, the dice tray too,
  // the roll is thrown big and slow in the middle with who rolled above it, and the number shows only once the die stops.
  // Several attack rolls in one (two beams, three rays) come one at a time, each result kept along the bottom. Esc or a
  // click skips it on your own screen; it plays on for everyone else. Dice tuning's "Dramatic rolls" sets how it moves.
  let dramaRun = 0;
  function throwDrama(e, focus, dice, name) {
    const box = thrower(), t = tuning('drama'), run = ++dramaRun, gone = () => run !== dramaRun;
    const dmg = focus === 'damage' && e.damage;
    const rays = !dmg && D20.includes(e.kind) ? ((e.main && e.main.parts) || []).filter(x => x.kept != null) : [];
    const what = dmg ? (e.damage.crit ? 'critical damage' : 'damage') : e.label + (KIND_WORDS[e.kind] || '');
    const total = dmg ? e.damage.total : focus === 'bonus' && e.bonus ? e.bonus.total : e.total;
    const start = () => {
      clearTimeout(throwTimer);
      throwTune(t);
      throwEl.classList.remove('landed', 'others');
      throwEl.classList.add('on', 'drama');
      throwEl.querySelector('.dt-who').innerHTML = '<span aria-hidden="true">🎬</span><b>' + esc(name || 'You') + '</b> · ' + esc(what);
      throwEl.querySelector('.dt-strip').innerHTML = '';
      throwEl.querySelector('.dt-card').innerHTML = '';
    };
    const end = () => { throwCard((name ? name + ' · ' : '') + what, rays.length > 1 ? rays.map(r => r.total).join(' · ') : total, dmg || rays.length > 1 ? null : e.nat,
                                  !dmg && rays.length <= 1 && e.nat && e.kind !== 'death' ? 'Natural ' + e.nat : ''); throwEl._skip = null; };
    throwEl && (throwEl._skip = null);
    return box.ready.then(() => {
      throwEl._skip = () => { dramaRun++; box.clear(); end(); };
      if (rays.length > 1) {  // (one at a time: the tension builds to the last)
        let chain = Promise.resolve();
        rays.forEach((r, i) => {
          const one = [...r.dice.map(v => ({ s: 20, v })), ...(r.extras || []).filter(x => (x.dice || []).length).flatMap(x => x.dice.map(v => ({ s: +((/d(\d+)/.exec(x.formula) || [])[1] || 6), v })))];
          chain = chain.then(() => box.throw(one, dice, i ? null : start, async () => {
            throwEl.querySelector('.dt-strip').insertAdjacentHTML('beforeend', '<span class="' + (r.kept === 20 ? 'nat20' : r.kept === 1 ? 'nat1' : '') + '">' + esc(r.label || 'Roll ' + (i + 1)) + ': <b>' + r.total + '</b></span>');
            if (i < rays.length - 1) { await sleep(0.8); box.clear(); }
          }, t, gone));
        });
        return chain.then(() => { if (!gone()) end(); });
      }
      return box.throw(throwList(e, focus), dice, start, () => { if (!gone()) end(); }, t, gone);
    });
  }
  function throwMine(e, focus) {
    const list = throwList(e, focus);
    if (!list.length) return Promise.resolve();
    if (e.dramatic) return throwDrama(e, focus, diceOf(document.body), '');
    const box = thrower(), t = tuning('mine');
    return box.ready.then(() => box.throw(list, diceOf(document.body), () => {
      clearTimeout(throwTimer);
      throwTune(t);
      throwEl.classList.remove('landed', 'others');
      throwEl.classList.add('on');
    }, () => {
      const dmg = focus === 'damage' && e.damage;
      const total = dmg ? e.damage.total : focus === 'bonus' && e.bonus ? e.bonus.total : e.total;
      throwCard(dmg ? (e.damage.crit ? 'Critical damage' : 'Damage') : e.label + (KIND_WORDS[e.kind] || ''), total, dmg ? null : e.nat,
                !dmg && e.nat && e.kind !== 'death' ? 'Natural ' + e.nat : '');
    }, t));
  }
  // Someone else's roll: on the whole page (the VTT piece), else in the corner tray. Their dice are live or they're
  // nothing: a throw still waiting after LIVE_MS is dropped, and the roll stays in Table rolls
  const LIVE_MS = 6000;
  let trayEl = null, trayBox = null;
  function tray() {
    if (trayEl) return trayBox;
    trayEl = document.createElement('div');
    trayEl.className = 'dice-tray';
    trayEl.setAttribute('aria-hidden', 'true');
    trayEl.innerHTML = '<div class="dtr-felt"><div class="dtr-box"></div></div><div class="dtr-foot"></div>';
    document.body.append(trayEl);
    trayBox = diceBox(trayEl.querySelector('.dtr-box'), {}, tuning('tray'), 300);  // (Dice tuning's tray is 300 wide)
    return trayBox;
  }
  function throwOthers(li) {
    let t; try { t = JSON.parse(li.dataset.throw || '{}'); } catch (err) { return Promise.reject(err); }
    t.damage = t.dmg;  // (named dmg in the markup)
    const followUp = +li.dataset.seq !== +li.dataset.id && t.damage;
    const list = throwList({ ...t, kind: t.kind }, followUp ? 'damage' : null);
    if (!list.length) return Promise.reject(new Error('nothing to throw'));
    const name = li.querySelector('.roll-who b').textContent, what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const total = followUp ? li.querySelector('.roll-dmg-line > b').textContent : (li.querySelector('.roll-total') || {}).textContent;
    const nat = followUp ? null : li.classList.contains('nat20') ? 20 : li.classList.contains('nat1') ? 1 : null;
    const dice = diceOf(li);
    const swatch = '<i class="sw-' + esc(dice.set || 'white') + '"></i>';
    if (li.dataset.dramatic === '1') {  // (dramatic: the middle of every screen, the dice tray too)
      thrower();
      return throwDrama({ ...t, label: what.replace(/ (to hit|damage|healing)$/, ''), total: +total, nat }, followUp ? 'damage' : null, dice, name);
    }
    if (!diceOf(document.body).tray || document.querySelector('.table-page')) {
      const box = thrower(), tune = tuning('vtt');
      return box.ready.then(() => box.throw(list, dice, () => {
        clearTimeout(throwTimer);
        throwTune(tune);
        throwEl.classList.remove('landed');
        throwEl.classList.add('on', 'others');
        throwEl.querySelector('.dt-who').innerHTML = swatch + '<b>' + esc(name) + '</b> · ' + esc(followUp ? 'damage' : what);
      }, () => { window.askdndThrowing.landed(li.dataset.id); throwCard(name + ' · ' + (followUp ? 'damage' : what), total, nat, nat ? 'Natural ' + nat : ''); }, tune, Date.now() + LIVE_MS));
    }
    const box = tray(), tune = tuning('tray');
    return box.ready.then(() => box.throw(list, dice, async () => {
      trayEl.querySelector('.dtr-foot').innerHTML = swatch + '<span class="dtr-what"><b>' + esc(name) + '</b> · ' + esc(followUp ? 'damage' : what) + '</span><b class="dtr-total">…</b>';
      trayEl.style.setProperty('--dtr-slide', tune.slide + 's');
      trayEl.classList.add('up');
      await sleep(tune.slide);
    }, async () => {
      window.askdndThrowing.landed(li.dataset.id);
      const tot = trayEl.querySelector('.dtr-total');
      tot.textContent = total; tot.classList.toggle('nat20', nat === 20); tot.classList.toggle('nat1', nat === 1);
      await sleep(tune.stay);
      trayEl.classList.remove('up');
      await sleep(tune.slide + 0.05);
      box.clear();
    }, tune, Date.now() + LIVE_MS));
  }
  // Your dice changed (the picker saved): use them from now on
  document.body.addEventListener('diceChanged', ev => {
    const d = ev.detail || {};  // htmx adds the form (elt) to it: keep only the dice
    if (d.set) document.body.dataset.dice = JSON.stringify({ set: d.set, material: d.material, by_type: d.by_type, tray: d.tray });
    const x = document.querySelector('.peek.open .peek-close'); if (x) x.click();
  });
  // The picker: throw a d20 in the preview whenever the set or material changes; sounds are per device
  let pickBox = null;
  function pickPreview(form) {
    const host = form.querySelector('[data-dice-preview]');
    if (!host) return;
    if (!pickBox || !host.isConnected || pickBox.host !== host) { pickBox = diceBox(host, { baseScale: 110 }); pickBox.host = host;
      pickBox.ready.then(() => { const l = host.querySelector('.dp-loading'); if (l) l.remove(); }, () => { const l = host.querySelector('.dp-loading'); if (l) l.textContent = "The dice couldn't load in this browser."; }); }
    const val = n => (form.querySelector('[name=' + n + ']:checked') || {}).value;
    pickBox.throw([{ s: 20, v: 1 + Math.floor(Math.random() * 20) }], { set: val('set'), material: val('material'), by_type: false });
  }
  document.addEventListener('panel:loaded', ev => {
    const form = ev.target.querySelector && ev.target.querySelector('[data-dice-picker]');
    if (!form) return;
    const snd = form.querySelector('[data-dice-sound]'), anim = form.querySelector('[data-dice-anim]');
    snd.checked = soundOn();
    snd.addEventListener('change', () => store.set('askdnd.diceSound', snd.checked ? 'on' : 'off'));
    // Dice animation on this device (it was at the bottom of Table rolls; Table rolls reads the same setting)
    const calmQ = window.matchMedia('(prefers-reduced-motion: reduce)'), was = store.get('askdnd.rollsAnim');
    anim.checked = was ? was === 'on' : !calmQ.matches;
    anim.addEventListener('change', () => store.set('askdnd.rollsAnim', anim.checked ? 'on' : 'off'));
    form.addEventListener('change', ev2 => { if (ev2.target.name === 'set' || ev2.target.name === 'material') pickPreview(form); });
    // In Table rolls' Roll window, Your dice is its second tab: the dice load once that tab is shown, not with Roll
    const tab = form.closest('[hidden]');
    if (tab) tab.addEventListener('tab:shown', () => pickPreview(form), { once: true });
    else pickPreview(form);
  });

  // ---------------------------------------------------------------- Dice tuning
  // Backstage › askdnd › Dice tuning (manage_dice.html, app/dice.py): a tab per place dice are thrown, sliders that show
  // their value and mark changes against what's saved, and a preview that throws with the sliders as they are now.
  const tuneShow = (v, how) => how === 'toggle' ? (v ? 'on' : 'off') : how === 'x' ? v.toFixed(1) + '×' : how === 'pct' ? Math.round(v * 100) + '%'
    : (how === 's' || how === 'px') ? +v.toFixed(2) + ' ' + how : +v.toFixed(2) + how;
  const TUNE_ROLLS = { d20: { what: 'Dexterity save', list: [{ s: 20, v: 14 }], total: 17, nat: 'Natural 14' },
    adv: { what: 'Shillelagh to hit · Advantage', list: [{ s: 20, v: 19 }, { s: 20, v: 6 }], total: 26, nat: 'Natural 19' },
    fireball: { what: 'Fireball damage', list: [6, 2, 5, 4, 3, 6, 1, 5].map(v => ({ s: 6, v, type: 'fire' })), total: 32, nat: '' } };
  function tuner(root) {
    const form = root.querySelector('form'), tnStage = root.querySelector('.tn-stage'), layer = tnStage.querySelector('.tn-layer');
    const tnTray = tnStage.querySelector('.tn-tray'), read = root.querySelector('[data-read]');
    let tnPlace = 'mine', full = false, dirty = false;
    const rows = () => [...form.querySelectorAll('.tn-row')];
    const value = row => row.querySelector('.switch') ? row.querySelector('.switch').getAttribute('aria-checked') === 'true' : +row.querySelector('input[type=range]').value;
    function set(row, v) {
      const sw = row.querySelector('.switch');
      if (sw) { sw.setAttribute('aria-checked', v); row.querySelector('input[type=hidden]').value = v ? '1' : ''; } else row.querySelector('input[type=range]').value = v;
      show(row);
    }
    function show(row) {
      const v = value(row), saved = JSON.parse(row.dataset.saved), out = row.querySelector('output');
      if (out) out.textContent = tuneShow(v, row.dataset.how);
      row.classList.toggle('changed', v !== saved);
      row.querySelector('.tn-reset').hidden = v === saved;
      const n = rows().filter(r => r.classList.contains('changed')).length;
      dirty = n > 0;
      form.querySelector('[data-changes]').textContent = n ? n + (n === 1 ? ' change' : ' changes') + ', not saved' : 'No changes';
      form.querySelector('[data-save]').disabled = form.querySelector('[data-undo]').disabled = !n;
    }
    const values = p => Object.fromEntries([...form.querySelectorAll('[data-place-panel="' + p + '"] .tn-row')].map(r => [r.dataset.k, value(r)]));
    rows().forEach(row => {
      const sw = row.querySelector('.switch'), range = row.querySelector('input[type=range]');
      if (range) row.querySelector('.tn-range').style.setProperty('--now', (JSON.parse(row.dataset.saved) - range.min) / (range.max - range.min));  // the tick
      if (sw) sw.addEventListener('click', () => set(row, !value(row)));
      else range.addEventListener('input', () => show(row));
      row.querySelector('.tn-reset').addEventListener('click', () => set(row, JSON.parse(row.dataset.saved)));
    });
    form.querySelector('[data-undo]').addEventListener('click', () => rows().forEach(r => set(r, JSON.parse(r.dataset.saved))));
    form.addEventListener('submit', () => { dirty = false; });
    window.addEventListener('beforeunload', e => { if (dirty) e.preventDefault(); });
    form.querySelectorAll('[data-place]').forEach(a => a.addEventListener('click', e => {
      e.preventDefault();
      tnPlace = tnStage.dataset.stage = a.dataset.place;
      form.querySelectorAll('[data-place]').forEach(x => x.classList.toggle('on', x === a));
      form.querySelectorAll('[data-place-panel]').forEach(p => { p.hidden = p.dataset.placePanel !== tnPlace; });
      read.innerHTML = '<span>Press Throw to time it.</span>';
    }));
    // The preview: the same dice and steps as the real throws above, with the sliders' values
    const pageBox = diceBox(tnStage.querySelector('.tn-dice'), {}, values('mine'), true), tnTrayBox = diceBox(tnStage.querySelector('#tn-dice-tray'), {}, values('tray'));
    const loading = tnStage.querySelector('.tn-loading');
    pageBox.ready.then(() => loading.remove(), () => { loading.textContent = "The dice couldn't load in this browser."; });
    const timed = (parts) => { read.innerHTML = parts.map(([w, s]) => '<span>' + w + ' <b>' + s.toFixed(1) + ' s</b></span>').join(''); };
    let t0 = 0;
    function throwPreview(key) {
      const r = TUNE_ROLLS[key], p = tnPlace, t = values(p), big = full, mine = diceOf(document.body);
      const dice = p === 'mine' ? mine : { set: 'starynight', material: 'glass', by_type: true };
      if (p === 'tray') {
        return tnTrayBox.throw(r.list, dice, async () => {
          tnStage.classList.toggle('full', big);
          tnTray.querySelector('.dtr-foot').innerHTML = '<i class="sw-starynight"></i><span class="dtr-what"><b>Ilsa</b> · ' + esc(r.what) + '</span><b class="dtr-total">…</b>';
          tnTray.style.setProperty('--dtr-slide', t.slide + 's');
          tnTray.classList.add('up');
          await sleep(t.slide);
          t0 = performance.now();
        }, async () => {
          const settleSecs = (performance.now() - t0) / 1000;
          tnTray.querySelector('.dtr-total').textContent = r.total;
          timed([['Dice settled in', settleSecs], ['Total up for', t.stay], ['On screen in all', t.slide * 2 + settleSecs + t.stay]]);
          await sleep(t.stay);
          tnTray.classList.remove('up');
          await sleep(t.slide + 0.05);
          tnTrayBox.clear();
          tnStage.classList.remove('full');
        }, t);
      }
      return pageBox.throw(r.list, dice, () => {
        tnStage.classList.toggle('full', big);
        [['--dt-in', t.fade_in + 's'], ['--dt-out', t.fade_out + 's'], ['--dt-dim', t.dim + '%'], ['--dt-blur', t.blur + 'px']].forEach(([k, v]) => layer.style.setProperty(k, v));
        layer.querySelector('.tn-who span').textContent = r.what;
        layer.classList.remove('landed');
        layer.classList.add('on');
        t0 = performance.now();
      }, async () => {
        const settleSecs = (performance.now() - t0) / 1000;
        layer.querySelector('.tn-card').innerHTML = '<span class="ds-what">' + (p === 'vtt' ? 'Ilsa · ' : '') + esc(r.what) + '</span><b class="ds-total">' + r.total + '</b>'
          + (r.nat ? '<span class="ds-what">' + r.nat + '</span>' : '');
        layer.classList.add('landed');
        timed([['Dice settled in', settleSecs], ['Result up for', t.stay], ['On screen in all', t.fade_in + settleSecs + t.stay + t.fade_out]]);
        await sleep(t.stay);
        layer.classList.remove('on', 'landed');
        await sleep(t.fade_out + 0.1);
        pageBox.clear();
        tnStage.classList.remove('full');
      }, t);
    }
    root.querySelectorAll('[data-throw]').forEach(b => b.addEventListener('click', () => throwPreview(b.dataset.throw).catch(() => {
      read.innerHTML = "<span>The dice couldn't be thrown in this browser.</span>"; tnStage.classList.remove('full'); })));
    const fullBtn = root.querySelector('[data-full]');
    fullBtn.addEventListener('click', () => { full = !full; fullBtn.setAttribute('aria-pressed', full); });
  }
  document.querySelectorAll('[data-dice-tuner]').forEach(tuner);

  // Click or a key anywhere: land now and clear the stage (the roll window keeps the result)
  ['pointerdown', 'keydown'].forEach(t => document.addEventListener(t, () => {
    if (stageEl) { const s = stageEl._skip; stageClear(); if (s) s(); }
    if (throwEl && throwEl.classList.contains('landed')) throwDone();  // thrown dice: once they've landed, a click clears them
    else if (throwEl && throwEl._skip) throwEl._skip();  // (a dramatic throw: skipped on this screen, straight to its result)
  }, true));

  function payload(go) {
    const p = new URLSearchParams();
    if (go.follow) {
      p.set('parent', go.parent); p.set('action', go.follow);
      if (go.follow === 'reroll') p.set('label', go.reason);
      if (go.follow === 'bonus') { p.set('die', go.die); p.set('label', go.bonusLabel || 'Added die'); }
      if (go.follow === 'damage') { if (go.asType) p.set('as_type', go.asType); if (go.twice) p.set('twice', 1); }  // (riders: Empowered Strikes, Savage Attacker)
      if (go.follow === 'save') p.set('label', go.label);  // (a rider's save: Stunning Strike; askdnd works out its DC)
    } else {
      Object.entries({ character: go.cid || '', kind: go.kind, label: go.label, mod: go.mod || '', dmg: go.dmg || '', mode: go.mode, to,
                       count: go.count || 1, each: go.each || '', once: go.once ? 1 : '', who: go.who || '', token: go.token || '' }).forEach(([k, v]) => p.set(k, v));
      (go.parts || []).forEach(x => p.append('part', x));
      (go.dmgParts || []).forEach(x => p.append('dmg_part', x));
      // What else the card or window knew, kept with the roll (Brett's round 2 note: every roll keeps its flavor as data):
      // the level it was cast at, Advantage's or Disadvantage's reasons (kept only when the mode isn't Normal), riders, Hidden
      if (go.level) p.set('level', go.level);
      (go.advWhy || '').split('\n').filter(Boolean).forEach(t => p.append('why', t.startsWith('!dis ') ? 'Disadvantage: ' + t.slice(5)
        : t.startsWith('!note ') ? t.slice(6) : 'Advantage: ' + t.replace(/^advantage\s*/i, '')));
      (go.riders || []).forEach(x => p.append('rider', x));
      if (go.endsHidden) p.set('hidden', 1);
      if (go.self) p.set('self', 1);  // (healing only its roller takes: Apply to offers only them)
      if (go.math) p.set('math', JSON.stringify(go.math));  // (how its numbers add up, kept with it: Show the Math, app/roll_math.py)
      if (go.dramatic && to === 'table') p.set('dramatic', 1);
      if (go.best) p.set('best', 1);  // (every healing die at its highest: Supreme Healing)  // (Make it dramatic: every screen throws it big and slow)
    }
    (go.extras || []).forEach(x => p.append('extra', x));
    if (go.via) p.set('via', go.via);  // (the roll card: counted as its own, app/usage.py)
    return p;
  }
  // A roll's whole journey, whatever shows it (the roll window, the roll card): rolled by the server for the table (or in
  // this browser for someone else's character), into the log, its dice thrown, into D&D Beyond's Game Log. Resolves
  // with the roll; rejects with a message (err.said) or a failure to reach askdnd.
  function sendRoll(go) {
    if (!go.shared) {
      const before = go.follow ? go.entry._death : undefined;
      const e = go.follow ? privateFollow(go.entry, go.follow, { extras: go.extras, reason: go.reason, die: go.die, label: go.bonusLabel, ctx: go.ctx, twice: go.twice, asType: go.asType })
                          : privateRoll(go);
      if (!e) return Promise.reject(Object.assign(new Error("Those dice don't look right."), { said: true, local: true }));
      if (e.kind === 'death' && go.follow !== 'damage') deathPrivate(go.cid, e, before);
      endHidden(go);
      return Promise.resolve(e);
    }
    const pending = !go.follow && logShown() && log ? placeholder(go.label) : null;
    return fetch('/rolls', { method: 'POST', body: payload(go), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw Object.assign(new Error(j.error || "askdnd couldn't roll that"), { said: true }); return j; }))
      .then(j => {
        if (pending) pending.remove();
        if (animate()) window.askdndThrowing.throwing(j.roll.id);
        addToLog(j.html, j.roll.id);
        endHidden(go);
        deathMarked(j.death);
        // A familiar's Initiative, rolled with its character's (app/initiative.py): its row too, and a word on it
        (j.also || []).forEach(a => { addToLog(a.html, a.roll.id); toast(a.who + "'s Initiative: " + a.roll.total, null, 'info'); });
        // Into D&D Beyond's Game Log too, as askdnd's (app/gamelog.py): the extension sends it from this player's sheet
        if (j.gamelog) window.postMessage({ askdndBridge: 'gamelog', ddbId: j.gamelog.ddbId, messages: j.gamelog.messages }, location.origin);
        return j.roll;
      }, err => { if (pending) pending.remove(); throw err; });
  }
  // Hidden ends with the attack (app/hiding.py), once it's rolled: the window's tick, which the DM may overrule
  function endHidden(go) {
    if (!(go.endsHidden && !go.follow && go.cid)) return;
    if (window.htmx && document.querySelector('#battle-body[data-character="' + go.cid + '"]')) {
      htmx.ajax('POST', '/characters/' + go.cid + '/conditions/end', { values: { name: 'Invisible' }, target: '#battle-body', swap: 'outerHTML' });
    } else {  // (rolled away from Battle, from Search: the page and its open panels show the new copy)
      fetch('/characters/' + go.cid + '/conditions/end', { method: 'POST', credentials: 'same-origin', body: new URLSearchParams({ name: 'Invisible' }) })
        .then(r => { if (r.ok) document.body.dispatchEvent(new CustomEvent('characterChanged')); });
    }
  }
  // A death save marks itself on the sheet (app/death_saves.py; Brett, 2026-10-29): a roll at the table is marked by
  // the server, which answers with what it marked; a private one says its result here. A reroll or an added die moves
  // the mark (`before`: what the roll counted as).
  function deathMarked(d) {  // (and a Hide roll's Hidden, or not: app/hiding.py)
    if (!d) return;
    toast(d.text);
    if (d.deliver) document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: d.deliver }));
    document.body.dispatchEvent(new CustomEvent('characterChanged'));
  }
  function deathPrivate(cid, e, before) {
    const result = e.nat === 20 ? 'nat20' : e.nat === 1 ? 'nat1' : e.total >= 10 ? 'success' : 'failure';
    if (!cid || result === before) return;
    fetch('/characters/' + cid + '/death', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                                            body: new URLSearchParams({ result, replaces: before || '' }) })
      .then(r => r.status === 200 ? r.json() : null)
      .then(j => { if (j && j.text) { e._death = result; deathMarked(j); } })
      .catch(() => {});
  }
  // Using an item (app/item_use.py; Brett, 2026-10-30): its button opens the roll window with what the server says, and
  // the window's Drink, Read, Use or Give makes it. A heal is thrown and logged as a roll is.
  function openUse(btn) {
    const w = openWin(btn);
    w.setAttribute('aria-label', btn.getAttribute('aria-label') || btn.textContent.trim());
    w._use = btn.dataset.useUrl;
    fetch(w._use, { headers: { 'X-Requested-With': 'fetch' } })
      .then(r => { if (!r.ok) throw new Error(); return r.text(); })
      .then(html => { if (win === w) { w.innerHTML = html; if (window.htmx) htmx.process(w); coinsWin(w); place(w, btn); w.querySelector('[autofocus]')?.focus(); } })
      .catch(() => { if (win === w) useFailed(w, "Couldn't reach askdnd.", () => openUse(btn)); });
  }
  // The Coins window (app/coins.py; docs/mockups/coins/ A): its button says what it will do ("Spend 25 gp"), and a line
  // says what happens before it does: change made from a place's other coins, not enough there, or a move's result.
  // The server decides the same things again (app/inventory.py).
  const COIN_CP = { cp: 1, sp: 10, ep: 50, gp: 100, pp: 1000 }, COIN_ORDER = ['pp', 'gp', 'ep', 'sp', 'cp'];
  function coinWords(c) { return COIN_ORDER.filter(k => c[k]).map(k => c[k].toLocaleString() + ' ' + k).join(', ') || 'no coins'; }
  function coinsWin(w) {
    const cw = w && w.querySelector('.coins-win');
    if (!cw || !cw.dataset.places) return;
    if (!cw._wired) { cw._wired = true; cw.addEventListener('input', () => coinsWin(w)); cw.addEventListener('change', () => coinsWin(w)); }
    let places = {};
    try { places = JSON.parse(cw.dataset.places); } catch (err) { return; }
    const val = n => (cw.querySelector('[name="' + n + '"]:checked') || cw.querySelector('select[name="' + n + '"], input[name="' + n + '"]:not([type=radio])') || {}).value;
    const doing = cw.dataset.do, n = Math.max(0, parseInt(val('amount'), 10) || 0), coin = val('coin') || 'gp';
    const go = cw.querySelector('[data-coins-go]'), said = cw.querySelector('[data-coins-said]');
    if (!go) return;
    const verb = doing.charAt(0).toUpperCase() + doing.slice(1);
    go.textContent = n ? verb + ' ' + n.toLocaleString() + ' ' + coin : verb;
    let say = '', ok = n > 0;
    if (doing === 'spend' && n) {
      const p = places[val('place') || 'me'], have = p.coins[coin] || 0;
      const worth = Object.keys(COIN_CP).reduce((t, k) => t + (p.coins[k] || 0) * COIN_CP[k], 0);
      if (have < n && worth >= n * COIN_CP[coin]) say = p.name + ' has ' + have.toLocaleString() + ' ' + coin + ': askdnd makes change from its other coins.';
      else if (have < n) { say = p.name + " hasn't that much, even making change."; ok = false; }
    }
    if (doing === 'move') {
      const from = cw.querySelector('select[name="from"]'), into = cw.querySelector('select[name="into"]');
      [...into.options].forEach(o => { o.hidden = o.disabled = o.value === from.value; });
      if (into.value === from.value) into.value = [...into.options].find(o => !o.disabled)?.value || '';
      const a = places[from.value], b = places[into.value];
      if (!a || !b) ok = false;
      else if (n && (a.coins[coin] || 0) < n) { say = a.name + ' has ' + (a.coins[coin] || 0).toLocaleString() + ' ' + coin + '.'; ok = false; }
      else if (n) {
        const after = (p, d) => ({ ...p.coins, [coin]: (p.coins[coin] || 0) + d });
        say = 'Afterwards: ' + a.name + ' ' + coinWords(after(a, -n)) + ' · ' + b.name + ' ' + coinWords(after(b, n));
      }
    }
    go.disabled = !ok;
    said.textContent = say;
    said.hidden = !say;
  }
  function swapUse(w, url) {
    w._use = url;
    fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(r => { if (!r.ok) throw new Error(); return r.text(); })
      .then(html => { if (win === w) { w.innerHTML = html; if (window.htmx) htmx.process(w); coinsWin(w); place(w); w.querySelector('[autofocus]')?.focus(); } })
      .catch(() => { if (win === w) useFailed(w, "Couldn't reach askdnd.", () => swapUse(w, url)); });
  }
  // The hit points window in it: its working redraws as you type, and taking it closes it
  document.body.addEventListener('htmx:afterSwap', e => { if (win && win.contains(e.target)) place(win); });
  document.body.addEventListener('closePanel', () => setTimeout(() => { if (win && win.querySelector('.hp-form')) closeWin(); }));  // (after the answer's other events: they start from the form)
  function posted(url, fields) {
    return fetch(url, { method: 'POST', body: new URLSearchParams(fields), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.detail || j.error || "askdnd couldn't do that"); return j; }));
  }
  // Your scratch pad's + Add (app/turn_bar.py): opens upward from the bar, or downward when there isn't room above it
  // (under the menu bar), and never taller than the room it has
  document.addEventListener('toggle', e => {
    const d = e.target;
    if (!(d.matches && d.matches('.tbar-add')) || !d.open) return;
    const m = d.querySelector('.tbar-add-menu'), r = d.getBoundingClientRect();
    const top = (document.querySelector('.topbar') || { getBoundingClientRect: () => ({ bottom: 64 }) }).getBoundingClientRect().bottom;
    const above = r.top - top - 12, below = innerHeight - r.bottom - 12;
    const down = above < 220 && below > above;
    m.classList.toggle('down', down);
    m.style.maxHeight = Math.max(160, Math.min(320, down ? below : above)) + 'px';
  }, true);
  // Your turn's bar on askdnd's table (app/turn_bar.py): a roll, Cast or Use made from one of its rows marks that row's
  // Action, Bonus Action or Reaction used (pressing the mark unticks it); askdnd counts, never stops you
  function turnUsed(anchor) {
    const it = anchor && anchor.closest && anchor.closest('[data-turn-cost]'), bar = it && it.closest('#turn-bar');
    if (!bar) return;
    // (rolled from your scratch pad: its line is ticked too)
    fetch('/characters/' + bar.dataset.character + '/turn', { method: 'POST', body: new URLSearchParams({ what: 'use', cost: it.dataset.turnCost, n: '1', pad: it.dataset.padKey || '' }), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => { if (r.ok) document.body.dispatchEvent(new CustomEvent('characterChanged')); });
  }
  function itemChanged(j) {
    document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: j.deliver }));
    document.body.dispatchEvent(new CustomEvent('characterChanged'));
  }
  // A count spent from the roll card (a rider's Focus Point, a row's own cost): Use one's own change (app/resources.py), its
  // corner card with that window's Undo
  function spendCount(cid, field, n, name) {
    return posted('/characters/' + cid + '/count?field=' + encodeURIComponent(field), { to: 'use', n: String(n || 1) }).then(j => {
      toast(j.text, j.undo ? { label: 'Undo', run: () => posted(j.undoUrl, j.undo).then(u => { toast(u.text); itemChanged(u); }).catch(err => toast(err.message, null, 'warn')) } : null);
      itemChanged(j);
    }).catch(err => toast(name + ': ' + err.message, null, 'warn'));
  }
  // A feature's Use window (app/feature_use.py): How many starts at what the one it's for is missing, never more than
  // what's left; a way with its own cost (End Poisoned, 5) has no How many; the button names the way
  document.addEventListener('change', e => {
    const w = e.target.closest && e.target.closest('.roll-win');
    if (!w || !w.querySelector('[data-feature-use], [data-feature-n], [data-feature-ways]') || !e.target.matches('input[type=radio]')) return;
    const n = w.querySelector('[data-feature-n]'), way = w.querySelector('input[name=way]:checked'), who = w.querySelector('input[name=target]:checked');
    const go = w.querySelector('[data-use-go]'), needs = w.querySelector('[data-feature-needs]');
    if (n) {
      n.closest('.rw-row').hidden = !!(way && way.dataset.spend);
      if (who && e.target === who && +who.dataset.needs) n.value = Math.max(1, Math.min(+n.max, +who.dataset.needs));
    }
    if (needs && who) { needs.textContent = +who.dataset.needs ? who.dataset.name + ' is missing ' + who.dataset.needs : who.dataset.name + ' is at full Hit Points'; }
    if (go && way) go.textContent = way.dataset.label;
  });
  // A Necklace of Prayer Beads' window: its button says "and roll" only for a bead whose spell rolls (Cure Wounds, Shining Smite)
  document.addEventListener('change', e => {
    if (!e.target.matches || !e.target.matches('[data-use-bead]')) return;
    const go = e.target.closest('.roll-win') && e.target.closest('.roll-win').querySelector('[data-use-go][data-verb]');
    const rolls = e.target.selectedOptions[0] && e.target.selectedOptions[0].dataset.rolls === '1';
    if (go) { go.textContent = go.dataset.verb + (rolls ? ' and roll' : ''); go.toggleAttribute('data-then-roll', rolls); }
  });
  function useItem(btn) {
    const w = win, said = w.querySelector('.use-said');
    w.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const chosen = Object.fromEntries([...w.querySelectorAll('select[name], input[name]')].filter(s => !/^(checkbox|radio)$/.test(s.type) || s.checked).map(s => [s.name, s.value]));
    posted(w._use, { ...chosen, to: btn.dataset.to || '' }).then(j => {
      // Cast and roll: the roll opens where the Cast window was, at the level just cast
      const bead = w.querySelector('[data-use-bead]');  // (a Necklace of Prayer Beads: the chosen bead's spell, at its level)
      const roller = 'thenRoll' in btn.dataset && (bead ? w.querySelector('.use-roll[data-bead="' + bead.value + '"]') : w.querySelector('.cast-roll, .use-roll'));
      if (roller && roller.matches('.use-roll')) openRoll(roller, { ...specFrom(roller), used: true, cast: +roller.dataset.castLevel || 0, castFree: true });  // (Use and roll: used, so it rolls at once)
      else if (roller) {
        const way = w.querySelector('select[name=way]')?.selectedOptions[0], level = way?.dataset.level;
        if (level) roller.dataset.slot = level;
        // (cast: the slot is spent, so its level is fixed and there's nothing left to choose; healing and damage roll at
        // once, an attack waits at its to-hit for Advantage; Brett, Nov 10: "Cast and roll" didn't roll)
        openRoll(roller, { ...specFrom(roller), cast: +level || 0, castFree: /^(none|ritual|free)/.test(way?.value || '') });
      } else closeWin();
      turnUsed(w._anchor);
      if (j.roll) {
        if (animate()) window.askdndThrowing.throwing(j.roll.id);
        addToLog(j.html, j.roll.id);
        if (j.gamelog) window.postMessage({ askdndBridge: 'gamelog', ddbId: j.gamelog.ddbId, messages: j.gamelog.messages }, location.origin);
      }
      toast(j.text, j.undo ? { label: 'Undo', run: () => posted(j.undoUrl, j.undo).then(u => { toast(u.text); itemChanged(u); }).catch(err => toast(err.message, null, 'warn')) } : null);
      itemChanged(j);
      if (j.area) document.body.dispatchEvent(new CustomEvent('areaTool', { detail: j.area }));  // (askdnd's table: its area to place)
    }).catch(err => {
      w.querySelectorAll('button').forEach(b => { b.disabled = false; });
      said.textContent = err.message;
      said.hidden = false;
    });
  }
  // A follow-up from the result or the log: damage and an added die ask first; a reroll just rolls.
  // A follow-up pressed in Table rolls (Roll damage, Reroll, + a die): the card on that roll's result
  function follow(anchor, action, e, shared, cid) {
    const play = e.kind === 'attack' ? 'attack' : e.kind === 'death' ? 'death' : D20.includes(e.kind) ? 'd20' : 'single';
    card(anchor, { kind: e.kind, label: e.label, shared, cid, mod: '', dmg: '' }, { name: e.label, label: e.label, roll: e.kind, play, bonus: null, notes: [], riders: [], modifiers: [] }, { entry: e, action });  // (the roll's own bonus is in its result)
  }
  function specFrom(el) {
    const cid = characterOf(el), kind = el.dataset.roll;
    // A creature on askdnd's table, rolled by the DM as it (app/table_creatures.py): its token's id goes with the roll
    const tokEl = el.closest('[data-token]'), token = tokEl ? tokEl.dataset.token : '';
    const shared = atTable() && !!side && (kind === 'dice' || !!token || (!!cid && (side.dataset.yours || '').split(',').includes(String(cid))));
    let recipe = null;
    try { recipe = el.dataset.recipe ? JSON.parse(el.dataset.recipe) : null; } catch (err) { recipe = null; }
    // A condition the character has now (Invisible…) offers Advantage with its reason, never forces it:
    // the roll window shows the reason and the player (and DM) decide (app/conditions.adv_reasons).
    let advWhy = el.dataset.advWhy || '';
    // On a creature's Battle (Your creatures) the roll is the creature's: it says so, and its master's conditions don't apply
    const whoEl = el.closest('[data-who]'), who = whoEl ? whoEl.dataset.who : (tokEl ? tokEl.dataset.name : '');
    // (its conditions and Hidden: from the roll's own holder, as Search's carries them, else the character's Battle on this page)
    const body = cid && !who && (el.closest('[data-cond-adv]') || document.querySelector('#battle-body[data-character="' + cid + '"]'));
    if (body) {
      let ca = {};
      try { ca = JSON.parse(body.dataset.condAdv || '{}'); } catch (err) { ca = {}; }
      const keys = (planOf(el) || {}).adv_keys || [];  // (which of them apply: the plan says, app/roll_plan.py)
      const lines = keys.flatMap(k => ca[k] || []).map(e => (e.mode === 'dis' ? '!dis ' : e.mode === 'note' ? '!note ' : '') + e.text);
      if (lines.length) advWhy = [advWhy, ...lines].filter(Boolean).join('\n');
    }
    // Hidden (app/hiding.py): an attack roll ends it, so its window offers that, ticked (the DM may rule otherwise)
    const endsHidden = !!(body && body.dataset.hidden && kind === 'attack');
    return { kind, label: el.dataset.label || '', mod: el.dataset.mod || '', dmg: el.dataset.dmg || '', adv: !!el.dataset.adv, recipe, slot: +el.dataset.slot || 0,
             advWhy, note: el.dataset.note || '', cid: token ? '' : kind === 'dice' && side ? side.dataset.mine : cid, shared, who, endsHidden, token };
  }

  document.addEventListener('click', e => {
    if (!e.target.isConnected) return;  // the window replaced what was clicked (Roll, a follow-up): not a click outside
    if (win && win.contains(e.target)) {
      if (e.target.closest('.rp-x')) { closeWin(); return; }
      if (e.target.closest('[data-use-go]')) { useItem(e.target.closest('[data-use-go]')); return; }
      if (e.target.closest('[data-use-close]')) { closeWin(); return; }
      if (e.target.closest('[data-panel-url], [data-modal-url]')) { setTimeout(closeWin); return; }  // (the side panel or modal opens from its own click)
      const other = e.target.closest('[data-use-url]');  // another of the same window (a Short Rest or a Long one): in place
      if (other && win._use) { swapUse(win, other.dataset.useUrl); return; }
      if (e.target.closest('[data-use-give]')) {
        const names = win.querySelector('.use-names');
        names.hidden = !names.hidden;
        e.target.closest('[data-use-give]').setAttribute('aria-expanded', !names.hidden);
        place(win);
        return;
      }
      const roller = win._use && e.target.closest('[data-roll]');  // (a roll button inside a window: the roll, where the window was)
      if (roller) { e.preventDefault(); openRoll(roller, specFrom(roller), e.shiftKey); return; }
      return;
    }
    const f = e.target.closest('.roll-follow');
    if (f) {
      e.preventDefault();
      const li = f.closest('.roll-item');
      const entry = { id: +f.dataset.parent, label: f.dataset.label || li.querySelector('.roll-what').firstChild.textContent.trim(), kind: li.className.match(/kind-(\w+)/)[1],
                      nat: f.dataset.crit ? 20 : null, can: { damage: f.dataset.dmg || '', reroll: f.dataset.reason || '' } };
      follow(f, f.dataset.follow, entry, true, side ? side.dataset.mine : '');
      return;
    }
    const using = e.target.closest('[data-use-url]');
    if (using) { e.preventDefault(); if (!using.disabled) openUse(using); return; }
    const el = e.target.closest('[data-roll]');
    if (!el) { if (win && !e.target.closest('[data-manual]') && !feedbackBusy(e)) closeWin(); return; }
    e.preventDefault();
    openRoll(el, specFrom(el), e.shiftKey);
  });
  // While the roll window is open, Enter rolls and Esc closes it (only it, not a side panel behind it), wherever focus
  // is: on an option just clicked (Advantage, a die, Just me), in its fields, on the roll button that opened it, or
  // nowhere (clicking its text leaves the page focused). Space still presses a focused option; Enter in a field
  // elsewhere on the page is left alone. Capture phase: before a focused button's own Enter.
  document.addEventListener('keydown', e => {
    if (!win || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'Escape' && feedbackBusy(e)) return;  // (closing Feedback for Claude, not the roll window under it)
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeWin(); return; }
    const go = win.querySelector('.rcard-go:not([disabled]), [data-use-go]'), t = e.target, a = win._anchor;
    if (e.key !== 'Enter' || !go) return;
    if (!win.contains(t) && t !== document.body && t !== document.documentElement && !(a && a.contains && a.contains(t))) return;
    e.preventDefault(); e.stopImmediatePropagation(); go.click();
  }, true);
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('[data-roll][tabindex]');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
  });

  // ---------------------------------------------------------------- Any dice (Roll's window; the sidebar's fold until Nov 10)
  function wireManual(manual) {
    if (manual.dataset.wired) return;
    manual.dataset.wired = '1';
    manual.innerHTML = pickerHTML({ extra: '<button type="button" class="btn primary small" data-manual-roll disabled>Roll</button>' });
    const go = manual.querySelector('[data-manual-roll]');
    let pick = null;
    pick = wirePicker(manual.querySelector('.dice-pick'), () => { go.disabled = !pick || !pick.dice(); });
    go.addEventListener('click', () => { if (pick.dice()) openRoll(go, { kind: 'dice', label: '', dmg: pick.formula(), cid: side && side.dataset.mine, shared: atTable() }); });
  }

  // ---------------------------------------------------------------- the sidebar's state
  // (base.html's first script applies the same rules before the page is drawn, so pages don't shift sideways as
  // they load; keep the two in step: tests/browser/test_layout.py checks nothing moves after the first paint.)
  // Desktop: "open" or "closed" (just the edge tab), one choice per device for every page: closed until you open it,
  // and only the start of a fight changes it on its own, once (Brett, 2026-10-30). Below WIDE it starts closed and opens over the
  // page until a click elsewhere. Phones: a bottom sheet ("closed" is its bar with each person's latest roll,
  // "open" the newest rolls, "full" the whole log and the dice; closed until you open it, as it covers a third of a phone).
  const narrow = () => !phone.matches && innerWidth < WIDE;
  const pref = () => (store.get(SIDE) === 'open' ? 'open' : 'closed');  // closed until opened; a fight opens it once (fightOpens)
  ['askdnd.rollsSide.play', 'askdnd.rollsSide.other', 'askdnd.rollsSeen'].forEach(k => { try { localStorage.removeItem(k); } catch (e) { /* private window */ } });  // the old rules' keys
  function setState(state, remember) {
    if (!side) return;
    const b = document.body.classList;
    b.toggle('rolls-on', atTable());
    b.toggle('rolls-open', state === 'open' || state === 'full');
    b.toggle('rolls-closed', state === 'closed');
    b.toggle('rolls-full', state === 'full');
    side.querySelector('.rs-toggle').setAttribute('aria-expanded', state === 'closed' ? 'false' : 'true');
    if (edge) edge.setAttribute('aria-expanded', state === 'closed' ? 'false' : 'true');
    if (remember && state !== 'full') store.set(SIDE, state);
  }
  function current() { const b = document.body.classList; return b.contains('rolls-full') ? 'full' : b.contains('rolls-open') ? 'open' : 'closed'; }
  function layout() { setState(narrow() ? 'closed' : pref()); }
  // The log's first fetch: htmx's "load" trigger on a page at the table.
  function loadLog() { if (atTable() && !loaded && log && window.htmx) htmx.trigger(log, 'rolls:load'); }
  const logShown = () => atTable() && side && (phone.matches ? current() === 'full' : current() === 'open');
  // Others' rolls are in view on a phone's sheet too, unless it's down to its bar.

  if (side) {
    side.querySelector('.rs-toggle').addEventListener('click', e => {
      e.stopPropagation();
      setState(current() === 'closed' ? 'open' : 'closed', !narrow());
    });
    if (edge) edge.addEventListener('click', e => { e.stopPropagation(); setState('open', !narrow()); });
    // Phones: tap the sheet's bar to see every roll and the dice (or back), or swipe it up and down.
    const head = side.querySelector('.rs-head');
    head.addEventListener('click', () => { if (phone.matches) setState(current() === 'full' ? 'open' : 'full'); });
    let y0 = null;
    head.addEventListener('touchstart', e => { y0 = e.touches[0].clientY; }, { passive: true });
    head.addEventListener('touchend', e => {
      if (y0 === null) return;
      const dy = e.changedTouches[0].clientY - y0, now = current();
      y0 = null;
      if (Math.abs(dy) < 30) return;
      e.preventDefault();  // not a tap
      if (dy < 0) setState(now === 'closed' ? 'open' : 'full', now === 'closed');
      else setState(now === 'full' ? 'open' : 'closed', now !== 'full');
    });
    // Clicking outside an over-the-page sidebar closes it
    document.addEventListener('click', e => {
      if (narrow() && current() === 'open' && e.target.isConnected && !side.contains(e.target) && !e.target.closest('[data-roll], .roll-win, .peek') && !feedbackBusy(e)) setState('closed');
    });
    // Crossing a width (the phone's sheet to the side panel, or WIDE) moves the sidebar to another place, not open or
    // closed: no slide, which would flash it across the page (Brett, 2026-10-26).
    const snap = () => { const b = document.body.classList; b.add('rolls-snap'); layout(); requestAnimationFrame(() => requestAnimationFrame(() => b.remove('rolls-snap'))); };
    let wasWide = innerWidth >= WIDE;
    addEventListener('resize', () => { const wide = innerWidth >= WIDE; if (wide !== wasWide) { wasWide = wide; snap(); } });
    phone.addEventListener('change', snap);
    // A fight that starts opens Table rolls once, on a screen with room for it; after that it stays how you leave it
    const fightOpens = () => {
      const id = document.body.dataset.fight;
      if (!id || phone.matches || narrow() || store.get('askdnd.rollsFight') === id) return;
      store.set('askdnd.rollsFight', id);
      setState('open', true);
      loadLog();
    };
    document.addEventListener('askdnd:fight', fightOpens);
    fightOpens();
    layout();
  }

  // ---------------------------------------------------------------- the log
  function ago(iso) {
    const s = Math.max((Date.now() - Date.parse(iso)) / 1000, 0);
    if (isNaN(s)) return '';
    return s < 10 ? 'now' : s < 60 ? Math.floor(s) + ' s' : s < 3600 ? Math.floor(s / 60) + ' min' : s < 86400 ? Math.floor(s / 3600) + ' h' : new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  // A roll comes again whole when it gets a follow-up: keep the newest copy (at the top).
  function tidy() {
    if (!log) return;
    const seen = new Set();
    log.querySelectorAll('.roll-item[data-id]').forEach(li => { if (seen.has(li.dataset.id)) li.remove(); else seen.add(li.dataset.id); });
    if (log.querySelector('.roll-item')) log.querySelectorAll('.roll-empty').forEach(li => li.remove());
    [...log.querySelectorAll('.roll-item')].slice(50).forEach(li => li.remove());
    log.querySelectorAll('time[data-at]').forEach(t => { t.textContent = ago(t.dataset.at); });
  }
  function addToLog(html, id) {
    if (!log) return;
    log.querySelectorAll('.roll-follow').forEach(b => b.remove());  // follow-ups go with your newest roll only
    log.querySelectorAll('.roll-item[data-id="' + id + '"]').forEach(li => li.remove());
    log.insertAdjacentHTML('afterbegin', html);
    tidy();
    if (window.askdndThrowing) window.askdndThrowing.markLanding();
    const li = log.firstElementChild;
    if (li) { li.classList.remove('fresh'); void li.offsetWidth; li.classList.add('fresh'); }
    buildPeople(li ? new Set([li.dataset.person]) : null);
  }

  // ---------------------------------------------------------------- a phone's closed bar: each person's latest roll
  // One avatar per person (their newest roll in the log) with its total, colored on a natural 20 or 1; a new roll
  // pulses it; a tap says what it was.
  function whatOf(li) {
    const name = li.querySelector('.roll-who b').textContent.trim(), total = li.querySelector('.roll-total');
    const what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const when = (li.querySelector('time') || {}).textContent || '';
    return name + ': ' + (total ? what + ' ' + total.textContent : what.charAt(0).toLowerCase() + what.slice(1)) + (when ? ' (' + when + ')' : '');
  }
  function buildPeople(pulse) {
    if (!people || !log) return;
    const seen = new Set(), latest = side.querySelector('.rs-latest'), newest = log.querySelector('.roll-item[data-person]');
    if (latest) latest.textContent = newest ? whatOf(newest).replace(/ \(.*\)$/, '') : '';
    people.innerHTML = '';
    log.querySelectorAll('.roll-item[data-person]').forEach(li => {
      if (seen.has(li.dataset.person) || seen.size >= 8) return;
      seen.add(li.dataset.person);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'rs-person ' + [...li.classList].filter(c => /^(hue\d|nat20|nat1|hidden-roll)$/.test(c)).join(' ');
      b.setAttribute('role', 'listitem');
      const tip = whatOf(li);
      b.title = tip;
      b.setAttribute('aria-label', tip);
      b.append(li.querySelector('.roll-av').cloneNode(true));
      const total = li.querySelector('.roll-total'), lock = li.querySelector('.roll-lock');
      if (total) { const t = document.createElement('b'); t.className = 'rs-p-total'; t.textContent = total.textContent.split(' · ')[0]; b.append(t); }
      else if (lock) b.append(lock.cloneNode(true));
      if (pulse && pulse.has(li.dataset.person)) b.classList.add('pulse');
      people.append(b);
    });
  }
  function showTip(btn) {
    if (tipEl) tipEl.remove();
    tipEl = document.createElement('div');
    tipEl.className = 'rs-tip';
    tipEl.setAttribute('role', 'status');
    tipEl.textContent = btn.title;
    document.body.append(tipEl);
    const r = btn.getBoundingClientRect();
    if (phone.matches) { tipEl.style.left = '8px'; tipEl.style.right = '8px'; tipEl.style.top = (r.top - tipEl.offsetHeight - 8) + 'px'; }
    else { tipEl.style.left = (r.right + 8) + 'px'; tipEl.style.top = (r.top + r.height / 2 - tipEl.offsetHeight / 2) + 'px'; }
    const mine = tipEl;
    setTimeout(() => { if (tipEl === mine) { mine.remove(); tipEl = null; } }, 3500);
  }
  if (people) people.addEventListener('click', e => { const b = e.target.closest('.rs-person'); if (b) { e.stopPropagation(); showTip(b); } });
  function placeholder(label) {
    const li = document.createElement('li');
    li.className = 'roll-pending';
    li.textContent = label + ' · sending…';
    log.prepend(li);
    return li;
  }
  // Polling every 3 s; every 30 s while the live connection is up, which brings rolls the moment they're made
  let polls = 0;
  let changedRoll = 0;
  window.askdndRolls = {
    wanted: () => atTable() && !loaded,
    poll: () => atTable() && loaded && document.visibilityState === 'visible' && (!(window.askdndLive || {}).up || ++polls % 10 === 0),
    since: () => (loaded ? lastId : -1),  // -1: the whole recent log
    also: () => { const a = changedRoll; changedRoll = 0; return a; },  // (a roll that changed without a new row: its outcome)
  };
  // Its first load, its polling and what each request asks for, here rather than in htmx's hx-trigger filters and
  // hx-vals="js:…", which evaluate text as code (the Content Security Policy runs only askdnd's own files, Nov 13)
  if (log && window.htmx) {
    log.addEventListener('htmx:configRequest', e => {
      if (e.detail.elt !== log) return;
      e.detail.parameters.since = window.askdndRolls.since();
      e.detail.parameters.also = window.askdndRolls.also();
    });
    // (its first load once htmx has set the page up: app.js runs before htmx's own start, a trigger then is lost)
    const first = () => setTimeout(() => { if (window.askdndRolls.wanted()) htmx.trigger(log, 'rolls:load'); });
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', first, { once: true }); else first();
    setInterval(() => { if (window.askdndRolls.poll()) htmx.trigger(log, 'rolls:load'); }, 3000);
  }
  document.addEventListener('askdnd:live', e => {
    if (e.detail.type === 'rolls' && atTable()) earlyThrow(e.detail.roll);
    if (e.detail.type === 'rolls' && e.detail.changed) changedRoll = e.detail.changed;
    if ((e.detail.type === 'rolls' || e.detail.type === 'resync') && atTable() && loaded && log && window.htmx) htmx.trigger(log, 'rolls:load');
  });
  // Hit Points beside Apply to (Brett's test, Nov 16: they stayed as they were when the roll was drawn): when a character
  // changes, or the connection catches up, every pill showing them is brought up to date from /hp/now.
  let hpTick = null, hpIds = new Set();
  function hpPills(ids) {
    const pills = [...document.querySelectorAll('[data-hp-of]')].filter(p => ids.has('*') || ids.has(p.dataset.hpOf));
    if (!pills.length) return;
    const want = [...new Set(pills.map(p => p.dataset.hpOf))];
    fetch('/hp/now?ids=' + want.join(','), { headers: { Accept: 'application/json' } }).then(r => (r.ok ? r.json() : {})).then(now => {
      pills.forEach(p => {
        const n = now[p.dataset.hpOf];
        if (!n || !n.hp) return;
        p.textContent = n.hp; p.dataset.hp = n.hp;
        p.classList.toggle('full', !!n.full && p.hasAttribute('data-heal'));
        p.title = 'Hit Points now' + (n.full ? ': full' : '');
      });
    }).catch(() => { /* they stay as they were */ });
  }
  document.addEventListener('askdnd:live', e => {
    const t = e.detail.type;
    if (t !== 'character' && t !== 'resync') return;
    hpIds.add(t === 'resync' ? '*' : String(e.detail.id));
    clearTimeout(hpTick);
    hpTick = setTimeout(() => { const ids = hpIds; hpIds = new Set(); hpPills(ids); }, 500);
  });
  // A roll the whole table sees comes in the live message itself (app/table_rolls.py _live; Brett, 2026-10-29: every
  // screen starts the dice at once, as D&D Beyond's do): someone else's dice start now, from it, and the row the page
  // then fetches doesn't throw them again (its number shows as they land)
  const thrownEarly = new Set();
  function earlyThrow(t) {
    if (!t || String(t.by) === document.body.dataset.me || !animate() || document.visibilityState !== 'visible') return;
    if (thrownEarly.has(String(t.seq))) return;
    thrownEarly.add(String(t.seq));
    const li = document.createElement('li');
    Object.assign(li.dataset, { id: t.id, seq: t.seq, dice: JSON.stringify(t.dice || {}),
                                throw: JSON.stringify({ kind: t.kind, main: t.main, dmg: t.damage, bonus: t.bonus }) });
    if (t.nat === 20 || t.nat === 1) li.classList.add('nat' + t.nat);
    if (t.dramatic) li.dataset.dramatic = '1';
    li.innerHTML = '<span class="roll-who"><b></b></span><span class="roll-what"></span><b class="roll-total"></b>' + (t.damage ? '<span class="roll-dmg-line"><b></b></span>' : '');
    li.querySelector('.roll-who b').textContent = t.name;
    li.querySelector('.roll-what').textContent = t.label + (t.kind === 'attack' ? ' to hit' : t.kind === 'damage' ? ' damage' : '');
    li.querySelector('.roll-total').textContent = t.total;
    if (t.damage) li.querySelector('.roll-dmg-line > b').textContent = t.damage.total;
    window.askdndThrowing.throwing(t.id);
    throwOthers(li).catch(() => {}).finally(() => window.askdndThrowing.landed(t.id));
  }
  // Rolls made while this tab was out of sight don't replay on your return (Brett, 2026-10-30: back from the VTT, five or
  // six in a row): they're in Table rolls, and one card says so while it's closed.
  const away = { on: false, rolls: 0 };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { away.on = true; return; }
    if (!away.on) return;
    if (loaded && log && window.htmx) htmx.trigger(log, 'rolls:load');  // (whatever came in while it was hidden)
    setTimeout(() => {
      const n = away.rolls;
      away.on = false; away.rolls = 0;
      if (n && current() === 'closed') toast(n + (n === 1 ? ' roll' : ' rolls') + ' while you were away', { label: 'Show', run: () => showMissed(n) }, 'info');
    }, 1200);
  });
  // Show on that card (feedback 46, Nov 7: it opened nothing Mark could see): Table rolls opened the way this screen
  // shows it (a phone's full sheet), at the newest, with the rolls you missed marked for a moment
  function showMissed(n) {
    setState(phone.matches ? 'full' : 'open', !narrow() && !phone.matches);
    if (!log) return;
    log.scrollTop = 0;
    [...log.querySelectorAll(':scope > .roll-item')].slice(0, n).forEach(li => {
      li.classList.add('rs-missed');
      setTimeout(() => li.classList.remove('rs-missed'), 6000);
    });
  }
  // Only polled rows move `lastId` on: your own roll can land before someone else's earlier one.
  let before = 0;
  if (log) log.addEventListener('htmx:beforeSwap', e => {
    before = lastId;
    for (const m of (e.detail.serverResponse || '').matchAll(/data-seq="(\d+)"/g)) lastId = Math.max(lastId, +m[1]);
  });
  if (log) log.addEventListener('htmx:afterSwap', () => {
    const first = !loaded;
    tidy();
    if (window.askdndThrowing) window.askdndThrowing.markLanding();
    loaded = true;
    if (first) return buildPeople();
    const fresh = new Set();
    [...log.querySelectorAll('.roll-item[data-seq]')].reverse().forEach(li => {
      if (+li.dataset.seq > before) fresh.add(li.dataset.person);
      if (+li.dataset.seq > before && !li.dataset.mine) {
        if (thrownEarly.delete(li.dataset.seq)) { /* its dice started from the live message */ }
        else if (away.on) away.rolls++;  // (they happened without you: no dice, no card)
        else if (+(li.dataset.thrown || li.dataset.seq) <= before) { /* applied to someone: it moves up, no dice (Brett's test, Nov 16) */ }
        else if (animate() && !li.classList.contains('hidden-roll')) { window.askdndThrowing.throwing(li.dataset.id); throwOthers(li).catch(() => notice(li)).finally(() => window.askdndThrowing.landed(li.dataset.id)); }  // thrown dice (Brett, 2026-10-23)
        else notice(li);
        li.classList.remove('fresh'); void li.offsetWidth; li.classList.add('fresh');
      }
    });
    buildPeople(fresh);
  });
  // Someone's roll as a corner card (when their dice aren't thrown): the d20 they kept, else the total, as its icon;
  // a roll for the DM, whose number you don't see, is "for your information"
  function notice(li) {
    if (!window.askdndCard) return;
    const name = li.querySelector('.roll-who b').textContent, total = li.querySelector('.roll-total');
    let d = null;
    if (total) {
      const d20 = D20.some(k => li.classList.contains('kind-' + k)), kept = li.querySelector('.roll-dice u');
      const dmgLine = li.querySelector('.roll-dmg-line > b') && +li.dataset.seq !== +li.dataset.id;
      const v = d20 && kept && !dmgLine ? kept.textContent : (dmgLine ? li.querySelector('.roll-dmg-line > b').textContent : total.textContent);
      d = gem(d20 && !dmgLine ? 20 : sidesOf(li.querySelector('.roll-dice') && li.querySelector('.roll-dice').textContent), v,
              (dmgLine || li.classList.contains('kind-damage') ? 'ruby' : li.classList.contains('kind-heal') ? 'jade' : 'gold')
              + (li.classList.contains('nat20') && !dmgLine ? ' crit' : li.classList.contains('nat1') && !dmgLine ? ' fumble' : ''), 'tiny');
      d.classList.add('card-ic');
      if (animate()) tumble(d, 150, 650); else { d.querySelector('.gem-n').textContent = v; d.classList.add('landed'); }
    }
    const what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const dmg = li.querySelector('.roll-dmg-line > b');
    const t = document.createElement('span');
    t.innerHTML = !total ? '<b>' + esc(name) + '</b> ' + esc(what.charAt(0).toLowerCase() + what.slice(1))
      : dmg && +li.dataset.seq !== +li.dataset.id ? '<b>' + esc(name) + '</b> rolled <b>' + esc(dmg.textContent) + '</b> damage · ' + esc(what.replace(/ to hit$/, ''))
      : '<b>' + esc(name) + '</b> rolled <b class="' + (li.classList.contains('nat20') ? 'nat20' : li.classList.contains('nat1') ? 'nat1' : '') + '">' + esc(total.textContent) + '</b> · ' + esc(what);
    window.askdndCard(t, { kind: total ? 'roll' : 'info', icon: d });
  }
})();

// Lists (DESIGN.md › Lists and filters; _lists.html): any [data-list] root. Optional views ([data-ls-view]:
// Prepared · Shortlist · All) pick which rows are in play (each row lists its views in data-views). Chips are OR within a group
// and AND across groups, each with a live count (greyed out at zero); a search looks through every row
// and pauses the filters. Filters, sort and lens are remembered per list in this browser and forgotten
// after a day without use; the view is kept for good, All the first time (Brett, 2026-11-02). The Spell Book adds
// its "Averages at" lens on top (below).
(function () {
  const DAY = 864e5, KEY = r => 'askdnd:list:' + r.dataset.list, VIEW = r => 'askdnd:view:' + r.dataset.list;
  const vals = (f, g) => { const v = f[g]; return Array.isArray(v) ? v : (v ? [v] : []); };
  const fOf = row => row._f || (row._f = (() => { try { return JSON.parse(row.dataset.f || '{}'); } catch (e) { return {}; } })());
  function load(root) {
    let s = null;
    try { s = JSON.parse(localStorage.getItem(KEY(root)) || 'null'); } catch (e) { s = null; }
    if (!s || Date.now() - (s.at || 0) > DAY) s = { sel: {} };
    let force = {};
    try { force = JSON.parse(root.dataset.lsForce || '{}'); } catch (e) { force = {}; }
    Object.entries(force).forEach(([g, vs]) => { s.sel[g] = [...new Set([...(s.sel[g] || []), ...vs])]; });
    const views = [...root.querySelectorAll('[data-ls-view]')].map(b => b.dataset.lsView);
    let kept = '';
    try { kept = localStorage.getItem(VIEW(root)) || ''; } catch (e) { kept = ''; }
    root._ls = { sel: s.sel || {}, sort: s.sort || '', lens: s.lens || '', more: !!s.more, above: !!s.above, q: '',
                 view: views.includes(kept) ? kept : views.includes('all') ? 'all' : (views[0] || '') };
    const sort = root.querySelector('[data-ls-sort]'); if (sort && root._ls.sort) sort.value = root._ls.sort;
    const lens = root.querySelector('[data-ls-lens]');
    if (lens && root._ls.lens && [...lens.options].some(o => o.value === root._ls.lens)) lens.value = root._ls.lens;
    const more = root.querySelector('[data-ls-more]'); if (more) more.open = root._ls.more;
    // (filters above a list: open or closed, as left; drawn by apply)
  }
  function save(root) {
    const st = root._ls;
    try {
      localStorage.setItem(KEY(root), JSON.stringify({ at: Date.now(), sel: st.sel, sort: st.sort, lens: st.lens, more: st.more, above: st.above }));
      if (st.view) localStorage.setItem(VIEW(root), st.view);
    } catch (e) { /* private window */ }
  }
  function apply(root) {
    const st = root._ls, sel = st.sel, q = st.q.trim().toLowerCase();
    // (a row a scope leaves out, such as another class's in Change spells' class tabs, isn't in the list at all)
    const all = [...root.querySelectorAll('[data-ls-row]')], rows = all.filter(r => !r.hasAttribute('data-ls-out'));
    all.forEach(r => { if (r.hasAttribute('data-ls-out')) r.hidden = true; });
    const on = Object.keys(sel).filter(g => (sel[g] || []).length);
    const passes = (f, skip) => on.every(g => g === skip || vals(f, g).some(v => sel[g].includes(v)));
    const inView = (r, v = st.view) => !v || (r.dataset.views || '').split(' ').includes(v);
    // A search looks through every row, whatever the view and filters
    rows.forEach(r => { r.hidden = q ? !(r.dataset.name || '').includes(q) : !(inView(r) && passes(fOf(r))); });
    root.querySelectorAll('[data-ls-view]').forEach(b => {
      b.setAttribute('aria-pressed', !q && b.dataset.lsView === st.view ? 'true' : 'false');
      const n = b.querySelector('[data-ls-view-n]');
      if (n) n.textContent = rows.filter(r => inView(r, b.dataset.lsView) && passes(fOf(r))).length;
    });
    root.querySelectorAll('[data-ls-group]').forEach(chip => {
      const g = chip.dataset.lsGroup, v = chip.dataset.lsValue, pressed = (sel[g] || []).includes(v);
      const n = rows.filter(r => inView(r) && passes(fOf(r), g) && vals(fOf(r), g).includes(v)).length;
      chip.setAttribute('aria-pressed', pressed ? 'true' : 'false');
      chip.classList.toggle('zero', !n && !pressed);
      const c = chip.querySelector('[data-ls-n]'); if (c) c.textContent = n;
    });
    // Clear, by the Filters heading and on a phone's folded Filters button, once something is filtered (Brett chose A,
    // Nov 16, docs/mockups/filter-clear/: the blue chips say what's on, so there's no row above the list)
    const picked = on.flatMap(g => sel[g].map(v => [g, v]));
    root.querySelectorAll('[data-ls-clear-filters]').forEach(b => { b.hidden = !picked.length; });
    // Filters above a list (filters_above): open or closed, and while closed what's on as pills, two at most, then "+N"
    const above = root.querySelector('[data-ls-above]');
    if (above) {
      const body = above.querySelector('[data-ls-above-body]'), toggle = above.querySelector('[data-ls-above-toggle]');
      body.hidden = !st.above;
      toggle.setAttribute('aria-expanded', st.above ? 'true' : 'false');
      const pills = st.above ? [] : picked.slice(0, 2).map(([g, v]) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'ls-pill'; b.dataset.lsRemove = g + '\u0000' + v; b.setAttribute('aria-label', 'Remove ' + v); b.title = v;
        const t = document.createElement('span'); t.textContent = v;
        const x = document.createElement('i'); x.textContent = '×'; x.setAttribute('aria-hidden', 'true');
        b.append(t, x);
        return b;
      });
      if (!st.above && picked.length > 2) {
        const more = document.createElement('button');
        more.type = 'button'; more.className = 'ls-pill more'; more.dataset.lsAboveToggle = ''; more.textContent = '+' + (picked.length - 2);
        more.title = picked.slice(2).map(([, v]) => v).join(', ');
        pills.push(more);
      }
      above.querySelector('[data-ls-pills]').replaceChildren(...pills);
    }
    const moreOn = root.querySelector('[data-ls-more-on]');
    if (moreOn) {
      const n = [...root.querySelectorAll('[data-ls-more] [data-ls-group][aria-pressed="true"]')].length;
      moreOn.textContent = n ? '(' + n + ' on)' : '';
    }
    const fc = root.querySelector('[data-ls-fold-count]'); if (fc) { fc.textContent = picked.length; fc.hidden = !picked.length; }
    // Sort, with group headings when sorted by level
    const box = root.querySelector('[data-ls-rows]'), sort = st.sort || root.dataset.defaultSort || 'level';
    root.dispatchEvent(new CustomEvent('list:before-sort', { bubbles: true, detail: { rows } }));
    const name = r => r.dataset.name || '';
    // level (with headings), name, avg (highest first), default (the server's order), or any other key:
    // highest first by the row's data-sort-<key> (Wild Shape: damage, hit, speed, cr). A sort whose rows carry
    // data-group-<key> is a grouping instead: in the server's order, with those headings (Items' Container), and the
    // list's data-group-notes-<key> puts a note beside each heading (a container's coins; feedback 49)
    const cap = k => k[0].toUpperCase() + k.slice(1);
    const by = k => r => +(r.dataset['sort' + cap(k)] || -1);
    const grouping = rows.some(r => r.dataset['group' + cap(sort)] != null);
    const groupOf = r => grouping ? r.dataset['group' + cap(sort)] : (sort === 'level' || sort === 'default') ? r.dataset.groupLabel : null;
    let notes = {}; try { notes = JSON.parse(root.dataset['groupNotes' + cap(sort)] || '{}'); } catch (err) { notes = {}; }
    const sorted = rows.slice().sort((a, b) => sort === 'name' ? name(a).localeCompare(name(b))
      : sort === 'level' ? (+a.dataset.level - +b.dataset.level) || name(a).localeCompare(name(b))
      : sort === 'default' || grouping ? by(sort)(a) - by(sort)(b)
      : (by(sort)(b) - by(sort)(a)) || name(a).localeCompare(name(b)));
    // Move rows only when the order or the headings change, and keep the scroll position: moving every
    // row on each press (a bookmark) made the page jump to the top.
    const scroller = root.closest('.peek-body'), y = window.scrollY, sy = scroller ? scroller.scrollTop : 0;
    const heads = new Map([...box.querySelectorAll('.ls-grouphead')].map(h => [h.dataset.label, h]));
    const want = [], shownIn = {};
    let last = null;
    sorted.forEach(r => {
      const g = groupOf(r);
      if (g != null && !r.hidden && g !== last) {
        last = g;
        let h = heads.get(last);
        if (h) heads.delete(last);
        else {
          h = document.createElement('div'); h.className = 'ls-grouphead'; h.dataset.label = last; h.textContent = last;
          if (notes[last]) { const n = document.createElement('span'); n.className = 'ls-group-note'; n.textContent = notes[last]; h.append(n); }
        }
        want.push(h);
      }
      if (g != null && !r.hidden) shownIn[g] = (shownIn[g] || 0) + 1;
      want.push(r);
    });
    // (a heading's count, where it has one, is what shows under it: searching or filtering, not every row)
    want.forEach(h => { const n = h.matches('.ls-grouphead') && h.querySelector('.count'); if (n) n.textContent = shownIn[h.dataset.label] || 0; });
    heads.forEach(h => h.remove());
    const now = [...box.children].filter(n => n.matches('[data-ls-row], .ls-grouphead'));
    if (now.length !== want.length || now.some((n, i) => n !== want[i])) want.forEach(n => box.appendChild(n));
    if (window.scrollY !== y) window.scrollTo(0, y);
    if (scroller && scroller.scrollTop !== sy) scroller.scrollTop = sy;
    const shown = rows.filter(r => !r.hidden).length, noun = root.dataset.noun || 'item';
    const sum = root.querySelector('[data-ls-summary]'); if (sum) sum.textContent = shown + ' ' + (shown === 1 ? noun : (root.dataset.nouns || noun + 's'));
    // Nothing to show: a view that's empty on its own says so (e.g. nothing shortlisted yet)
    const viewEmpty = !q && !picked.length && !rows.some(r => inView(r)) && root.querySelector('[data-ls-empty-view="' + st.view + '"]');
    root.querySelectorAll('[data-ls-empty-view]').forEach(m => { m.hidden = m !== viewEmpty; });
    const empty = root.querySelector('[data-ls-empty]'); if (empty) empty.hidden = shown > 0 || !!viewEmpty;
    root.classList.toggle('ls-is-searching', !!q);
    const sn = root.querySelector('[data-ls-searching]'); if (sn) sn.hidden = !q;
    save(root);
  }
  const rootOf = el => el.closest && el.closest('[data-list]');
  document.addEventListener('click', e => {
    const root = rootOf(e.target); if (!root || !root._ls) return;
    const st = root._ls, search = root.querySelector('[data-ls-search]');
    const clearSearch = () => { st.q = ''; if (search) search.value = ''; };
    if (e.target.closest('[data-ls-clear]')) { e.preventDefault(); st.sel = {}; clearSearch(); apply(root); return; }  // (in a folded summary: clears, never opens it)
    if (e.target.closest('[data-ls-clear-search]')) { clearSearch(); apply(root); if (search) search.focus(); return; }
    if (e.target.closest('[data-ls-above-toggle]')) { st.above = !st.above; apply(root); return; }  // (apply saves it)
    const rm = e.target.closest('[data-ls-remove]');
    if (rm) { const [g, v] = rm.dataset.lsRemove.split('\u0000'); st.sel[g] = (st.sel[g] || []).filter(x => x !== v); apply(root); return; }
    const view = e.target.closest('[data-ls-view]');
    if (view) { st.view = view.dataset.lsView; clearSearch(); apply(root); return; }
    const chip = e.target.closest('[data-ls-group]');
    if (chip) {
      const g = chip.dataset.lsGroup, v = chip.dataset.lsValue, cur = st.sel[g] || [];
      st.sel[g] = cur.includes(v) ? cur.filter(x => x !== v) : [...cur, v];
      apply(root);
    }
  });
  document.addEventListener('input', e => {
    const root = rootOf(e.target);
    if (root && root._ls && e.target.matches('[data-ls-search]')) { root._ls.q = e.target.value; apply(root); }
  });
  document.addEventListener('change', e => {
    const root = rootOf(e.target); if (!root || !root._ls) return;
    if (e.target.matches('[data-ls-sort]')) { root._ls.sort = e.target.value; apply(root); }
    if (e.target.matches('[data-ls-lens]')) { root._ls.lens = e.target.value; apply(root); }
  });
  document.addEventListener('toggle', e => {
    const root = rootOf(e.target);
    if (root && root._ls && e.target.matches('[data-ls-more]')) { root._ls.more = e.target.open; save(root); }
  }, true);
  // A page that changes rows (Change spells: a row moved into Yours, a class tab) asks the list to look again
  document.addEventListener('list:refresh', e => { const root = rootOf(e.target); if (root && root._ls) apply(root); });
  // Lists can arrive later (a modal): set each one up when it appears
  function init() {
    document.querySelectorAll('[data-list]:not([data-ls-ready])').forEach(root => {
      root.dataset.lsReady = '1';
      const fold = root.querySelector('[data-ls-fold]'); if (fold) fold.open = !matchMedia('(max-width: 900px)').matches;  // (the width app.css folds them at)
      load(root);
      apply(root);
    });
  }
  new MutationObserver(init).observe(document.body, { childList: true, subtree: true });
  init();
})();

// Spell Book: the "Averages at" lens. Each row carries its averages per slot level (data-avgs, from
// app/spellbook.py); before the list sorts, redraw the numbers, the upcast rolls and the
// Concentrate level for the chosen slot (a spell below its own level stays at its own level).
(function () {
  const ORD = n => n + ({ 1: 'st', 2: 'nd', 3: 'rd' }[n] || 'th');
  document.addEventListener('list:before-sort', e => {
    const root = e.target; if (!root.matches('[data-spellbook]')) return;
    const lens = +(root._ls.lens || 0);
    e.detail.rows.forEach(row => {
      const level = +row.dataset.level;
      let avgs = {};
      try { avgs = JSON.parse(row.dataset.avgs || '{}'); } catch (err) { avgs = {}; }
      const at = level ? Math.max(level, lens || level) : 0, a = avgs[at];
      row.dataset.sortAvg = a ? a.avg : '';
      const set = (sel, v) => { const el = row.querySelector(sel); if (el) el.textContent = v; };
      if (a) {
        set('[data-sb-avg]', a.avg);
        set('[data-sb-dice]', a.dice + (a.per === 'healed' ? ' healed' : a.per === 'each hit' ? ' each hit' : '') + (level && at > level ? ' · at ' + ORD(at) : ''));
        set('[data-sb-half]', ' · ' + Math.floor(a.avg / 2) + ' on a save');
      }
      row.querySelectorAll('.sb-roll').forEach(b => { if (level) b.dataset.slot = at; });
      const lv = row.querySelector('[data-sb-level]'); if (lv) lv.value = level ? at : 0;
    });
  });
  document.addEventListener('input', e => {
    // Concentration save: the DC from the damage just taken (10, or half the damage if higher; up to 30)
    if (e.target.matches('[data-conc-dmg]')) {
      const box = e.target.closest('.conc-box'), dc = Math.min(30, Math.max(10, Math.floor((+e.target.value || 0) / 2)));
      const out = box.querySelector('[data-conc-dc]'); if (out) out.textContent = dc;
      const btn = box.querySelector('[data-conc-roll]'); if (btn) btn.dataset.note = 'DC ' + dc;
    }
  });
  // Keep it (End Concentration?): close the little pop-up without doing anything
  document.addEventListener('click', e => {
    const k = e.target.closest('[data-close-details]');
    if (k) { const d = k.closest('details'); if (d) d.open = false; }
  });
})();

// All sessions: an open session's row hides and its scroll carries its date and title (Brett, Nov 10); Roll up ▴ in
// the scroll's corner rolls it back into its row, which keeps its place on the page and takes the focus
document.addEventListener('click', e => {
  const b = e.target.closest('[data-roll-up]'), d = b && b.closest('details.tale-roll');
  if (!d) return;
  d.open = false;
  const row = d.querySelector('summary');
  if (row.getBoundingClientRect().top < 0) row.scrollIntoView({ block: 'start' });
  row.focus({ preventScroll: true });
});

// Story search (Brett, 2026-10-29): as you type, All sessions shows only the sessions whose recap, key moments or DM's
// notes hold every word, opened, with the words marked; clearing the box shows them all again, as they were
(function () {
  const box = document.querySelector('[data-story-search]');
  if (!box) return;
  const pane = document.getElementById('t-sessions'), found = pane.querySelector('[data-story-found]'), sub = pane.querySelector('[data-story-sub]');
  const sessions = [...pane.querySelectorAll('details.tale-roll')], wasOpen = new Map(sessions.map(d => [d, d.open]));
  const unmark = () => pane.querySelectorAll('mark.story-hit').forEach(m => { const p = m.parentNode; m.replaceWith(m.textContent); p.normalize(); });
  function mark(el, words) {
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), nodes = [];
    while (walk.nextNode()) if (walk.currentNode.nodeValue.trim() && !walk.currentNode.parentNode.closest('summary, form, .suggest, button, .btn')) nodes.push(walk.currentNode);
    const re = new RegExp('(' + words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
    nodes.forEach(n => {
      if (!re.test(n.nodeValue)) return;
      re.lastIndex = 0;
      const frag = document.createDocumentFragment();
      n.nodeValue.split(re).forEach((part, i) => frag.append(i % 2 ? Object.assign(document.createElement('mark'), { className: 'story-hit', textContent: part }) : part));
      n.replaceWith(frag);
    });
  }
  let timer = null;
  box.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 150); });
  function run() {
    unmark();
    const words = box.value.trim().toLowerCase().split(/\s+/).filter(w => w.length > 1);
    if (!words.length) {
      sessions.forEach(d => { d.hidden = false; d.open = wasOpen.get(d); d.querySelectorAll('details.km-more').forEach(x => { x.open = false; }); });
      found.hidden = true; sub.hidden = false;
      return;
    }
    const tab = document.querySelector('[role=tab][data-tab="t-sessions"]');
    if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
    let n = 0;
    sessions.forEach(d => {
      const text = d.querySelector('.session-body').textContent.toLowerCase() + ' ' + d.querySelector('summary').textContent.toLowerCase();
      const hit = words.every(w => text.includes(w));
      d.hidden = !hit; d.open = hit;
      d.querySelectorAll('details.tale-more').forEach(x => { x.open = hit; });  // (a key moment past the first few)
      if (hit) { n++; mark(d.querySelector('.session-body'), words); }
    });
    sub.hidden = true; found.hidden = false;
    found.textContent = n ? n + ' session' + (n === 1 ? '' : 's') + ' mention' + (n === 1 ? 's' : '') + ' “' + box.value.trim() + '”' : 'No session mentions “' + box.value.trim() + '”';
  }
})();

// The Night's awards (a session's own page, Brett chose C, Nov 9, docs/mockups/full-tale/): each card starts face
// down with its award's name; Reveal turns it over (Reveal all, every one), as at an awards night on a shared screen.
// What's been revealed is remembered on this device, by session and published version (a new pick starts face down).
(function () {
  const key = box => 'askdnd-awards-' + box.dataset.awards;
  const seen = box => { try { return JSON.parse(localStorage.getItem(key(box)) || '[]'); } catch (err) { return []; } };
  const keep = box => { try { localStorage.setItem(key(box), JSON.stringify([...box.querySelectorAll('[data-award]:not(.face-down)')].map(c => c.dataset.award))); } catch (err) { /* private window */ } };
  const all = box => box.closest('section') && box.closest('section').querySelector('[data-reveal-all]');
  function show(card, now) {
    card.classList.remove('face-down');
    card.querySelector('.award-face').hidden = false;
    const b = card.querySelector('[data-award-reveal]'); if (b) b.remove();
    if (now) card.classList.add('revealed');
  }
  function sync(box) { const b = all(box); if (b) b.hidden = !box.querySelector('.face-down'); }
  function setup() {
    document.querySelectorAll('[data-awards]').forEach(box => {
      const s = seen(box);
      box.querySelectorAll('[data-award].face-down').forEach(c => { if (s.includes(c.dataset.award)) show(c, false); });
      sync(box);
    });
  }
  document.addEventListener('click', e => {
    const one = e.target.closest('[data-award-reveal]'), every = !one && e.target.closest('[data-reveal-all]');
    const box = one ? one.closest('[data-awards]') : every && every.closest('section').querySelector('[data-awards]');
    if (!box) return;
    const cards = one ? [one.closest('[data-award]')] : [...box.querySelectorAll('[data-award].face-down')];
    cards.forEach(c => show(c, true));
    keep(box);
    sync(box);
    if (one) cards[0].focus({ preventScroll: true });  // (its button is gone: focus stays on the card it turned over)
    else { const next = box.querySelector('[data-award]'); if (next) next.focus({ preventScroll: true }); }
  });
  setup();
  document.addEventListener('askdnd:swapped', setup);  // (a new copy of the page keeps what's been revealed)
})();

// Story and the Campaign page's Map tab (menu bar Option B). A [data-goto-tab] link shows that tab on this page
// ("Earlier sessions"); /?tab=sessions#s12 opens that session. The map's frame loads when its tab is first shown,
// and "Show on map" on the Campaign page recenters it there instead of loading the page again.
(function () {
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-goto-tab]'), t = a && document.querySelector('[role=tab][data-tab="' + a.dataset.gotoTab + '"]');
    if (!t || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    t.click();
    t.closest('[role=tablist]').scrollIntoView({ block: 'start' });
  });
  // Phones: a tab row that scrolls sideways keeps the chosen tab in view, and fades the edge it's cut at, so you can see
  // there's more (Brett, 2026-11-02, docs/artifacts/ui-ux-pass.html, question 7)
  const edges = list => {
    list.classList.toggle('cut-l', list.scrollLeft > 2);
    list.classList.toggle('cut-r', list.scrollLeft + list.clientWidth < list.scrollWidth - 2);
  };
  const inView = list => {
    const t = list.querySelector('[aria-selected=true]');
    if (t && list.scrollWidth > list.clientWidth) {
      const l = t.offsetLeft - list.offsetLeft, r = l + t.offsetWidth;
      if (l < list.scrollLeft + 24) list.scrollLeft = l - 24;
      else if (r > list.scrollLeft + list.clientWidth - 24) list.scrollLeft = r - list.clientWidth + 24;
    }
    edges(list);
  };
  const bars = root => root.querySelectorAll('.tabbar').forEach(list => {
    inView(list);
    if (!list._edges) { list._edges = true; list.addEventListener('scroll', () => edges(list), { passive: true }); }
  });
  bars(document);
  window.addEventListener('resize', () => bars(document));
  document.addEventListener('click', e => { const t = e.target.closest('.tabbar [role=tab]'); if (t) setTimeout(() => inView(t.closest('.tabbar')), 0); });
  document.body.addEventListener('htmx:afterSwap', e => bars(e.detail.target));
  document.addEventListener('panel:loaded', e => bars(e.target));
  if (location.hash.length > 1) {
    const d = document.getElementById(location.hash.slice(1));
    if (d && d.tagName === 'DETAILS') d.open = true;
  }
  const frame = document.getElementById('map-frame');
  if (!frame) return;
  document.addEventListener('tab:shown', e => {
    if (e.target.id === 't-map' && !frame.getAttribute('src') && frame.dataset.src) frame.src = frame.dataset.src;
  });
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-map-src]');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    frame.removeAttribute('data-src');
    frame.src = a.dataset.mapSrc;
    document.getElementById('map-open').href = a.dataset.mapSrc;
    const tag = document.getElementById('map-at'); tag.textContent = a.dataset.mapAt; tag.hidden = false;
    const peek = a.closest('.peek'); if (peek) document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    document.querySelector('[role=tab][data-tab="t-map"]').click();
    const u = new URL(location.href); u.searchParams.set('tab', 'map'); u.searchParams.set('at', a.dataset.mapAt);
    history.replaceState(null, '', u.pathname + u.search);
  });
})();

// The Campaign page's Reader (campaign.html): picking a name swaps the entry in (HTMX) and marks it in the list;
// ↑ ↓ move through the names that are showing. On narrow screens the entry sits below the list. Its tabs keep
// their place in the address (?tab=), and "Part of" chips jump to the quest on the Quests tab.
(function () {
  document.addEventListener('tab:shown', e => {
    const list = document.querySelector('[data-tab-param]'); if (!list || !list.contains(document.querySelector('[data-tab="' + e.target.id + '"]'))) return;
    const u = new URL(location.href); u.searchParams.set('tab', e.target.id.replace(/^t-/, ''));
    history.replaceState(null, '', u.pathname + u.search + u.hash);
    if (document.querySelector('.help')) try { localStorage.setItem('askdnd-help-tab', e.target.id); } catch (err) { /* private window */ }
  });
  // Help: a link to an answer (/help#id) opens the FAQ there; otherwise the tab you used last
  if (document.querySelector('.help [data-tab-param]')) {
    const answer = location.hash.length > 1 && document.getElementById(location.hash.slice(1));
    const inTab = answer && answer.closest('[id^="t-"]');
    let last = null; try { last = localStorage.getItem('askdnd-help-tab'); } catch (err) { /* private window */ }
    const open = inTab ? inTab.id : new URLSearchParams(location.search).has('tab') ? null : last;
    const tab = open && document.querySelector('[role=tab][data-tab="' + open + '"]');
    if (tab && tab.getAttribute('aria-selected') !== 'true') tab.click();
    if (inTab) answer.scrollIntoView();
  }
  // The quest log (Quests tab): Open or Done down the left, one quest's journal on the right
  function questView(state) {
    document.querySelectorAll('[data-ql-view]').forEach(b => b.setAttribute('aria-pressed', b.dataset.qlView === state ? 'true' : 'false'));
    const items = [...document.querySelectorAll('[data-ql-state]')];
    items.forEach(n => { n.hidden = n.dataset.qlState !== state; });
    document.querySelectorAll('[data-ql-empty]').forEach(p => { p.hidden = p.dataset.qlEmpty !== state || items.some(n => !n.hidden); });
    return items.filter(n => !n.hidden);
  }
  function showQuest(id, scroll) {
    const journal = document.querySelector('[data-ql-journal="' + id + '"]'), btn = document.querySelector('[role=tab][data-tab="t-quests"]');
    const item = document.querySelector('[data-ql-id="' + id + '"]');
    if (!journal || !btn) return false;
    if (document.getElementById('t-quests').hidden) btn.click();
    document.querySelectorAll('[data-ql-journal]').forEach(j => { j.hidden = j !== journal; });
    document.querySelectorAll('[data-ql-id]').forEach(n => n.classList.toggle('sel', n === item));
    if (item && item.hidden) questView(item.dataset.qlState);
    const u = new URL(location.href); u.searchParams.set('tab', 'quests'); u.searchParams.set('open', id);
    history.replaceState(null, '', u.pathname + u.search + u.hash);
    if (scroll || matchMedia('(max-width: 900px)').matches) journal.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return true;
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('[data-goto-quest]');
    if (a && !a.closest('.peek') && !e.metaKey && !e.ctrlKey && showQuest(a.dataset.gotoQuest, true)) { e.preventDefault(); return; }
    const item = e.target.closest('[data-ql-id]');
    if (item && !e.metaKey && !e.ctrlKey && showQuest(item.dataset.qlId)) { e.preventDefault(); return; }
    const view = e.target.closest('[data-ql-view]');
    if (view) {
      const shown = questView(view.dataset.qlView), sel = document.querySelector('[data-ql-id].sel');
      if (shown.length && !(sel && !sel.hidden)) showQuest(shown[0].dataset.qlId);
    }
  });
  function mark() {  // each Reader (World, Glossary) marks the name its page shows
    document.querySelectorAll('.reader').forEach(r => {
      const art = r.querySelector('.reader-article'); if (!art) return;
      r.querySelectorAll('[data-rd-id]').forEach(n => {
        const on = n.dataset.rdId === art.dataset.readerId;
        n.classList.toggle('sel', on);
        if (on) n.setAttribute('aria-current', 'true'); else n.removeAttribute('aria-current');
      });
    });
  }
  // Opening the page at an entry's address: show its name in the list
  document.querySelectorAll('.rd-item.sel').forEach(sel => { const nav = sel.closest('.reader-nav');
    if (nav) nav.scrollTop = sel.offsetTop - nav.clientHeight / 3; });
  document.body.addEventListener('htmx:afterSwap', e => {
    const id = e.detail.target && e.detail.target.id;  // (a Reader's article swapped in: World, Glossary, Testing's)
    const art = id && document.getElementById(id);
    if (!art || !(art.matches('.reader-article') || art.querySelector('.reader-article'))) return;
    mark();
    if (art && matchMedia('(max-width: 900px)').matches) art.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (!document.getElementById('reader') || document.querySelector('.peek.open')) return;
    const t = e.target;
    if (t.matches && t.matches('textarea, select, input:not([data-ls-search]), [contenteditable]')) return;
    const reader = [...document.querySelectorAll('.reader')].find(r => r.checkVisibility());  // World's or Glossary's, whichever shows
    if (!reader) return;
    const items = [...reader.querySelectorAll('.rd-item')].filter(n => !n.hidden);
    if (!items.length) return;
    const i = items.findIndex(n => n.classList.contains('sel'));
    const next = items[i < 0 ? 0 : Math.max(0, Math.min(items.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next && !next.classList.contains('sel')) { e.preventDefault(); next.click(); next.scrollIntoView({ block: 'nearest' }); }
  });
})();

// The new-player tour (? › Take the tour, and Show me on Help › What askdnd adds; app/tour.py). It walks this
// person's stops across pages: each dims the page, lights one thing and says what it is and why. It only reads: it
// clicks a tab, or + Add and a row to open the side panel, and shows example rows on Battle that exist only on the
// page (class tour-example), so nothing changes. Where it is lives in sessionStorage, so it carries on after
// each page change; Esc or ✕ asks before ending it.
(function () {
  const KEY = 'askdnd-tour';
  let tour = null, spot = null, card = null, lit = null, lits = [], asking = false;
  const keep = () => { try { if (tour) sessionStorage.setItem(KEY, JSON.stringify(tour)); else sessionStorage.removeItem(KEY); } catch (e) { /* private window: the tour still works page by page */ } };
  // (on screen across: a panel slid off to the side, like closed Table rolls on a computer, isn't there to light)
  const visible = sel => [...document.querySelectorAll(sel)].find(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.right > 0 && r.left < innerWidth; });
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  async function start(group) {
    const res = await fetch('/tour', { headers: { Accept: 'application/json' } });
    if (!res.ok) return;
    const stops = (await res.json()).stops;
    if (!stops.length) return;
    tour = { stops, i: 0 };
    go(group ? Math.max(0, stops.findIndex(s => s.group === group)) : 0);
  }
  function go(i) {
    if (i >= tour.stops.length) return end();
    tour.i = Math.max(0, i);
    const s = tour.stops[tour.i];
    if (s.url && new URL(s.url, location.href).pathname !== location.pathname) {
      tour.arriving = true; tour.shown = null; keep(); location.href = s.url; return;  // carries on when the page has loaded (a new page is the real one)
    }
    tour.arriving = false; keep(); show(s);
  }
  // What a stop showed, put back: examples go, a side panel the tour opened closes, and on ending, Battle is itself
  // again. Between stops prepare() puts Battle back (or swaps it) itself, waiting for it, so two swaps never race
  // (2026-10-26: one landing late replaced Battle under the next stop's light).
  function tidy(ending) {
    document.querySelectorAll('.tour-example').forEach(x => x.remove());
    if (tour && tour.panel) { const x = document.querySelector('.peek.open .peek-close'); if (x) x.click(); tour.panel = false; }
    if (ending && tour && tour.shown && tour.restore) { swapBattle(tour.restore); tour.shown = null; }
  }
  // Wild Shape's stops show Battle in a form: the server draws it (/characters/<id>/battle/preview, nothing saved or
  // announced) and it replaces Battle on this page only; `restore` draws the real one back.
  let swapping = Promise.resolve();  // one swap at a time, in order
  const swapBattle = url => (swapping = swapping.then(() => swapNow(url), () => swapNow(url)));
  async function swapNow(url) {
    const res = await fetch(url, { headers: { 'HX-Request': 'true' } });
    const cur = document.getElementById('battle-body');
    if (!res.ok || !cur) return;
    const tmpBox = document.createElement('div'); tmpBox.innerHTML = await res.text();
    const next = tmpBox.querySelector('#battle-body');
    if (!next) return;
    cur.replaceWith(next);
    if (window.htmx) htmx.process(next);
  }
  function end() {
    tidy(true); tour = null; keep(); lit = null; lits = []; asking = false;
    if (spot) spot.remove(); if (card) card.remove(); spot = card = null;
  }
  // A target taller than most of the screen (a recap, a sheet) is lit from its top down to just under half the screen,
  // with the card below, so the dimming still shows where to look.
  const tall = r => r.height > innerHeight * 0.55;
  function box() {  // the lit thing, or for an `all` stop every match together (a column: its heading and cells)
    if (lits.length < 2) return lit.getBoundingClientRect();
    const rs = lits.map(el => el.getBoundingClientRect()).filter(r => r.width && r.height);
    if (!rs.length) return lit.getBoundingClientRect();
    const top = Math.min(...rs.map(r => r.top)), left = Math.min(...rs.map(r => r.left));
    const right = Math.max(...rs.map(r => r.right)), bottom = Math.max(...rs.map(r => r.bottom));
    return { top, left, right, bottom, width: right - left, height: bottom - top };
  }
  // Bars that stick across the top of the page (the menu bar, Sheet's tabs): found once per stop, so
  // the light never sits under them (Brett, 2026-10-26: Battle's columns were lit from behind its numbers).
  let bars = [];
  function findBars() {
    bars = [...document.body.querySelectorAll('*')].filter(el => {
      const p = getComputedStyle(el).position;
      if ((p !== 'sticky' && p !== 'fixed') || el.closest('.peek, .tour-card, .tour-spot, .rolls-side, .cards, .dice-tray, .menu, .rs-edge')) return false;
      const r = el.getBoundingClientRect(), at = p === 'sticky' ? parseFloat(getComputedStyle(el).top) : r.top;  // where it sticks, not where it is now
      return r.width > innerWidth * 0.4 && at < innerHeight * 0.3;
    });
  }
  // How far down the page those bars reach now, over the lit thing: none when it's in a bar itself (the Live pill in the
  // menu bar sits over everything), and only bars that start above its bottom (Brett, 2026-10-26: Live was lit below Battle's
  // numbers, an empty box mid-page)
  const covered = () => {
    if (!lit || bars.some(el => el.contains(lit))) return 0;
    const litBottom = lit.getBoundingClientRect().bottom;
    return bars.reduce((m, el) => {
      if (lit.contains(el)) return m;
      const r = el.getBoundingClientRect();
      return r.top < litBottom && r.top < innerHeight * 0.3 && r.bottom < innerHeight * 0.75 ? Math.max(m, r.bottom) : m;  // (a bar that fills over half a short window)
    }, 0);
  };
  function rect() {
    if (!lit) return null;
    const b = box(), top = lit.closest('.peek') ? b.top : Math.max(b.top, covered());
    const r = { top, left: b.left, right: b.right, width: b.width, bottom: b.bottom, height: b.bottom - top };
    if (!tall(r)) return r;
    const bottom = Math.min(r.bottom, Math.max(r.top, 0) + innerHeight * 0.45);
    return { ...r, bottom, height: bottom - r.top };
  }
  function place() {
    if (!tour || !card) return;
    const r = rect(), pad = 6;
    spot.hidden = !r;
    card.classList.toggle('alone', !r);
    if (!r) { card.style.top = card.style.left = ''; return; }
    Object.assign(spot.style, { top: r.top - pad + 'px', left: r.left - pad + 'px', width: r.width + pad * 2 + 'px', height: r.height + pad * 2 + 'px' });
    if (matchMedia('(max-width: 640px)').matches) return;  // phones: the card sits at the bottom (app.css)
    const h = card.offsetHeight, w = card.offsetWidth;
    let top = r.bottom + 14 + h < innerHeight ? r.bottom + 14 : r.top - h - 14;  // below the lit thing if it fits, else above
    let left = Math.min(Math.max(12, r.left), innerWidth - w - 12);
    if (top < 12) {  // too tall either way: beside it, or over its bottom corner
      top = Math.min(Math.max(12, r.top), innerHeight - h - 12);
      left = r.right + 18 + w < innerWidth ? r.right + 18 : r.left - w - 18 >= 12 ? r.left - w - 18 : innerWidth - w - 12;
    }
    const peek = lit.closest('.peek');  // in the side panel: beside the panel, so its rows stay readable
    if (peek) {
      const p = peek.getBoundingClientRect();
      if (p.left - w - 18 >= 12) { left = p.left - w - 18; top = Math.min(Math.max(12, r.top), innerHeight - h - 12); }
    }
    card.style.top = top + 'px'; card.style.left = left + 'px';
  }
  async function waitFor(sel, ms) {  // the side panel loads after a click
    for (const t0 = Date.now(); Date.now() - t0 < ms; await new Promise(r => { setTimeout(r, 80); })) { const el = visible(sel); if (el) return el; }
    return null;
  }
  // Get the page ready for a stop: click what it opens, in turn, and add its example row
  async function prepare(s) {
    document.querySelectorAll('.tour-example').forEach(x => x.remove());
    if (!s.panel && tour.panel) tidy();
    if (s.swap && tour.shown !== s.swap) {  // ("own" is the real Battle: nothing left to put back after it)
      await swapBattle(s.swap); tour.shown = s.swap === s.restore ? null : s.swap; tour.restore = s.restore; keep();
    }
    else if (!s.swap && tour.shown) { await swapBattle(tour.restore); tour.shown = null; keep(); }
    const opens = [].concat(s.open || []);  // (a tour saved before opens were lists: one selector)
    if (opens.length && !(s.panel && visible(s.at))) {  // the panel already showing what this stop lights: leave it
      for (const sel of opens) {
        const el = await waitFor(sel, 3000); if (!el) break;
        if (el.getAttribute('aria-selected') !== 'true') el.click();
        if (s.panel) { tour.panel = true; keep(); }
      }
      if (s.panel) {  // let the panel finish sliding in: until it stays put for a moment
        const el = await waitFor(s.at, 4000), panel = el && el.closest('.peek');
        for (let k = 0, x = NaN; k < (panel ? 25 : 0); k++) {  // (it can wait a frame or two before it starts to move)
          await new Promise(res => { setTimeout(res, 60); });
          const r = panel.getBoundingClientRect(), at = r.left + ',' + r.top;  // sliding in from the side, or up on phones
          if (at === x && r.left < innerWidth - 40 && r.top < innerHeight - 40) break; x = at;
        }
      }
    }
    if (s.example) {
      const col = visible('[data-tour="battle"] [data-econ-col="action"] .moves');
      if (col) {
        const row = document.createElement('div'); row.className = 'move tour-example';
        row.innerHTML = `<b>${esc(tour.example || 'Your pick')}</b> <span class="tag">Example</span>`
          + (s.example === 'note' ? '<div class="meta move-note">✎ Your note shows here</div>' : '');
        col.prepend(row);
      }
    }
    return s.panel ? waitFor(s.at, 4000) : visible(s.at);
  }
  async function show(s) {
    const i = tour.i, found = await prepare(s);
    if (!tour || tour.i !== i || asking) return;  // moved on, ended or asked to end while the panel loaded
    if (!spot) {
      spot = document.createElement('div'); spot.className = 'tour-spot';
      card = document.createElement('div'); card.className = 'tour-card'; card.setAttribute('role', 'dialog'); card.setAttribute('aria-label', 'Tour');
      document.body.append(spot, card);
    }
    render(s);
    lit = found || null;
    lits = s.all && lit ? [...document.querySelectorAll(s.at)] : [];
    const row = lit && lit.closest('.ri');  // a row in the side panel: its name is the example on Battle next
    if (row && row.querySelector('.ri-name')) { tour.example = row.querySelector('.ri-name').textContent.trim(); keep(); }
    if (lit) {
      findBars();
      frame(s);
      shownAt = Date.now(); holding = true; scrolled = 0;
    }
    requestAnimationFrame(() => { if (!card || asking) return; place(); card.querySelector('[data-tour-go="1"]').focus({ preventScroll: true }); });  // (ended meanwhile)
    follow();
  }
  // The card: a bar for how far along the tour is, the stop's words, and Back, Next and ✕
  function render(s) {
    const n = tour.stops.length, last = tour.i === n - 1;
    asking = false;
    card.innerHTML = `<div class="tour-progress" role="progressbar" aria-label="Tour progress" aria-valuemin="1" aria-valuemax="${n}" aria-valuenow="${tour.i + 1}"><i style="width:${((tour.i + 1) / n * 100).toFixed(1)}%"></i></div>`
      + `<h3>${esc(s.title)}</h3><p>${s.what}</p><p class="why">${s.why}</p>`  // the words are askdnd's own (app/tour.py), with <b> for names
      + `<div class="tour-foot"><span class="tour-n">${tour.i + 1} of ${n}</span>`
      + (tour.i ? '<button type="button" class="btn small" data-tour-go="-1">Back</button>' : '')
      + `<button type="button" class="btn small primary" data-tour-go="1">${last ? 'Done' : 'Next'}</button>`
      + '<button type="button" class="btn small link" data-tour-end aria-label="End the tour">✕</button></div>';
  }
  // ✕ or Esc asks first, in the card (Brett, 2026-10-26); Done on the last stop just ends
  function askEnd() {
    asking = true;
    card.querySelector('h3').textContent = 'End the tour?';
    card.querySelectorAll('p').forEach(x => x.remove());
    card.querySelector('h3').insertAdjacentHTML('afterend', '<p>Take it again any time from <b>?</b> › Take the tour.</p>');
    card.querySelector('.tour-foot').innerHTML = '<span class="tour-n"></span><button type="button" class="btn small" data-tour-resume>Keep going</button>'
      + '<button type="button" class="btn small primary" data-tour-end-now>End tour</button>';
    place();
    card.querySelector('[data-tour-end-now]').focus({ preventScroll: true });
  }
  const resume = () => { asking = false; show(tour.stops[tour.i]); };  // (Esc may have closed the stop's side panel too: show opens it again)

  document.addEventListener('click', e => {
    const a = e.target.closest('[data-tour-start]');
    if (a) { e.preventDefault(); start(a.dataset.tourStart || ''); return; }
    if (!tour) return;
    const b = e.target.closest('[data-tour-go]');
    if (b) go(tour.i + +b.dataset.tourGo);
    else if (e.target.closest('[data-tour-end]')) askEnd();
    else if (e.target.closest('[data-tour-end-now]')) end();
    else if (e.target.closest('[data-tour-resume]')) resume();
  });
  document.addEventListener('keydown', e => {
    if (!tour || !card || e.target.matches('input, textarea, select, [contenteditable]')) return;
    if (e.key === 'Escape') { if (asking) resume(); else askEnd(); }
    else if (asking) return;  // (Enter presses the focused End tour or Keep going)
    else if (e.key === 'ArrowRight') go(tour.i + 1);
    else if (e.key === 'ArrowLeft' && tour.i > 0) go(tour.i - 1);
    else return;
    e.preventDefault();
  });
  addEventListener('resize', place);
  // Keep the light and the card on their target while anything on the page still moves or loads (a panel sliding in,
  // the Table rolls rail settling, a scrollbar coming or going, a picture loading), not only on scroll and resize:
  // every frame, re-place if the target moved. One rect read per frame, only while the tour is open.
  // Every stop is framed in the part of the screen the bars stuck across the top leave free: centered there when it fits,
  // else its top just under them (a few tries: a bar can stick, or change height, only once the page has scrolled).
  // While the stop shows, it's framed again whenever its top slips under them (fonts arriving, a picture, a new copy
  // redrawing Battle), until the person scrolls the page themselves (Brett, 2026-10-26: Battle's column headings kept
  // ending up behind its numbers; centering on the whole screen ignored them).
  // Something inside a stuck bar (Live, in the menu bar) or in the side panel isn't scrolled into place by the page.
  // Only a real scroll counts: not the last page's momentum, nor a finger resting on a trackpad (tiny wheel events; Brett,
  // 2026-10-26, on his laptop)
  let holding = false, shownAt = 0, scrolled = 0;
  addEventListener('wheel', e => { if (Date.now() - shownAt > 800 && (scrolled += Math.abs(e.deltaY)) > 60) holding = false; }, { passive: true });
  addEventListener('touchmove', () => { if (Date.now() - shownAt > 800) holding = false; }, { passive: true });
  function frame(s) {
    if (lit.closest('.peek')) { lit.scrollIntoView({ block: s.all ? 'nearest' : 'center' }); return; }
    if (bars.some(el => el.contains(lit))) return;
    for (let k = 0; k < 4; k++) {
      const r = box(), free = covered(), room = innerHeight - free;
      const want = r.height + 32 <= room ? free + (room - r.height) / 2 : free + 16;
      if (Math.abs(r.top - want) < 2) break;
      scrollBy(0, r.top - want);
    }
  }
  let following = false, was = '';
  function follow() {
    if (following) return;
    following = true;
    const tick = () => {
      if (!tour || !card) { following = false; was = ''; return; }
      if (lit && !lit.isConnected) {  // redrawn under the stop (a fresh sheet): light the new one
        const s = tour.stops[tour.i], now = s && visible(s.at);
        if (now) { lit = now; if (s.all) lits = [...document.querySelectorAll(s.at)]; }
      }
      if (lit && holding && !lit.closest('.peek') && box().top < covered() + 4) frame(tour.stops[tour.i]);
      const r = rect(), now = r ? [r.left, r.top, r.width, r.height].map(Math.round).join() : '';
      if (now !== was) { was = now; place(); }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  addEventListener('scroll', place, { passive: true });
  try { tour = JSON.parse(sessionStorage.getItem(KEY)); } catch (e) { tour = null; }
  if (tour && tour.stops && tour.stops[tour.i]) {
    const s = tour.stops[tour.i];
    // Arrived on the stop's page (or the address redirected): carry on here. Otherwise this is a page the person
    // opened themselves mid-tour, so the tour ends instead of pulling them back.
    if (tour.arriving || !s.url || new URL(s.url, location.href).pathname === location.pathname) { tour.arriving = false; keep(); show(s); }
    else end();
  } else tour = null;
})();

// ---------------------------------------------------------------- the D&D Beyond bridge
// The bridge (app/ddb_bridge.py): every number comes from D&D Beyond; a change made here
// is an intent askdnd keeps until the extension (extension/askdnd-bridge/) has made it on D&D Beyond and askdnd has
// read it back. Pages talk to the extension with window messages ({askdndBridge: ...}). The bridge's health shows on
// Backstage › askdnd › D&D Beyond bridge (admins); players see how their own sheet is kept in step in the Live pill.
(function () {

  // Is the extension in this browser? It answers a ping; on a computer, no answer means the Live pill offers it. (Phones
  // can't add it, and change things on D&D Beyond.)
  if (document.body.classList.contains('at-table') && !matchMedia('(max-width: 900px)').matches) {
    let heard = false;
    addEventListener('message', e => {
      if (e.source !== window || !e.data || e.data.askdndBridge !== 'hello') return;
      heard = true;
      document.body.dataset.bridgeVersion = e.data.version || 'before 0.9.9';  // which extension this browser has (0.9.9 on says)
      document.body.classList.remove('no-bridge');
      document.dispatchEvent(new Event('askdnd:pill'));  // (an open roll card's Game Log line)
    });
    window.postMessage({ askdndBridge: 'ping' }, location.origin);
    setTimeout(() => {
      if (heard) return;
      document.body.classList.add('no-bridge');
      document.dispatchEvent(new Event('askdnd:pill'));  // (an open roll card's Game Log line)
      if (!/Chrome\//.test(navigator.userAgent)) document.body.classList.add('bridge-elsewhere');  // (Safari, Firefox: it can't be added here)
    }, 1500);
  }

  // The pill on every page
  const pill = document.querySelector('[data-bridge-health]');
  let health = null, healthTimer = null;
  async function checkHealth() {  // (one loop, however often it's called)
    if (!pill) return;
    clearTimeout(healthTimer);
    try { const r = await fetch('/bridge/health', { headers: { Accept: 'application/json' } }); if (r.ok) health = await r.json(); } catch (e) { /* offline */ }
    if (health) {
      pill.className = pill.dataset.base + ' ' + ({ live: 'br-live', wait: 'br-wait', off: 'br-off', asleep: 'br-asleep' }[health.state] || 'br-wait');
      pill.textContent = health.text + (health.checked_at ? ' (checked ' + new Date(health.checked_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + ')' : '');
      pill.title = health.state === 'asleep' ? (health.awake.why || 'Asleep') + ' Wakes as soon as someone opens or uses askdnd or a sheet; click to run the check.'
        : 'D&D Beyond read ' + (health.read_check.ok ? 'OK' : 'failed: ' + health.read_check.error) + (health.round_trip && health.round_trip.error ? ' · check: ' + health.round_trip.error : '');
    }
    clearTimeout(healthTimer);  // (again: another call may have finished while this one waited)
    healthTimer = setTimeout(checkHealth, health && health.state === 'wait' ? 3000 : 30000);
  }
  if (document.body.dataset.bridgeOn !== undefined) {
    // Awake whenever someone is using askdnd (app/ddb_bridge.py): opening a page, and using it (at most once a
    // minute), keeps it awake 30 more minutes; the extension starts its pulls at once. (A running fight keeps it awake
    // too: ddb_bridge.awake.)
    let usedAt = 0;
    const used = () => {
      usedAt = Date.now();
      fetch('/bridge/active', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(r => r.json()).then(h => { const slept = !health || health.state === 'asleep'; health = h; if (slept) window.postMessage({ askdndBridge: 'wake' }, location.origin); checkHealth(); })
        .catch(() => {});
    };
    ['click', 'keydown', 'change'].forEach(k => document.addEventListener(k, () => { if (Date.now() - usedAt > 60000) used(); }, { passive: true }));
    used();
  }
  if (pill) {
    checkHealth();
    pill.addEventListener('click', async () => {  // run the round trip on the test character (Backstage › askdnd › D&D Beyond bridge)
      pill.textContent = 'D&D Beyond · checking…';
      const r = await fetch('/bridge/check', { method: 'POST', headers: { Accept: 'application/json' } });
      if (r.ok) { window.postMessage({ askdndBridge: 'deliver', ddbId: (await r.json()).test_ddb_id }, location.origin); }
      else pill.textContent = 'D&D Beyond · open the test character\'s sheet to check';
      checkHealth();
    });
  }

  const all = document.querySelector('[data-br-check-all]');
  if (all) all.addEventListener('click', async () => {  // Backstage › askdnd › D&D Beyond bridge: every kind of change, out and back
    all.disabled = true;
    const r = await fetch('/bridge/check?full=1', { method: 'POST', headers: { Accept: 'application/json' } });
    if (r.ok) window.postMessage({ askdndBridge: 'deliver', ddbId: (await r.json()).test_ddb_id }, location.origin);
    all.textContent = r.ok ? 'Checking: the menu bar shows how it goes' : 'Open the test character\'s sheet first';
    setTimeout(() => { all.disabled = false; all.textContent = 'Check everything'; }, 8000);
  });

  // Backstage › Design system: its navigation row lights the section you're in and keeps that chip in view; ↑ Top goes back
  // up (Brett, 2026-10-29)
  const dsJump = document.querySelector('[data-ds-jump]');
  if (dsJump && window.IntersectionObserver) {
    const links = new Map([...dsJump.querySelectorAll('a[href^="#"]:not([data-ds-top])')].map(a => [a.getAttribute('href').slice(1), a]));
    const seen = new Set();
    let lit = null;
    const light = () => {
      const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      // the first section on screen, in page order; the last one once you're at the bottom; else the one lit before
      const id = (atEnd && [...links.keys()].pop()) || [...links.keys()].find(k => seen.has(k)) || lit;
      if (id === lit) return;
      lit = id;
      links.forEach((a, k) => a.setAttribute('aria-current', String(k === id)));
      const a = links.get(id);
      if (a) dsJump.scrollTo({ left: Math.max(0, a.offsetLeft - dsJump.clientWidth / 2 + a.offsetWidth / 2), behavior: 'smooth' });
    };
    const io = new IntersectionObserver(es => { es.forEach(e => e.isIntersecting ? seen.add(e.target.id) : seen.delete(e.target.id)); light(); },
                                        { rootMargin: '-120px 0px -50% 0px' });
    links.forEach((a, id) => { const sec = document.getElementById(id); if (sec) io.observe(sec); });
    window.addEventListener('scroll', () => { if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) light(); }, { passive: true });
    dsJump.querySelector('[data-ds-top]').addEventListener('click', e => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
  }
  // ⓘ by the character's name on a phone: the line about them (Brett chose B, Nov 4, feedback 11)
  document.addEventListener('click', e => {
    const b = e.target.closest('.char-about');
    if (!b) return;
    const sub = document.getElementById(b.getAttribute('aria-controls'));
    const open = b.getAttribute('aria-expanded') !== 'true';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (sub) sub.classList.toggle('open', open);
  });
  // A change for D&D Beyond was just made on this page, whichever it is (web.deliver_now): the extension makes it now,
  // not at its next check every 30 seconds (Brett, 2026-10-29: Battle's changes waited up to half a minute)
  document.body.addEventListener('bridgeDeliver', e => {
    const ddbId = e.detail && e.detail.ddbId;
    for (const id of [...((e.detail && e.detail.also) || []), ddbId]) if (id) window.postMessage({ askdndBridge: 'deliver', ddbId: String(id) }, location.origin);
    if (e.detail && e.detail.upto) window.askdndFollow(e.detail);  // its corner card follows it (app.js "following a change")
  });
})();

// ---------------------------------------------------------------- Manage counts
// Beside Needs you, Inbox and Feedback (app/manage.py counts): asked for once, when the Manage or Admin menu opens or a Manage page
// loads, so no other page waits for them
// (issue 46, Nov 19: the counts blinked out and back on every click down Manage's list) The last counts this tab heard
// are shown at once, kept in sessionStorage, and the fresh ones replace them when they come.
(function () {
  let asked = false;
  const at = document.querySelector('[data-manage-counts]'), KEY = 'askdnd-manage-counts:' + (at ? at.dataset.manageCounts : '');  // (a campaign's own)
  const show = c => document.querySelectorAll('[data-manage-count]').forEach(el => {
    if (!(el.dataset.manageCount in c)) return;
    const n = c[el.dataset.manageCount]; el.textContent = n || ''; el.hidden = !n;
  });
  try { show(JSON.parse(sessionStorage.getItem(KEY) || '{}')); } catch (e) { /* (no storage: they come with the answer) */ }
  function fill() {
    const src = document.querySelector('[data-manage-counts]');
    if (asked || !src) return;
    asked = true;
    fetch(src.dataset.manageCounts, { headers: { Accept: 'application/json' } }).then(r => (r.ok ? r.json() : {})).then(c => {
      show(c);
      try { sessionStorage.setItem(KEY, JSON.stringify(Object.assign(JSON.parse(sessionStorage.getItem(KEY) || '{}'), c))); } catch (e) { /* (fine) */ }
    }).catch(() => {});
  }
  if (document.querySelector('.manage-side')) fill();
  document.addEventListener('click', e => { if (e.target.closest('[data-menu="manage-menu"], [data-menu="admin-menu"], [data-menu="more-menu"]')) fill(); });
  // (issue 40, Nov 19: a press redrawn in place drew Manage's side list with its counts empty until they came again)
  // The new copy gets the last counts in the same moment it goes in, before it's painted, so a count never blinks.
  document.addEventListener('askdnd:swapped', () => { try { show(JSON.parse(sessionStorage.getItem(KEY) || '{}')); } catch (e) { /* (no storage) */ } });
})();

// ---------------------------------------------------------------- For you's count on Backstage
// (Brett, Nov 19, the work flow's slice 2: a count on the gear, For you first in its menu; on Backstage since Nov 20) Everything waiting on him,
// asked for once the page has shown (no page waits for it) and again when Found, Fixed, Tried changes; hidden at zero
(function () {
  const badge = document.querySelector('[data-for-you-count]');
  if (!badge) return;
  const btn = badge.closest('button'), said = btn.getAttribute('aria-label');
  const KEY = 'askdnd-for-you-count';  // (the last count, shown at once so it never blinks between pages: issue 46)
  let tick = null;
  function put(n) {
    document.querySelectorAll('[data-for-you-count], [data-manage-count="for-you"]').forEach(el => { el.textContent = n || ''; el.hidden = !n; });
    btn.setAttribute('aria-label', n ? said + ', ' + n + ' waiting on you' : said);
  }
  try { const was = sessionStorage.getItem(KEY); if (was !== null) put(Number(was)); } catch (e) { /* (no storage: it comes with the answer) */ }
  function ask(shown) {
    fetch('/manage/for-you/count' + (shown === true ? '?seen=1' : ''), { headers: { Accept: 'application/json' }, cache: 'no-store' }).then(r => (r.ok ? r.json() : null)).then(j => {
      if (!j) return;
      put(j.n);
      try { sessionStorage.setItem(KEY, String(j.n || 0)); } catch (e) { /* (fine) */ }
    }).catch(() => {});
  }
  const seen = () => ask(true);  // (a page of his just showed: Available's quiet signal reads it)
  if (document.readyState === 'complete') setTimeout(seen, 300); else addEventListener('load', () => setTimeout(seen, 300));
  document.addEventListener('askdnd:live', e => { if (e.detail.type === 'fft') { clearTimeout(tick); tick = setTimeout(ask, 400); } });
  document.addEventListener('askdnd:changed', seen);  // (a press redrawn in place: his count may have moved)
  document.addEventListener('askdnd:swapped', () => { try { const was = sessionStorage.getItem(KEY); if (was !== null) put(Number(was)); } catch (e) { /* (no storage) */ } });  // (the redrawn side list: its count at once, issue 40)
})();

// ---------------------------------------------------------------- Changing spells and forms
// (app/choosing.py, _change_window.html; Brett, Nov 16: the wide window, D on docs/mockups/changing-spells/) Sheet's own
// list in a large modal. A row's button changes nothing yet: the counts, each rule's Now or Not now, the warnings and Your
// changes follow as you go, and Make sends them all. A full count is held, as D&D Beyond holds it (let one go first);
// a swap past its 2024 rule (how many, or when) is warned about, never blocked. Two classes: a tab each, the list showing
// that class's rows (the others are left out of the list's counts, `data-ls-out`), Your changes keeping both.
(function () {
  function start(root) {
    if (root._chg) return;
    root._chg = true;
    const lists = JSON.parse(root.dataset.lists || '{}'), occs = JSON.parse(root.dataset.occs || '[]');
    const head = (root.closest('.peek') || document).querySelector('.chg-head'), list = root.querySelector('[data-list]');
    const rows = [...root.querySelectorAll('[data-pick-row]')];
    const on = r => r.dataset.on === '1', moved = r => !r.dataset.always && r.dataset.on !== r.dataset.base;
    const count = id => rows.filter(r => r.dataset.pickList === id && !r.dataset.always && on(r)).length;
    const now = L => root.dataset.occ === 'look' ? '' : L.occ.includes(root.dataset.occ) ? 'yes' : 'no';
    const occText = () => (occs.find(o => o[0] === root.dataset.occ) || [])[2] || '';
    function changes() {
      return Object.entries(lists).map(([id, L]) => {
        const rs = rows.filter(r => r.dataset.pickList === id && moved(r));
        return { id, L, adds: rs.filter(on).map(r => r.dataset.label), drops: rs.filter(r => !on(r)).map(r => r.dataset.label) };
      }).filter(g => g.adds.length || g.drops.length);
    }
    function draw() {
      // each list's rule line: its count, Now or Not now, and Full
      Object.entries(lists).forEach(([id, L]) => {
        const line = root.querySelector('[data-rule="' + id + '"]'); if (!line) return;
        const n = count(id), st = now(L);
        line.querySelector('[data-rule-count]').textContent = n;
        const pill = line.querySelector('[data-rule-now]');
        pill.textContent = st === 'yes' ? 'Now' : st === 'no' ? 'Not now' : 'Just looking';
        pill.className = 'rl-now' + (st ? ' ' + st : '');
        const full = line.querySelector('[data-rule-full]'); if (full) full.hidden = !(L.cap && n >= L.cap);
      });
      // each row: its button's words, its mark, held when its list is full, in Yours or not
      rows.forEach(r => {
        const L = lists[r.dataset.pickList], m = moved(r), b = r.querySelector('[data-pick-act]');
        r.classList.toggle('add', m && on(r));
        r.classList.toggle('drop', m && !on(r));
        const mark = r.querySelector('.sh-status');
        if (mark && !r.dataset.always) { mark.textContent = on(r) ? '✓' : '○'; mark.classList.toggle('on', on(r)); mark.classList.toggle('off', !on(r)); }
        const views = (r.dataset.views || '').split(' ').filter(v => v && v !== 'mine');
        r.dataset.views = (on(r) || r.dataset.always ? ['mine'] : []).concat(views).join(' ');
        if (!b) return;
        const full = !on(r) && L.cap && count(r.dataset.pickList) >= L.cap;
        b.textContent = m ? 'Undo' : on(r) ? L.drop : L.add;
        b.classList.toggle('mine', on(r) && !m);
        b.classList.toggle('undo', m);
        b.setAttribute('aria-pressed', on(r) ? 'true' : 'false');
        b.disabled = !!full;
        b.title = full ? `${count(r.dataset.pickList)} of ${L.cap}: ${L.first}` : '';
      });
      // the class tabs: the chosen class's rows in the list; a dot for whether its rules allow it now
      const cls = root.dataset.cls;
      root.querySelectorAll('[data-chg-cls]').forEach(t => {
        t.setAttribute('aria-selected', t.dataset.chgCls === cls ? 'true' : 'false');
        const ls = Object.values(lists).filter(L => L.cls === t.dataset.chgCls), dot = t.querySelector('[data-chg-dot]');
        if (dot) dot.className = 'chg-dot ' + (root.dataset.occ === 'look' ? '' : ls.some(L => now(L) === 'yes') ? 'yes' : 'no');
      });
      if (root.querySelector('[data-chg-cls]')) rows.forEach(r => r.toggleAttribute('data-ls-out', r.dataset.cls !== cls));
      (head || root).querySelectorAll('[data-chg-occ]').forEach(b => { const o = b.dataset.chgOcc === root.dataset.occ; b.classList.toggle('on', o); b.setAttribute('aria-pressed', o ? 'true' : 'false'); });
      // Your changes, and what goes past a rule
      const ch = changes(), n = ch.reduce((a, g) => a + g.adds.length + g.drops.length, 0);
      const box = root.querySelector('[data-chg-list]');
      box.replaceChildren(...(n ? ch.flatMap(g => [...g.adds.map(x => ['add', '+ ' + x]), ...g.drops.map(x => ['drop', x])]).map(([k, t]) => {
        const s = document.createElement('span'); s.className = 'chg-chip ' + k; s.textContent = t; return s;
      }) : [Object.assign(document.createElement('span'), { className: 'note', textContent: 'None yet' })]));
      const warns = [];
      ch.forEach(g => {
        if (root.dataset.occ !== 'look' && !g.L.occ.includes(root.dataset.occ)) warns.push(`${g.L.label}: ${g.L.when}, not ${occText()}.`);
        const swaps = Math.max(g.adds.length, g.drops.length);
        if (g.L.one && swaps > 1) warns.push(`${g.L.label}: ${g.L.when}; this swaps ${swaps}.`);
      });
      root.querySelector('[data-chg-warns]').replaceChildren(...warns.map(w => {
        const p = document.createElement('p'); p.className = 'chg-warn';
        const b = document.createElement('b'); b.textContent = 'Past the rule';
        p.append(b, ' ', w); return p;
      }));
      const make = root.querySelector('[data-chg-make]');
      if (make) { make.disabled = !n; make.textContent = n ? `Make ${n} change${n === 1 ? '' : 's'} on D&D Beyond` : 'Make changes'; }
      if (list) list.dispatchEvent(new CustomEvent('list:refresh', { bubbles: true }));
    }
    const post = body => fetch(root.dataset.url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' }, body: JSON.stringify(body) })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.detail || "askdnd couldn't do that"); return j; }));
    const told = j => { document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: j.deliver })); document.body.dispatchEvent(new CustomEvent('characterChanged')); };
    root.addEventListener('click', e => {
      const act = e.target.closest('[data-pick-act]');
      if (act) { e.stopPropagation(); const r = act.closest('[data-pick-row]'); r.dataset.on = on(r) ? '' : '1'; draw(); return; }
      const tab = e.target.closest('[data-chg-cls]');
      if (tab) { root.dataset.cls = tab.dataset.chgCls; draw(); return; }
      if (e.target.closest('[data-chg-reset]')) { rows.forEach(r => { r.dataset.on = r.dataset.base; }); draw(); return; }
      const make = e.target.closest('[data-chg-make]');
      if (make && !make.disabled) {
        const said = root.querySelector('[data-chg-said]');
        make.disabled = true;
        post({ changes: rows.filter(moved).map(r => ({ id: r.dataset.pick, on: on(r) })) })
          .then(j => {
            told(j);
            window.askdndToast(j.text, j.undo ? { label: 'Undo', run: () => post({ undo: j.undo }).then(u => { told(u); window.askdndToast(u.text); }).catch(err => window.askdndToast(err.message, null, 'warn')) } : null);
            window.askdndPanel(root.dataset.url + (root.dataset.url.includes('?') ? '&' : '?') + 'cls=' + encodeURIComponent(root.dataset.cls) + '&why=' + root.dataset.occ, null, null, 'large');  // (again: each change shows ↻ until D&D Beyond has it)
          })
          .catch(err => { said.hidden = false; said.textContent = err.message; make.disabled = false; });
      }
    });
    // Why you're changing (Brett chose B, Nov 16, docs/mockups/why-changing/): asked first when no reason came with the
    // window (a tile each), then a chip by the title that opens the reasons again, in the window's head
    const reasonChip = head && head.querySelector('[data-chg-reason]'), reasons = head && head.querySelector('[data-chg-reasons]');
    function choose(k) {
      root.dataset.occ = k;
      root.removeAttribute('data-asking');
      const ask = root.querySelector('[data-chg-ask]'); if (ask) ask.hidden = true;
      root.querySelector('[data-chg-main]').hidden = false;
      if (reasonChip) {
        reasonChip.hidden = false;
        reasonChip.querySelector('[data-chg-reason-label]').textContent = (occs.find(o => o[0] === k) || [])[1] || '';
        reasonChip.setAttribute('aria-expanded', 'false');
      }
      if (reasons) reasons.hidden = true;
      draw();
    }
    root.addEventListener('click', e => { const t = e.target.closest('[data-chg-ask] [data-chg-occ]'); if (t) choose(t.dataset.chgOcc); });
    if (head) head.addEventListener('click', e => {
      const b = e.target.closest('[data-chg-occ]');
      if (b) { choose(b.dataset.chgOcc); return; }
      if (e.target.closest('[data-chg-reason]') && reasons) { reasons.hidden = !reasons.hidden; reasonChip.setAttribute('aria-expanded', reasons.hidden ? 'false' : 'true'); }
    });
    draw();
  }
  document.addEventListener('panel:loaded', e => { const root = e.target.querySelector('[data-change]'); if (root) start(root); });
})();

// ---------------------------------------------------------------- Item browser
// (app/item_browser.py, _item_browser.html; Brett, 2026-11-03, docs/mockups/item-browser/) A large modal over D&D
// Beyond's 2024 items, using the Lists pattern for search and filters. A name (or its row) shows what the item is beside
// the list, over it on a narrow screen; + puts one in Adding, where − and + change how many; one press makes them all.
// What's paid starts at the book's price for the items that have one and is the player's to change (the DM agrees a
// price); once they've typed in it, it stays theirs.
(function () {
  const COPPER = { gp: 100, sp: 10, cp: 1 };
  const money = cp => Object.entries(COPPER).map(([c, v]) => { const n = Math.floor(cp / v); cp -= n * v; return n ? n.toLocaleString() + ' ' + c : ''; })
    .filter(Boolean).join(' ') || '0 gp';
  function start(root) {
    if (root._ib) return;
    root._ib = true;
    const loot = root.dataset.mode === 'loot', $ = s => root.querySelector(s);
    const basket = new Map();  // id -> {name, n, cp}
    const detail = $('[data-ib-detail]'), pay = $('[data-ib-pay]'), paying = $('[data-ib-paying]'), go = $('[data-ib-go]');
    const amount = $('[data-ib-amount]'), said = $('[data-ib-said]');
    let typed = false, shown = null;
    const rowOf = id => root.querySelector('[data-ls-row][data-id="' + id + '"]');
    function draw() {
      const box = $('[data-ib-basket]');
      box.replaceChildren(...[...basket].map(([id, b]) => {
        const chip = document.createElement('span');
        chip.className = 'ib-chip';
        const name = document.createElement('b');
        name.textContent = b.name;
        const n = document.createElement('span');
        n.textContent = '×' + b.n;
        const less = document.createElement('button'), more = document.createElement('button');
        less.type = more.type = 'button';
        less.textContent = '−'; more.textContent = '+';
        less.dataset.ibLess = more.dataset.ibMore = id;
        less.setAttribute('aria-label', 'One fewer ' + b.name);
        more.setAttribute('aria-label', 'One more ' + b.name);
        chip.append(name, n, less, more);
        return chip;
      }));
      const items = [...basket.values()], count = items.reduce((t, b) => t + b.n, 0);
      $('[data-ib-empty]').hidden = count > 0;
      root.querySelectorAll('[data-ls-row]').forEach(r => r.classList.toggle('in-basket', basket.has(r.dataset.id)));
      if (pay) {
        if (!typed) pay.value = count ? money(items.reduce((t, b) => t + b.n * b.cp, 0)) : '';
        pay.disabled = !paying.checked;
        if ($('[data-ib-from]')) $('[data-ib-from]').disabled = !paying.checked;
        const unpriced = items.filter(b => !b.cp).length, note = $('[data-ib-price-note]');
        note.hidden = !unpriced;
        note.textContent = unpriced ? (unpriced === 1 ? '1 item has' : unpriced + ' items have') + " no price in the books (a magic item never does): what you pay for it is the DM's to say." : '';
      }
      const coins = amount && +amount.value > 0 ? (+amount.value).toLocaleString() + ' ' + $('[data-ib-coin]').value : '';
      if (go) {
        go.disabled = !count && !coins;
        const what = [count && count + ' item' + (count === 1 ? '' : 's'), coins].filter(Boolean).join(' and ');
        go.textContent = (loot ? 'Give ' : 'Add ') + (what || '');
      }
    }
    function add(id, n = 1) {
      const r = rowOf(id); if (!r) return;
      const b = basket.get(id) || { name: r.dataset.label, n: 0, cp: +r.dataset.cp || 0 };
      b.n = Math.min(100, b.n + n);
      if (b.n > 0) basket.set(id, b); else basket.delete(id);
      draw();
    }
    function show(id) {
      shown = id;
      root.querySelectorAll('[data-ls-row]').forEach(r => r.classList.toggle('sel', r.dataset.id === id));
      fetch(root.dataset.detailUrl + id, { headers: { 'HX-Request': 'true' } })
        .then(r => (r.ok ? r.text() : Promise.reject(r.status)))
        .then(html => { if (shown !== id) return; detail.innerHTML = html; detail.scrollTop = 0; root.classList.add('ib-showing'); })
        .catch(() => { detail.innerHTML = '<p class="note">That item didn\'t load. Try again.</p>'; });
    }
    root.addEventListener('click', e => {
      const plus = e.target.closest('[data-ib-add]');
      if (plus) { add((plus.closest('[data-ls-row], [data-ib-card]')).dataset.id); return; }
      const less = e.target.closest('[data-ib-less]'); if (less) { add(less.dataset.ibLess, -1); return; }
      const more = e.target.closest('[data-ib-more]'); if (more) { add(more.dataset.ibMore, 1); return; }
      if (e.target.closest('[data-ib-hide]')) { root.classList.remove('ib-showing'); return; }
      const row = e.target.closest('[data-ls-row]');
      if (row) { show(row.dataset.id); return; }
      if (go && e.target.closest('[data-ib-go]') && !go.disabled) {
        go.disabled = true;
        said.hidden = true;
        const body = { items: [...basket].map(([id, b]) => ({ id: +id, n: b.n })), into: $('[data-ib-into]').value };
        if (paying && paying.checked) { body.pay = pay.value; body.from = $('[data-ib-from]')?.value || 'me'; }
        if (amount) { body.amount = amount.value; body.coin = $('[data-ib-coin]').value; }
        fetch(root.dataset.url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' }, body: JSON.stringify(body) })
          .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.detail || "askdnd couldn't do that"); return j; }))
          .then(j => {
            document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: j.deliver }));
            document.body.dispatchEvent(new CustomEvent('characterChanged'));
            window.askdndToast(j.text);
            const x = root.closest('.peek').querySelector('.peek-close'); if (x) x.click();
          })
          .catch(err => { said.hidden = false; said.textContent = err.message; go.disabled = false; });
      }
    });
    root.addEventListener('input', e => {
      if (e.target === pay) { typed = pay.value.trim() !== ''; draw(); }
      if (e.target === amount) draw();
    });
    root.addEventListener('change', e => {
      if (e.target.matches('[data-ib-place]')) {  // For <character>: what it takes the place of (docs/mockups/gear-compare/)
        const box = e.target.closest('[data-ib-compare]');
        box.querySelectorAll('[data-ib-place-rows]').forEach(t => { t.hidden = t.dataset.ibPlaceRows !== e.target.value; });
        return;
      }
      if (e.target === paying || e.target.matches('[data-ib-coin]')) draw();
    });
    draw();
  }
  document.addEventListener('panel:loaded', e => { const root = e.target.querySelector('[data-ib]'); if (root) start(root); });
})();

// ---------------------------------------------------------------- picks from a mockup
// A mockup opened inside askdnd (Documents, For you's Open mockup) sits in a sealed frame that can't save anything
// itself, so its Save my picks hands its picks here, which saves them as the answer to the question asking about it,
// and opening it again shows them (Brett's round, Nov 18: his picks were lost). The frame names nothing: askdnd knows
// which document each of its frames holds (`data-doc`), and answers only a frame of its own.
(() => {
  const frameOf = src => [...document.querySelectorAll('iframe.doc-frame[data-doc]')].find(f => f.contentWindow === src);
  addEventListener('message', async e => {
    const d = e.data, f = frameOf(e.source);
    if (!f || !d || typeof d !== 'object' || !/^picks-(load|save)$/.test(d.askdnd || '')) return;
    const reply = msg => e.source.postMessage({ askdnd: 'picks', ...msg }, '*');
    try {
      if (d.askdnd === 'picks-load') {
        const r = await fetch('/manage/testing/picks?doc=' + encodeURIComponent(f.dataset.doc), { headers: { Accept: 'application/json' } });
        if (r.ok) reply({ ...(await r.json()), loaded: true });
        return;
      }
      const r = await fetch('/manage/testing/picks', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ doc: f.dataset.doc, picks: Array.isArray(d.picks) ? d.picks : [], notes: String(d.notes || '') }) });
      const j = await r.json().catch(() => ({}));
      reply(r.ok ? { saved: true, at: j.at, picks: d.picks, notes: d.notes } : { saved: false, said: j.detail || "Couldn't save them. Try again." });
    } catch (err) { reply({ saved: false, said: "Couldn't reach askdnd. Try again." }); }
  });
})();

// ---------------------------------------------------------------- send a note
// (Found, Fixed, Tried: app/fft/sending.py; screen 9 of docs/mockups/found-fixed-tried/) A note from any page, for
// whoever the page lets send one (body[data-feedback]). \ opens it (never while typing), as do the account menu's item
// and More's, and pressing and holding the askdnd logo. What it is is picked each time. The page's picture is drawn just
// after the window shows (html-to-image, vendored; the window left out), only what's on screen, and comes as two copies:
// the full one, its sender's alone, and the safe copy with every [data-private] part on screen (a player's character
// notes) covered, which an admin, the DM and Claude see (T5). More pictures are pasted (⌘V), dropped or chosen. Each
// picture is marked with Box, Arrow, Draw and Text; Undo and Clear sit apart. Take a screenshot puts the window away,
// keeping everything, until Back to it (or a paste) brings it back; Cancel closes it (Brett's pick 3A, issue 18).
(function () {
  const win = document.getElementById('fb-win');
  if (!win || document.body.dataset.feedback === undefined) return;
  const form = win.querySelector('form'), said = win.querySelector('[data-fb-said]'), send = win.querySelector('[data-fb-send]');
  const chips = win.querySelector('[data-fb-chips]'), addChip = win.querySelector('.fb-add-pic'), shotChip = win.querySelector('[data-fb-shot]'), stageNote = win.querySelector('[data-fb-stage-note]');
  const wrap = win.querySelector('[data-fb-wrap]'), canvas = win.querySelector('[data-fb-canvas]'), tools = win.querySelector('[data-fb-tools]'), edits = win.querySelector('[data-fb-edits]');
  const covered = win.querySelector('[data-fb-covered]'), lineEl = win.querySelector('[data-fb-line]'), titleEl = win.querySelector('[data-fb-title]');
  const wrongParts = [...win.querySelectorAll('[data-fb-wrong]')], stillBox = win.querySelector('[data-fb-still]'), kindRow = win.querySelector('[data-fb-kind-row]');
  const blockChips = [...win.querySelectorAll('[data-fb-block]')], stopsBox = win.querySelector('[data-fb-stops]');
  let pics = [], reading = 0, at = -1, html = '', ctx = {}, lib = null, taking = null, round = 0, why = '', kind = '', checking = null, blocking = null, hidden = false, hideCard = null;
  // Something's wrong… on a check (Testing, screen 3): whether it stops the check, picked each time like what it is
  const pickBlock = v => {
    blocking = v === 'yes' ? true : v === 'no' ? false : null;
    blockChips.forEach(c => { const on = c.dataset.fbBlock === v; c.classList.toggle('on', on); c.setAttribute('aria-checked', on ? 'true' : 'false'); });
    stopsBox.disabled = blocking !== true;
    if (blocking !== true) stopsBox.checked = false;
  };
  blockChips.forEach(c => c.addEventListener('click', () => { pickBlock(c.dataset.fbBlock); say(''); }));
  function checkMode(c) {  // the window as What's wrong? for a check, or back to Send a note
    checking = c;
    wrongParts.forEach(el => { el.hidden = !c; });
    kindRow.hidden = !!c;
    titleEl.textContent = c ? "What's wrong?" : 'Send a note';
    pickBlock('');
    stillBox.replaceChildren();
    if (!c) return;
    win.querySelector('[data-fb-wrong-where]').textContent = 'On ' + c.title;
    fetch('/manage/testing/checks/' + c.id + '/wrong', { headers: { Accept: 'application/json' } }).then(r => (r.ok ? r.json() : null)).then(j => {
      if (!j || checking !== c) return;
      c.try = c.another ? j.try : null;  // (✗ Another… adds to the try just failed; Something's wrong… starts a new one)
      win.querySelector('[data-fb-wrong-where]').textContent = 'On ' + j.title + ' · ' + j.device + ' · v' + j.version + ' · askdnd' + (j.where === 'live' ? '.ai' : ' (' + j.where + ')') + ' as of ' + j.app_version;
      const opt = (value, label, small) => {
        const l = Object.assign(document.createElement('label'), { className: 'fft-opt' });
        const i = Object.assign(document.createElement('input'), { type: 'radio', name: 'fb-still', value });
        if (value === '') i.checked = true;
        l.dataset.still = value;
        l.append(i, Object.assign(document.createElement('span'), { textContent: label }), Object.assign(document.createElement('small'), { className: 'note', textContent: small }));
        stillBox.append(l);
      };
      j.issues.forEach(i => opt(String(i.id), i.title, i.said + ' · still happening'));
      if (j.issues.length) opt('', 'Something new', 'describe it below');
    }).catch(() => { /* the window works without the list: it's something new */ });
  }
  const kindChips = [...win.querySelectorAll('[data-fb-kind]')], ask = win.querySelector('[data-fb-ask]'), askFirst = ask.textContent;
  const pickKind = k => {
    kind = k;
    kindChips.forEach(c => { const on = c.dataset.fbKind === k; c.classList.toggle('on', on); c.setAttribute('aria-checked', on ? 'true' : 'false'); });
    const chip = kindChips.find(c => c.dataset.fbKind === k);
    ask.textContent = chip ? chip.dataset.ask : askFirst;
  };
  kindChips.forEach(c => c.addEventListener('click', () => { pickKind(c.dataset.fbKind); say(''); }));
  const typing = el => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  const say = text => { said.textContent = text; said.hidden = !text; };
  const loadLib = () => lib || (lib = new Promise((ok, no) => {
    const s = document.createElement('script');
    s.src = '/static/vendor/html-to-image-1.11.11/html-to-image.js';
    s.onload = () => ok(window.htmlToImage); s.onerror = no;
    document.head.append(s);
  }));
  const offscreen = n => {
    if (n.nodeType !== 1 || !n.getBoundingClientRect) return false;
    const r = n.getBoundingClientRect();
    return (r.width || r.height) && (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth);
  };
  const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  // The parts of the page that are a player's own (their character's notes): where they are on screen, to cover
  const privateRects = () => [...document.querySelectorAll('[data-private]')].map(el => el.getBoundingClientRect())
    .filter(r => r.width && r.height && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth);
  function cover(c, rects) {  // the safe copy: each private part painted over, hatched, saying what it was
    const g = c.getContext('2d');
    rects.forEach(r => {
      g.save();
      g.fillStyle = getComputedStyle(document.body).backgroundColor || '#15171a'; g.fillRect(r.left, r.top, r.width, r.height);
      g.beginPath(); g.rect(r.left, r.top, r.width, r.height); g.clip();
      g.strokeStyle = 'rgba(128,128,128,.35)'; g.lineWidth = 2;
      for (let x = r.left - r.height; x < r.right; x += 14) { g.beginPath(); g.moveTo(x, r.bottom); g.lineTo(x + r.height, r.top); g.stroke(); }
      g.fillStyle = 'rgba(128,128,128,.9)'; g.font = '600 13px system-ui, sans-serif';
      g.fillText('Private notes', r.left + 10, r.top + 22);
      g.restore();
    });
  }
  // askdnd's own fonts (the page's Google Fonts, their Latin faces) as data, made once a visit (read from their stylesheet,
  // never setting a font: tests/test_design.py): the picture is drawn in
  // them, not in a wider stand-in that wraps words onto lines the page doesn't have (Brett's round, Nov 18: a heading
  // wrapped over its rows in the picture, never on the page)
  let fontsCSS = null;
  const embedFonts = () => fontsCSS || (fontsCSS = (async () => {
    await document.fonts.ready;
    const link = document.querySelector('link[rel="stylesheet"][href^="https://fonts.googleapis.com/"]');
    if (!link) return '';
    const css = await (await fetch(link.href)).text();
    // (only the faces the page is drawing with: a font loaded too late on a first visit stays out of the page for that
    // visit, display=optional, though it counts as loaded; drawn in the picture, its wider letters wrapped the page's
    // words, GitHub's machines, Nov 18. A face is in use when a word set in it, with a plain fallback, comes out a
    // different width from the fallback alone)
    const probe = document.createElement('span');
    Object.assign(probe.style, { position: 'absolute', left: '-9999px', top: '0', fontSize: '40px', whiteSpace: 'nowrap', visibility: 'hidden' });
    probe.textContent = 'Hamburgefonstiv 0123';
    document.body.append(probe);
    const width = (family, weight) => { probe.style.fontFamily = family; probe.style.fontWeight = weight; return probe.getBoundingClientRect().width; };
    const used = f => { const fam = f.family.replace(/["']/g, ''); return width(`"${fam}", monospace`, f.weight) !== width('monospace', f.weight); };
    const shown = new Set([...document.fonts].filter(f => f.status === 'loaded' && used(f)).map(f => f.family.replace(/["']/g, '') + ' ' + f.weight));
    probe.remove();
    const faces = css.split('@font-face').slice(1).map(b => '@font-face' + b.slice(0, b.indexOf('}') + 1))
      .filter(f => /U\+0000-00FF/.test(f) && shown.has(((/font-family\s*:\s*'?([^';]+)/.exec(f) || [])[1] || '') + ' ' + ((/font-weight\s*:\s*(\d+)/.exec(f) || [])[1] || '')));
    const inline = await Promise.all(faces.map(async f => {
      const m = f.match(/url\((https:[^)]+)\)/);
      if (!m) return '';
      const blob = await (await fetch(m[1])).blob();
      const data = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(blob); });
      return f.replace(m[1], data);
    }));
    return inline.join('\n');
  })().catch(() => ''));
  async function picture() {  // what's on screen, drawn again as an image (the 3D dice may differ)
    let h;
    try { h = await loadLib(); } catch (e) { why = "the picture's code didn't load"; return null; }
    const fonts = await embedFonts();
    const options = {
      quality: 0.8, pixelRatio: 1, width: innerWidth, height: innerHeight, skipFonts: true, imagePlaceholder: BLANK, ...(fonts ? { fontEmbedCSS: fonts } : {}),
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      // (scrolled by a margin, not a transform: a transform would carry what's fixed on screen down the page's height)
      style: { margin: '0', marginTop: -scrollY + 'px', marginLeft: -scrollX + 'px' },
      // (not this window, the corner cards or Battle's condition edge; nothing below the screen, so a long list costs
      // what its rows down to the screen's foot cost)
      filter: n => !(n.id === 'fb-win' || n.id === 'cards' || n.id === 'check-card' || (n.classList && n.classList.contains('cond-halo')) || n.hidden || gone.has(n)),
    };
    // True to what's on screen (Brett's round, Nov 18: parts of the page came out blank). The picture is drawn from the
    // page with nothing scrolled. Only what's below or right of the screen is left out (what's above it holds up what's
    // on it: left out, everything under it moved up). A part that stays put as you scroll is held where it is, and
    // what's scrolled inside a box is moved up by as much; all put back once it's drawn, its scrolling too.
    // (the private parts measured as the screen shows them, before anything is held or moved for the drawing: measured
    // after, a part inside a scrolled box was off by its scroll, and the covering missed it; the review of #417)
    const rects = privateRects();
    const all = [...document.body.querySelectorAll('*')];
    const past = n => { const r = n.getBoundingClientRect(); return (r.width || r.height) && (r.top > innerHeight || r.left > innerWidth); };
    const gone = new Set(all.filter(past));
    const scrolled = all.filter(el => el.scrollTop || el.scrollLeft).map(el => [el, el.scrollTop, el.scrollLeft]);
    const held = [];
    const hold = (el, props) => { held.push([el, el.getAttribute('style')]); Object.assign(el.style, props); };
    all.filter(el => !gone.has(el) && getComputedStyle(el).position === 'sticky').map(el => {
      const stuck = el.getBoundingClientRect(), was = el.getAttribute('style');
      Object.assign(el.style, { position: 'relative', top: '0px', left: '0px' });
      const free = el.getBoundingClientRect();
      if (was === null) el.removeAttribute('style'); else el.setAttribute('style', was);
      return [el, stuck.top - free.top, stuck.left - free.left];
    }).forEach(([el, dy, dx]) => { if (Math.abs(dy) > 0.5 || Math.abs(dx) > 0.5) hold(el, { position: 'relative', top: dy + 'px', left: dx + 'px' }); });
    scrolled.filter(([box]) => !gone.has(box)).forEach(([box, top, left]) => {
      [...box.children].forEach(ch => hold(ch, { translate: -left + 'px ' + -top + 'px' }));
    });
    // (words the screen shows on one line stay on one: the picture's letters can come out a hair wider than the screen's,
    // and a box as wide as its words then drops the last letter onto a line of its own, "Part / y"; Brett's round, Nov 18)
    // (and a name the screen shows whole isn't cut short with … in the picture)
    // (every measure first, then every change: changing as it went made the page lay itself out again for each line, and a
    // long list froze the tab; what's above the screen counts too, as its lines set where the rest falls; the review of
    // #417)
    const keep = [];
    all.forEach(el => {
      if (gone.has(el)) return;
      const words = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
      if (!words.length) return;
      const cs = getComputedStyle(el);
      if (cs.textOverflow === 'ellipsis' && el.scrollWidth <= el.clientWidth) { keep.push([el, { textOverflow: 'clip', overflow: 'visible' }]); return; }
      if (cs.whiteSpace !== 'normal') return;
      const tops = new Set();
      words.forEach(n => { const r = document.createRange(); r.selectNodeContents(n); [...r.getClientRects()].forEach(x => tops.add(Math.round(x.top))); });
      if (tops.size !== 1) return;
      keep.push([el, { whiteSpace: 'nowrap' }]);
      // (only its own words: what's inside it wraps as it did, or a step's why under its one-line step ran on past the
      // pane in one line; Brett's round, Nov 18. One inside that's on one line too is held after this, by its own turn)
      [...el.children].forEach(ch => { if (getComputedStyle(ch).whiteSpace === 'normal') keep.push([ch, { whiteSpace: 'normal' }]); });
    });
    const sideMargins = new Map();  // (each part's side margins as the screen has them: see the drawing, below)
    all.forEach(el => { if (gone.has(el)) return; const cs = getComputedStyle(el); if (cs.marginLeft !== '0px' || cs.marginRight !== '0px') sideMargins.set(el, [cs.marginLeft, cs.marginRight]); });
    keep.forEach(([el, props]) => hold(el, props));
    // (an attribute named with a colon stops the picture's SVG: set aside while it's drawn, and put back)
    const aside = [], blanked = [];
    document.querySelectorAll('*').forEach(el => { for (const a of [...el.attributes]) if (a.name.includes(':')) { aside.push([el, a.name, a.value]); el.removeAttribute(a.name); } });
    // (a picture from another site can't be read from here: drawn blank at its own size)
    document.querySelectorAll('img').forEach(im => {
      if (im.complete && im.naturalWidth && im.src.startsWith(location.origin + '/')) return;
      const r = im.getBoundingClientRect();
      blanked.push([im, im.getAttribute('src'), im.getAttribute('srcset'), im.style.width, im.style.height]);
      Object.assign(im.style, { width: r.width + 'px', height: r.height + 'px' });
      im.removeAttribute('srcset'); im.src = BLANK;
    });
    // (the 3D dice keep no copy of their last frame: each box on screen draws once more into a picture over its canvas)
    const stills = [];
    (window.askdndDice || []).forEach(b => {
      const c = b.renderer && b.renderer.domElement, r = c && c.getBoundingClientRect();
      if (!c || !c.isConnected || !r.width || !r.height || offscreen(c)) return;
      try { b.renderer.render(b.scene, b.camera); } catch (e) { return; }
      const im = document.createElement('img');
      im.src = c.toDataURL();
      Object.assign(im.style, { position: 'absolute', left: c.offsetLeft + 'px', top: c.offsetTop + 'px', width: c.offsetWidth + 'px', height: c.offsetHeight + 'px', pointerEvents: 'none' });
      im.className = 'fb-still';
      c.parentElement.append(im);
      stills.push(im);
    });
    // The drawing copies each part's computed style, read through getComputedStyle; while it reads, two of its answers
    // are put right (Brett's round, Nov 18, issues 29 and 31 on askdnd.ai). A part's side margins are the ones measured
    // before anything was changed for the drawing: once a picture from another site is blanked, Chrome gives a part
    // centred by auto margins 0px until that picture loads, and its shorthand margin is 0px too, so the page and the
    // menu bar were drawn against the left edge, more so the wider the screen. And a font size is given so the drawing
    // doesn't shave it (it took up to a pixel off every size: narrower letters, so a title the screen wraps fitted on
    // one line in its two-line box).
    const realStyle = window.getComputedStyle;
    const SIDE = { 'margin-left': 0, 'margin-inline-start': 0, 'margin-right': 1, 'margin-inline-end': 1 };
    const styleOf = (t, el, name) => {
      const m = sideMargins.get(el);
      if (m && name in SIDE) return m[SIDE[name]];
      const v = side => (m && side in SIDE ? m[SIDE[side]] : t.getPropertyValue(side));
      if (name === 'margin') return [v('margin-top'), m ? m[1] : v('margin-right'), v('margin-bottom'), m ? m[0] : v('margin-left')].join(' ');
      if (name === 'margin-inline') return m ? m.join(' ') : [v('margin-left'), v('margin-right')].join(' ');
      if (name === 'margin-block') return [v('margin-top'), v('margin-bottom')].join(' ');
      return name === 'font-size' ? t.getPropertyValue(name) + ' ' : t.getPropertyValue(name);
    };
    window.getComputedStyle = function (el, pseudo) {
      const cs = realStyle.call(window, el, pseudo);
      return new Proxy(cs, { get(t, k) {
        if (k === 'getPropertyValue') return name => styleOf(t, pseudo ? null : el, name);
        const v = Reflect.get(t, k);
        return typeof v === 'function' ? v.bind(t) : v;
      } });
    };
    const draw = async () => { try { return await h.toSvg(document.body, options); } finally { window.getComputedStyle = realStyle; } };
    try {
      const svg = (await draw()).replace(/%(?:0[0-8BbCcEeFf]|1[0-9A-Fa-f])/g, '');
      const im = new Image();
      await new Promise((ok, no) => { im.onload = ok; im.onerror = () => no(new Error("the page's drawing wouldn't load")); im.src = svg; });
      const c = Object.assign(document.createElement('canvas'), { width: innerWidth, height: innerHeight }), g = c.getContext('2d');
      g.fillStyle = options.backgroundColor; g.fillRect(0, 0, c.width, c.height); g.drawImage(im, 0, 0, c.width, c.height);
      const full = c.toDataURL('image/jpeg', 0.8);
      if (!rects.length) return { full, safe: null };
      cover(c, rects);
      return { full, safe: c.toDataURL('image/jpeg', 0.8) };
    } catch (e) { why = (e && (e.message || e.type)) || 'unknown'; return null; } finally {
      held.reverse().forEach(([el, style]) => { if (style === null) el.removeAttribute('style'); else el.setAttribute('style', style); });
      scrolled.forEach(([el, top, left]) => { el.scrollTop = top; el.scrollLeft = left; });
      stills.forEach(im => im.remove());
      aside.forEach(([el, name, value]) => el.setAttribute(name, value));
      blanked.forEach(([im, src, srcset, w, hgt]) => { if (srcset !== null) im.setAttribute('srcset', srcset); if (src !== null) im.setAttribute('src', src); else im.removeAttribute('src'); im.style.width = w; im.style.height = hgt; });
    }
  }
  // The page as drawn, with its private parts emptied (only ever shown to an admin as text, and to Claude on request)
  function drawn() {
    const copy = document.documentElement.cloneNode(true);
    copy.querySelectorAll('[data-private]').forEach(el => {  // (its words, and any attribute that could carry them: a title)
      el.replaceChildren();
      [...el.attributes].forEach(a => { if (a.name !== 'class' && a.name !== 'data-private') el.removeAttribute(a.name); });
      el.setAttribute('data-private', 'emptied');
      // (a window holding it is labelled with its title, a player's note's own: never in the copy; the review of #417)
      for (let up = el.parentElement; up; up = up.parentElement) ['aria-label', 'title'].forEach(n => up.removeAttribute(n));
    });
    copy.querySelectorAll('#fb-win, script').forEach(el => el.remove());
    return copy.outerHTML.slice(0, 3000000);
  }
  function browser() {
    const ua = navigator.userAgent, d = navigator.userAgentData;
    const brands = d && d.brands ? d.brands.filter(b => !/Not.?A.?Brand/i.test(b.brand)) : [];
    const brand = brands.find(b => b.brand !== 'Chromium') || brands[0] || null;
    const safari = /Version\/([\d.]+).*Safari/.exec(ua), firefox = /Firefox\/([\d.]+)/.exec(ua);
    const name = brand ? brand.brand + ' ' + brand.version : safari ? 'Safari ' + safari[1] : firefox ? 'Firefox ' + firefox[1] : ua.slice(0, 60);
    const os = (d && d.platform) || (/iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Mac OS X/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : '');
    return name + (os ? ' on ' + os : '');
  }
  function gather() {
    const pill = document.getElementById('live-pill'), body = document.body;
    const tab = document.querySelector('main [role=tab][aria-selected=true], main .tabbar .on, main .sub-tabs .on, main .tabs .on');
    const panel = [...document.querySelectorAll('.peek:not([hidden]) #peek-title')].find(t => !t.closest('[data-private]'));  // (a player's own note's title stays theirs)
    const zoom = window.visualViewport ? visualViewport.scale : 1, outer = outerWidth && innerWidth ? outerWidth / innerWidth : 1;
    const now = new Date();
    return {
      page: document.title.replace(/ · askdnd$/, ''), at: now.toLocaleString() + ' (' + Intl.DateTimeFormat().resolvedOptions().timeZone + ')', at_iso: now.toISOString(),
      window: innerWidth + ' × ' + innerHeight, screen: screen.width + ' × ' + screen.height + ' · ' + devicePixelRatio + '× pixels',
      zoom: 'about ' + Math.round(zoom * (outer > 0.5 && outer < 4 ? outer : 1) * 100) + '%', browser: browser(), user_agent: navigator.userAgent,
      extension: body.dataset.bridgeVersion || (body.classList.contains('no-bridge') ? 'not in this browser' : ''),
      live: pill ? [((pill.querySelector('.live-ago') || pill).textContent || '').trim().replace(/\s+/g, ' '), pill.className.replace('live-pill', '').trim()].filter(Boolean).join(' · ') : '', tab: tab ? tab.textContent.trim().replace(/\s+/g, ' ').slice(0, 60) : '',
      panel: panel ? panel.textContent.trim().slice(0, 80) : '', fight: body.dataset.fight ? 'on' : '', scroll: scrollX + ', ' + scrollY,
      errors: (window.askdndErrors || []).slice(-5),
    };
  }
  function drawCtx() {
    const dl = win.querySelector('[data-fb-ctx]');
    dl.replaceChildren();
    [['Page', ctx.page + ' · ' + location.pathname], ['When', ctx.at], ['Window', ctx.window + ' · zoom ' + ctx.zoom], ['Browser', ctx.browser],
     ['askdnd bridge', ctx.extension], ['Live pill', ctx.live], ['Page errors', String(ctx.errors.length)], ['The page itself', 'As drawn (' + Math.round(html.length / 1024) + ' KB)']]
      .filter(([, v]) => v).forEach(([k, v]) => { dl.append(Object.assign(document.createElement('dt'), { textContent: k }), Object.assign(document.createElement('dd'), { textContent: v })); });
  }
  // ---- the pictures: a chip each, the chosen one on the stage with its marks
  function drawChips() {
    chips.querySelectorAll('[data-fb-pic], [data-fb-unpic]').forEach(c => c.remove());
    let added = 0;
    pics.forEach((p, i) => {
      const name = p.kind === 'page' ? 'The page' : 'Your picture ' + (++added);
      const b = Object.assign(document.createElement('button'), { type: 'button', className: 'chip' + (i === at ? ' on' : ''), textContent: name });
      b.dataset.fbPic = String(i); b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(i === at));
      b.addEventListener('click', () => show(i));
      if (p.kind === 'page') { chips.insertBefore(b, shotChip); return; }  // (the page's own picture stays: it says where you were; Brett's round, Nov 18)
      // (a picture you added: one pill, its name and its ✕, each a button of its own)
      const pair = Object.assign(document.createElement('span'), { className: 'chip chip-pair' + (i === at ? ' on' : '') });
      pair.dataset.fbPic = String(i); b.className = 'chip-name'; delete b.dataset.fbPic;
      const x = Object.assign(document.createElement('button'), { type: 'button', className: 'chip-x', textContent: '✕' });
      x.dataset.fbUnpic = String(i); x.setAttribute('aria-label', 'Remove ' + name);
      x.addEventListener('click', () => { pics.splice(i, 1); show(pics.length ? Math.min(at > i ? at - 1 : at, pics.length - 1) : -1); if (!pics.length) stageNote.textContent = 'No picture: paste or add one if it helps.'; });
      pair.append(b, x);
      chips.insertBefore(pair, shotChip);
    });
    addChip.hidden = shotChip.hidden = pics.length + (taking ? 1 : 0) >= 4;  // (four pictures at most, the page's own counted while it's drawn)
  }
  function show(i) {
    at = i; drawChips();
    const p = pics[i];
    wrap.hidden = tools.hidden = edits.hidden = !p; stageNote.hidden = !!p;
    covered.hidden = !(p && (p.safe || p.kind === 'added'));
    if (p) covered.textContent = p.kind === 'added' ? 'A picture you add is shown as it is to an admin, the DM and Claude.' : "Your character's notes are covered in the copy an admin and Claude see; only you see them.";
    if (!p) return;
    const im = new Image();
    im.onload = () => {
      if (pics[at] !== p) return;  // (another picture was chosen meanwhile: it draws itself)
      p.img = im; canvas.width = im.naturalWidth; canvas.height = im.naturalHeight; fit(); redraw();
    };
    im.src = p.full;
  }
  // The canvas keeps its picture's shape (never letterboxed, so a mark lands where it's drawn): as wide as the window
  // allows, no taller than about half the screen
  const fit = () => {
    if (!canvas.width || !canvas.height) return;
    canvas.style.width = Math.max(120, Math.min(wrap.clientWidth || canvas.width, innerHeight * 0.46 * canvas.width / canvas.height)) + 'px';
  };
  addEventListener('resize', () => { if (win.open) fit(); });
  const MARK = '#f0a020';
  // Marks are sized as they look on your screen, whatever the picture's own size (Brett's round, Nov 18, issue 16: on a
  // large screenshot shown small, the arrow came out thin with a small head): each mark keeps `k`, the picture's pixels
  // per screen pixel as it was drawn, so it's the same in the picture that's sent
  const shownAt = () => canvas.width / (canvas.getBoundingClientRect().width || canvas.width);
  function paint(g, w, list) {
    g.strokeStyle = g.fillStyle = MARK; g.lineCap = g.lineJoin = 'round';
    for (const m of list) {
      const k = m.k || Math.max(1, w / 800), [a, b] = [m.pts[0], m.pts[m.pts.length - 1]];
      g.lineWidth = 3.5 * k;
      g.beginPath();
      if (m.tool === 'box') g.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y));
      else if (m.tool === 'draw') { m.pts.forEach((p, n) => (n ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.stroke(); }
      else if (m.tool === 'text') {
        const size = Math.round(16 * k), pad = 4 * k;
        g.font = '700 ' + size + 'px system-ui, sans-serif';
        const tw = g.measureText(m.text).width;
        g.fillStyle = 'rgba(15,17,19,.85)'; g.fillRect(a.x - pad, a.y - size, tw + 2 * pad, size + 2 * pad);
        g.fillStyle = MARK; g.fillText(m.text, a.x, a.y);
      } else {
        const t = Math.atan2(b.y - a.y, b.x - a.x), hd = 20 * k;  // (its head 20 screen pixels long)
        const end = { x: b.x - hd * 0.6 * Math.cos(t), y: b.y - hd * 0.6 * Math.sin(t) };  // (the shaft stops inside the head: a sharp point)
        g.moveTo(a.x, a.y); g.lineTo(end.x, end.y); g.stroke();
        g.beginPath(); g.moveTo(b.x, b.y);
        g.lineTo(b.x - hd * Math.cos(t - 0.45), b.y - hd * Math.sin(t - 0.45)); g.lineTo(b.x - hd * Math.cos(t + 0.45), b.y - hd * Math.sin(t + 0.45));
        g.closePath(); g.fill();
      }
    }
  }
  let tool = 'box', drag = null, typingAt = null;
  const redraw = () => {
    const p = pics[at];
    if (!p || !p.img) return;
    const g = canvas.getContext('2d');
    g.drawImage(p.img, 0, 0);
    paint(g, canvas.width, drag ? [...p.marks, drag] : p.marks);
  };
  const point = e => { const r = canvas.getBoundingClientRect(); return { x: (e.clientX - r.left) * canvas.width / r.width, y: (e.clientY - r.top) * canvas.height / r.height }; };
  canvas.addEventListener('pointerdown', e => {
    if (!pics[at]) return;
    e.preventDefault();
    if (tool === 'text') return placeText(e);
    canvas.setPointerCapture(e.pointerId); drag = { tool, pts: [point(e)], k: shownAt() };
  });
  canvas.addEventListener('pointermove', e => { if (!drag) return; const p = point(e); if (drag.tool === 'draw') drag.pts.push(p); else drag.pts[1] = p; redraw(); });
  canvas.addEventListener('pointerup', () => { if (drag && drag.pts.length > 1) pics[at].marks.push(drag); drag = null; redraw(); });
  canvas.addEventListener('pointercancel', () => { drag = null; redraw(); });
  function placeText(e) {  // Text: a box where you clicked; Enter (or leaving it) puts the words on the picture
    if (typingAt) typingAt.blur();
    const r = canvas.getBoundingClientRect(), wr = wrap.getBoundingClientRect(), p = point(e);
    const box = Object.assign(document.createElement('input'), { type: 'text', className: 'fb-text-input', maxLength: 80, placeholder: 'Type, then Enter' });
    box.setAttribute('aria-label', 'Words on the picture');
    Object.assign(box.style, { left: (e.clientX - wr.left) + 'px', top: (e.clientY - wr.top - 14) + 'px', maxWidth: (r.right - e.clientX) + 'px' });
    wrap.append(box); box.focus(); typingAt = box;
    let ended = false;
    const done = keep => {  // (once: removing the box blurs it, which would end it again)
      if (ended) return;
      ended = true;
      const t = box.value.trim(); typingAt = null; box.remove();
      if (keep && t && pics[at]) { pics[at].marks.push({ tool: 'text', pts: [p], text: t, k: shownAt() }); redraw(); }
    };
    box.addEventListener('keydown', k => { if (k.key === 'Enter') { k.preventDefault(); done(true); } else if (k.key === 'Escape') { k.preventDefault(); k.stopPropagation(); done(false); } });
    box.addEventListener('blur', () => done(true));
  }
  win.querySelectorAll('[data-fb-tool]').forEach(b => b.addEventListener('click', () => {
    tool = b.dataset.fbTool;
    win.querySelectorAll('[data-fb-tool]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  }));
  win.querySelector('[data-fb-undo]').addEventListener('click', () => { if (pics[at]) { pics[at].marks.pop(); redraw(); } });
  win.querySelector('[data-fb-clear]').addEventListener('click', () => { if (pics[at]) { pics[at].marks = []; redraw(); } });
  // What's sent: each picture with its marks drawn in, the full copy and (where there is one) the safe copy
  const flat = (src, marks) => (!marks.length ? Promise.resolve(src) : new Promise(ok => {
    const im = new Image();
    im.onload = () => {
      const c = Object.assign(document.createElement('canvas'), { width: im.naturalWidth, height: im.naturalHeight }), g = c.getContext('2d');
      g.drawImage(im, 0, 0); paint(g, c.width, marks); ok(c.toDataURL('image/jpeg', 0.85));
    };
    im.onerror = () => ok(src);
    im.src = src;
  }));
  const outgoing = () => Promise.all(pics.map(async p => ({ kind: p.kind, full: await flat(p.full, p.marks), safe: p.safe ? await flat(p.safe, p.marks) : null, marks: p.marks.length })));
  function take(file) {
    if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) return say('A picture as PNG, JPEG or WebP, please.');
    if (file.size > 8e6) return say('That picture is over 8 MB.');
    // (four at most, counting the page's own picture while it's still being drawn and any still being read: the review
    // of #417, five could be added on a slow page and Send then refused them all)
    if (pics.length + reading + (taking ? 1 : 0) >= 4) return say('Four pictures at most.');
    const r = new FileReader();
    reading += 1;
    r.onloadend = () => { reading -= 1; };
    r.onload = () => { pics.push({ kind: 'added', full: r.result, safe: null, marks: [] }); say(''); show(pics.length - 1); };
    r.readAsDataURL(file);
  }
  const pasted = e => [...((e.clipboardData && e.clipboardData.files) || [])].find(x => x.type.startsWith('image/'));
  win.addEventListener('paste', e => { const f = pasted(e); if (f) { e.preventDefault(); take(f); } });
  document.addEventListener('paste', e => {  // (hidden for a screenshot: pasting it anywhere brings the window back with it)
    if (!hidden || !hideCard || !hideCard.isConnected) return;  // (its card closed: the note waits for \ or the logo, and pastes elsewhere are theirs)
    const f = pasted(e);
    if (f) { e.preventDefault(); back(); take(f); }
  });
  const stage = win.querySelector('[data-fb-stage]');
  stage.addEventListener('dragover', e => { e.preventDefault(); stage.classList.add('over'); });
  stage.addEventListener('dragleave', () => stage.classList.remove('over'));
  stage.addEventListener('drop', e => { e.preventDefault(); stage.classList.remove('over'); take(e.dataTransfer.files[0]); });
  win.querySelector('[data-fb-file]').addEventListener('change', e => { take(e.target.files[0]); e.target.value = ''; });
  // ---- opening, hiding for a screenshot, closing
  async function open(opts) {
    if (win.open) return;
    if (hidden) {  // (the note put away for a screenshot comes back, unless this is for another check or none: then it's a new one)
      const want = opts && opts.check ? opts.check.id : null, have = checking ? checking.id : null;
      if (want === have) return back();
      hidden = false;
      if (hideCard && hideCard._close) hideCard._close();
      hideCard = null;
    }
    const mine = ++round;
    pics = []; at = -1;
    ctx = gather(); html = drawn();
    form.reset(); say(''); send.disabled = false; pickKind('');
    checkMode((opts && opts.check) || null);
    show(-1); stageNote.textContent = "Taking the page's picture…";
    drawCtx();
    lineEl.textContent = '';
    fetch('/feedback/line', { headers: { Accept: 'application/json' } }).then(r => (r.ok ? r.json() : null)).then(j => {
      if (!j) return;
      lineEl.textContent = j.line; lineEl.classList.toggle('fb-listening', !!j.listening);
    }).catch(() => { /* the line stays empty */ });
    win.showModal();
    form.text.focus();
    // (the picture once the window has shown, so it's left out; never two at once)
    await new Promise(r => { requestAnimationFrame(() => setTimeout(r, 0)); setTimeout(r, 100); });
    taking = taking || picture().finally(() => { taking = null; });
    const got = await taking;
    if (mine !== round) return;
    if (!got) { ctx.picture = 'Not taken: ' + why; stageNote.textContent = 'No picture of the page this time: paste one if it helps.'; return; }
    pics.unshift({ kind: 'page', full: got.full, safe: got.safe, marks: [] });
    show(at < 0 ? 0 : at + 1);
  }
  function hide() {  // Take a screenshot: everything kept; a card says how, and brings it back
    hidden = true; win.close();
    const mac = /Mac/.test(navigator.platform || navigator.userAgent) && !/iPhone|iPad/.test(navigator.userAgent);
    const box = document.createElement('div');
    box.append(Object.assign(document.createElement('b'), { textContent: 'Your note is waiting' }), document.createElement('br'),
      document.createTextNode(/iPhone|iPad/.test(navigator.userAgent) ? 'Take your screenshot (the side and volume-up buttons), then Back to it and add it.'
        : mac ? 'Take your screenshot: ⇧⌘3 for the whole screen, ⇧⌘4 for a part (hold ⌃ too to copy it), then ⌘V here.' : 'Take your screenshot, then paste it here (Ctrl+V).'));
    hideCard = window.askdndCard ? window.askdndCard(box, { kind: 'info', stay: true, actions: [{ label: 'Back to it', run: back }] }) : null;
  }
  function back() {
    hidden = false;
    if (hideCard && hideCard._close) hideCard._close();
    hideCard = null;
    if (!win.open) win.showModal();
  }
  shotChip.addEventListener('click', hide);
  const close = () => { win.close(); hidden = false; pics = []; };
  win.querySelectorAll('[data-fb-cancel]').forEach(b => b.addEventListener('click', close));  // (✕ and Cancel)
  win.addEventListener('cancel', e => { if (typingAt) { e.preventDefault(); return; } pics = []; });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = form.text.value.trim();
    if (checking && blocking === null) return say('Say whether it stops this check passing.');
    if (!checking && !kind) return say('Say what it is first: a problem, an idea or a question.');
    if (!text) return say(checking ? "Say what's wrong first." : "Say what it's about first.");
    send.disabled = true; say('');
    if (taking && !pics.some(p => p.kind === 'page')) { say("Finishing the page's picture…"); await taking; say(''); }
    try {
      const pictures = await outgoing();
      const common = { text, url: location.href, context: { ...ctx, marked: pictures.reduce((n, p) => n + p.marks, 0) }, html, pictures: pictures.map(({ kind: k, full, safe }) => ({ kind: k, full, safe })) };
      const still = checking && stillBox.querySelector('input:checked');
      const r = await fetch(checking ? '/manage/testing/checks/' + checking.id + '/wrong' : '/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(checking ? { ...common, blocking, stops_round: stopsBox.checked, issue: still && still.value ? +still.value : null, try: (checking.another && checking.try) || null } : { ...common, kind }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || "Couldn't send it: askdnd answered " + r.status + '.');
      const was = checking;
      close();
      if (was) {  // (from a check: the card shows what was sent, in place; on Testing, the page shows it)
        const slot = document.getElementById('check-card');
        if (slot && slot.querySelector('[data-fft-card]') && window.htmx) {
          htmx.ajax('GET', '/manage/testing/card?at=' + encodeURIComponent(location.pathname), { target: slot, swap: 'innerHTML' });
          if (window.askdndToast) window.askdndToast(j.said || 'Sent');
        } else {  // (the page shows what was sent: its card comes after the reload)
          try { sessionStorage.setItem('askdnd-said', j.said || 'Sent'); } catch (err) { /* no storage: the page says it */ }
          location.reload();
        }
        return;
      }
      if (window.askdndToast) window.askdndToast(j.said || 'Sent', { label: 'Notes you sent', run: () => { location.href = '/your-notes?tab=askdnd'; } });
    } catch (err) { send.disabled = false; say(err.message || "Couldn't send it."); }
  });
  // \ anywhere but a field; the menus' item; pressing and holding the logo
  document.addEventListener('keydown', e => {
    if (e.key !== '\\' || e.metaKey || e.ctrlKey || e.altKey || typing(document.activeElement) || document.querySelector('dialog[open]')) return;
    e.preventDefault(); open();
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-fb-open]');
    if (!b) return;
    e.preventDefault();
    open(b.dataset.fbCheck ? { check: { id: +b.dataset.fbCheck, title: b.dataset.fbCheckTitle || '', another: 'fbAnother' in b.dataset } } : null);
  });
  window.askdndSendNote = open;
  const logo = document.querySelector('.brand');
  if (logo) {
    let held = null, fired = false;
    logo.addEventListener('touchstart', () => { fired = false; held = setTimeout(() => { fired = true; open(); }, 700); }, { passive: true });
    ['touchend', 'touchmove', 'touchcancel'].forEach(k => logo.addEventListener(k, () => clearTimeout(held), { passive: true }));
    logo.addEventListener('click', e => { if (fired) { e.preventDefault(); fired = false; } });
    logo.addEventListener('contextmenu', e => { if (fired) e.preventDefault(); });
  }
})();

// ---------------------------------------------------------------- screenshots in Add to it
// (feedback 64, Nov 16; _feedback_pics.html) A form with [data-pics] takes screenshots: chosen with its button, or
// pasted anywhere in the form; the note beside the button says how many are going with it.
document.addEventListener('paste', e => {
  const form = e.target.closest && e.target.closest('form[data-pics]');
  const input = form && form.querySelector('[data-pics-input]');
  const pasted = [...((e.clipboardData && e.clipboardData.files) || [])].filter(f => /^image\/(png|jpeg|webp)$/.test(f.type));
  if (!input || !pasted.length) return;
  e.preventDefault();
  const all = new DataTransfer();
  [...input.files, ...pasted].forEach(f => all.items.add(f));
  input.files = all.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
});
document.addEventListener('change', e => {
  if (!e.target.matches || !e.target.matches('[data-pics-input]')) return;
  const said = e.target.closest('form').querySelector('[data-pics-said]'), n = e.target.files.length;
  if (said) said.textContent = n ? n + (n === 1 ? ' screenshot' : ' screenshots') + ' going with it' : 'Or paste one here (⌘V)';
});

// ---------------------------------------------------------------- the Picture window
// (app/picture_window.py; Brett, 2026-11-04, docs/mockups/pictures/ board 2) Upload takes a picture chosen, dropped on
// its box or pasted anywhere in the window, and shows it before it's sent; the form sends it as the file.
(() => {
  const win = () => document.querySelector('[data-picture-window]');
  function take(box, file) {
    if (!box || !file || !file.type.startsWith('image/')) return;
    const input = box.querySelector('[data-pw-file]'), img = box.querySelector('[data-pw-preview]'), note = box.querySelector('[data-pw-drop-note]');
    try { const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files; } catch (e) { /* (an older browser: choosing still works) */ }
    if (img) { img.src = URL.createObjectURL(file); img.hidden = false; }
    if (note) note.hidden = true;
  }
  document.addEventListener('change', e => {
    const input = e.target.closest && e.target.closest('[data-pw-file]');
    if (input && input.files[0]) take(input.closest('[data-pw-drop]'), input.files[0]);
  });
  document.addEventListener('dragover', e => { const box = e.target.closest && e.target.closest('[data-pw-drop]'); if (box) { e.preventDefault(); box.classList.add('over'); } });
  document.addEventListener('dragleave', e => { const box = e.target.closest && e.target.closest('[data-pw-drop]'); if (box) box.classList.remove('over'); });
  document.addEventListener('drop', e => {
    const box = e.target.closest && e.target.closest('[data-pw-drop]');
    if (!box) return;
    e.preventDefault(); box.classList.remove('over'); take(box, e.dataTransfer.files[0]);
  });
  document.addEventListener('paste', e => {
    const w = win();
    if (!w || !w.closest('.peek.open')) return;  // (a closed window's contents stay in the page)
    const f = [...((e.clipboardData && e.clipboardData.files) || [])].find(x => x.type.startsWith('image/'));
    if (!f) return;
    e.preventDefault();
    const up = w.querySelector('[role=tab][data-tab="pw-up"]');
    if (up && up.getAttribute('aria-selected') !== 'true') up.click();
    take(w.querySelector('[data-pw-drop]'), f);
  });
  // Frame it (app/templates/_picture_frame.html; feedback 12, Nov 5): the picture moves under a fixed square and zooms;
  // the square's middle, as fractions of the picture, and the zoom go with Save. The wide band beside it shows the same
  // middle. The square always stays covered.
  function framer(box) {
    if (!box || box.dataset.ready) return;
    const stage = box.querySelector('[data-pw-stage]'), img = box.querySelector('[data-pw-img]'), bands = box.querySelectorAll('[data-pw-band]');
    const zoomIn = box.querySelector('[data-pw-zoom]'), fx = box.querySelector('[data-pw-x]'), fy = box.querySelector('[data-pw-y]'), fz = box.querySelector('[data-pw-z]');
    let x = Number(box.dataset.x) || 0.5, y = Number(box.dataset.y) || 0.5, zoom = Number(box.dataset.zoom) || 1;
    const draw = () => {
      const W = img.naturalWidth, H = img.naturalHeight, S = stage.clientWidth;
      if (!W || !H || !S) return;
      const k = S * zoom / Math.min(W, H), w = W * k, h = H * k;
      const left = Math.min(0, Math.max(S - w, S / 2 - x * w)), top = Math.min(0, Math.max(S - h, S / 2 - y * h));
      x = (S / 2 - left) / w; y = (S / 2 - top) / h;  // (held inside the picture)
      Object.assign(img.style, { width: w + 'px', height: h + 'px', left: left + 'px', top: top + 'px' });
      bands.forEach(b => { b.style.objectPosition = (x * 100).toFixed(1) + '% ' + (y * 100).toFixed(1) + '%'; });  // (each preview, its own shape)
      fx.value = x.toFixed(4); fy.value = y.toFixed(4); fz.value = zoom.toFixed(3);
    };
    box.dataset.ready = '1';
    if (img.complete) draw(); else img.addEventListener('load', draw);
    if (window.ResizeObserver) new ResizeObserver(draw).observe(stage);  // (laid out after the picture loaded: drawn then)
    zoomIn.addEventListener('input', () => { zoom = Number(zoomIn.value) || 1; draw(); });
    stage.addEventListener('pointerdown', e => {
      e.preventDefault(); stage.setPointerCapture(e.pointerId);
      const W = img.naturalWidth, H = img.naturalHeight, k = stage.clientWidth * zoom / Math.min(W, H);
      const start = { px: e.clientX, py: e.clientY, x, y };
      const move = ev => { x = start.x - (ev.clientX - start.px) / (W * k); y = start.y - (ev.clientY - start.py) / (H * k); draw(); };
      const up = () => { stage.removeEventListener('pointermove', move); stage.removeEventListener('pointerup', up); stage.removeEventListener('pointercancel', up); };
      stage.addEventListener('pointermove', move); stage.addEventListener('pointerup', up); stage.addEventListener('pointercancel', up);
    });
    stage.addEventListener('keydown', e => {  // (arrow keys move it too)
      const d = { ArrowLeft: [-0.02, 0], ArrowRight: [0.02, 0], ArrowUp: [0, -0.02], ArrowDown: [0, 0.02] }[e.key];
      if (d) { e.preventDefault(); x += d[0]; y += d[1]; draw(); }
    });
  }
  const frameAll = () => document.querySelectorAll('[data-pw-frame]').forEach(framer);
  document.addEventListener('htmx:afterSettle', frameAll);
  document.addEventListener('panel:loaded', frameAll);
  frameAll();

  // ---------------------------------------------------------------- the DM changes the fight's order
  // Initiative from askdnd (app/initiative.py; Brett, Nov 4, docs/mockups/initiative/ board 5): on the DM's rows a row is
  // dragged by its handle (a dashed line says the number it will get before you let go), or moved by ↑ ↓, or given a
  // number by pressing it. The server works out the number, shows it at once and sends it to D&D Beyond's VTT through
  // the DM's open VTT page; the corner card has Undo. Every page at the table swaps in the new order (realtime "game").
  const toast = (...a) => window.askdndToast && window.askdndToast(...a);
  const order = {
    heads: tb => [...tb.querySelectorAll('tr[data-ft-key]')],
    n: v => (v === '' || v === undefined ? null : Number(v)),
    low(tr) {  // a fighter's lowest number, with the creatures that act right after it
      let low = order.n(tr.dataset.ftIni);
      for (let x = tr.nextElementSibling; x && x.hasAttribute('data-ft-follows'); x = x.nextElementSibling) {
        const v = order.n(x.dataset.ftIni);
        if (v !== null && (low === null || v < low)) low = v;
      }
      return low;
    },
    // The number at `slot` (as app/initiative.py plan works it out, to show before you let go)
    plan(heads, from, slot) {
      if (slot === from || slot === from + 1) return null;
      const rest = heads.filter((_, i) => i !== from), k = slot > from ? slot - 1 : slot;
      const hi = k > 0 ? order.low(rest[k - 1]) : null;
      let lo = k < rest.length ? order.n(rest[k].dataset.ftIni) : null, below = null;
      if (hi === null && lo === null) return null;
      if (hi === null) return { ini: Math.floor(lo) + 1 };
      if (lo === null) return { ini: Math.ceil(hi) - 1 };
      if (hi === lo) { below = hi - 0.5; lo = below; }
      const mid = (hi + lo) / 2;
      return { ini: [Math.floor(mid), Math.ceil(mid), Math.round(mid * 2) / 2, mid].find(n => n > lo && n < hi), below };
    },
    send(data) {
      fetch('/fight/initiative', { method: 'POST', body: new URLSearchParams(data), headers: { 'X-Requested-With': 'fetch' } })
        .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.error || "askdnd couldn't change the order"); return j; }))
        .then(j => {
          if (!j.text) return;
          window.postMessage({ askdndBridge: 'vtt-now' }, location.origin);  // (the DM's VTT, if open in this browser, asks at once)
          toast(j.text, j.back && j.back.length ? { label: 'Undo', run: () => order.send({ back: JSON.stringify(j.back) }) } : null, 'ok');
        })
        .catch(err => toast(err.message, null, 'error'));
    },
    drop: null,
    clear() { document.querySelectorAll('tr.ft-drop').forEach(x => x.remove()); document.querySelectorAll('tr.ft-lifted').forEach(x => x.classList.remove('ft-lifted')); },
  };
  let dragged = null;
  document.addEventListener('dragstart', e => {
    const tr = e.target.closest && e.target.closest('tr[data-ft-key]');
    if (!tr) return;
    dragged = tr;
    tr.classList.add('ft-lifted');
    try { e.dataTransfer.setData('text/plain', tr.dataset.ftKey); e.dataTransfer.effectAllowed = 'move'; } catch (err) { /* (some browsers) */ }
  });
  document.addEventListener('dragover', e => {
    if (!dragged) return;
    const tb = dragged.closest('tbody'), over = e.target.closest && e.target.closest('tr');
    if (!over || over.closest('tbody') !== tb) return;
    e.preventDefault();
    if (over.classList.contains('ft-drop')) return;
    const heads = order.heads(tb), from = heads.indexOf(dragged);
    let head = over;  // (a creature's row counts as its master's)
    while (head && !head.hasAttribute('data-ft-key')) head = head.previousElementSibling;
    if (!head) return;
    const r = over.getBoundingClientRect(), i = heads.indexOf(head);
    const slot = over === head && e.clientY < r.top + r.height / 2 ? i : i + 1;
    if (order.drop && order.drop.slot === slot) return;
    order.clear(); dragged.classList.add('ft-lifted');
    const p = order.plan(heads, from, slot);
    order.drop = { slot, p };
    if (!p) return;
    const line = document.createElement('tr'), td = document.createElement('td');
    line.className = 'ft-drop';
    td.colSpan = 5;
    td.textContent = dragged.dataset.ftName + ' here → ' + p.ini + (p.below !== null && p.below !== undefined ? ' · the one below → ' + p.below : '');
    line.append(td);
    let at = slot < heads.length ? heads[slot] : null;
    if (at) tb.insertBefore(line, at);
    else { let end = heads[heads.length - 1]; while (end.nextElementSibling && end.nextElementSibling.hasAttribute('data-ft-follows')) end = end.nextElementSibling; end.after(line); }
  });
  document.addEventListener('drop', e => {
    if (!dragged) return;
    e.preventDefault();
    const d = order.drop, key = dragged.dataset.ftKey;
    order.clear(); dragged = null; order.drop = null;
    if (d && d.p) order.send({ key, slot: d.slot });
  });
  document.addEventListener('dragend', () => { if (dragged) { order.clear(); dragged = null; order.drop = null; } });
  document.addEventListener('click', e => {
    const mv = e.target.closest('[data-ft-move]'), ty = e.target.closest('[data-ft-type]');
    if (mv) {
      const tr = mv.closest('tr[data-ft-key]'), heads = order.heads(tr.closest('tbody')), i = heads.indexOf(tr);
      const slot = mv.dataset.ftMove === 'up' ? i - 1 : i + 2;
      if (slot >= 0 && slot <= heads.length) order.send({ key: tr.dataset.ftKey, slot });
    } else if (ty) {  // its number, typed (as in the VTT's sidebar)
      const tr = ty.closest('tr[data-ft-key]'), input = document.createElement('input');
      Object.assign(input, { type: 'number', step: '0.5', value: tr.dataset.ftIni, className: 'ft-type' });
      input.setAttribute('aria-label', tr.dataset.ftName + "'s initiative");
      ty.replaceWith(input);
      input.focus(); input.select();
      const done = go => { if (!input.isConnected) return; input.replaceWith(ty); if (go && input.value !== '' && input.value !== tr.dataset.ftIni) order.send({ key: tr.dataset.ftKey, to: input.value }); };
      input.addEventListener('keydown', k => { if (k.key === 'Enter') { k.preventDefault(); done(true); } if (k.key === 'Escape') done(false); });
      input.addEventListener('blur', () => done(false));
    }
  });

})();

// Listen to the recap (a Labs feature, app/narration.py; Brett, Nov 6): ▶ Listen on Previously on… opens a full-screen
// "previously on": the narrator reads the recap while each paragraph's pictures pan slowly behind its words. The first
// Listen on a recap has the narration made (the button says so while it waits); a paragraph is on screen for its share
// of the narration's length. Space plays and pauses, Escape closes.
(function () {
  let open = null;
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  function close() {
    if (!open) return;
    open.audio.pause(); open.box.remove(); document.removeEventListener('keydown', open.keys); document.body.classList.remove('tale-playing');
    open.back?.focus(); open = null;
  }
  async function play(btn) {
    const base = btn.dataset.listen;
    const box = el('div', 'tale-player'), stage = el('div', 'tp-stage'), words = el('p', 'tp-words'), say = el('p', 'tp-say');
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-label', 'Previously on');
    const head = el('div', 'tp-head'), kicker = el('span', 'tp-kicker'), title = el('h2', 'tp-title');
    const bar = el('div', 'tp-bar'), fill = el('span'), controls = el('div', 'tp-controls');
    const toggle = el('button', 'btn tp-toggle', '❚❚ Pause'), shut = el('button', 'btn link tp-close', '✕ Close');
    const redo = el('button', 'btn link tp-redo', 'Re-record the voice'); redo.title = 'A new narration of the same recap (the pictures are picked fresh every time)'; redo.hidden = true;
    toggle.type = shut.type = redo.type = 'button'; bar.append(fill); head.append(kicker, title); controls.append(redo, toggle, shut);
    box.append(stage, head, words, say, bar, controls);
    document.body.append(box); document.body.classList.add('tale-playing');
    const audio = new Audio();
    open = { box, audio, back: btn, keys: e => { if (e.key === 'Escape') close(); else if (e.key === ' ' && e.target === document.body) { e.preventDefault(); toggle.click(); } } };
    document.addEventListener('keydown', open.keys);
    shut.addEventListener('click', close);
    toggle.addEventListener('click', () => { if (audio.paused) audio.play(); else audio.pause(); });
    audio.addEventListener('play', () => { toggle.textContent = '❚❚ Pause'; });
    audio.addEventListener('pause', () => { toggle.textContent = '▶ Play'; });
    shut.focus();
    say.textContent = 'Opening the tale…';
    let tale;
    try { tale = await (await fetch(base + '/tale', { headers: { Accept: 'application/json' } })).json(); } catch (e) { tale = null; }
    if (!open || open.box !== box) return;
    if (!tale || tale.error) { say.textContent = (tale && tale.error) || "The tale couldn't be opened. Try again."; return; }
    kicker.textContent = tale.label; title.textContent = tale.title || '';
    const slides = tale.slides, total = slides.reduce((n, s) => n + s.weight, 0) || 1;
    const ends = []; slides.reduce((n, s) => { ends.push((n + s.weight) / total); return n + s.weight; }, 0);
    let shown = -1;
    const show = i => {
      if (i === shown || !slides[i]) return;
      shown = i;
      const s = slides[i], layer = el('div', 'tp-layer');
      // The place behind (Brett, Nov 6: the location as the backdrop), the people the paragraph names in front
      if (s.place) {
        const back = el('img', 'tp-place'); back.src = s.place.src; back.alt = ''; back.style.objectPosition = s.place.pos; back.referrerPolicy = 'no-referrer';
        back.style.setProperty('--tp-drift', i % 2 ? 1 : -1);
        layer.append(back);
      } else layer.classList.add('bare');
      if (s.people.length) {
        const row = el('div', 'tp-people');
        s.people.forEach(p => {
          const card = el('figure', 'tp-person'), img = el('img'), cap = el('figcaption', '', p.name);
          img.src = p.src; img.alt = ''; img.style.objectPosition = p.pos; img.referrerPolicy = 'no-referrer';
          card.append(img, cap); row.append(card);
        });
        layer.append(row);
      }
      stage.append(layer);
      requestAnimationFrame(() => layer.classList.add('on'));
      [...stage.children].slice(0, -2).forEach(old => old.remove());  // (the last one fades out under the new)
      words.classList.remove('on'); words.textContent = s.intro ? tale.intro : s.text; words.scrollTop = 0;
      requestAnimationFrame(() => words.classList.add('on'));
    };
    show(0);
    let src = tale.audio;
    if (!src) {
      say.textContent = 'The narrator is reading it for the first time… (about half a minute)';
      try {
        const got = await (await fetch(base + '/narrate', { method: 'POST', headers: { Accept: 'application/json' } })).json();
        src = got.audio; if (!src) { say.textContent = got.error || "The narration couldn't be made. Try again later."; return; }
      } catch (e) { say.textContent = "The narration couldn't be made. Try again later."; return; }
      if (!open || open.box !== box) return;
    }
    say.textContent = '';
    // An admin's Re-record the voice (Brett, Nov 6): a new narration in its place, played from the start; the pictures
    // aren't made, they're picked from the World each time
    redo.hidden = !tale.can_redo;
    redo.addEventListener('click', async () => {
      audio.pause(); redo.disabled = true; say.textContent = 'Recording the voice again… (about half a minute)';
      try {
        const got = await (await fetch(base + '/narrate?again=1', { method: 'POST', headers: { Accept: 'application/json' } })).json();
        if (got.audio) { audio.src = got.audio; shown = -1; audio.play().catch(() => {}); say.textContent = ''; }
        else say.textContent = got.error || "The voice couldn't be recorded again. Try later.";
      } catch (e) { say.textContent = "The voice couldn't be recorded again. Try later."; }
      redo.disabled = false;
    });
    audio.src = src;
    audio.addEventListener('timeupdate', () => {
      if (!audio.duration) return;
      const at = audio.currentTime / audio.duration;
      fill.style.width = (at * 100).toFixed(1) + '%';
      const i = Math.max(0, ends.findIndex(e => at < e));
      show(i);
      // A paragraph longer than its box scrolls with the voice (a phone, Brett, Nov 6), so it's read through, not cut off
      const from = i ? ends[i - 1] : 0, part = Math.min(1, Math.max(0, (at - from) / ((ends[i] - from) || 1)));
      if (words.scrollHeight > words.clientHeight) words.scrollTop = part * (words.scrollHeight - words.clientHeight);
    });
    audio.addEventListener('ended', () => { fill.style.width = '100%'; toggle.textContent = '▶ Play again'; shown = -1; });
    audio.play().catch(() => { toggle.textContent = '▶ Play'; });
  }
  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-listen]');
    if (btn) { e.preventDefault(); play(btn); }
  });
})();

// Your turn's bar on a phone (askdnd's table, slice 4): one line at the bottom until pulled up; it stays as you left it
// while the page shows a new copy
(function () {
  let open = false;
  const apply = () => { const bar = document.getElementById('turn-bar'); if (!bar) return; bar.classList.toggle('open', open); const b = bar.querySelector('[data-tbar-toggle]'); if (b) b.setAttribute('aria-expanded', String(open)); };
  document.addEventListener('click', e => { if (e.target.closest('[data-tbar-toggle]')) { open = !open; apply(); } });
  document.addEventListener('askdnd:swapped', apply);
})();

// askdnd's table map (app/table_page.py, table.html; docs/plans/2026-11-06-table-build-plan.md): the picture, its grid
// and the tokens in one world, moved and zoomed together (a drag on the map pans, the wheel or a pinch zooms, + − Fit,
// ⌖ to whose turn it is). A token you may move is dragged to a square (POST …/move; the page then shows its new copy,
// as every page at the table does), with a ruler saying its feet as app/measure.py counts them (the campaign's diagonal
// rule, the DM's Difficult Terrain), what's left of your movement on your turn, and whose reach it leaves. Tools: the
// ruler, a spell's area (app/areas.py: the same shapes and who's in it), the DM's scene pin, fog and terrain (drag over
// squares, or click in a room). Keys (the ? window): + − 0 zoom, T and F find, arrows move the token you picked, R
// ruler, A area, N next turn, Esc stops. The view (where you look, how close) is kept per place while the page shows
// new copies, and per tab; when the turn passes to a token off the screen, the map glides to it.
(function () {
  const VIEW = 'askdnd:tmap:', STEP = 5, SVG = 'http://www.w3.org/2000/svg';
  let view = null, drag = null, tool = null, area = null, picked = null, lastNow;
  const map = () => document.getElementById('tmap');
  const world = m => m.querySelector('.tmap-world');
  const esc = v => { const d = document.createElement('div'); d.textContent = v == null ? '' : String(v); return d.innerHTML; };
  const store = (m, v) => { try { sessionStorage.setItem(VIEW + m.dataset.place, JSON.stringify(v)); } catch (e) { /* private window */ } };
  const kept = m => { try { return JSON.parse(sessionStorage.getItem(VIEW + m.dataset.place) || 'null'); } catch (e) { return null; } };
  const json = (s, d) => { try { return JSON.parse(s || ''); } catch (e) { return d; } };
  function fit(m) {
    const w = +m.dataset.w, h = +m.dataset.h, r = m.getBoundingClientRect();
    const z = Math.min(r.width / w, r.height / h) || 1;
    return { x: (r.width - w * z) / 2, y: (r.height - h * z) / 2, z };
  }
  function apply(m, glide) {  // (--inv keeps a pin's and a name's words the same size at any zoom)
    const w = world(m);
    if (!w || !view) return;
    w.classList.toggle('glide', !!glide);
    w.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
    w.style.setProperty('--inv', String(1 / view.z));
  }
  function zoomAt(m, factor, cx, cy, glide) {
    const r = m.getBoundingClientRect(), px = cx - r.left, py = cy - r.top;
    const z = Math.min(4, Math.max(0.05, view.z * factor)), k = z / view.z;
    view = { ...view, x: px - (px - view.x) * k, y: py - (py - view.y) * k, z };
    apply(m, glide); store(m, view);
  }
  function centerOn(m, el, glide = true) {  // a token in the middle of the screen, as close as it is now (closer if far out)
    const r = m.getBoundingClientRect(), z = Math.max(view.z, Math.min(1, fit(m).z * 2));
    const cx = parseFloat(el.style.left) + el.offsetWidth / 2, cy = parseFloat(el.style.top) + el.offsetHeight / 2;
    view = { ...view, z, x: r.width / 2 - cx * z, y: r.height / 2 - cy * z };
    apply(m, glide); store(m, view);
  }
  function onScreen(m, el) {
    const r = m.getBoundingClientRect(), t = el.getBoundingClientRect();
    return t.right > r.left + 20 && t.left < r.right - 20 && t.bottom > r.top + 20 && t.top < r.bottom - 20;
  }
  const toWorld = (m, cx, cy) => { const r = m.getBoundingClientRect(); return { x: (cx - r.left - view.x) / view.z, y: (cy - r.top - view.y) / view.z }; };
  const squares = (m, p) => ({ x: (p.x - +m.dataset.gx) / +m.dataset.size, y: (p.y - +m.dataset.gy) / +m.dataset.size });
  const at = (m, e) => squares(m, toWorld(m, e.clientX, e.clientY));
  const cell = p => ({ x: Math.floor(p.x), y: Math.floor(p.y) });
  function post(url, fields) {
    return fetch(url, { method: 'POST', body: new URLSearchParams(fields), headers: { 'X-Requested-With': 'fetch', 'HX-Request': 'true' } })
      .then(r => { const t = r.headers.get('HX-Trigger'); if (t) { try { Object.entries(JSON.parse(t)).forEach(([k, v]) => document.body.dispatchEvent(new CustomEvent(k, { detail: v }))); } catch (e) { /* plain */ } }
        if (!r.ok) r.json().then(j => window.askdndToast && window.askdndToast(j.detail || "That didn't work.", null, 'warn')).catch(() => {}); return r; });
  }

  // ------------------------------------------------ measuring: app/measure.py's numbers, the same here
  function path(a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, n = Math.round(Math.max(Math.abs(dx), Math.abs(dy))), out = [];
    let px = a.x, py = a.y;
    for (let i = 1; i <= n; i++) {
      const x = Math.round(a.x + dx * i / n), y = Math.round(a.y + dy * i / n);
      out.push({ x, y, diag: x !== px && y !== py }); px = x; py = y;
    }
    return out;
  }
  function cost(steps, rule, terrain, size) {
    let feet = 0, rough = 0, diagonals = 0;
    const span = Math.max(1, Math.round(size || 1));
    for (const s of steps) {
      let base = STEP;
      if (s.diag) { diagonals++; if (rule === 'alternate' && diagonals % 2 === 0) base = 2 * STEP; }
      let hard = false;
      for (let i = 0; i < span && !hard; i++) for (let j = 0; j < span && !hard; j++) hard = terrain.has((s.x + i) + ',' + (s.y + j));
      if (hard) { rough++; base += STEP; }
      feet += base;
    }
    return { feet, rough, squares: steps.length };
  }
  function apart(a, b) {
    const gap = (p, ps, q, qs) => Math.max(0, q - (p + ps), p - (q + qs));
    const sa = Math.max(a.size || 1, 0.5), sb = Math.max(b.size || 1, 0.5);
    return Math.round(Math.max(gap(a.x, sa, b.x, sb), gap(a.y, sa, b.y, sb))) * STEP + STEP;
  }
  const tokensOn = m => [...m.querySelectorAll('.tok-m')].map(el => ({ el, id: +el.dataset.token, name: el.dataset.name, x: +el.dataset.x, y: +el.dataset.y,
    size: +el.dataset.sq || 1, reach: +el.dataset.reach || STEP, foe: el.hasAttribute('data-foe'), down: el.hasAttribute('data-down'), character: +el.dataset.character || 0 }));
  function leaves(m, mover, endAt) {
    return tokensOn(m).filter(o => o.id !== mover.id && o.foe !== mover.foe && !o.down)
      .filter(o => apart(mover, o) <= o.reach && o.reach < apart({ ...mover, ...endAt }, o)).map(o => o.name);
  }

  // ------------------------------------------------ areas: app/areas.py's shapes, the same here
  function covers(a, px, py) {
    const r = a.feet / STEP, dx = px - a.x, dy = py - a.y, ang = (a.angle || 0) * Math.PI / 180;
    const along = dx * Math.cos(ang) + dy * Math.sin(ang), across = -dx * Math.sin(ang) + dy * Math.cos(ang), e = 1e-9;
    if (a.shape === 'sphere' || a.shape === 'cylinder') return Math.hypot(dx, dy) <= r + e;
    if (a.shape === 'cone') return along > 0 && along <= r + e && Math.abs(across) <= along / 2 + e;
    if (a.shape === 'line') return along >= 0 && along <= r + e && Math.abs(across) <= (a.wide || STEP) / STEP / 2 + e;
    if (a.shape === 'cube') return along >= 0 && along <= r + e && Math.abs(across) <= r / 2 + e;
    if (a.shape === 'emanation') { const s = a.size || 1; return px >= a.x - r && px <= a.x + s + r && py >= a.y - r && py <= a.y + s + r; }
    return false;
  }
  function inside(a, toks) {
    return toks.filter(t => {
      if (a.shape === 'emanation' && a.token === t.id) return false;
      const span = Math.max(1, Math.round(t.size));
      for (let i = 0; i < span; i++) for (let j = 0; j < span; j++) if (covers(a, t.x + i + 0.5, t.y + j + 0.5)) return true;
      return false;
    });
  }
  function shapeOf(a) {  // (app/areas.py outline: in squares)
    const r = a.feet / STEP, ang = (a.angle || 0) * Math.PI / 180;
    const pt = (al, ac) => [a.x + al * Math.cos(ang) - ac * Math.sin(ang), a.y + al * Math.sin(ang) + ac * Math.cos(ang)];
    if (a.shape === 'sphere' || a.shape === 'cylinder') return `<circle cx="${a.x}" cy="${a.y}" r="${r}"/>`;
    if (a.shape === 'emanation') { const s = a.size || 1; return `<rect x="${a.x - r}" y="${a.y - r}" width="${s + 2 * r}" height="${s + 2 * r}" rx="${r}"/>`; }
    const half = a.shape === 'line' ? (a.wide || STEP) / STEP / 2 : r / 2;
    const pts = a.shape === 'cone' ? [pt(0, 0), pt(r, -half), pt(r, half)] : [pt(0, -half), pt(r, -half), pt(r, half), pt(0, half)];
    return `<polygon points="${pts.map(p => p.map(v => v.toFixed(3)).join(',')).join(' ')}"/>`;
  }

  // ------------------------------------------------ the draft layer: the ruler, a rectangle being dragged, an area being placed
  function draft(m) {
    let s = m.querySelector('.tmap-draft');
    if (!s) {
      const cols = +m.dataset.cols, rows = +m.dataset.rows, size = +m.dataset.size;
      s = document.createElementNS(SVG, 'svg');
      s.setAttribute('class', 'tmap-layer tmap-draft');
      s.setAttribute('viewBox', `0 0 ${cols} ${rows}`);
      s.setAttribute('preserveAspectRatio', 'none');
      s.setAttribute('aria-hidden', 'true');
      Object.assign(s.style, { left: m.dataset.gx + 'px', top: m.dataset.gy + 'px', width: cols * size + 'px', height: rows * size + 'px' });
      world(m).appendChild(s);
    }
    return s;
  }
  function tip(m, p, html) {  // words beside the draft, as big at any zoom
    let t = m.querySelector('.tmap-tip');
    if (!t) { t = document.createElement('div'); t.className = 'tmap-tip'; t.setAttribute('role', 'status'); world(m).appendChild(t); }
    t.style.left = (+m.dataset.gx + p.x * +m.dataset.size) + 'px';
    t.style.top = (+m.dataset.gy + p.y * +m.dataset.size) + 'px';
    t.innerHTML = html;
  }
  function clearDraft(m) { m.querySelector('.tmap-draft')?.remove(); m.querySelector('.tmap-tip')?.remove(); }
  function measureLine(m, from, to, size, mover) {
    const rule = m.dataset.rule, terrain = new Set(json(m.dataset.terrain, []));
    const c = cost(path(from, to), rule, terrain, size), h = (size || 1) / 2;
    draft(m).innerHTML = `<line x1="${from.x + h}" y1="${from.y + h}" x2="${to.x + h}" y2="${to.y + h}"/>` +
      `<rect class="to" x="${to.x}" y="${to.y}" width="${size || 1}" height="${size || 1}"/>`;
    let words = `<b>${c.feet} ft</b>`;
    if (c.rough) words += ` <small>· ${c.rough} Difficult</small>`;
    const turn = json(m.dataset.turn, null);
    if (mover && turn && mover.character && mover.character === turn.character) {
      const left = turn.left - c.feet;
      words += left >= 0 ? ` <small>· ${left} ft left</small>` : ` <small class="over">· ${-left} ft over your Speed</small>`;
    }
    if (mover) { const l = leaves(m, mover, to); if (l.length) words += `<br><small class="warn">Leaves the reach of ${esc(l.join(', '))}</small>`; }
    tip(m, { x: to.x + (size || 1), y: to.y }, words);
  }
  function drawRect(m, a, b) {
    const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(a.x - b.x) + 1, h = Math.abs(a.y - b.y) + 1;
    draft(m).innerHTML = `<rect class="${tool.startsWith('fog-hide') || tool === 'terrain-clear' ? 'off' : 'on'}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
    tip(m, { x: x + w, y }, `${w * STEP} × ${h * STEP} ft`);
  }
  function drawArea(m, a) {
    draft(m).innerHTML = shapeOf(a);
    const names = inside(a, tokensOn(m)).map(t => t.name);
    tip(m, { x: a.x, y: a.y }, `<b>${esc(a.label || (a.feet + '-ft ' + a.shape[0].toUpperCase() + a.shape.slice(1)))}</b>` +
      (names.length ? `<br><small>In it: ${esc(names.join(', '))}</small>` : '<br><small>No one in it</small>'));
  }

  // ------------------------------------------------ tools
  const HELP = {
    pin: 'Click where the scene is.', ruler: 'Drag to measure.', 'fog-show': 'Drag over the squares to show them.',
    'fog-hide': 'Drag over the squares to hide them.', 'fog-room': 'Click in a room to show it.', 'fog-hide-room': 'Click in a room to hide it.',
    'terrain-add': 'Drag over Difficult Terrain.', 'terrain-clear': 'Drag over the squares to clear them.',
    area: { sphere: 'Click the corner of a square where it centers.', cylinder: 'Click the corner of a square where it centers.',
            cone: 'Press where it starts and drag the way it goes.', line: 'Press where it starts and drag the way it goes.',
            cube: 'Press the middle of its near side and drag the way it goes.', emanation: 'Click the creature it spreads from.' }
  };
  function showTool(m) {
    document.querySelectorAll('[data-tool]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tool === tool)));
    if (!m) return;
    m.classList.toggle('tooling', !!tool);
    const help = m.querySelector('[data-tool-help]');
    if (help) { help.hidden = !tool; help.textContent = tool ? (tool === 'area' ? HELP.area[area.shape] : HELP[tool]) + ' Esc to stop.' : ''; }
  }
  function useTool(name) { tool = name; const m = map(); if (m) clearDraft(m); showTool(m); }
  const ROOMS = { 'fog-room': 'room', 'fog-hide-room': 'hide_room' };
  const RECTS = { 'fog-show': ['fog', 'show'], 'fog-hide': ['fog', 'hide'], 'terrain-add': ['terrain', 'add'], 'terrain-clear': ['terrain', 'clear'] };
  const placeArea = (m, a) => post(m.dataset.base + '/table/places/' + m.dataset.place + '/areas',
    { shape: a.shape, feet: a.feet, wide: a.wide || STEP, x: a.x.toFixed(2), y: a.y.toFixed(2), angle: (a.angle || 0).toFixed(1), label: a.label || '', token: a.token || 0 });
  // The area window: its shape and size, then the map (Cast on the table page starts it already sized: "areaTool")
  function startArea(spec) {
    area = { shape: spec.shape, feet: +spec.feet || 20, wide: +spec.wide || STEP, label: spec.label || '' };
    useTool('area');
  }
  document.addEventListener('submit', e => {
    const f = e.target.closest('[data-area-form]');
    if (!f) return;
    e.preventDefault();
    const d = new FormData(f);
    f.closest('dialog')?.close();
    startArea({ shape: d.get('shape'), feet: d.get('feet'), wide: d.get('wide'), label: d.get('label') });
  });
  document.addEventListener('change', e => {
    const f = e.target.closest('[data-area-form]');
    if (f) f.querySelector('[data-area-wide]').hidden = f.querySelector('input[name=shape]:checked')?.value !== 'line';
  });
  document.body.addEventListener('areaTool', e => {  // a spell just cast on the table page: its area, sized from its words
    const d = e.detail || {};
    if (map() && d.shape) startArea(d);
  });

  // ------------------------------------------------ pointers: a token drags, a tool works, anything else pans; two pinch
  const pts = new Map();
  document.addEventListener('pointerdown', e => {
    const m = e.target.closest && e.target.closest('#tmap');
    if (!m || e.button > 0 || e.target.closest('.tmap-zoom, .tmap-tools, .tmap-pin, .tmap-area-x')) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) { const [a, b] = [...pts.values()]; drag = { kind: 'pinch', d: Math.hypot(a.x - b.x, a.y - b.y), z: view.z, moved: true }; m.setPointerCapture(e.pointerId); return; }
    const p = at(m, e), tok = e.target.closest('.tok-m');
    if (tool === 'ruler') drag = { kind: 'ruler', a: cell(p), moved: true };
    else if (RECTS[tool]) drag = { kind: 'rect', a: cell(p), b: cell(p), moved: true };
    else if (tool === 'area' && ['cone', 'line', 'cube'].includes(area.shape)) {
      const o = { x: Math.round(p.x * 2) / 2, y: Math.round(p.y * 2) / 2 };
      drag = { kind: 'area', a: { ...area, ...o, angle: 0 }, moved: true };
      drawArea(m, drag.a);
    } else if (tool) drag = { kind: 'click', moved: false, sx: e.clientX, sy: e.clientY };
    else if (tok && tok.hasAttribute('data-moves')) drag = { kind: 'tok', el: tok, sx: e.clientX, sy: e.clientY, moved: false, left: parseFloat(tok.style.left), top: parseFloat(tok.style.top) };
    else drag = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y, moved: false };
    m.setPointerCapture(e.pointerId);
  });
  document.addEventListener('pointermove', e => {
    const m = map();
    if (!m || !view) return;
    if (tool === 'area' && !drag && ['sphere', 'cylinder'].includes(area.shape) && e.target.closest && e.target.closest('#tmap')) {
      const p = at(m, e);
      drawArea(m, { ...area, x: Math.round(p.x), y: Math.round(p.y) });  // (a corner of a square)
      return;
    }
    if (!drag || !pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (drag.kind === 'pinch' && pts.size === 2) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
      zoomAt(m, (drag.z * d / drag.d) / view.z, (a.x + b.x) / 2, (a.y + b.y) / 2);
      return;
    }
    if (drag.kind === 'ruler') { const b = cell(at(m, e)); measureLine(m, drag.a, b, 1, null); return; }
    if (drag.kind === 'rect') { drag.b = cell(at(m, e)); drawRect(m, drag.a, drag.b); return; }
    if (drag.kind === 'area') {
      const p = at(m, e), dx = p.x - drag.a.x, dy = p.y - drag.a.y;
      if (Math.hypot(dx, dy) > 0.3) { let ang = Math.atan2(dy, dx) * 180 / Math.PI; if (e.shiftKey) ang = Math.round(ang / 45) * 45; drag.a.angle = ang; }
      drawArea(m, drag.a);
      return;
    }
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    drag.moved = true;
    m.classList.add('dragging');
    if (drag.kind === 'pan') { view = { ...view, x: drag.vx + dx, y: drag.vy + dy }; apply(m); }
    else if (drag.kind === 'tok') {
      if (!drag.el.isConnected) {  // (a fresh copy of the map replaced the token mid-drag: hold the new one, the same token)
        const now = m.querySelector('.tok-m[data-token="' + drag.el.dataset.token + '"]');
        if (now) drag.el = now;
      }
      const el = drag.el, sq = +el.dataset.sq || 1;
      el.style.left = (drag.left + dx / view.z) + 'px'; el.style.top = (drag.top + dy / view.z) + 'px'; el.classList.add('lifted');
      const to = snap(m, el), me = tokensOn(m).find(t => t.el === el);
      if (me) measureLine(m, { x: me.x, y: me.y }, to, sq, me);  // (the token gone from the map altogether: no line)
    }
  });
  function snap(m, el) {
    const size = +m.dataset.size, step = +el.dataset.sq < 1 ? 0.5 : 1;
    const sq = { x: (parseFloat(el.style.left) - +m.dataset.gx) / size, y: (parseFloat(el.style.top) - +m.dataset.gy) / size };
    return { x: Math.max(0, Math.round(sq.x / step) * step), y: Math.max(0, Math.round(sq.y / step) * step) };
  }
  function moveTo(m, el, to) {
    const size = +m.dataset.size;
    el.style.left = (+m.dataset.gx + to.x * size) + 'px'; el.style.top = (+m.dataset.gy + to.y * size) + 'px';
    el.dataset.x = to.x; el.dataset.y = to.y;
    return post(m.dataset.base + '/table/tokens/' + el.dataset.token + '/move', to);
  }
  function end(e) {
    const m = map();
    pts.delete(e.pointerId);
    if (!m || !drag || pts.size) return;
    const was = drag;
    drag = null;
    m.classList.remove('dragging');
    if (was.kind === 'pan' && was.moved) store(m, view);
    if (was.kind === 'pinch') store(m, view);
    if (was.kind === 'tok' && was.moved) {
      const el = was.el, to = snap(m, el);
      el.classList.remove('lifted');
      clearDraft(m);
      moveTo(m, el, to);
    } else if (was.kind === 'tok') pick(was.el);
    if (was.kind === 'rect') {
      const [what, doing] = RECTS[tool];
      clearDraft(m);
      post(m.dataset.base + '/table/places/' + m.dataset.place + '/' + what, { do: doing, rect: [was.a.x, was.a.y, was.b.x, was.b.y].join(',') });
    }
    if (was.kind === 'area') { clearDraft(m); placeArea(m, was.a); useTool(null); }
    if (was.kind === 'click') {  // a tool's click: a pin, a room, an area that needs only a point or a creature
      const p = at(m, e);
      if (tool === 'pin') { useTool(null); post(m.dataset.base + '/table/scenes', { place: m.dataset.place, x: Math.max(0, p.x).toFixed(2), y: Math.max(0, p.y).toFixed(2) }); }
      else if (ROOMS[tool]) { const c = cell(p); post(m.dataset.base + '/table/places/' + m.dataset.place + '/fog', { do: ROOMS[tool], x: c.x, y: c.y }); }
      else if (tool === 'area' && area.shape === 'emanation') {
        const tok = e.target.closest && e.target.closest('.tok-m');
        if (!tok) { window.askdndToast && window.askdndToast('Click the creature it spreads from.', null, 'warn'); }
        else { clearDraft(m); placeArea(m, { ...area, x: +tok.dataset.x, y: +tok.dataset.y, token: +tok.dataset.token }); useTool(null); }
      } else if (tool === 'area') { clearDraft(m); placeArea(m, { ...area, x: Math.round(p.x), y: Math.round(p.y) }); useTool(null); }
    }
    if (was.moved || was.kind === 'click') { const stop = ev => { ev.stopPropagation(); ev.preventDefault(); }; document.addEventListener('click', stop, { capture: true, once: true }); setTimeout(() => document.removeEventListener('click', stop, true), 50); }
  }
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
  document.addEventListener('wheel', e => {
    const m = e.target.closest && e.target.closest('#tmap');
    if (!m || !view) return;
    e.preventDefault();
    zoomAt(m, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY);  // (a trackpad's pinch comes as ctrl+wheel)
  }, { passive: false });
  document.addEventListener('dblclick', e => {
    const m = e.target.closest && e.target.closest('#tmap');
    if (m && view && !tool && !e.target.closest('.tok-m, .tmap-zoom, .tmap-tools, .tmap-pin, .tmap-area')) zoomAt(m, 1.6, e.clientX, e.clientY, true);
  });
  function pick(el) {  // the token the arrow keys move
    picked = el && el.hasAttribute('data-moves') ? el.dataset.token : null;
    document.querySelectorAll('.tok-m.picked').forEach(t => t.classList.toggle('picked', t.dataset.token === picked));
    if (el && picked) el.classList.add('picked');
  }
  document.addEventListener('click', e => {
    const z = e.target.closest('[data-zoom]');
    const m = map();
    if (z && m) {
      if (z.dataset.zoom === 'fit') { view = { ...fit(m), place: m.dataset.place }; apply(m, true); store(m, view); }
      else if (z.dataset.zoom === 'turn') { const now = m.querySelector('.tok-m.now'); if (now) centerOn(m, now); else window.askdndToast && window.askdndToast("No one's turn on this map.", null, 'info'); }
      else { const r = m.getBoundingClientRect(); zoomAt(m, +z.dataset.zoom, r.left + r.width / 2, r.top + r.height / 2, true); }
      return;
    }
    const b = e.target.closest('[data-tool]');
    if (b && m) { b.closest('details')?.removeAttribute('open'); useTool(tool === b.dataset.tool ? null : b.dataset.tool); }
  }, true);

  // ------------------------------------------------ keys (the ? window lists them)
  const typing = t => t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  document.addEventListener('keydown', e => {
    const m = map();
    if (e.key === 'Escape') {
      document.querySelectorAll('details.tbl-more[open]').forEach(d => d.removeAttribute('open'));
      if (m && tool) { useTool(null); e.preventDefault(); }
      return;
    }
    if (!m || !view || e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || document.querySelector('dialog[open], .roll-win')) return;
    const r = m.getBoundingClientRect(), mid = [r.left + r.width / 2, r.top + r.height / 2];
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    let done = true;
    if (k === '+' || k === '=') zoomAt(m, 1.25, ...mid, true);
    else if (k === '-' || k === '_') zoomAt(m, 0.8, ...mid, true);
    else if (k === '0') { view = { ...fit(m), place: m.dataset.place }; apply(m, true); store(m, view); }
    else if (k === 't') { const now = m.querySelector('.tok-m.now'); if (now) centerOn(m, now); }
    else if (k === 'f') { const mine = m.querySelector('.tok-m.picked') || m.querySelector('.tok-m.mine'); if (mine) centerOn(m, mine); }
    else if (k === 'r') useTool(tool === 'ruler' ? null : 'ruler');
    else if (k === 'a') document.getElementById('tbl-area')?.showModal();
    else if (k === '?') document.getElementById('tbl-keys')?.showModal();
    else if (k === 'n') { const b = [...document.querySelectorAll('[data-key="n"]')].find(x => x.offsetParent); if (b) b.click(); else done = false; }
    else if (arrows[k] && e.shiftKey) { view = { ...view, x: view.x - arrows[k][0] * 80, y: view.y - arrows[k][1] * 80 }; apply(m, true); store(m, view); }
    else if (arrows[k]) {
      const el = picked && m.querySelector(`.tok-m[data-token="${picked}"]`);
      if (!el) done = false;
      else {
        const step = +el.dataset.sq < 1 ? 0.5 : 1, me = tokensOn(m).find(t => t.el === el);
        const to = { x: Math.max(0, me.x + arrows[k][0] * step), y: Math.max(0, me.y + arrows[k][1] * step) };
        moveTo(m, el, to);
        if (!onScreen(m, el)) centerOn(m, el);
      }
    } else done = false;
    if (done) e.preventDefault();
  });

  // ------------------------------------------------ each copy of the page
  function setup() {
    const m = map();
    if (!m) { view = null; return; }
    if (!view || view.place !== m.dataset.place) { view = { ...(kept(m) || fit(m)), place: m.dataset.place }; lastNow = undefined; }
    apply(m);
    if (picked) pick(m.querySelector(`.tok-m[data-token="${picked}"]`));
    showTool(m);
    // When the turn passes to a token off the screen, glide to it (not on the page's first drawing)
    const now = m.querySelector('.tok-m.now'), id = now ? now.dataset.token : null;
    if (lastNow !== undefined && id && id !== lastNow && !onScreen(m, now)) centerOn(m, now);
    lastNow = id;
  }
  // The DM's place picker, and the page's windows (<dialog>): opened by data-open-dialog, closed by data-close-dialog or
  // when the form in them is done
  document.addEventListener('change', e => {
    const s = e.target.closest('[data-tbl-place]');
    if (s && s.value) location.href = location.pathname + '?place=' + s.value;
  });
  document.addEventListener('click', e => {
    // A click outside the table's own menus (Map ▾, ⋯, Fog ▾, Scenes ▾) closes them
    document.querySelectorAll('details.tbl-more[open]').forEach(d => { if (!d.contains(e.target)) d.removeAttribute('open'); });
    const o = e.target.closest('[data-open-dialog]');
    if (o) { const d = document.getElementById(o.dataset.openDialog); if (d) { o.closest('details')?.removeAttribute('open'); d.showModal(); d.querySelector('[autofocus], input:not([type=hidden])')?.focus(); } }
    const c = e.target.closest('[data-close-dialog]');
    if (c) c.closest('dialog')?.close();
  });
  document.body.addEventListener('htmx:afterRequest', e => {
    const d = e.target.closest && e.target.closest('dialog.win-dialog');
    if (d && e.detail.successful && d.id !== 'tbl-creatures') d.close();
  });
  addEventListener('resize', () => { const m = map(); if (m && view && !kept(m)) { view = { ...fit(m), place: m.dataset.place }; apply(m); } });
  document.addEventListener('askdnd:swapped', setup);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup); else setup();
})();

// ---------------------------------------------------------------- a picture, large
// Tapping a picture shows it large over the page (feedback 44, Nov 7: Mark wanted to see a familiar's picture); a tap
// or Esc closes it. A picture that is itself a button or link (your creature's, which opens the Picture window; a
// party card) keeps doing that.
(() => {
  const PICS = '.ws-pic, .ep-pic img, .ep-mark, .peek-pic, img.portrait, .ib-pic, .fm-pic, .fb-pic, .fft-pic';  // (.fb-pic: a feedback note's screenshots, Nov 16)
  const big = pic => pic.matches(PICS) && !pic.closest('a, button, [data-panel-url], [data-modal-url], [data-use-url], label');
  document.addEventListener('click', e => {
    const pic = e.target.closest && e.target.closest('img');
    if (!pic || !big(pic) || !(pic.currentSrc || pic.src)) return;  // (a lazy picture not loaded yet still opens)
    e.preventDefault();
    const d = document.createElement('dialog');
    d.className = 'pic-big';
    d.setAttribute('aria-label', pic.alt || 'Picture');
    const img = document.createElement('img');
    img.src = pic.dataset.full || pic.currentSrc || pic.src; img.alt = pic.alt || ''; img.referrerPolicy = 'no-referrer';
    // A ✕ that says how to close it (Brett, Nov 16: a tap anywhere or Esc closes it, but nothing said so)
    const x = document.createElement('button');
    x.type = 'button'; x.className = 'pic-big-x'; x.setAttribute('aria-label', 'Close'); x.textContent = '✕';
    d.append(img, x);
    d.addEventListener('click', () => d.close());
    d.addEventListener('close', () => d.remove());
    document.body.append(d);
    d.showModal();
  });
  document.addEventListener('mouseover', e => {
    const pic = e.target.closest && e.target.closest('img');
    if (pic && !pic.dataset.bigChecked) { pic.dataset.bigChecked = '1'; if (big(pic)) pic.classList.add('pic-can-big'); }
  });
})();

// ---------------------------------------------------------------- Describe it: pictures to go by
// A name picked with @ in Describe it that has a picture joins "Pictures to go by", ticked (feedback 36, Nov 7); the
// server says whether it has one this person may send (/pictures/ref). A relative's are listed already, unticked.
document.addEventListener('askdnd:mention', e => {
  const form = e.target.closest && e.target.closest('.pw-draw-form');
  const box = form && form.querySelector('[data-pw-refs]');
  if (!box) return;
  fetch('/pictures/ref?for=' + encodeURIComponent(box.dataset.for) + '&name=' + encodeURIComponent(e.detail.name))
    .then(r => (r.status === 200 ? r.text() : ''))
    .then(html => {
      if (!html) return;
      const t = document.createElement('template'); t.innerHTML = html.trim();
      const row = t.content.firstElementChild, had = row && box.querySelector('[data-pw-ref="' + row.dataset.pwRef + '"]');
      if (had) { had.querySelector('input').checked = true; return; }
      if (row) { box.append(row); box.hidden = false; }
    })
    .catch(() => {});
});

// ---------------------------------------------------------------- your notes
// Once a page for anyone signed in (app/your_notes.py `news`): the badge on your picture, on More and beside Your
// notes (what you haven't seen; opening that tab clears it), and a corner card for each note that moved since your last
// card (once each), with See it
(() => {
  if (!document.getElementById('account-menu') && !document.getElementById('more-menu')) return;
  const badge = n => document.querySelectorAll('[data-notes-count]').forEach(b => { b.textContent = n || ''; b.hidden = !n; });
  // On Your notes, opening the other tab clears its news (the page cleared the one it opened on)
  document.addEventListener('tab:shown', e => {
    if (!e.target.closest || !e.target.closest('.notes-page')) return;
    const tab = e.target.id.replace(/^t-/, '');
    fetch('/your-notes/seen?tab=' + encodeURIComponent(tab), { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null)).then(j => {
        if (!j) return;
        badge(j.count);
        const n = document.querySelector('[data-notes-tab="' + tab + '"]');
        if (n && n.classList.contains('notes-tab-new')) { n.classList.remove('notes-tab-new'); const rows = e.target.querySelectorAll('[data-ls-row]').length; n.textContent = rows; n.hidden = !rows; }  // (a 0 isn't shown: Count)
      }).catch(() => {});
  });
  // Your notes' Reader (round 2, Layout B): a row opens its note beside the list (on a phone, under it), and the address
  // says which (?note=), so Back and a shared link open the same one; nothing is fetched, every note is on the page
  document.addEventListener('click', e => {
    const row = e.target.closest && e.target.closest('.notes-page [data-note]');
    if (!row || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    const tab = row.closest('.notes-tab'), key = row.dataset.note;
    tab.querySelectorAll('[data-note]').forEach(r => r.classList.toggle('sel', r === row));
    let shown = null;
    tab.querySelectorAll('[data-note-read]').forEach(a => { a.hidden = a.dataset.noteRead !== key; if (!a.hidden) shown = a; });
    const u = new URL(location.href); u.searchParams.set('note', key); u.searchParams.set('tab', tab.id.replace(/^t-/, ''));
    history.replaceState(null, '', u);
    if (shown && matchMedia('(max-width: 900px)').matches) shown.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.querySelectorAll('.notes-page .notes-tab').forEach(tab => {  // (the one shown at first: marked in its list)
    const a = tab.querySelector('[data-note-read]:not([hidden])');
    tab.querySelectorAll('[data-note]').forEach(r => r.classList.toggle('sel', !!a && r.dataset.note === a.dataset.noteRead));
  });
  const news = () => fetch('/your-notes/news', { headers: { Accept: 'application/json' }, cache: 'no-store' })
    .then(r => (r.ok ? r.json() : { count: 0, cards: [] }))
    .then(j => {
      badge(j.count);
      if (location.pathname === '/your-notes') return;  // (here, the page itself says what's new)
      (j.cards || []).forEach(c => window.askdndToast && window.askdndToast(c.text, { label: 'See it', run: () => { location.href = c.href; } }, 'info'));
    })
    .catch(() => {});
  news();
  // A change in Found, Fixed, Tried (app/fft/live.py): the badge and its card come at once, not on the next page
  let newsTick = null;
  document.addEventListener('askdnd:live', e => { if (e.detail.type === 'fft') { clearTimeout(newsTick); newsTick = setTimeout(news, 400); } });
})();

// ---------------------------------------------------------------- markers instead of inline handlers
// (Nov 13: no inline handlers or evaluated text, so the Content Security Policy can run only askdnd's own files)
//   data-confirm="…" on a form     asks before it's sent (once each form's onsubmit="return confirm(…)")
//   data-reset-after on an htmx form  empties it once its request succeeded (once hx-on::after-request)
//   data-ds-toast="…" (-kind, -undo)  the Design system page's sample corner cards
(function () {
  document.addEventListener('submit', e => {
    const f = e.target.closest && e.target.closest('form[data-confirm]');
    if (f && !confirm(f.dataset.confirm)) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  document.body.addEventListener('htmx:afterRequest', e => {
    const f = e.detail.elt && e.detail.elt.closest && e.detail.elt.closest('form[data-reset-after]');
    if (f && e.detail.successful) f.reset();
  });
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('[data-ds-toast]');
    if (!b || !window.askdndToast) return;
    const undo = b.dataset.dsUndo;
    window.askdndToast(b.dataset.dsToast, undo ? { label: 'Undo', run: () => window.askdndToast(undo) } : null, b.dataset.dsKind || undefined);
  });
})();
