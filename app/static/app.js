// askdnd: small page behaviors. Server-rendered pages; HTMX handles partial updates.
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
      if (t.dataset.clock === 'date') Object.assign(o, { month: 'short', day: 'numeric' }, d.getFullYear() !== year ? { year: 'numeric' } : {});
      t.textContent = d.toLocaleString([], o);
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
  const CARD = { ok: ['✓', 4000], info: ['i', 6000], roll: ['', 6000], warn: ['!', 10000], error: ['✕', 0] };
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
    while (box.children.length > most) box.firstElementChild.remove();
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
        const ids = (s.failed || []).map(f => f.id), act = (path, then) => () => Promise.all(ids.map(id => fetch(path + id, { method: 'POST', headers: { Accept: 'application/json' } }))).then(then);
        const row = Object.assign(document.createElement('span'), { className: 'card-acts card-follow-acts' });
        [['Try again', act('/bridge/retry/', () => { row.remove(); el.className = 'card k-ok following'; if (ic) ic.textContent = '↻'; sub.textContent = 'Trying again'; el._following = true; clearTimeout(el._hide); told(); setTimeout(tick, 1500); })],
         ['Undo', act('/bridge/dismiss/', () => { row.remove(); sub.textContent = 'Undone in askdnd'; told(); settle(4000); })]].forEach(([label, run]) => {
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
    if (message && typeof message === 'object') { kind = message.kind; message = message.text; }
    if (message) card(document.createTextNode(message), { kind: kind || 'ok', action });
  }
  window.askdndToast = toast;
  window.askdndCard = card;
  // A change's corner card: the one just shown, or the next one (web.changed sends the change before its message)
  window.askdndFollow = d => {
    if (lastCard && lastCard.el.isConnected && Date.now() - lastCard.at < 1500) followChange(lastCard.el, d);
    else waitingFollow = { d, at: Date.now() };
  };

  // Server can trigger a toast with the HX-Trigger header: {"toast": "Saved"}
  document.body.addEventListener('toast', e => toast(e.detail && ('value' in e.detail ? e.detail.value : e.detail)));

  document.addEventListener('click', e => {
    // Menus (campaign, Party, Live, Manage, account, phone More). A click elsewhere closes
    // them; clicks inside a [data-keep-open] menu (the Live popover's switch) don't.
    const opener = e.target.closest('[data-menu]');
    document.querySelectorAll('.menu').forEach(m => {
      if ((!opener || m.id !== opener.dataset.menu) && !(m.hasAttribute('data-keep-open') && m.contains(e.target))) m.hidden = true;
    });
    if (opener) {
      const m = document.getElementById(opener.dataset.menu);
      if (m) { m.hidden = !m.hidden; opener.setAttribute('aria-expanded', m.hidden ? 'false' : 'true'); }
    }
    // Read/edit toggles: data-show="id" reveals #id and hides data-hide targets
    const show = e.target.closest('[data-show]');
    if (show) {
      e.preventDefault();
      const target = document.getElementById(show.dataset.show);
      (show.dataset.hide || '').split(' ').filter(Boolean).forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
      target.hidden = false;
      const field = target.querySelector('textarea, input[type=text]');
      if (field) field.focus();
    }
    const cancel = e.target.closest('[data-cancel]');
    if (cancel) {
      e.preventDefault();
      const form = document.getElementById(cancel.dataset.cancel);
      form.hidden = true;
      (cancel.dataset.restore || '').split(' ').filter(Boolean).forEach(id => { const el = document.getElementById(id); if (el) el.hidden = false; });
    }
  });

  // @-mentions: in any textarea (or input[data-mention]), typing "@" and a few
  // letters suggests entity names (incl. aliases and known misspellings);
  // choosing one inserts the canonical name in place of "@letters".
  const mention = { box: null, field: null, start: 0, items: [], active: 0, timer: null, seq: 0 };
  const TRIGGER = /(?:^|[\s(\["'\u201c\u2018])@([\p{L}\p{N}'\u2019-][\p{L}\p{N}'\u2019 -]{0,39})$/u;
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
  // An entry's address, /c/<campaign>/campaign?open=<id>, or a glossary term's, …/campaign/glossary/<id> (2026-10-23)
  const ENTITY_URL = /^(?:\/c\/[a-z0-9-]+)?\/campaign(?:\/(glossary\/\d+)|\?open=(\d+))$/;
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
  // option's details). data-modal-url opens a centered modal; data-modal-size="large" makes it wide
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
    if (back) { /* returning: the history entry was already taken off */ }
    else if (inside && panel.dataset.url) {
      const title = panel.querySelector('#peek-title');
      layer.history.push({ url: panel.dataset.url, modal: panel.classList.contains('large') ? 'large' : panel.classList.contains('modal'), scroll: (panel.querySelector('.peek-body') || {}).scrollTop || 0,
                           title: title ? title.textContent.trim() : '', layer });
    } else layer.history = [];
    if (!inside && !back) { if (layer.name === 'top') layer.focus = opener; else lastFocus = opener; }
    panel.classList.toggle('modal', !!modal);
    panel.classList.toggle('large', modal === 'large');
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
  window.askdndPanel = openPanel;
  // ✕ closes its own layer. Delegated, so it still works after part of a panel is swapped in
  // (Wild Shape's "Kept in a form" boxes re-render the whole window).
  document.addEventListener('click', e => {
    const x = e.target.closest('.peek-close'); if (!x) return;
    const layer = Object.values(layers).find(l => l && l.panel === x.closest('.peek'));  // the innermost (the top layer sits inside a modal)
    if (layer) closeLayer(layer);
  });

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-panel-url], [data-modal-url]');
    if (!t || e.target.closest('button[hx-post], form, [data-roll], [data-use-url], details, a[data-no-peek], .ft-init button, .ft-init input')) return;  // (a pop-up in a row: the row stays put; a link of its own goes where it says)
    e.preventDefault();
    if (t.dataset.modalUrl) openPanel(t.dataset.modalUrl, t, t.getAttribute('href'), t.dataset.modalSize === 'large' ? 'large' : true);
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
    const ref = m[1] || m[2];
    // On the Campaign page, a name opens that entry in the Reader (World) instead
    const item = !a.closest('.peek') && document.querySelector('[data-rd-id="' + ref + '"]');
    if (item) {
      const tab = item.closest('[id^="t-"]'), btn = tab && tab.hidden && document.querySelector('[role=tab][data-tab="' + tab.id + '"]');
      if (btn) btn.click();
      item.click();
      return;
    }
    openPeek(ref, a);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePeek(); });

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
    // Party's cards too (Brett, 2026-11-02): each card's resources by their whole names while they fit on one line.
    // They arrive short (party.html), so a card never grows and then shrinks as the page loads.
    document.querySelectorAll('.pt-res').forEach(r => {
      r.classList.remove('short');
      const one = r.firstElementChild?.offsetHeight || 24;
      if (r.offsetHeight > one * 1.5) r.classList.add('short');
    });
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
  // Resources on a phone: one line that opens, one choice per device for every character
  try { document.body.classList.toggle('res-open', localStorage.getItem('askdnd-res-open') === '1'); } catch (err) { /* private window */ }
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-res-more]'); if (!b) return;
    const open = document.body.classList.toggle('res-open');
    document.querySelectorAll('[data-res-more]').forEach(x => x.setAttribute('aria-expanded', open ? 'true' : 'false'));
    try { localStorage.setItem('askdnd-res-open', open ? '1' : '0'); } catch (err) { /* private window */ }
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
      keep.type = 'hidden'; keep.name = btn.name; keep.value = btn.value;
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
  // Coming back with the browser's Back button shows the page as it was left: undo busy states.
  window.addEventListener('pageshow', () => document.querySelectorAll('button.busy').forEach(b => {
    b.classList.remove('busy'); b.disabled = false; if (b.dataset.label) b.textContent = b.dataset.label;
  }));

  // At the table (body.at-table; docs/mockups/table-without-modes.html): every few minutes, while the tab is visible, the
  // page asks the server to keep the party fresh (throttled per character, however many pages ask). askdnd reads the
  // party from D&D Beyond (the character on screen, or your own, first) and the Live pill comes back. Whatever changed
  // reaches the pages showing it through the live connection, like every change (showInPlace below); while that's down,
  // this page asks for its new copy itself.
  function freshen() {
    const pill = document.getElementById('live-pill');
    if (!window.htmx || !pill) return;
    htmx.ajax('POST', '/live/sync' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-pill', swap: 'outerHTML' })
      .then(() => { liveWindowAgain(); if (!live.up) showInPlace(); });
  }
  // The Live window, while it's open, says what the pill says (Bridge Review, Nov 3: an open window said "Not connected"
  // under a pill saying Connected): it's fetched again whenever the pill is
  function liveWindowAgain() {
    const menu = document.getElementById('live-menu'), pill = document.getElementById('live-pill');
    if (!window.htmx || !menu || menu.hidden || !pill) return;
    htmx.ajax('GET', '/live' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-menu', swap: 'innerHTML' });
  }
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
  const PARTY = /^(\/c\/[^/]+)?\/party$/;
  let showWait = null, showing = false, again = false;
  function showsAny(ids) {  // ids: character ids as text, or '*' for any
    const page = document.querySelector('main[data-character]');
    const mine = document.querySelector('[data-cond-dots]');  // your character's button in the menu bar shows its conditions
    return PARTY.test(location.pathname) || !!(page && (ids.includes('*') || ids.includes(page.dataset.character)))
      || !!(mine && ids.includes(mine.dataset.character));
  }
  function busyHere() {
    const a = document.activeElement;
    return !!(document.querySelector('.peek.open, .roll-win, .tour-card, dialog[open], details.conc-pop[open], details.cond-pill[open]') ||
              (a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName))));
  }
  // A field that saves as you type (a note in a side panel): the box holding it isn't swapped while you're in it
  const typingIn = box => { const a = document.activeElement; return !!(a && box.contains(a) && a.closest('form[hx-trigger*="input"]')); };
  function keepState(box) {  // what the person had in a box (the page's main, a side panel); returns what puts it back
    const scroller = () => box.matches('main') ? document.scrollingElement : box.querySelector('.peek-body');
    const y = (scroller() || {}).scrollTop || 0;
    const a = document.activeElement, form = a && box.contains(a) && a.name && a.closest('form');
    const field = form && ('form[' + (form.getAttribute('hx-post') ? 'hx-post="' + form.getAttribute('hx-post') : 'action="' + form.getAttribute('action')) + '"] [name="' + a.name + '"]');
    const tabs = [...box.querySelectorAll('[role=tab][data-tab][aria-selected=true]')].map(t => t.dataset.tab);
    const searches = [...box.querySelectorAll('[data-list]')].map(r => [r.dataset.list, (r.querySelector('[data-ls-search]') || {}).value || '']).filter(([, q]) => q);
    return () => {
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
  function swapMain(html) {
    const doc = new DOMParser().parseFromString(html, 'text/html'), here = document.querySelector('main'), there = doc.querySelector('main');
    if (!here || !there) return;
    const restore = keepState(here), before = marksIn(here);
    [...here.attributes].forEach(a => { if (!there.hasAttribute(a.name)) here.removeAttribute(a.name); });
    [...there.attributes].forEach(a => here.setAttribute(a.name, a.value));
    here.replaceChildren(...[...there.childNodes].map(n => document.importNode(n, true)));
    const pill = document.getElementById('live-pill'), newPill = doc.getElementById('live-pill');
    if (pill && newPill) { pill.className = newPill.className; pill.title = newPill.title; pill.innerHTML = newPill.innerHTML; Object.assign(pill.dataset, newPill.dataset); liveWindowAgain(); }
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
    if (showing) { again = true; return; }
    clearTimeout(showWait); showWait = null;
    const later = () => { showWait = setTimeout(() => showInPlace(), 2000); };
    if (!now && (busyHere() || document.visibilityState !== 'visible')) return later();
    showing = true;
    const get = url => fetch(url, { headers: { 'HX-Request': 'true' } }).then(r => r.ok ? r.text() : Promise.reject(r.status));
    const open = ['base', 'top'].map(n => layers[n]).filter(l => isOpen(l) && l.panel.dataset.url);
    Promise.all([get(location.pathname + location.search), ...open.map(l => get(l.panel.dataset.url))])
      .then(([page, ...panels]) => {
        showing = false;
        if (!now && busyHere()) return later();
        const main = document.querySelector('main');
        if (main && !typingIn(main)) swapMain(page);  // (askdnd:swapped measures Resources again)
        open.forEach((l, i) => { if (isOpen(l) && l.panel.dataset.url && !typingIn(l.panel)) swapPanel(l, panels[i]); });
        if (again) { again = false; showInPlace(now); }
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
    if (t === 'deliver') { window.postMessage({ askdndBridge: 'deliver', ddbId: String(e.detail.ddb) }, location.origin); return; }  // (a change another one waited for may go now: ddb_bridge._release)  // the fight moved on: every page, once it isn't in the way of a pop-up
    if (t !== 'character' && t !== 'resync') return;
    liveIds.add(t === 'resync' ? '*' : String(e.detail.id));
    clearTimeout(liveTick);
    liveTick = setTimeout(() => {
      const ids = [...liveIds];
      liveIds = new Set();
      if (showsAny(ids)) showInPlace();
      else freshen();
    }, 400);
  });
  // You changed something of a character's (a pin, bookmark, reminder or note: character_pages, player_notes):
  // the page and its open panels show their new copy at once. A form that's done with its window closes it first.
  document.body.addEventListener('closePanel', () => closePeek());
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
  // Battle's "See all" / "+ Add" panels: chips show one kind (attacks, features, spells…), search looks at names
  // and descriptions; groups with nothing left hide (Brett, 2026-10-22)
  function optFilter(panel) {
    const on = [...panel.querySelectorAll('[data-opt-kind][aria-pressed=true]')].map(b => b.dataset.optKind);
    const q = ((panel.querySelector('[data-opt-search]') || {}).value || '').toLowerCase().trim();
    let any = false;
    panel.querySelectorAll('.opt-group').forEach(g => {
      const kindOk = !on.length || on.includes(g.dataset.kind);
      let shown = 0;
      g.querySelectorAll('.ri').forEach(r => { const ok = kindOk && (!q || r.textContent.toLowerCase().includes(q)); r.hidden = !ok; if (ok) shown++; });
      g.hidden = !shown; any = any || shown > 0;
    });
    const none = panel.querySelector('[data-opt-none]'); if (none) none.hidden = any;
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-opt-kind]'); if (!b) return;
    b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    optFilter(b.closest('[data-opt-panel]'));
  });
  document.addEventListener('input', e => { if (e.target.matches('[data-opt-search]')) optFilter(e.target.closest('[data-opt-panel]')); });
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
      list._sortable = Sortable.create(list, {
        draggable: list.dataset.sortItem || '.move', animation: 150, delay: 180, delayOnTouchOnly: true, ghostClass: 'drag-ghost',
        onEnd: () => {
          const body = new URLSearchParams({ column: list.dataset.sortColumn });
          list.querySelectorAll('[data-key]').forEach(m => body.append('keys', m.dataset.key));
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
    if (termTip && !e.target.closest('.term-tip')) termHide();
  });
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('.term');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
    else if (e.key === 'Escape' && termTip) { e.stopImmediatePropagation(); const f = termFor; termHide(); if (f) f.focus(); }
  }, true);
  document.addEventListener('scroll', () => { if (termPinned) termPlace(); else if (termTip) termHide(); }, true);
  window.addEventListener('resize', termPlace);

  // A select with data-autosave saves as you pick (Manage › Table)
  document.addEventListener('change', e => { if (e.target.matches('select[data-autosave]')) e.target.form.requestSubmit(); });
  // A file picker with data-autosubmit sends its form as soon as a file is chosen (entity pictures).
  document.addEventListener('change', e => { if (e.target.matches('input[type=file][data-autosubmit]') && e.target.files.length) e.target.form.requestSubmit(); });

  // Sticky headings sit below the top bar.
  function stickTop() {
    const bar = $('.topbar'), tabs = $('.sheet .tabbar');
    document.documentElement.style.setProperty('--stick-top', (bar ? bar.offsetHeight : 0) + 'px');
    if (tabs) document.documentElement.style.setProperty('--tabs-h', tabs.offsetHeight + 'px');
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
  const WIDE = 1100;  // narrower than this, the sidebar starts closed and opens over the page
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
  const atTable = () => document.body.classList.contains('at-table');
  // The animation switch: on or off as chosen on this device; until then, off only if the device asks for less motion
  const animate = () => { const v = store.get(ANIM); return v ? v === 'on' : !calm.matches; };
  // Whether a roll of yours reaches D&D Beyond's Game Log, for the roll window; "" where it never would (the Live pill's
  // data-log: your sheet is connected, closed, or your character isn't in a D&D Beyond game)
  function logNote() {
    const d = (document.getElementById('live-pill') || { dataset: {} }).dataset, state = d.log;
    if (state && document.body.classList.contains('no-bridge')) return "Not in D&D Beyond's Game Log: the askdnd bridge isn't in this browser.";
    // (past `data-log-until` the sheet hasn't been heard: a closed tab whose word never came, or a pill not redrawn yet)
    if (state === 'on' && Date.now() / 1000 < Number(d.logUntil)) return "Also goes to D&D Beyond's Game Log.";
    if (state === 'on') return "Not in D&D Beyond's Game Log: your sheet isn't open.";
    if (state === 'sheet') return "Not in D&D Beyond's Game Log: " + (phone.matches ? 'that needs Chrome on a computer.' : "your sheet isn't open.");
    return '';
  }
  const TO_WORDS = { table: 'to the table', dm: 'DM only', self: 'just you', private: 'only in this browser' };

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

  // Recipes (app/roll_recipes.py, audited in docs/rules/rolls-audit.md): a spell's events, resolved
  // for the slot level you cast it with (or your character level, for a cantrip). Parts are
  // "2d6+3 fire" or a fixed "4 spellcasting modifier".
  const PART = /^(?:(\d+)d(\d+)([+-]\d+)?|([+-]?\d+))(?:\s+(.+))?$/;
  function parsePart(p) {
    const m = PART.exec(String(p || '').trim());
    if (!m) return null;
    return m[4] != null ? { n: 0, s: 0, flat: +m[4], kind: m[5] || '' } : { n: +m[1], s: +m[2], flat: +(m[3] || 0), kind: m[5] || '' };
  }
  const partText = p => (p.n ? p.n + 'd' + p.s + (p.flat ? ascii(p.flat) : '') : String(p.flat)) + (p.kind ? ' ' + p.kind : '');
  function grow(part, extra, times) {
    const p = parsePart(part);
    if (!p || !extra || times <= 0) return part;
    if (/^[+-]\d+$/.test(extra)) { p.flat += +extra * times; return partText(p); }
    const e = parsePart(extra);
    if (!e || e.s !== p.s) return part;
    p.n += e.n * times;
    return partText(p);
  }
  const tierOf = lvl => 1 + (lvl >= 5) + (lvl >= 11) + (lvl >= 17);
  const baseDice = p => p.split(' ')[0].split(/[+-]/)[0];
  function resolve(rec, ev, slot, charLevel) {
    const level = rec.level || 0, e = { ...ev, parts: (ev.parts || []).slice(), count: ev.count || 1 };
    if (level && slot > level) {
      const times = Math.floor((slot - level) / (ev.every || 1));
      e.parts = e.parts.map((p, i) => grow(p, (ev.upcast || [])[i] || '', times));
      e.count += (ev.count_upcast || 0) * times;
    }
    if (!level && ev.cantrip) {
      const t = tierOf(charLevel || 1);
      if (ev.cantrip === 'count') e.count *= t;
      else if (ev.cantrip === 'extra') { if (t === 1) return null; e.parts = e.parts.map(p => grow(p, baseDice(p), t - 2)); }
      else e.parts = e.parts.map(p => grow(p, baseDice(p), t - 1));
    }
    return e;
  }
  const kindOf = ev => ({ heal: 'heal', temp: 'temp', plain: 'dice' }[ev.on] || 'damage');
  const SUCCESS = { half: 'half on a success', none: 'nothing on a success' };
  function describe(ev) {
    const many = ev.count > 1 ? ev.count + ' ' + (ev.count_label || 'time') + 's × ' + (ev.once ? 'one roll: ' : '') : '';
    const how = ev.on === 'save' ? (ev.save ? ev.save + ' save' : 'save') + (ev.success ? ', ' + SUCCESS[ev.success] : '') : ev.on === 'hit' ? 'on a hit' : '';
    const shown = ev.parts.map(p => { const x = parsePart(p); return x && !x.n ? Math.abs(x.flat) + (x.kind ? ' (' + x.kind + ')' : '') : p; });
    const text = ev.parts.map((p, i) => { const x = parsePart(p); return (i ? (x && !x.n && x.flat < 0 ? ' \u2212 ' : ' + ') : '') + shown[i]; }).join('');
    return many + text + (ev.mod ? ' + spellcasting modifier' : '') + (how && ev.on !== 'hit' ? ' · ' + how : '');
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
        const crit = e.nat === 20;
        d = e.spec ? rollParts(e.spec.parts, [crit], '', true) : rollFormula(e.dmg, crit, true);
        if (!d) return e;
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
      const n = die(opts.die);
      e.bonus = { label: opts.label || 'Added die', formula: '1d' + opts.die, dice: [n], total: n };
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
    let s = d20 ? 'd20 ' + p.dice.map((d, i) => (i === p.kept_at ? '<u>' + d + '</u>' : d)).join(' / ') + ' ' + signed(p.modifier) + (p.mode === 'adv' ? ' · Adv' : p.mode === 'dis' ? ' · Dis' : '')
                : esc(p.formula) + ': ' + p.dice.join(' ') + (p.modifier ? ' ' + signed(p.modifier) : '');
    (p.extras || []).forEach(x => { s += ' · ' + esc(x.label) + ' ' + signed(x.total) + (x.dice.length ? ' <span class="roll-x">(' + esc(x.formula.replace('-', '\u2212')) + ')</span>' : ''); });
    return s;
  }
  const KIND_WORDS = { attack: ' to hit', damage: ' damage', heal: ' healing' };
  function resultHTML(e, focus) {
    const d20 = D20.includes(e.kind), dmgFirst = focus === 'damage' && e.damage;
    const big = dmgFirst ? e.damage.total : e.total;
    const what = dmgFirst ? ' ' + (e.damage.crit ? 'critical damage' : 'damage') : (KIND_WORDS[e.kind] || '');
    const flag = e.kind === 'death' ? e.outcome : e.nat ? 'Natural ' + e.nat + (e.kind === 'attack' ? (e.nat === 20 ? ': critical hit' : ': miss') : '') : '';
    const rays = (e.main.parts || []).filter(x => x.kept != null);
    const bigText = !dmgFirst && rays.length > 1 ? rays.map(r => r.total).join(' · ') : big;
    let h = '<div class="rp-label">' + esc(e.label) + what + ' · ' + TO_WORDS[e.to] + '</div>'
      + '<div class="rp-res"><b>' + bigText + '</b> <span class="roll-sub">' + (dmgFirst ? dline(e.damage, false) : dline(e.main, d20)) + '</span></div>';
    if (dmgFirst) h += '<div class="rp-line">To hit <b>' + e.total + '</b> · ' + dline(e.main, true) + '</div>';
    if (e.rerolled) h += '<div class="rp-line">Rerolled (' + esc(e.rerolled.reason) + '): was <s>' + e.rerolled.total + '</s></div>';
    if (e.bonus) h += '<div class="rp-line">+ ' + esc(e.bonus.label) + ' ' + e.bonus.total + ' <span class="roll-x">(' + esc(e.bonus.formula) + ')</span></div>';
    if (flag) h += '<div class="rp-flag">' + esc(flag) + '</div>';
    if (e.damage && !dmgFirst) h += '<div class="rp-line">' + (e.damage.crit ? 'Critical damage' : 'Damage') + ' <b>' + e.damage.total + '</b> · ' + dline(e.damage, false) + '</div>';
    const c = e.can || {};
    if (c.damage || c.reroll || c.bonus) {
      h += '<div class="rp-acts">'
        + (c.damage ? '<button type="button" class="btn small primary" data-act="damage">Roll ' + (e.nat === 20 ? 'critical ' : '') + 'damage (' + esc(c.damage) + ')</button>' : '')
        + (c.reroll ? '<button type="button" class="btn small" data-act="reroll">Reroll (' + esc(c.reroll) + ')</button>' : '')
        + (c.bonus ? '<button type="button" class="btn small link" data-act="bonus">+ Add a die</button>' : '') + '</div>';
    }
    return h;
  }

  // ---------------------------------------------------------------- the roll window
  // A dice picker (the roll window's "Add dice or a bonus" and the sidebar's Manual roll): click a
  // die to add one (in the window, "−" then a die subtracts it), plus a flat bonus.
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
    try { return el ? JSON.parse(el.dataset.rollCtx) : {}; } catch (e) { return {}; }
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
  function place(w, anchor) {
    const r = anchor && anchor.isConnected ? anchor.getBoundingClientRect() : w._r;
    if (!r && !phone.matches) return;
    w._r = r;
    const pw = w.offsetWidth, ph = w.offsetHeight, m = 8;
    if (phone.matches) {  // phones: at the bottom, over the bottom bar, within thumb reach
      w.style.left = m + 'px'; w.style.top = Math.max(m, innerHeight - ph - m) + 'px';
      return;
    }
    let left = Math.min(Math.max(r.left, m), innerWidth - pw - m), top = r.bottom + 6;
    if (top + ph > innerHeight - m) top = r.top - ph - 6;
    if (top < m) top = Math.max(m, innerHeight - ph - m);
    w.style.left = left + 'px'; w.style.top = top + 'px';
  }
  function openWin(anchor) {
    const prev = win && anchor && win.contains(anchor) ? win.getBoundingClientRect() : null;  // a follow-up takes the result's place
    closeWin();
    win = document.createElement('div');
    if (prev) win._r = { left: prev.left, top: prev.top, bottom: prev.top - 6 };
    win.className = 'roll-win';
    win.setAttribute('role', 'dialog');
    win.setAttribute('aria-label', 'Roll');
    document.body.appendChild(win);
    win._anchor = anchor;
    return win;
  }

  // spec: what to roll. {kind, label, mod, dmg, adv, advWhy, note, cid, shared, follow, parent, entry}
  function chooser(anchor, spec) {
    const w = openWin(anchor), d20 = D20.includes(spec.kind) && !spec.follow, ctx = ctxFor(spec.cid);
    let mode = spec.adv ? 'adv' : 'normal';
    const title = spec.follow === 'damage' ? esc(spec.label) + ' · ' + (spec.crit ? 'critical damage' : 'damage') + ' <span class="roll-sub">' + esc(spec.dmg) + (spec.crit ? ', dice doubled' : '') + '</span>'
      : spec.follow === 'bonus' ? 'Add a die to ' + esc(spec.label)
      : esc(spec.label || 'Dice') + ' <span class="roll-sub">' + (d20 ? 'd20' + (spec.kind === 'death' ? '' : ' ' + signed(num(spec.mod))) : esc(spec.dmg)) + '</span>';
    let h = '<button type="button" class="rp-x" aria-label="Close">×</button><div class="rw-title">' + title + '</div>';
    if (d20) {
      h += '<div class="rw-row rw-mode">' + seg('Mode', [['normal', 'Normal'], ['adv', 'Advantage'], ['dis', 'Disadvantage']], mode) + '</div>';
      const notes = [];
      // Reasons: Advantage by default; "!dis " marks Disadvantage and "!note " a plain note (conditions)
      (spec.advWhy || '').split('\n').filter(Boolean).forEach(t => notes.push(
        t.startsWith('!dis ') ? '<b>Disadvantage</b> ' + esc(t.slice(5)) : t.startsWith('!note ') ? '<b>Note</b> ' + esc(t.slice(6))
        : /^advantage\b/i.test(t) ? '<b>Advantage</b>' + esc(t.slice(9)) : '<b>Advantage</b> ' + esc(t)));
      if (ctx.luck) notes.push('<b>Lucky</b> you can spend a Luck Point (' + ctx.luck + ' left) for Advantage');
      if (ctx.inspiration) notes.push('<b>Heroic Inspiration</b> you have it: you can reroll after you see the roll');
      if (ctx.halfling) notes.push('<b>Luck</b> (Halfling) you can reroll a 1');
      if (/^Con save/.test(spec.label)) notes.push('<b>Concentration</b> after damage: DC 10 or half the damage, whichever is higher (up to 30)');
      if (spec.label === 'Initiative') notes.push('<b>Initiative</b> Disadvantage if you\'re Surprised, Advantage if you\'re Invisible');
      if (notes.length) h += '<ul class="rw-notes">' + notes.map(n => '<li>' + n + '</li>').join('') + '</ul>';
    }
    if (spec.note) h += '<p class="rw-note">' + esc(spec.note) + '</p>';
    if (spec.follow === 'damage' && spec.crit) h += '<p class="rw-note">Critical hit: every damage die is rolled twice, extra dice too.</p>';
    // A recipe: the slot level (when it changes the dice), the choice between its effects, what it rolls
    const rec = spec.recipe && !spec.follow ? spec.recipe : null;
    let evs = [], evi = 0, slot = 0;
    if (rec) {
      evs = rec.events.filter(e => (spec.kind === 'attack') === (e.on === 'hit'));
      const grows = rec.level && evs.some(e => (e.upcast || []).some(Boolean) || e.count_upcast);
      slot = rec.level ? (spec.slot >= rec.level ? spec.slot : ((ctx.slots || []).find(l => l >= rec.level) || rec.level)) : 0;
      if (grows) h += '<div class="rw-row"><span class="rw-label">Cast at</span><select class="rw-slot" data-slot aria-label="Spell slot level">'
        + [1, 2, 3, 4, 5, 6, 7, 8, 9].filter(l => l >= rec.level).map(l => '<option value="' + l + '"' + (l === slot ? ' selected' : '') + '>Level ' + l
          + (ctx.slots && ctx.slots.length && !ctx.slots.includes(l) ? ' (no slot left)' : '') + '</option>').join('') + '</select></div>';
      if (evs.length > 1) h += '<div class="rw-row rw-evs"><span class="rw-label">Which</span><span class="rw-ev-list">' + evs.map((e, i) =>
        '<button type="button" class="chip" data-ev="' + i + '" aria-pressed="' + (i === 0) + '">' + esc(e.name) + '</button>').join('') + '</span></div>';
      h += '<p class="rw-sum"></p>';
      (rec.house_rules || []).forEach(r => { h += '<p class="rw-note rw-house"><b>House rule</b> ' + esc(r.text) + (r.reason ? ' · ' + esc(r.reason) : '') + '</p>'; });
      if (rec.checked === 'D&D Beyond') h += '<p class="rw-note">From D&amp;D Beyond\'s data: not checked against the rules text (askdnd\'s audit only covers the 2024 rules).</p>';
    }
    let other = '';
    if (spec.follow === 'bonus') {
      h += '<div class="rw-row"><span class="rw-label">Die</span>' + seg('Die', [[4, 'd4'], [6, 'd6'], [8, 'd8'], [10, 'd10'], [12, 'd12']], 6) + '</div>'
        + '<div class="rw-row"><span class="rw-label">From</span><input type="text" class="rw-text" data-bonus-label placeholder="Bardic Inspiration, Guidance…" maxlength="40"></div>';
    } else if (spec.kind === 'dice') {
      h += '<div class="rw-row"><span class="rw-label">For</span><input type="text" class="rw-text" data-for placeholder="What the DM asked for (optional)" maxlength="60"></div>';
    } else if (spec.follow !== 'reroll') {
      h += '<details class="rw-add"><summary>Add dice or a bonus</summary>' + pickerHTML({ minus: true }) + '</details>';
    }
    if (spec.shared && !spec.follow) h += '<div class="rw-row"><span class="rw-label">Who sees</span>' + seg('To', [['table', 'Table'], ['dm', 'DM only'], ['self', 'Only me']], to) + '</div><p class="rw-note" data-log-note' + (to === 'self' || !logNote() ? ' hidden' : '') + '>' + logNote() + '</p>';
    else if (!spec.shared) h += '<p class="rw-note">You don\'t play this character, so only you see this roll.</p>';
    h += '<div class="rw-go"><button type="button" class="btn primary" data-go>Roll</button><span class="note">Enter rolls · Esc closes</span></div>';
    w.innerHTML = h;
    const pick = w.querySelector('.dice-pick') ? wirePicker(w.querySelector('.dice-pick'), () => place(w, anchor)) : null;
    // What the chosen effect rolls at this slot level, with the spellcasting modifier when the recipe adds it
    function current() {
      const ev = resolve(rec, evs[evi], slot, ctx.level);
      if (!ev) return null;
      if (ev.mod && ctx.spell_mod != null) ev.parts = ev.parts.concat([ascii(ctx.spell_mod) + ' spellcasting modifier']);
      return ev;
    }
    function summarize() {
      const out = w.querySelector('.rw-sum');
      if (!out) return;
      const ev = current();
      out.innerHTML = !ev ? 'Nothing extra at your level yet.' : (spec.kind === 'attack' ? (ev.count > 1 ? ev.count + ' ' + ev.count_label + 's, an attack roll each. ' : '') + 'Damage on a hit: ' : '')
        + esc(ev ? describe({ ...ev, mod: ev.mod && ctx.spell_mod == null }) : '')
        + (ev && ev.repeat ? '<br><span class="note">Again: ' + esc(ev.repeat) + '</span>' : '') + (ev && ev.note ? '<br><span class="note">' + esc(ev.note) + '</span>' : '');
      place(w, anchor);
    }
    summarize();
    w.querySelector('[data-slot]')?.addEventListener('change', e => { slot = +e.target.value; summarize(); });
    w.querySelector('.rw-add')?.addEventListener('toggle', () => place(w, anchor));
    place(w, anchor);
    w.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      if (b.classList.contains('rp-x')) return closeWin();
      if (b.dataset.mode) { mode = b.dataset.mode; w.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', x === b)); }
      if (b.dataset.to) {
        to = b.dataset.to;
        store.set(TO, to);  // (remembered on this device: a player practising stays on Only me)
        w.querySelectorAll('[data-to]').forEach(x => x.setAttribute('aria-pressed', x === b));
        const note = w.querySelector('[data-log-note]');
        if (note) note.hidden = to === 'self' || !logNote();
        place(w);
      }
      if (b.dataset.die) w.querySelectorAll('[data-die]').forEach(x => x.setAttribute('aria-pressed', x === b));
      if (b.dataset.extra) b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') !== 'true');
      if (b.dataset.ev) { evi = +b.dataset.ev; w.querySelectorAll('[data-ev]').forEach(x => x.setAttribute('aria-pressed', x === b)); summarize(); }
      if (b.hasAttribute('data-go')) {
        const extras = pick ? pick.extras('Bonus') : [];
        const forText = ((w.querySelector('[data-for]') || {}).value || '').trim();
        const ev = rec ? current() : null;
        if (rec && !ev) return;
        const fromRecipe = ev ? (spec.kind === 'attack' ? { dmgParts: ev.parts, count: ev.count, each: ev.count_label || '' }
          : { kind: kindOf(evs[evi]), parts: ev.parts, count: ev.count, once: !!ev.once, each: ev.count_label || '', label: spec.label + (evs.length > 1 ? ' · ' + evs[evi].name : '') }) : {};
        const go = { ...spec, ...fromRecipe, mode, extras, label: spec.kind === 'dice' ? (forText || 'Dice') : (fromRecipe.label || spec.label), ctx,
                     die: +((w.querySelector('[data-die][aria-pressed=true]') || {}).dataset || {}).die || 6,
                     bonusLabel: ((w.querySelector('[data-bonus-label]') || {}).value || '').trim() };
        roll(w, go);
      }
    });
    (w.querySelector('[data-go]') || w).focus();
  }

  // ---------------------------------------------------------------- rolling
  const D20SVG = '<svg class="rp-die" viewBox="0 0 30 30" aria-hidden="true"><polygon points="15,2 27,9 27,21 15,28 3,21 3,9"/><text x="15" y="18.5" text-anchor="middle"></text></svg>';
  // Turn the window into the result: a short tumble (click to skip), then the numbers.
  function showRolling(w) {
    w.classList.add('result');
    w.innerHTML = '<button type="button" class="rp-x" aria-label="Close">×</button><div class="rw-result">' + D20SVG + '<div class="rp-body"><div class="rp-res">Rolling…</div></div></div>';
    w._ready = Promise.resolve();  // with the animation on, the dice on stage (below) take the time instead
    place(w, w._anchor);
  }
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
  function showResult(w, e, focus) {
    return w._ready.then(() => animate() ? throwMine(e, focus).catch(() => stage(e, focus)) : null).then(() => {
      landed(e.id);
      if (!w.isConnected) return;
      w._entry = e;
      const dieEl = w.querySelector('.rp-die');
      dieEl.classList.remove('tumble');
      dieEl.querySelector('text').textContent = focus === 'damage' && e.damage ? e.damage.total : D20.includes(e.kind) ? e.main.kept : e.total;
      w.classList.toggle('nat20', e.nat === 20);
      w.classList.toggle('nat1', e.nat === 1);
      w.querySelector('.rp-body').innerHTML = resultHTML(e, focus);
      place(w, w._anchor);
      const first = w.querySelector('.rp-acts button');
      if (first) first.focus();
    });
  }
  function showFailure(w, text, retry) {
    w._ready.then(() => {
      if (!w.isConnected) return;
      w.querySelector('.rp-die').classList.remove('tumble');
      w.classList.add('failed');
      w.querySelector('.rp-body').innerHTML = '<div class="rp-res">' + esc(text) + '</div><div class="rp-acts"><button type="button" class="btn small" data-retry>Try again</button></div>';
      w.querySelector('[data-retry]').onclick = retry;
      place(w, w._anchor);
    });
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
    if (focus === 'bonus' && e.bonus) return [{ s: sidesOf(e.bonus.formula), v: e.bonus.dice[0], look: 'gold' }];
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
  // How the dice move and how long they stay in each place (mine, tray, vtt): Manage › Dice tuning, on every page as
  // body[data-dice-tuning] (app/dice.py); askdnd's own tuning if it's missing
  const TUNE = { mine: { strength: 1.4, gravity: 300, size: 95, shadows: true, light: 0.7, dim: 55, blur: 2, fade_in: 0.2, stay: 3.2, fade_out: 0.3 },
                 tray: { strength: 1, gravity: 400, size: 60, shadows: false, light: 0.7, slide: 0.3, stay: 2.6 },
                 vtt: { strength: 1.4, gravity: 300, size: 95, shadows: true, light: 0.7, dim: 35, blur: 0, fade_in: 0.2, stay: 3.2, fade_out: 0.3 } };
  const tuning = place => { let t = {}; try { t = JSON.parse(document.body.dataset.diceTuning || '{}'); } catch (e) { /* askdnd's own */ } return { ...TUNE[place], ...(t[place] || {}) }; };
  const sleep = s => new Promise(res => setTimeout(res, s * 1000));
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
    const side = Math.min(host.clientWidth || innerWidth, host.clientHeight || innerHeight);
    return Math.round(Math.min(1.8, Math.max(0.55, side / 900)) * 20) / 20;  // in steps of 5%, so a small resize doesn't rebuild
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
      throw: (list, dice, before, after, t, until) => (queue = queue.catch(() => {}).then(async () => { if (until && Date.now() > until) return; if (before) await before(); await go(list, dice, t); if (after) await after(); })) };
  }
  // The page-wide layer: dim, dice, who rolled (others' rolls), and the result card
  let throwEl = null, throwBox = null, throwTimer = null;
  function thrower() {
    if (throwEl) return throwBox;
    throwEl = document.createElement('div');
    throwEl.className = 'dice-throw';
    throwEl.setAttribute('aria-hidden', 'true');  // the roll window and Table rolls say the same in words
    throwEl.innerHTML = '<div class="dt-dim"></div><div class="dt-box"></div><div class="dt-who"></div><div class="dt-card"></div>';
    document.body.append(throwEl);
    throwBox = diceBox(throwEl.querySelector('.dt-box'), {}, tuning('mine'), true);
    return throwBox;
  }
  // The page-wide layer takes this throw's tuning: its fades and the backdrop behind the dice
  function throwTune(t) {
    throwEl._t = t;
    [['--dt-in', t.fade_in + 's'], ['--dt-out', t.fade_out + 's'], ['--dt-dim', t.dim + '%'], ['--dt-blur', t.blur + 'px']].forEach(([k, v]) => throwEl.style.setProperty(k, v));
  }
  function throwDone() { if (!throwEl) return; clearTimeout(throwTimer); throwEl.classList.remove('on', 'landed');
    throwTimer = setTimeout(() => { if (throwBox && !throwEl.classList.contains('on')) throwBox.clear(); }, ((throwEl._t || TUNE.mine).fade_out + 0.1) * 1000); }
  function throwCard(what, total, nat, sub) {
    throwEl.querySelector('.dt-card').innerHTML = '<span class="ds-what">' + esc(what) + '</span><b class="ds-total' + (nat === 20 ? ' nat20' : nat === 1 ? ' nat1' : '') + '">' + total + '</b>'
      + (sub ? '<span class="ds-what">' + esc(sub) + '</span>' : '');
    throwEl.classList.add('landed');
    clearTimeout(throwTimer);
    throwTimer = setTimeout(throwDone, (throwEl._t || TUNE.mine).stay * 1000);
  }
  function throwMine(e, focus) {
    const list = throwList(e, focus);
    if (!list.length) return Promise.resolve();
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
    const total = followUp ? li.querySelector('.roll-dmg-line b').textContent : (li.querySelector('.roll-total') || {}).textContent;
    const nat = followUp ? null : li.classList.contains('nat20') ? 20 : li.classList.contains('nat1') ? 1 : null;
    const dice = diceOf(li);
    const swatch = '<i class="sw-' + esc(dice.set || 'white') + '"></i>';
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
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)'), was = store.get('askdnd.rollsAnim');
    anim.checked = was ? was === 'on' : !calm.matches;
    anim.addEventListener('change', () => store.set('askdnd.rollsAnim', anim.checked ? 'on' : 'off'));
    form.addEventListener('change', ev2 => { if (ev2.target.name === 'set' || ev2.target.name === 'material') pickPreview(form); });
    pickPreview(form);
  });

  // ---------------------------------------------------------------- Dice tuning
  // Manage › askdnd › Dice tuning (manage_dice.html, app/dice.py): a tab per place dice are thrown, sliders that show
  // their value and mark changes against what's saved, and a preview that throws with the sliders as they are now.
  const tuneShow = (v, how) => how === 'toggle' ? (v ? 'on' : 'off') : how === 'x' ? v.toFixed(1) + '×' : how === 'pct' ? Math.round(v * 100) + '%'
    : (how === 's' || how === 'px') ? +v.toFixed(2) + ' ' + how : +v.toFixed(2) + how;
  const TUNE_ROLLS = { d20: { what: 'Dexterity save', list: [{ s: 20, v: 14 }], total: 17, nat: 'Natural 14' },
    adv: { what: 'Shillelagh to hit · Advantage', list: [{ s: 20, v: 19 }, { s: 20, v: 6 }], total: 26, nat: 'Natural 19' },
    fireball: { what: 'Fireball damage', list: [6, 2, 5, 4, 3, 6, 1, 5].map(v => ({ s: 6, v, type: 'fire' })), total: 32, nat: '' } };
  function tuner(root) {
    const form = root.querySelector('form'), stage = root.querySelector('.tn-stage'), layer = stage.querySelector('.tn-layer');
    const trayEl = stage.querySelector('.tn-tray'), read = root.querySelector('[data-read]');
    let place = 'mine', full = false, dirty = false;
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
      place = stage.dataset.stage = a.dataset.place;
      form.querySelectorAll('[data-place]').forEach(x => x.classList.toggle('on', x === a));
      form.querySelectorAll('[data-place-panel]').forEach(p => { p.hidden = p.dataset.placePanel !== place; });
      read.innerHTML = '<span>Press Throw to time it.</span>';
    }));
    // The preview: the same dice and steps as the real throws above, with the sliders' values
    const pageBox = diceBox(stage.querySelector('.tn-dice'), {}, values('mine'), true), trayBox = diceBox(stage.querySelector('#tn-dice-tray'), {}, values('tray'));
    const loading = stage.querySelector('.tn-loading');
    pageBox.ready.then(() => loading.remove(), () => { loading.textContent = "The dice couldn't load in this browser."; });
    const timed = (parts) => { read.innerHTML = parts.map(([w, s]) => '<span>' + w + ' <b>' + s.toFixed(1) + ' s</b></span>').join(''); };
    let t0 = 0;
    function throwPreview(key) {
      const r = TUNE_ROLLS[key], p = place, t = values(p), big = full, mine = diceOf(document.body);
      const dice = p === 'mine' ? mine : { set: 'starynight', material: 'glass', by_type: true };
      if (p === 'tray') {
        return trayBox.throw(r.list, dice, async () => {
          stage.classList.toggle('full', big);
          trayEl.querySelector('.dtr-foot').innerHTML = '<i class="sw-starynight"></i><span class="dtr-what"><b>Ilsa</b> · ' + esc(r.what) + '</span><b class="dtr-total">…</b>';
          trayEl.style.setProperty('--dtr-slide', t.slide + 's');
          trayEl.classList.add('up');
          await sleep(t.slide);
          t0 = performance.now();
        }, async () => {
          const settle = (performance.now() - t0) / 1000;
          trayEl.querySelector('.dtr-total').textContent = r.total;
          timed([['Dice settled in', settle], ['Total up for', t.stay], ['On screen in all', t.slide * 2 + settle + t.stay]]);
          await sleep(t.stay);
          trayEl.classList.remove('up');
          await sleep(t.slide + 0.05);
          trayBox.clear();
          stage.classList.remove('full');
        }, t);
      }
      return pageBox.throw(r.list, dice, () => {
        stage.classList.toggle('full', big);
        [['--dt-in', t.fade_in + 's'], ['--dt-out', t.fade_out + 's'], ['--dt-dim', t.dim + '%'], ['--dt-blur', t.blur + 'px']].forEach(([k, v]) => layer.style.setProperty(k, v));
        layer.querySelector('.tn-who span').textContent = r.what;
        layer.classList.remove('landed');
        layer.classList.add('on');
        t0 = performance.now();
      }, async () => {
        const settle = (performance.now() - t0) / 1000;
        layer.querySelector('.tn-card').innerHTML = '<span class="ds-what">' + (p === 'vtt' ? 'Ilsa · ' : '') + esc(r.what) + '</span><b class="ds-total">' + r.total + '</b>'
          + (r.nat ? '<span class="ds-what">' + r.nat + '</span>' : '');
        layer.classList.add('landed');
        timed([['Dice settled in', settle], ['Result up for', t.stay], ['On screen in all', t.fade_in + settle + t.stay + t.fade_out]]);
        await sleep(t.stay);
        layer.classList.remove('on', 'landed');
        await sleep(t.fade_out + 0.1);
        pageBox.clear();
        stage.classList.remove('full');
      }, t);
    }
    root.querySelectorAll('[data-throw]').forEach(b => b.addEventListener('click', () => throwPreview(b.dataset.throw).catch(() => {
      read.innerHTML = "<span>The dice couldn't be thrown in this browser.</span>"; stage.classList.remove('full'); })));
    const fullBtn = root.querySelector('[data-full]');
    fullBtn.addEventListener('click', () => { full = !full; fullBtn.setAttribute('aria-pressed', full); });
  }
  document.querySelectorAll('[data-dice-tuner]').forEach(tuner);

  // Click or a key anywhere: land now and clear the stage (the roll window keeps the result)
  ['pointerdown', 'keydown'].forEach(t => document.addEventListener(t, () => {
    if (stageEl) { const s = stageEl._skip; stageClear(); if (s) s(); }
    if (throwEl && throwEl.classList.contains('landed')) throwDone();  // thrown dice: once they've landed, a click clears them
  }, true));

  function payload(go) {
    const p = new URLSearchParams();
    if (go.follow) {
      p.set('parent', go.parent); p.set('action', go.follow);
      if (go.follow === 'reroll') p.set('label', go.reason);
      if (go.follow === 'bonus') { p.set('die', go.die); p.set('label', go.bonusLabel || 'Added die'); }
    } else {
      Object.entries({ character: go.cid || '', kind: go.kind, label: go.label, mod: go.mod || '', dmg: go.dmg || '', mode: go.mode, to,
                       count: go.count || 1, each: go.each || '', once: go.once ? 1 : '', who: go.who || '' }).forEach(([k, v]) => p.set(k, v));
      (go.parts || []).forEach(x => p.append('part', x));
      (go.dmgParts || []).forEach(x => p.append('dmg_part', x));
    }
    (go.extras || []).forEach(x => p.append('extra', x));
    return p;
  }
  function roll(w, go) {
    showRolling(w);
    w._go = go;
    if (!go.shared) {
      const before = go.follow ? go.entry._death : undefined;
      const e = go.follow ? privateFollow(go.entry, go.follow, { extras: go.extras, reason: go.reason, die: go.die, label: go.bonusLabel, ctx: go.ctx })
                          : privateRoll(go);
      if (!e) return showFailure(w, "Those dice don't look right.", () => chooser(w._anchor, go));
      if (e.kind === 'death' && go.follow !== 'damage') deathPrivate(go.cid, e, before);
      return showResult(w, e, go.follow);
    }
    const pending = !go.follow && logShown() && log ? placeholder(go.label) : null;
    fetch('/rolls', { method: 'POST', body: payload(go), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw Object.assign(new Error(j.error || "askdnd couldn't roll that"), { said: true }); return j; }))
      .then(j => {
        if (pending) pending.remove();
        if (animate()) window.askdndThrowing.throwing(j.roll.id);
        addToLog(j.html, j.roll.id);
        showResult(w, j.roll, go.follow);
        deathMarked(j.death);
        // A familiar's Initiative, rolled with its character's (app/initiative.py): its row too, and a word on it
        (j.also || []).forEach(a => { addToLog(a.html, a.roll.id); toast(a.who + "'s Initiative: " + a.roll.total, null, 'info'); });
        // Into D&D Beyond's Game Log too, as askdnd's (app/gamelog.py): the extension sends it from this player's sheet
        if (j.gamelog) window.postMessage({ askdndBridge: 'gamelog', ddbId: j.gamelog.ddbId, messages: j.gamelog.messages }, location.origin);
      })
      .catch(err => {
        if (pending) pending.remove();
        showFailure(w, (err.said ? err.message : "Couldn't reach askdnd") + ': not rolled.', () => roll(w, go));
      });
  }
  // A death save marks itself on the sheet (app/death_saves.py; Brett, 2026-10-29): a roll at the table is marked by
  // the server, which answers with what it marked; a private one says its result here. A reroll or an added die moves
  // the mark (`before`: what the roll counted as).
  function deathMarked(d) {
    if (!d) return;
    toast(d.text);
    document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: d.deliver }));
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
      .then(html => { if (win === w) { w.innerHTML = html; if (window.htmx) htmx.process(w); place(w, btn); w.querySelector('[autofocus]')?.focus(); } })
      .catch(() => { if (win === w) showFailure(w, "Couldn't reach askdnd.", () => openUse(btn)); });
  }
  function swapUse(w, url) {
    w._use = url;
    fetch(url, { headers: { 'X-Requested-With': 'fetch' } })
      .then(r => { if (!r.ok) throw new Error(); return r.text(); })
      .then(html => { if (win === w) { w.innerHTML = html; if (window.htmx) htmx.process(w); place(w); } })
      .catch(() => { if (win === w) showFailure(w, "Couldn't reach askdnd.", () => swapUse(w, url)); });
  }
  // The hit points window in it: its working redraws as you type, and taking it closes it
  document.body.addEventListener('htmx:afterSwap', e => { if (win && win.contains(e.target)) place(win); });
  document.body.addEventListener('closePanel', () => setTimeout(() => { if (win && win.querySelector('.hp-form')) closeWin(); }));  // (after the answer's other events: they start from the form)
  function posted(url, fields) {
    return fetch(url, { method: 'POST', body: new URLSearchParams(fields), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.detail || j.error || "askdnd couldn't do that"); return j; }));
  }
  function itemChanged(j) {
    document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: j.deliver }));
    document.body.dispatchEvent(new CustomEvent('characterChanged'));
  }
  function useItem(btn) {
    const w = win, said = w.querySelector('.use-said');
    w.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const chosen = Object.fromEntries([...w.querySelectorAll('select[name], input[name]')].filter(s => !/^(checkbox|radio)$/.test(s.type) || s.checked).map(s => [s.name, s.value]));
    posted(w._use, { ...chosen, to: btn.dataset.to || '' }).then(j => {
      // Cast and roll: the roll opens where the Cast window was, at the level just cast
      const roller = 'thenRoll' in btn.dataset && w.querySelector('.cast-roll');
      if (roller) {
        const level = w.querySelector('select[name=way]')?.selectedOptions[0]?.dataset.level;
        if (level) roller.dataset.slot = level;
        chooser(roller, specFrom(roller));
      } else closeWin();
      if (j.roll) {
        if (animate()) window.askdndThrowing.throwing(j.roll.id);
        addToLog(j.html, j.roll.id);
        if (j.gamelog) window.postMessage({ askdndBridge: 'gamelog', ddbId: j.gamelog.ddbId, messages: j.gamelog.messages }, location.origin);
      }
      toast(j.text, j.undo ? { label: 'Undo', run: () => posted(j.undoUrl, j.undo).then(u => { toast(u.text); itemChanged(u); }).catch(err => toast(err.message, null, 'warn')) } : null);
      itemChanged(j);
    }).catch(err => {
      w.querySelectorAll('button').forEach(b => { b.disabled = false; });
      said.textContent = err.message;
      said.hidden = false;
    });
  }
  // A follow-up from the result or the log: damage and an added die ask first; a reroll just rolls.
  function follow(anchor, action, e, shared, cid) {
    const base = { follow: action, parent: e.id, label: e.label, entry: e, shared, cid, kind: action === 'damage' ? 'damage' : e.kind };
    if (action === 'damage') chooser(anchor, { ...base, dmg: e.can.damage, crit: e.nat === 20 });
    else if (action === 'bonus') chooser(anchor, base);
    else { const w = win && win.contains(anchor) ? win : openWin(anchor); roll(w, { ...base, reason: e.can.reroll, ctx: ctxFor(cid), extras: [] }); }
  }
  // Which ability a roll uses, from its label ("Stealth", "Dex save", "Strength check"), for conditions
  const SKILL_ABILITY = { athletics: 'str', acrobatics: 'dex', 'sleight of hand': 'dex', stealth: 'dex', arcana: 'int', history: 'int',
    investigation: 'int', nature: 'int', religion: 'int', 'animal handling': 'wis', insight: 'wis', medicine: 'wis', perception: 'wis',
    survival: 'wis', deception: 'cha', intimidation: 'cha', performance: 'cha', persuasion: 'cha' };
  function abilityOf(label) {
    const l = (label || '').toLowerCase();
    const skill = Object.keys(SKILL_ABILITY).find(k => l.includes(k));
    if (skill) return SKILL_ABILITY[skill];
    const m = l.match(/\b(str|dex|con|int|wis|cha)/);
    return m ? m[1] : '';
  }
  function specFrom(el) {
    const cid = characterOf(el), kind = el.dataset.roll;
    const shared = atTable() && !!side && (kind === 'dice' || (!!cid && (side.dataset.yours || '').split(',').includes(String(cid))));
    let recipe = null;
    try { recipe = el.dataset.recipe ? JSON.parse(el.dataset.recipe) : null; } catch (err) { recipe = null; }
    // A condition the character has now (Invisible…) offers Advantage with its reason, never forces it:
    // the roll window shows the reason and the player (and DM) decide (app/conditions.adv_reasons).
    let advWhy = el.dataset.advWhy || '';
    // On a creature's Battle (Your creatures) the roll is the creature's: it says so, and its master's conditions don't apply
    const whoEl = el.closest('[data-who]'), who = whoEl ? whoEl.dataset.who : '';
    const body = cid && !who && document.querySelector('#battle-body[data-character="' + cid + '"]');
    if (body) {
      let ca = {};
      try { ca = JSON.parse(body.dataset.condAdv || '{}'); } catch (err) { ca = {}; }
      const label = el.dataset.label || '', ab = abilityOf(label);
      const keys = kind === 'attack' ? ['attack', 'd20']
        : kind === 'check' && /^initiative$/i.test(label) ? ['initiative', 'check', 'check:dex', 'd20']
        : kind === 'check' ? ['check', 'check:' + ab, 'd20']
        : kind === 'save' ? ['save:' + ab, 'd20'] : kind === 'death' ? ['d20'] : [];
      const lines = keys.flatMap(k => ca[k] || []).map(e => (e.mode === 'dis' ? '!dis ' : e.mode === 'note' ? '!note ' : '') + e.text);
      if (lines.length) advWhy = [advWhy, ...lines].filter(Boolean).join('\n');
    }
    return { kind, label: el.dataset.label || '', mod: el.dataset.mod || '', dmg: el.dataset.dmg || '', adv: !!el.dataset.adv, recipe, slot: +el.dataset.slot || 0,
             advWhy, note: el.dataset.note || '', cid: kind === 'dice' && side ? side.dataset.mine : cid, shared, who };
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
      const act = e.target.closest('[data-act]');
      if (act && win._entry) { const g = win._go || {}; follow(act, act.dataset.act, win._entry, g.shared, g.cid); return; }
      if (win._skip && win.classList.contains('result')) { win._skip(); }
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
    if (!el) { if (win && !e.target.closest('[data-manual]')) closeWin(); return; }
    e.preventDefault();
    const spec = specFrom(el);
    if (e.shiftKey) { const w = openWin(el); roll(w, { ...spec, mode: spec.adv ? 'adv' : 'normal', extras: [], ctx: ctxFor(spec.cid) }); }
    else chooser(el, spec);
  });
  // While the roll window is open, Enter rolls and Esc closes it (only it, not a side panel behind it), wherever focus
  // is: on an option just clicked (Advantage, a die, Just me), in its fields, on the roll button that opened it, or
  // nowhere (clicking its text leaves the page focused). Space still presses a focused option; Enter in a field
  // elsewhere on the page is left alone. Capture phase: before a focused button's own Enter.
  document.addEventListener('keydown', e => {
    if (!win || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeWin(); return; }
    const go = win.querySelector('[data-go]'), t = e.target, a = win._anchor;
    if (e.key !== 'Enter' || !go) return;
    if (!win.contains(t) && t !== document.body && t !== document.documentElement && !(a && a.contains && a.contains(t))) return;
    e.preventDefault(); e.stopImmediatePropagation(); go.click();
  }, true);
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('[data-roll][tabindex]');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
  });
  addEventListener('resize', () => { if (win) place(win, win._anchor); });
  document.addEventListener('scroll', e => { if (win && !win.contains(e.target)) place(win, win._anchor); }, true);

  // ---------------------------------------------------------------- the sidebar's Manual roll
  const manual = side && side.querySelector('[data-manual]');
  if (manual) {
    manual.innerHTML = pickerHTML({ extra: '<button type="button" class="btn primary small" data-manual-roll disabled>Roll</button>' });
    const go = manual.querySelector('[data-manual-roll]');
    let pick = null;
    pick = wirePicker(manual.querySelector('.dice-pick'), () => { go.disabled = !pick || !pick.dice(); });
    go.addEventListener('click', () => { if (pick.dice()) chooser(go, { kind: 'dice', label: '', dmg: pick.formula(), cid: side.dataset.mine, shared: atTable() }); });
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
      if (narrow() && current() === 'open' && e.target.isConnected && !side.contains(e.target) && !e.target.closest('[data-roll], .roll-win, .peek')) setState('closed');
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
  window.askdndRolls = {
    wanted: () => atTable() && !loaded,
    poll: () => atTable() && loaded && document.visibilityState === 'visible' && (!(window.askdndLive || {}).up || ++polls % 10 === 0),
    since: () => (loaded ? lastId : -1),  // -1: the whole recent log
  };
  document.addEventListener('askdnd:live', e => {
    if (e.detail.type === 'rolls' && atTable()) earlyThrow(e.detail.roll);
    if ((e.detail.type === 'rolls' || e.detail.type === 'resync') && atTable() && loaded && log && window.htmx) htmx.trigger(log, 'rolls:load');
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
    li.innerHTML = '<span class="roll-who"><b></b></span><span class="roll-what"></span><b class="roll-total"></b>' + (t.damage ? '<span class="roll-dmg-line"><b></b></span>' : '');
    li.querySelector('.roll-who b').textContent = t.name;
    li.querySelector('.roll-what').textContent = t.label + (t.kind === 'attack' ? ' to hit' : t.kind === 'damage' ? ' damage' : '');
    li.querySelector('.roll-total').textContent = t.total;
    if (t.damage) li.querySelector('.roll-dmg-line b').textContent = t.damage.total;
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
      if (n && current() === 'closed') toast(n + (n === 1 ? ' roll' : ' rolls') + ' while you were away', { label: 'Show', run: () => setState('open', !narrow()) }, 'info');
    }, 1200);
  });
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
        if (thrownEarly.delete(li.dataset.seq)) {}  // (its dice started from the live message)
        else if (away.on) away.rolls++;  // (they happened without you: no dice, no card)
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
      const dmgLine = li.querySelector('.roll-dmg-line b') && +li.dataset.seq !== +li.dataset.id;
      const v = d20 && kept && !dmgLine ? kept.textContent : (dmgLine ? li.querySelector('.roll-dmg-line b').textContent : total.textContent);
      d = gem(d20 && !dmgLine ? 20 : sidesOf(li.querySelector('.roll-dice') && li.querySelector('.roll-dice').textContent), v,
              (dmgLine || li.classList.contains('kind-damage') ? 'ruby' : li.classList.contains('kind-heal') ? 'jade' : 'gold')
              + (li.classList.contains('nat20') && !dmgLine ? ' crit' : li.classList.contains('nat1') && !dmgLine ? ' fumble' : ''), 'tiny');
      d.classList.add('card-ic');
      if (animate()) tumble(d, 150, 650); else { d.querySelector('.gem-n').textContent = v; d.classList.add('landed'); }
    }
    const what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const dmg = li.querySelector('.roll-dmg-line b');
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
    root._ls = { sel: s.sel || {}, sort: s.sort || '', lens: s.lens || '', more: !!s.more, q: '',
                 view: views.includes(kept) ? kept : views.includes('all') ? 'all' : (views[0] || '') };
    const sort = root.querySelector('[data-ls-sort]'); if (sort && root._ls.sort) sort.value = root._ls.sort;
    const lens = root.querySelector('[data-ls-lens]');
    if (lens && root._ls.lens && [...lens.options].some(o => o.value === root._ls.lens)) lens.value = root._ls.lens;
    const more = root.querySelector('[data-ls-more]'); if (more) more.open = root._ls.more;
  }
  function save(root) {
    const st = root._ls;
    try {
      localStorage.setItem(KEY(root), JSON.stringify({ at: Date.now(), sel: st.sel, sort: st.sort, lens: st.lens, more: st.more }));
      if (st.view) localStorage.setItem(VIEW(root), st.view);
    } catch (e) { /* private window */ }
  }
  function apply(root) {
    const st = root._ls, sel = st.sel, q = st.q.trim().toLowerCase();
    const rows = [...root.querySelectorAll('[data-ls-row]')];
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
    // The active-filter row: one chip per value with ×
    const active = root.querySelector('[data-ls-active]'), list = root.querySelector('[data-ls-active-chips]');
    const picked = on.flatMap(g => sel[g].map(v => [g, v]));
    if (list) list.replaceChildren(...picked.map(([g, v]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ls-chip on'; b.dataset.lsRemove = g + '\u0000' + v;
      b.setAttribute('aria-label', 'Remove filter ' + v); b.textContent = v + ' ×';
      return b;
    }));
    if (active) active.hidden = !picked.length || !!q;
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
    // highest first by the row's data-sort-<key> (Wild Shape: damage, hit, speed, cr)
    const by = k => r => +(r.dataset['sort' + k[0].toUpperCase() + k.slice(1)] || -1);
    const sorted = rows.slice().sort((a, b) => sort === 'name' ? name(a).localeCompare(name(b))
      : sort === 'level' ? (+a.dataset.level - +b.dataset.level) || name(a).localeCompare(name(b))
      : sort === 'default' ? by('default')(a) - by('default')(b)
      : (by(sort)(b) - by(sort)(a)) || name(a).localeCompare(name(b)));
    // Move rows only when the order or the headings change, and keep the scroll position: moving every
    // row on each press (a bookmark) made the page jump to the top.
    const scroller = root.closest('.peek-body'), y = window.scrollY, sy = scroller ? scroller.scrollTop : 0;
    const heads = new Map([...box.querySelectorAll('.ls-grouphead')].map(h => [h.textContent, h]));
    const want = [];
    let last = null;
    sorted.forEach(r => {
      if ((sort === 'level' || sort === 'default') && !r.hidden && r.dataset.groupLabel !== last) {
        last = r.dataset.groupLabel;
        let h = heads.get(last);
        if (h) heads.delete(last);
        else { h = document.createElement('div'); h.className = 'ls-grouphead'; h.textContent = last; }
        want.push(h);
      }
      want.push(r);
    });
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
    if (e.target.closest('[data-ls-clear]')) { st.sel = {}; clearSearch(); apply(root); return; }
    if (e.target.closest('[data-ls-clear-search]')) { clearSearch(); apply(root); if (search) search.focus(); return; }
    const view = e.target.closest('[data-ls-view]');
    if (view) { st.view = view.dataset.lsView; clearSearch(); apply(root); return; }
    const rm = e.target.closest('[data-ls-remove]');
    if (rm) { const [g, v] = rm.dataset.lsRemove.split('\u0000'); st.sel[g] = (st.sel[g] || []).filter(x => x !== v); apply(root); return; }
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
        set('[data-sb-dice]', a.dice + (a.per === 'healed' ? ' healed' : '') + (level && at > level ? ' · at ' + ORD(at) : ''));
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

// Story search (Brett, 2026-10-29): as you type, All sessions shows only the sessions whose recap, key moments or DM's
// notes hold every word, opened, with the words marked; clearing the box shows them all again, as they were
(function () {
  const box = document.querySelector('[data-story-search]');
  if (!box) return;
  const pane = document.getElementById('t-sessions'), found = pane.querySelector('[data-story-found]'), sub = pane.querySelector('[data-story-sub]');
  const sessions = [...pane.querySelectorAll('details.section')], wasOpen = new Map(sessions.map(d => [d, d.open]));
  const unmark = () => pane.querySelectorAll('mark.story-hit').forEach(m => { const p = m.parentNode; m.replaceWith(m.textContent); p.normalize(); });
  function mark(el, words) {
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), nodes = [];
    while (walk.nextNode()) if (walk.currentNode.nodeValue.trim() && !walk.currentNode.parentNode.closest('summary, form, .suggest')) nodes.push(walk.currentNode);
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
      sessions.forEach(d => { d.hidden = false; d.open = wasOpen.get(d); });
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
      if (hit) { n++; mark(d.querySelector('.session-body'), words); }
    });
    sub.hidden = true; found.hidden = false;
    found.textContent = n ? n + ' session' + (n === 1 ? '' : 's') + ' mention' + (n === 1 ? 's' : '') + ' “' + box.value.trim() + '”' : 'No session mentions “' + box.value.trim() + '”';
  }
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
  function mark() {
    const art = document.getElementById('reader-article'); if (!art) return;
    document.querySelectorAll('[data-rd-id]').forEach(n => n.classList.toggle('sel', n.dataset.rdId === art.dataset.readerId));
  }
  // Opening the page at an entry's address: show its name in the list
  { const sel = document.querySelector('.rd-item.sel'), nav = sel && sel.closest('.reader-nav');
    if (nav) nav.scrollTop = sel.offsetTop - nav.clientHeight / 3; }
  document.body.addEventListener('htmx:afterSwap', e => {
    if (!e.detail.target || e.detail.target.id !== 'reader-article') return;
    mark();
    const art = document.getElementById('reader-article');
    if (art && matchMedia('(max-width: 900px)').matches) art.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (!document.getElementById('reader') || document.querySelector('.peek.open')) return;
    const t = e.target;
    if (t.matches && t.matches('textarea, select, input:not([data-ls-search]), [contenteditable]')) return;
    if (document.getElementById('t-world').hidden) return;
    const items = [...document.querySelectorAll('.rd-item')].filter(n => !n.hidden);
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
  const visible = sel => [...document.querySelectorAll(sel)].find(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
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
    const box = document.createElement('div'); box.innerHTML = await res.text();
    const next = box.querySelector('#battle-body');
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
    const end = lit.getBoundingClientRect().bottom;
    return bars.reduce((m, el) => {
      if (lit.contains(el)) return m;
      const r = el.getBoundingClientRect();
      return r.top < end && r.top < innerHeight * 0.3 && r.bottom < innerHeight * 0.75 ? Math.max(m, r.bottom) : m;  // (a bar that fills over half a short window)
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
    for (const t0 = Date.now(); Date.now() - t0 < ms; await new Promise(r => setTimeout(r, 80))) { const el = visible(sel); if (el) return el; }
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
        for (let k = 0, x = NaN; panel && k < 25; k++) {  // (it can wait a frame or two before it starts to move)
          await new Promise(r => setTimeout(r, 60));
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
      + `<div class="tour-foot"><span class="count">${tour.i + 1} of ${n}</span>`
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
    card.querySelector('.tour-foot').innerHTML = '<span class="count"></span><button type="button" class="btn small" data-tour-resume>Keep going</button>'
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
// Manage › askdnd › D&D Beyond bridge (admins); players see how their own sheet is kept in step in the Live pill.
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
    });
    window.postMessage({ askdndBridge: 'ping' }, location.origin);
    setTimeout(() => {
      if (heard) return;
      document.body.classList.add('no-bridge');
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
    pill.addEventListener('click', async () => {  // run the round trip on the test character (Manage › askdnd › D&D Beyond bridge)
      pill.textContent = 'D&D Beyond · checking…';
      const r = await fetch('/bridge/check', { method: 'POST', headers: { Accept: 'application/json' } });
      if (r.ok) { window.postMessage({ askdndBridge: 'deliver', ddbId: (await r.json()).test_ddb_id }, location.origin); }
      else pill.textContent = 'D&D Beyond · open the test character\'s sheet to check';
      checkHealth();
    });
  }

  const all = document.querySelector('[data-br-check-all]');
  if (all) all.addEventListener('click', async () => {  // Manage › askdnd › D&D Beyond bridge: every kind of change, out and back
    all.disabled = true;
    const r = await fetch('/bridge/check?full=1', { method: 'POST', headers: { Accept: 'application/json' } });
    if (r.ok) window.postMessage({ askdndBridge: 'deliver', ddbId: (await r.json()).test_ddb_id }, location.origin);
    all.textContent = r.ok ? 'Checking: the menu bar shows how it goes' : 'Open the test character\'s sheet first';
    setTimeout(() => { all.disabled = false; all.textContent = 'Check everything'; }, 8000);
  });

  // Manage › Design system: its navigation row lights the section you're in and keeps that chip in view; ↑ Top goes back
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
(function () {
  let asked = false;
  function fill() {
    const src = document.querySelector('[data-manage-counts]');
    if (asked || !src) return;
    asked = true;
    fetch(src.dataset.manageCounts, { headers: { Accept: 'application/json' } }).then(r => (r.ok ? r.json() : {})).then(c => {
      document.querySelectorAll('[data-manage-count]').forEach(el => { const n = c[el.dataset.manageCount]; el.textContent = n || ''; el.hidden = !n; });
    }).catch(() => {});
  }
  if (document.querySelector('.manage-side')) fill();
  document.addEventListener('click', e => { if (e.target.closest('[data-menu="manage-menu"], [data-menu="admin-menu"]')) fill(); });
})();

// ---------------------------------------------------------------- Prepare spells
// (app/preparing.py, _prepare_spells.html; Brett, 2026-11-02, docs/mockups/prepare-spells/) A large modal like the Spell
// Book. Ticking a spell changes nothing yet: the count, the meter and the list of changes follow as you go, and Make
// sends them all at once. The count against the class's number is said, never enforced (going over is the DM's call).
(function () {
  function start(root) {
    if (root._prep) return;
    root._prep = true;
    const fold = root.querySelector('.prep-fold');  // (the filters fold into one line on narrower screens, as the Spell Book's)
    if (fold && matchMedia('(max-width: 900px)').matches) fold.open = false;
    const rows = [...root.querySelectorAll('[data-prep-row]')];
    const most = +root.dataset.max || 0;
    const filter = { show: 'all', level: '', effect: '' };
    const on = r => r.dataset.on === '1';
    const changed = () => rows.filter(r => !r.dataset.always && r.dataset.on !== r.dataset.base);
    const scope = root.closest('.peek') || root;  // (the count is in the window's head, frozen above the list)
    const $ = s => scope.querySelector(s);
    const ORD = n => n + ({ 1: 'st', 2: 'nd', 3: 'rd' }[n] || 'th');
    function draw() {
      const count = rows.filter(r => on(r) && !r.dataset.always).length, over = !!most && count > most;
      $('[data-prep-have]').textContent = count;
      $('[data-prep-have]').classList.toggle('over', over);
      if (most) $('[data-prep-left]').textContent = over ? `${count - most} over` : `${most - count} left`;
      const boxes = $('[data-prep-boxes]');
      if (boxes) {
        boxes.querySelectorAll('i').forEach((b, i) => b.classList.toggle('on', i < count));
        boxes.classList.toggle('over', over);
        boxes.setAttribute('aria-label', `${count} of ${most} prepared`);
        const extra = $('[data-prep-extra]');
        extra.hidden = !over;
        extra.textContent = over ? `+${count - most}` : '';
      }
      const warn = $('[data-prep-over]');
      if (warn) {
        warn.hidden = !over;
        warn.textContent = `${count} prepared: more than the ${most} a ${root.dataset.class} prepares at this level. D&D Beyond allows it; whether it stands is the DM's call.`;
      }
      const ch = changed();
      // Each change: + to prepare, − to drop, the spell and its level (Brett, 2026-11-02, the UI pass: no amber)
      $('[data-prep-changes]').replaceChildren(...ch.map(r => {
        const p = document.createElement('div');
        p.className = 'prep-change ' + (on(r) ? 'add' : 'drop');
        const k = document.createElement('span');
        k.className = 'prep-k'; k.textContent = on(r) ? '+' : '−';
        k.setAttribute('aria-label', on(r) ? 'prepare' : 'drop');
        const name = document.createElement('b');
        name.textContent = r.dataset.name;
        const what = document.createElement('small');
        what.textContent = ORD(+r.dataset.level);
        p.append(k, name, what);
        return p;
      }));
      $('[data-prep-none]').hidden = ch.length > 0;
      const adds = ch.filter(on).length, drops = ch.length - adds;
      $('[data-prep-note]').textContent = ch.length
        ? [adds && `prepare ${adds}`, drops && `drop ${drops}`].filter(Boolean).join(', ').replace(/^./, x => x.toUpperCase())
        : 'Nothing changes until you press Make';
      const make = $('[data-prep-make]');
      if (make) { make.disabled = !ch.length; make.textContent = ch.length ? `Make ${ch.length} change${ch.length === 1 ? '' : 's'} on D&D Beyond` : 'Make these changes'; }
      rows.forEach(r => {
        const moved = !r.dataset.always && r.dataset.on !== r.dataset.base;
        r.classList.toggle('changed', moved);
        r.classList.toggle('add', moved && on(r));
        r.classList.toggle('drop', moved && !on(r));
        const t = r.querySelector('[data-prep-tick]');
        if (t) t.setAttribute('aria-pressed', on(r) ? 'true' : 'false');
        r.hidden = !((filter.show === 'all' || (filter.show === 'on' ? on(r) : filter.show === 'off' ? !on(r) : r.dataset.fav === '1'))
          && (!filter.level || r.dataset.level === filter.level) && (!filter.effect || r.dataset.effect === filter.effect));
      });
      root.querySelectorAll('[data-prep-heading]').forEach(h => { h.hidden = !rows.some(r => !r.hidden && r.dataset.level === h.dataset.prepHeading); });
      $('[data-prep-empty]').hidden = rows.some(r => !r.hidden);
    }
    root.addEventListener('click', e => {
      const tick = e.target.closest('[data-prep-tick]');
      if (tick) { const r = tick.closest('[data-prep-row]'); r.dataset.on = on(r) ? '' : '1'; draw(); return; }
      const chip = e.target.closest('[data-prep-show], [data-prep-level], [data-prep-effect]');
      if (chip) {
        const key = 'prepShow' in chip.dataset ? 'show' : 'prepLevel' in chip.dataset ? 'level' : 'effect';
        const val = chip.dataset['prep' + key[0].toUpperCase() + key.slice(1)];
        filter[key] = key !== 'show' && filter[key] === val ? '' : val;
        chip.parentElement.querySelectorAll('.chip').forEach(x => x.classList.toggle('on', x === chip && (key === 'show' || filter[key] === val)));
        draw();
        return;
      }
      if (e.target.closest('[data-prep-reset]')) { rows.forEach(r => { r.dataset.on = r.dataset.base; }); draw(); return; }
      const make = e.target.closest('[data-prep-make]');
      if (make && !make.disabled) {
        const said = $('[data-prep-said]');
        make.disabled = true;
        fetch(root.dataset.url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
          body: JSON.stringify({ changes: changed().map(r => ({ key: r.dataset.key, on: on(r) })) }) })
          .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.detail || "askdnd couldn't do that"); return j; }))
          .then(j => {
            document.body.dispatchEvent(new CustomEvent('bridgeDeliver', { detail: j.deliver }));
            document.body.dispatchEvent(new CustomEvent('characterChanged'));
            window.askdndToast(j.text);
            window.askdndPanel(root.dataset.url, null, null, 'large');  // (again: each change shows ↻ until D&D Beyond has it)
          })
          .catch(err => { said.hidden = false; said.textContent = err.message; make.disabled = false; });
      }
    });
    draw();
  }
  document.addEventListener('panel:loaded', e => { const root = e.target.querySelector('[data-prep]'); if (root) start(root); });
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
        if (paying && paying.checked) body.pay = pay.value;
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

// ---------------------------------------------------------------- feedback for Claude
// (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/) A note for Claude from any page, for whoever the
// page lets send one (body[data-feedback]: admins and the accounts switched on for it on Accounts). \ opens it (never
// while typing), as do the account menu's item and More's (admins), and pressing and holding the askdnd logo (a phone,
// as a test account). The window opens at once; the page's picture is drawn just after (html-to-image, vendored; the
// window itself is left out of it), only what's on screen, one at a time, and sent with the note, where it was pointed at, a pasted or chosen screenshot, the page as drawn, and where, when
// and how the page was.
(function () {
  const win = document.getElementById('fb-win');
  if (!win || document.body.dataset.feedback === undefined) return;
  const form = win.querySelector('form'), said = win.querySelector('[data-fb-said]'), send = win.querySelector('[data-fb-send]');
  const shotImg = win.querySelector('[data-fb-shot]'), shotNote = win.querySelector('[data-fb-shot-note]');
  const pastedImg = win.querySelector('[data-fb-pasted]'), dropNote = win.querySelector('[data-fb-drop-note]'), pointedNote = win.querySelector('[data-fb-pointed]');
  let shot = null, pasted = null, html = '', pointed = null, ctx = {}, outlined = null, lib = null, taking = null, round = 0, why = '';
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
  async function picture() {  // what's on screen: the page drawn again as an image (the 3D dice and some fonts may differ)
    let h;
    try { h = await loadLib(); } catch (e) { why = "the picture's code didn't load"; return null; }
    // (fonts aren't embedded: Google's stylesheet can't be read from here, so the picture uses the browser's own font)
    const options = {
      quality: 0.8, pixelRatio: 1, width: innerWidth, height: innerHeight, skipFonts: true, imagePlaceholder: BLANK,
      backgroundColor: getComputedStyle(document.body).backgroundColor,
      // (scrolled by a margin, not a transform: a transform would carry what's fixed on screen, a modal like the item
      // browser, down the whole page's height and out of the picture)
      style: { margin: '0', marginTop: -scrollY + 'px', marginLeft: -scrollX + 'px' },
      // (not this window or the corner cards, and not Battle's condition edge: its border-image comes out as a wash over
      // the whole picture)
      // Only what's on screen: anything hidden or scrolled out of view is left out, so a long list (the item browser's
      // 1,289 rows) costs what its visible rows cost (Brett, Nov 3: it was slow, and froze the tab once)
      filter: n => !(n.id === 'fb-win' || n.id === 'cards' || (n.classList && n.classList.contains('cond-halo')) || n.hidden || offscreen(n)),
    };
    // An attribute named with a colon (htmx's hx-on::after-request) is fine in a page but not in the picture's SVG, where
    // it stops the whole drawing: they're set aside while it's drawn, and put back
    const aside = [], blanked = [];
    document.querySelectorAll('*').forEach(el => { for (const at of [...el.attributes]) if (at.name.includes(':')) { aside.push([el, at.name, at.value]); el.removeAttribute(at.name); } });
    // A picture the page couldn't load would stop the drawing, and one from another site (a D&D Beyond portrait, an
    // item's picture) can't be read from here: each is drawn blank at its own size, so what's around it stays in place
    // (left out, the item browser's details ran into each other)
    document.querySelectorAll('img').forEach(im => {
      if (im.complete && im.naturalWidth && im.src.startsWith(location.origin + '/')) return;
      const r = im.getBoundingClientRect();
      blanked.push([im, im.getAttribute('src'), im.getAttribute('srcset'), im.style.width, im.style.height]);
      Object.assign(im.style, { width: r.width + 'px', height: r.height + 'px' });
      im.removeAttribute('srcset'); im.src = BLANK;
    });
    // The 3D dice are drawn in WebGL, which keeps no copy of its last frame, so a copy of the page drew them blank
    // (feedback 7): each box on screen draws once more and is copied at once into a picture over its canvas
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
    try {
      // Drawn as an SVG first: a character XML can't hold (a NUL, another control character; another extension's text
      // carried one on Nov 4) stopped the whole picture, so they're taken out before it's painted
      const svg = (await h.toSvg(document.body, options)).replace(/%(?:0[0-8BbCcEeFf]|1[0-9A-Fa-f])/g, '');
      const im = new Image();
      await new Promise((ok, no) => { im.onload = ok; im.onerror = () => no(new Error("the page's drawing wouldn't load")); im.src = svg; });
      const c = Object.assign(document.createElement('canvas'), { width: innerWidth, height: innerHeight }), g = c.getContext('2d');
      g.fillStyle = options.backgroundColor; g.fillRect(0, 0, c.width, c.height); g.drawImage(im, 0, 0, c.width, c.height);
      return c.toDataURL('image/jpeg', 0.8);
    } catch (e) { why = (e && (e.message || e.type)) || 'unknown'; return null; } finally {
      stills.forEach(im => im.remove());
      aside.forEach(([el, name, value]) => el.setAttribute(name, value));
      blanked.forEach(([im, src, srcset, w, hgt]) => { if (srcset !== null) im.setAttribute('srcset', srcset); if (src !== null) im.setAttribute('src', src); else im.removeAttribute('src'); im.style.width = w; im.style.height = hgt; });
    }
  }
  function browser() {
    const ua = navigator.userAgent, d = navigator.userAgentData;
    const brands = d && d.brands ? d.brands.filter(b => !/Not.?A.?Brand/i.test(b.brand)) : [];  // (the made-up one every Chrome lists)
    const brand = brands.find(b => b.brand !== 'Chromium') || brands[0] || null;
    const safari = /Version\/([\d.]+).*Safari/.exec(ua), firefox = /Firefox\/([\d.]+)/.exec(ua);
    const name = brand ? brand.brand + ' ' + brand.version : safari ? 'Safari ' + safari[1] : firefox ? 'Firefox ' + firefox[1] : ua.slice(0, 60);
    const os = (d && d.platform) || (/iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Mac OS X/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : '');
    return name + (os ? ' on ' + os : '');
  }
  function gather() {
    const pill = document.getElementById('live-pill'), body = document.body;
    const tab = document.querySelector('main [role=tab][aria-selected=true], main .tabbar .on, main .sub-tabs .on, main .tabs .on');
    const panel = document.querySelector('.peek:not([hidden]) #peek-title');
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
  function unmark() { if (outlined) outlined.classList.remove('fb-pointed'); outlined = null; }
  async function open() {
    if (win.open) return;
    const mine = ++round;
    unmark(); pointed = null; pasted = null; shot = null;
    ctx = gather(); html = document.documentElement.outerHTML.slice(0, 3000000);
    form.reset(); say(''); send.disabled = false;
    shotImg.hidden = true; shotNote.hidden = false; shotNote.textContent = "Taking the page's picture…";
    pastedImg.hidden = true; dropNote.hidden = false; pointedNote.textContent = 'Click the thing you mean, if it helps';
    drawCtx();
    win.showModal();
    form.text.focus();
    // The picture once the window has shown (it's left out of the picture), and never two at once: pressing \ again
    // while one is drawn waits for that one
    await new Promise(r => { requestAnimationFrame(() => setTimeout(r, 0)); setTimeout(r, 100); });  // (a tab out of sight never paints)
    taking = taking || picture().finally(() => { taking = null; });
    const pic = await taking;
    if (mine !== round) return;  // (closed and opened again meanwhile: the newer window draws its own)
    shot = pic;
    if (!shot) ctx.picture = 'Not taken: ' + why;  // (so a note says why it came without one)
    if (shot) { shotImg.src = shot; shotImg.hidden = false; shotNote.hidden = true; } else shotNote.textContent = "No picture this time: paste one if it helps";
  }
  function describe(el) {
    const t = el.closest('[aria-label], [title], [data-tour], .nt, .ri, button, a, h1, h2, h3, label, li, td') || el;
    const words = (t.getAttribute('aria-label') || t.getAttribute('title') || t.textContent || '').trim().replace(/\s+/g, ' ');
    return words.slice(0, 60) || t.tagName.toLowerCase();
  }
  function where(el) {  // a short path to it, for finding it in the page's HTML
    const out = [];
    for (let n = el; n && n !== document.body && out.length < 6; n = n.parentElement) {
      out.unshift(n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.classList.length ? '.' + [...n.classList].slice(0, 2).join('.') : ''));
    }
    return out.join(' > ');
  }
  win.querySelector('[data-fb-point]').addEventListener('click', () => {
    win.close();
    document.body.classList.add('fb-pointing');
    const done = () => { document.removeEventListener('click', pick, true); document.removeEventListener('keydown', esc, true); document.body.classList.remove('fb-pointing'); win.showModal(); };
    const pick = e => {
      e.preventDefault(); e.stopPropagation();
      unmark();
      outlined = e.target; outlined.classList.add('fb-pointed');
      pointed = { label: describe(e.target), path: where(e.target), text: (e.target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 160) };
      pointedNote.textContent = 'Pointed at: ' + pointed.label;
      done();
    };
    const esc = e => { if (e.key === 'Escape') { e.preventDefault(); done(); } };
    setTimeout(() => { document.addEventListener('click', pick, true); document.addEventListener('keydown', esc, true); }, 0);
  });
  function take(file) {
    if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) return say('A picture as PNG, JPEG or WebP, please.');
    if (file.size > 8e6) return say('That picture is over 8 MB.');
    const r = new FileReader();
    r.onload = () => { pasted = r.result; pastedImg.src = pasted; pastedImg.hidden = false; dropNote.hidden = true; say(''); };
    r.readAsDataURL(file);
  }
  win.addEventListener('paste', e => {
    const f = [...((e.clipboardData && e.clipboardData.files) || [])].find(x => x.type.startsWith('image/'));
    if (f) { e.preventDefault(); take(f); }
  });
  const drop = win.querySelector('[data-fb-drop]');
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); take(e.dataTransfer.files[0]); });
  win.querySelector('[data-fb-file]').addEventListener('change', e => take(e.target.files[0]));
  win.querySelector('[data-fb-cancel]').addEventListener('click', () => { win.close(); unmark(); });
  win.addEventListener('cancel', unmark);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const text = form.text.value.trim();
    if (!text) return say("Say what it's about first.");
    send.disabled = true; say('');
    if (taking && !shot) { say("Finishing the page's picture…"); shot = await taking; say(''); }  // (Send pressed before it was drawn)
    try {
      const r = await fetch('/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ text, url: location.href, context: { ...ctx, pointed }, html, shot, pasted }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || "Couldn't send it: askdnd answered " + r.status + '.');
      win.close(); unmark();
      if (window.askdndToast) window.askdndToast('In the queue · ' + j.waiting + ' new');
    } catch (err) { send.disabled = false; say(err.message || "Couldn't send it."); }
  });
  // \ anywhere but a field; the menus' item; pressing and holding the logo
  document.addEventListener('keydown', e => {
    if (e.key !== '\\' || e.metaKey || e.ctrlKey || e.altKey || typing(document.activeElement) || document.querySelector('dialog[open]')) return;
    e.preventDefault(); open();
  });
  document.addEventListener('click', e => { if (e.target.closest('[data-fb-open]')) { e.preventDefault(); open(); } });
  const logo = document.querySelector('.brand');
  if (logo) {
    let held = null, fired = false;
    logo.addEventListener('touchstart', () => { fired = false; held = setTimeout(() => { fired = true; open(); }, 700); }, { passive: true });
    ['touchend', 'touchmove', 'touchcancel'].forEach(k => logo.addEventListener(k, () => clearTimeout(held), { passive: true }));
    logo.addEventListener('click', e => { if (fired) { e.preventDefault(); fired = false; } });
    logo.addEventListener('contextmenu', e => { if (fired) e.preventDefault(); });
  }
})();

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
