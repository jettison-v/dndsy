// askdnd: small page behaviors. Server-rendered pages; HTMX handles partial updates.
(function () {
  const $ = (s, el = document) => el.querySelector(s);

  function toast(message) {
    const t = $('#toast');
    if (!t || !message) return;
    t.textContent = message;
    t.classList.add('show');
    clearTimeout(t._hide);
    t._hide = setTimeout(() => t.classList.remove('show'), 2200);
  }
  window.askdndToast = toast;

  // Server can trigger a toast with the HX-Trigger header: {"toast": "Saved"}
  document.body.addEventListener('toast', e => toast(e.detail && e.detail.value));

  document.addEventListener('click', e => {
    // Menus (character switcher, Live, Manage, account, phone More). A click elsewhere closes
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

  // Peek panel: clicking a name (any link to /campaign/<id>) opens a summary in a
  // right-hand pane on desktop or a bottom sheet on phones. Cmd/Ctrl/Shift-click,
  // links marked data-no-peek and links in the panel's footer open the full page as usual.
  const ENTITY_URL = /^\/campaign\/((?:glossary\/)?\d+)$/;  // people/places, or glossary terms
  let peek = null, lastFocus = null;

  function peekPanel() {
    if (peek) return peek;
    const backdrop = document.createElement('div');
    backdrop.className = 'peek-backdrop';
    backdrop.hidden = true;
    const panel = document.createElement('aside');
    panel.className = 'peek';
    panel.id = 'peek';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'false');
    panel.setAttribute('aria-labelledby', 'peek-title');
    panel.hidden = true;
    backdrop.addEventListener('click', closePeek);
    document.body.append(backdrop, panel);
    peek = { panel, backdrop };
    return peek;
  }

  function closePeek() {
    if (!peek || peek.panel.hidden) return;
    peek.panel.classList.remove('open');
    peek.backdrop.hidden = true;
    panelHistory = [];
    setTimeout(() => { peek.panel.hidden = true; }, 180);
    if (lastFocus) lastFocus.focus();
  }

  function openPeek(id, opener) { openPanel('/campaign/' + id + '/peek', opener, '/campaign/' + id); }

  // Any element with data-panel-url opens that fragment in the same side panel
  // (Battle: "See all", an option's details). data-modal-url opens a centered modal;
  // add data-modal-size="large" for a wide one (a Wild Shape form).
  // Opening something from inside the panel (a row in "See all", a link in a short
  // character view) remembers what was there, so "← Back" can return to it.
  let panelHistory = [];
  function openPanel(url, opener, fallback, modal, back) {
    const { panel, backdrop } = peekPanel();
    const inside = panel.classList.contains('open') && opener && panel.contains(opener);
    if (back) { /* returning: the history entry was already taken off */ }
    else if (inside && panel.dataset.url) {
      const title = panel.querySelector('#peek-title');
      panelHistory.push({ url: panel.dataset.url, modal: panel.classList.contains('large') ? 'large' : panel.classList.contains('modal'), scroll: (panel.querySelector('.peek-body') || {}).scrollTop || 0,
                          title: title ? title.textContent.trim() : '' });
    } else panelHistory = [];
    if (!inside && !back) lastFocus = opener;
    panel.classList.toggle('modal', !!modal);
    panel.classList.toggle('large', modal === 'large');
    backdrop.classList.toggle('dim', !!modal);
    fetch(url, { headers: { 'HX-Request': 'true' } })
      .then(r => (r.ok ? r.text() : Promise.reject(r.status)))
      .then(html => {
        panel.innerHTML = html;
        panel.dataset.url = url;
        const prev = panelHistory[panelHistory.length - 1];
        if (prev) {
          const head = panel.querySelector('.peek-head > div');
          const b = document.createElement('button');
          b.type = 'button'; b.className = 'btn link peek-back';
          b.textContent = '← Back' + (prev.title ? ' to ' + prev.title : '');
          b.addEventListener('click', () => {
            const p = panelHistory.pop();
            openPanel(p.url, null, null, p.modal, p);
          });
          if (head) head.prepend(b);
        }
        panel.hidden = false;
        backdrop.hidden = false;
        void panel.offsetWidth; // let the browser place it off-screen first, then slide in
        panel.classList.add('open');
        panel.scrollTop = 0;
        const body = panel.querySelector('.peek-body');
        if (body) body.scrollTop = back ? back.scroll : 0;
        if (window.htmx) htmx.process(panel);  // forms inside the panel (suggestions, edits)
        const close = panel.querySelector('.peek-close');
        if (close) { close.addEventListener('click', closePeek); close.focus(); }
      })
      .catch(() => { if (fallback) location.href = fallback; });
  }
  window.askdndPanel = openPanel;

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-panel-url], [data-modal-url]');
    if (!t || e.target.closest('button[hx-post], form, [data-roll]')) return;
    e.preventDefault();
    if (t.dataset.modalUrl) openPanel(t.dataset.modalUrl, t, t.getAttribute('href'), t.dataset.modalSize === 'large' ? 'large' : true);
    else openPanel(t.dataset.panelUrl, t, t.getAttribute('href'));
  });
  document.addEventListener('keydown', e => {
    if (e.target.closest && e.target.closest('[data-roll]')) return;
    const t = e.target.closest && e.target.closest('[data-panel-url][tabindex], [data-modal-url][tabindex]');
    if (t && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); t.click(); }
  });

  // Tabs (Character page): buttons with data-tab show #id and hide their siblings' panels.
  document.addEventListener('click', e => {
    const b = e.target.closest('[role=tab][data-tab]');
    if (!b) return;
    const list = b.closest('[role=tablist]');
    list.querySelectorAll('[role=tab]').forEach(x => {
      x.setAttribute('aria-selected', x === b ? 'true' : 'false');
      const p = document.getElementById(x.dataset.tab); if (p) p.hidden = x !== b;
    });
    const panel = document.getElementById(b.dataset.tab);
    if (panel) panel.dispatchEvent(new CustomEvent('tab:shown', { bubbles: true }));
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
    openPeek(m[1], a);
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePeek(); });

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

  // Game Mode (the Live popover in the menu bar): one switch per browser, off unless this
  // browser turned it on. While on and the tab is visible, every couple of minutes: on Play,
  // ask the server to sync that character and swap in the updated body (the pill comes along
  // out of band); anywhere else, sync the character on screen (or your own) and swap the pill.
  // The server throttles per character, however many browsers ask.
  const GM = 'askdnd.gameMode';
  let gmTimer = null;
  function gmIsOn() {
    try {  // older versions kept one switch per character: any of those still counts
      return localStorage.getItem(GM) === 'on' || Object.keys(localStorage).some(k => k.startsWith(GM + '.') && localStorage.getItem(k) === 'on');
    } catch (e) { return false; }
  }
  function gmStore(on) {
    try {
      Object.keys(localStorage).filter(k => k.startsWith(GM + '.') || k.startsWith('askdnd.gameModeName.')).forEach(k => localStorage.removeItem(k));
      localStorage.setItem(GM, on ? 'on' : 'off');
    } catch (e) {}
  }
  function gmTick() {
    if (!window.htmx) return;
    const body = document.getElementById('battle-body'), pill = document.getElementById('live-pill');
    if (body) htmx.ajax('POST', '/characters/' + body.dataset.character + '/sync', { target: '#battle-body', swap: 'outerHTML' });
    else if (pill) htmx.ajax('POST', '/live/sync' + (pill.dataset.focus ? '?c=' + pill.dataset.focus : ''), { target: '#live-pill', swap: 'outerHTML' });
  }
  function gmSetup() {
    const on = gmIsOn(), pill = document.getElementById('live-pill');
    document.body.classList.toggle('gm-on', on);
    document.querySelectorAll('[data-game-mode]').forEach(sw => sw.setAttribute('aria-checked', on ? 'true' : 'false'));
    clearInterval(gmTimer); gmTimer = null;
    if (on && pill) gmTimer = setInterval(() => { if (document.visibilityState === 'visible') gmTick(); }, (Number(pill.dataset.every) || 150) * 1000);
    document.dispatchEvent(new CustomEvent('askdnd:gamemode', { detail: { on } }));  // Table rolls follow it
  }
  document.addEventListener('click', e => {
    const sw = e.target.closest('[data-game-mode]');
    if (!sw) return;
    const on = !gmIsOn();
    gmStore(on);
    gmSetup();
    if (on) gmTick();
    toast(on ? 'Game Mode on: updating from D&D Beyond every 2–3 minutes' : 'Game Mode off');
  });
  // After "Refresh now" or "Refresh everyone": show the new copy. Play swaps its body; other
  // pages showing that character (Sheet, Plan, Party) reload.
  document.body.addEventListener('liveRefreshed', e => {
    const ids = ((e.detail && e.detail.ids) || []).map(String), body = document.getElementById('battle-body');
    const page = document.querySelector('[data-character]');
    if (body && ids.includes(body.dataset.character)) htmx.ajax('POST', '/characters/' + body.dataset.character + '/sync', { target: '#battle-body', swap: 'outerHTML' });
    else if ((page && ids.includes(page.dataset.character)) || location.pathname === '/party') location.reload();
  });
  document.body.addEventListener('htmx:afterSettle', e => {
    const ids = [e.target.id, e.detail.target && e.detail.target.id];
    if (ids.includes('live-menu')) gmSetup();  // the popover's switch
    if (ids.includes('battle-body')) { sortSetup(); econSetup(); }
  });
  gmSetup();

  // Phones (Play): Action / Bonus / Reaction as tabs over the three columns. The choice is
  // kept while Game Mode swaps in a new body.
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
          fetch(list.dataset.sortUrl, { method: 'POST', body }).then(r => { if (!r.ok) toast("Couldn't save the order"); });
        },
      });
    });
  }
  window.addEventListener('load', sortSetup);

  // Star and Remind me buttons sit inside <summary>: don't open/close the row when pressed.
  document.addEventListener('click', e => { if (e.target.closest('summary .pick')) e.preventDefault(); }, true);

  // Spell planner (Character › Spells): a view (ready / shortlist / all), filters that
  // all have to match, and a search box. Rows carry data-* attributes from the server.
  function plannerApply(root) {
    const view = (root.querySelector('[data-view][aria-pressed=true]') || {}).dataset?.view || 'ready';
    const filters = [...root.querySelectorAll('[data-filter][aria-pressed=true]')].map(b => b.dataset.filter);
    const levels = filters.filter(f => f.startsWith('level:')).map(f => f.slice(6));
    const q = (root.querySelector('[data-search]')?.value || '').trim().toLowerCase();
    let shown = 0;
    root.querySelectorAll('.spell-row').forEach(r => {
      const d = r.dataset, tags = ' ' + d.tags + ' ';
      let ok = view === 'all' || (view === 'ready' ? d.state === 'ready' : d.fav === '1');
      if (levels.length && !levels.includes(d.level)) ok = false;
      for (const f of filters) {
        const [k, v] = f.split(':');
        if (k === 'cast' && d.cast !== v) ok = false;
        if (k === 'tag' && !tags.includes(' ' + v + ' ')) ok = false;
        if (k === 'notag' && tags.includes(' ' + v + ' ')) ok = false;
      }
      if (q && !d.name.includes(q)) ok = false;
      r.hidden = !ok;
      if (ok) shown++;
    });
    root.querySelectorAll('.planner-level, .planner-group').forEach(g => { g.hidden = !g.querySelector('.spell-row:not([hidden])'); });
    const label = root.querySelector('[data-shown]');
    const noun = root.dataset.noun || 'spell';
    if (label) label.textContent = shown + ' ' + noun + (shown === 1 ? '' : 's') + ' shown.';
    const empty = root.querySelector('.planner-empty'); if (empty) empty.hidden = shown > 0;
  }
  document.addEventListener('click', e => {
    const root = e.target.closest('[data-planner]');
    if (!root) return;
    const v = e.target.closest('[data-view]'), f = e.target.closest('[data-filter]');
    if (v) root.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', b === v ? 'true' : 'false'));
    if (f) f.setAttribute('aria-pressed', f.getAttribute('aria-pressed') === 'true' ? 'false' : 'true');
    if (v || f) plannerApply(root);
  });
  document.addEventListener('input', e => { const root = e.target.closest('[data-planner]'); if (root && e.target.matches('[data-search]')) plannerApply(root); });
  // A ♥ press updates the row's data so the Shortlist view is right without a reload.
  document.addEventListener('click', e => {
    const b = e.target.closest('.pick.fav:not(.static)'), row = b && b.closest('.spell-row');
    if (row) row.dataset.fav = b.classList.contains('on') ? '0' : '1';  // the server toggles it the same way
    // ♥ in the side panel: keep the matching row on the page in step
    if (b && b.closest('.pick-note')) {
      const on = !b.classList.contains('on'), ref = JSON.parse(b.getAttribute('hx-vals') || '{}').ref;
      document.querySelectorAll('.spell-row[data-ref]').forEach(r => {
        if (r.dataset.ref !== ref) return;
        r.dataset.fav = on ? '1' : '0';
        const h = r.querySelector('.pick.fav');
        if (h) { h.classList.toggle('on', on); h.textContent = on ? '♥' : '♡'; h.setAttribute('aria-pressed', on); }
      });
    }
  }, true);
  document.querySelectorAll('[data-planner]').forEach(plannerApply);
  // Manage › People: the line under each person says what their access will let them do, as you change it.
  document.addEventListener('change', e => {
    const form = e.target.closest('.person-form'); if (!form) return;
    const out = form.querySelector('.access-summary'); if (!out) return;
    const lvl = (form.querySelector('select[name=level]') || {}).value || 'admin';
    const dmBox = form.querySelector('input[type=checkbox][name=is_dm]'), dmHidden = form.querySelector('input[type=hidden][name=is_dm]');
    const dm = dmBox ? dmBox.checked : !!(dmHidden && dmHidden.value);
    out.textContent = JSON.parse(out.dataset.summaries)[lvl + '|' + (dm ? 1 : 0)] || '';
  });

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

  // Wild Shape cards: sort by what matters for choosing (damage, attack bonus, speed, CR).
  document.addEventListener('change', e => {
    const sel = e.target.closest('[data-card-sort]');
    if (!sel) return;
    const root = sel.closest('[data-planner]'), box = root && root.querySelector('[data-sortable-cards]');
    if (!box) return;
    const key = sel.value, attr = 'sort' + key[0].toUpperCase() + key.slice(1);
    const cards = [...box.children];
    cards.sort((a, b) => key === 'default' ? a.dataset.sortDefault - b.dataset.sortDefault
                                           : (parseFloat(b.dataset[attr]) || 0) - (parseFloat(a.dataset[attr]) || 0));
    cards.forEach(c => box.appendChild(c));
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
        if (!('on' in res)) return toast(res.error || 'Not saved');
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

  // A link like /campaign#glossary opens that tab (only on arrival; tabs don't change the address).
  if (location.hash) {
    const t = document.querySelector('[role=tab][data-tab="t-' + CSS.escape(location.hash.slice(1)) + '"]');
    if (t) t.click();
  }

  // Flash message from a full page load
  const flash = document.body.dataset.toast;
  if (flash) toast(flash);
})();


// Rolls. Anything with data-roll rolls when clicked: data-label names it, data-mod is the bonus,
// data-dmg the damage dice, data-adv="1" when Advantage always applies.
// - Game Mode on and it's your own character: the server rolls (app/table_rolls.py) and the
//   table sees it in the Table rolls sidebar (_table_rolls.html), or in a pop-up near the bottom
//   left when the sidebar isn't open. Others' rolls arrive by polling, as small notices then.
// - Otherwise: a private roll in this browser only (crypto random), kept in "Your rolls".
(function () {
  const KEY = 'askdnd.rolls', SIDE = 'askdnd.rollsSide.', ANIM = 'askdnd.rollsAnim', TO = 'askdnd.rollsTo';
  const WIDE = 1100;  // narrower than this, the sidebar collapses to its rail
  const phone = matchMedia('(max-width: 800px)'), calm = matchMedia('(prefers-reduced-motion: reduce)');
  const side = document.getElementById('table-rolls'), log = document.getElementById('roll-log');
  const pops = document.querySelector('.roll-pops');
  const store = {
    get: (k, s) => { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set: (k, v, s) => { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* private window */ } },
  };
  let mode = 'normal';  // the next d20 roll: normal, adv or dis (back to normal after rolling)
  let to = store.get(TO, true) || 'table';  // who sees your rolls; kept for this tab only, so it starts at Table
  let tray = null, lastId = 0, loaded = false, overlay = false, myPop = null;

  function die(sides) {
    const a = new Uint32Array(1);
    crypto.getRandomValues(a);
    return (a[0] % sides) + 1;
  }
  const num = s => parseInt(String(s || '0').replace('−', '-'), 10) || 0;
  const signed = n => (n >= 0 ? '+' : '−') + Math.abs(n);
  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  const gmOn = () => document.body.classList.contains('gm-on');
  const animate = () => !calm.matches && store.get(ANIM) !== 'off';
  const TO_WORDS = { table: 'to the table', dm: 'DM only', self: 'just you' };
  const MODE_WORDS = { normal: 'Normal', adv: 'Adv', dis: 'Dis' };
  const TO_SHORT = { table: 'Table', dm: 'DM', self: 'Me' };

  // ---------------------------------------------------------------- private rolls (this browser)
  function parseDice(expr) {
    const m = /(\d+)d(\d+)(?:([+-])(\d+))?/.exec(expr || '');
    if (!m) return null;
    return { count: +m[1], sides: +m[2], bonus: m[3] ? (m[3] === '-' ? -1 : 1) * +m[4] : 0 };
  }
  function history() {
    try { return JSON.parse(store.get(KEY) || '[]'); } catch (e) { return []; }
  }
  function remember(entry) {
    const list = [entry, ...history()].slice(0, 30);
    store.set(KEY, JSON.stringify(list));
    return list;
  }
  function who() {
    const b = document.getElementById('battle-body');
    return b ? b.dataset.name || '' : '';
  }
  function d20(el) {
    const mod = num(el.dataset.mod);
    const use = mode !== 'normal' ? mode : (el.dataset.adv ? 'adv' : 'normal');
    const dice = use === 'normal' ? [die(20)] : [die(20), die(20)];
    const kept = use === 'adv' ? Math.max(...dice) : use === 'dis' ? Math.min(...dice) : dice[0];
    const attack = el.dataset.roll === 'attack';
    return { kind: el.dataset.roll, label: el.dataset.label, who: who(), mode: use, dice, kept, mod, total: kept + mod,
             crit: attack && kept === 20, miss: attack && kept === 1, dmg: el.dataset.dmg || '', at: Date.now() };
  }
  function damage(label, expr, crit) {
    const d = parseDice(expr);
    if (!d) return null;
    const n = crit ? d.count * 2 : d.count;
    const dice = Array.from({ length: n }, () => die(d.sides));
    const total = dice.reduce((a, b) => a + b, 0) + d.bonus;
    return { kind: 'damage', label, who: who(), expr: (crit ? n + 'd' + d.sides + (d.bonus ? signed(d.bonus) : '') : expr),
             dice, mod: d.bonus, total: Math.max(total, 0), crit: !!crit, at: Date.now() };
  }
  // The same shape the server sends, so the pop-up shows both alike
  function asShared(r) {
    const nat = r.kind !== 'damage' && (r.kept === 20 || r.kept === 1) ? r.kept : null;
    return { label: r.label, kind: r.kind, total: r.total, dice: r.dice, kept: r.kept ?? null, modifier: r.mod, mode: r.mode || 'normal',
             formula: r.expr || '', crit: !!(r.kind === 'damage' && r.crit), nat, to: 'private',
             kept_at: r.dice.length > 1 ? r.dice.indexOf(r.kept) : -1, damage: r.kind === 'attack' && r.dmg && !r.miss ? r.dmg : '', local: r };
  }
  function line(r) {
    if (r.kind === 'damage') {
      return '<b>' + r.total + '</b> <span class="roll-sub">' + esc(r.expr) + ': ' + r.dice.join(' + ') + (r.mod ? ' ' + signed(r.mod) : '') + (r.crit ? ' · critical' : '') + '</span>';
    }
    const dice = r.dice.length > 1 ? r.dice.map(x => x === r.kept ? '<u>' + x + '</u>' : x).join(' / ') : String(r.dice[0]);
    const tag = r.mode === 'adv' ? ' · Advantage' : r.mode === 'dis' ? ' · Disadvantage' : '';
    const flag = r.crit ? ' · <span class="roll-crit">natural 20: critical hit</span>' : r.miss ? ' · <span class="roll-fumble">natural 1: miss</span>' : '';
    return '<b>' + r.total + '</b> <span class="roll-sub">d20 ' + dice + ' ' + signed(r.mod) + tag + flag + '</span>';
  }
  function renderTray(latest) {
    if (!tray) return;
    const list = history();
    const top = latest || list[0];
    tray.querySelector('.roll-last').innerHTML = top
      ? '<div class="roll-label">' + esc(top.label) + (top.kind === 'damage' ? ' · damage' : top.kind === 'attack' ? ' · to hit' : '') + '</div><div class="roll-result">' + line(top) + '</div>'
        + (top.kind === 'attack' && top.dmg ? '<button type="button" class="btn small roll-dmg-btn">Roll ' + (top.crit ? 'critical ' : '') + 'damage (' + esc(top.dmg) + ')</button>' : '')
      : '<div class="roll-sub">Click a save, Initiative or an attack bonus to roll. Only you see these rolls.</div>';
    const btn = tray.querySelector('.roll-dmg-btn');
    if (btn) btn.onclick = () => { const r = damage(top.label, top.dmg, top.crit); if (r) { remember(r); renderTray(r); } };
    tray.querySelector('.roll-history').innerHTML = list.slice(top ? 1 : 0, 9).map(r =>
      '<li><span>' + esc(r.label) + (r.kind === 'damage' ? ' dmg' : '') + '</span><b>' + r.total + '</b></li>').join('');
    renderModes();
  }
  // "Your rolls" shows while Game Mode is off on pages with roll buttons (with it on, rolls show
  // in the sidebar or a pop-up). It hides while a side panel or window is open, so it never
  // covers their buttons; rolls made in one show as a pop-up instead.
  function ensureTray() {
    if (!document.querySelector('[data-roll]') || gmOn()) { if (tray) tray.hidden = true; return; }
    if (!tray) {
      tray = document.createElement('aside');
      tray.className = 'roll-tray';
      tray.setAttribute('aria-label', 'Your dice rolls');
      tray.innerHTML = '<div class="roll-head" title="Private: only you see these rolls"><span class="roll-title">Your rolls</span>'
        + '<span class="roll-modes" role="group" aria-label="Next d20 roll">'
        + '<button type="button" data-mode="normal">Normal</button><button type="button" data-mode="adv">Adv</button><button type="button" data-mode="dis">Dis</button></span>'
        + '<button type="button" class="roll-fold" aria-label="Show or hide past rolls" title="Past rolls">▾</button></div>'
        + '<div class="roll-last" aria-live="polite"></div><ol class="roll-history"></ol>';
      document.body.appendChild(tray);
      tray.addEventListener('click', e => { if (e.target.closest('.roll-fold')) tray.classList.toggle('open'); });
      renderTray();
    }
    tray.hidden = false;
  }
  const panelOpen = () => document.querySelector('.peek.open');

  // ---------------------------------------------------------------- the sidebar's state
  // Desktop: "open" or "rail", remembered per device for Play and for everywhere else; below
  // WIDE it starts as the rail and opening it lays it over the page. Phones: a bottom sheet
  // ("open" shows the newest rolls, "rail" just its bar, "full" the whole log).
  const where = () => (side && side.dataset.play ? 'play' : 'other');
  function pref() { return store.get(SIDE + where()) || (where() === 'play' ? 'open' : 'rail'); }
  function setState(state, remember) {
    if (!side) return;
    const b = document.body.classList;
    b.toggle('rolls-on', gmOn());
    b.toggle('rolls-open', state === 'open' || state === 'full');
    b.toggle('rolls-rail', state === 'rail');
    b.toggle('rolls-full', state === 'full');
    b.toggle('rolls-over', overlay && state === 'open');
    side.querySelector('.rs-toggle').setAttribute('aria-expanded', state === 'rail' ? 'false' : 'true');
    if (remember && state !== 'full') store.set(SIDE + where(), state);
  }
  function current() { const b = document.body.classList; return b.contains('rolls-full') ? 'full' : b.contains('rolls-open') ? 'open' : 'rail'; }
  function layout() {
    overlay = false;
    setState(!phone.matches && innerWidth < WIDE ? 'rail' : pref());
  }
  // The log's first fetch: htmx's "load" trigger on a page that opens with Game Mode on, this
  // when it's turned on later.
  function loadLog() { if (gmOn() && !loaded && log && window.htmx) htmx.trigger(log, 'rolls:load'); }
  // Is the log on screen? (Then your roll shows there; otherwise a pop-up.)
  const logShown = () => gmOn() && side && (phone.matches ? current() === 'full' : current() === 'open');
  // Others' rolls are in view on a phone's sheet too, unless it's down to its bar.
  const othersShown = () => gmOn() && side && current() !== 'rail';

  if (side) {
    side.querySelector('.rs-toggle').addEventListener('click', e => {
      e.stopPropagation();
      const now = current();
      if (phone.matches) setState(now === 'rail' ? 'open' : 'rail', true);
      else if (innerWidth < WIDE) { overlay = now === 'rail'; setState(overlay ? 'open' : 'rail'); }
      else setState(now === 'rail' ? 'open' : 'rail', true);
    });
    // Phones: tap the sheet's bar to see every roll (or back), or swipe it up and down.
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
      if (dy < 0) setState(now === 'rail' ? 'open' : 'full', now === 'rail');
      else setState(now === 'full' ? 'open' : 'rail', now !== 'full');
    });
    // Clicking outside an over-the-page sidebar closes it
    document.addEventListener('click', e => {
      if (overlay && current() === 'open' && !side.contains(e.target) && !e.target.closest('[data-roll], .roll-pop')) { overlay = false; setState('rail'); }
    });
    let wasWide = innerWidth >= WIDE;
    addEventListener('resize', () => { const wide = innerWidth >= WIDE; if (wide !== wasWide) { wasWide = wide; layout(); } });
    phone.addEventListener('change', layout);
    document.addEventListener('askdnd:gamemode', () => { layout(); loadLog(); ensureTray(); });
    const anim = side.querySelector('[data-roll-anim]');
    anim.checked = store.get(ANIM) !== 'off';
    anim.addEventListener('change', () => store.set(ANIM, anim.checked ? 'on' : 'off'));
    layout();
  }

  // ---------------------------------------------------------------- Normal / Adv / Dis and who sees it
  function renderModes() {
    document.querySelectorAll('.roll-tray [data-mode], .rolls-side [data-mode]').forEach(b => b.setAttribute('aria-pressed', b.dataset.mode === mode ? 'true' : 'false'));
    document.querySelectorAll('.rolls-side [data-to]').forEach(b => b.setAttribute('aria-pressed', b.dataset.to === to ? 'true' : 'false'));
    if (!side) return;
    const m = side.querySelector('[data-cycle=mode]'), t = side.querySelector('[data-cycle=to]');
    m.textContent = MODE_WORDS[mode]; m.classList.toggle('on', mode !== 'normal');
    t.textContent = TO_SHORT[to]; t.classList.toggle('on', to !== 'table');
    m.setAttribute('aria-label', 'Next d20 roll: ' + MODE_WORDS[mode]);
    t.setAttribute('aria-label', 'Who sees your rolls: ' + TO_WORDS[to]);
  }
  document.addEventListener('click', e => {
    const m = e.target.closest('.roll-tray [data-mode], .rolls-side [data-mode]');
    const t = e.target.closest('.rolls-side [data-to]');
    const c = e.target.closest('.rolls-side [data-cycle]');
    if (m) mode = m.dataset.mode;
    else if (t) { to = t.dataset.to; store.set(TO, to, true); }
    else if (c && c.dataset.cycle === 'mode') mode = { normal: 'adv', adv: 'dis', dis: 'normal' }[mode];
    else if (c) { to = { table: 'dm', dm: 'self', self: 'table' }[to]; store.set(TO, to, true); }
    else return;
    renderModes();
  });
  renderModes();

  // ---------------------------------------------------------------- the log
  function ago(iso) {
    const s = Math.max((Date.now() - Date.parse(iso)) / 1000, 0);
    if (isNaN(s)) return '';
    return s < 10 ? 'now' : s < 60 ? Math.floor(s) + ' s' : s < 3600 ? Math.floor(s / 60) + ' min' : s < 86400 ? Math.floor(s / 3600) + ' h' : new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  function tidy() {
    if (!log) return;
    const seen = new Set();
    log.querySelectorAll('.roll-item[data-id]').forEach(li => { if (seen.has(li.dataset.id)) li.remove(); else seen.add(li.dataset.id); });
    if (log.querySelector('.roll-item')) log.querySelectorAll('.roll-empty').forEach(li => li.remove());
    [...log.querySelectorAll('.roll-item')].slice(50).forEach(li => li.remove());
    log.querySelectorAll('time[data-at]').forEach(t => { t.textContent = ago(t.dataset.at); });
  }
  window.askdndRolls = {
    wanted: () => gmOn() && !loaded,
    poll: () => gmOn() && loaded && document.visibilityState === 'visible',
    since: () => (loaded ? lastId : -1),  // -1: the whole recent log
  };
  // Only polled rows move `lastId` on: your own roll can land before someone else's earlier one.
  let before = 0;
  if (log) log.addEventListener('htmx:beforeSwap', e => {
    before = lastId;
    for (const m of (e.detail.serverResponse || '').matchAll(/data-id="(\d+)"/g)) lastId = Math.max(lastId, +m[1]);
  });
  if (log) log.addEventListener('htmx:afterSwap', () => {
    const first = !loaded;
    tidy();
    loaded = true;
    if (first) return;
    [...log.querySelectorAll('.roll-item[data-id]')].reverse().forEach(li => {
      if (+li.dataset.id > before && !li.dataset.mine) {
        if (!othersShown()) notice(li);
        li.classList.add('fresh');
      }
    });
  });

  // ---------------------------------------------------------------- pop-ups and notices
  const D20 = '<svg class="rp-die" viewBox="0 0 30 30" aria-hidden="true"><polygon points="15,2 27,9 27,21 15,28 3,21 3,9"/><text x="15" y="18.5" text-anchor="middle"></text></svg>';
  // Rolls made inside a window show in that window, above its buttons; otherwise near the bottom left.
  function popHost(pop) {
    const modal = document.querySelector('.peek.open.modal');
    if (modal) {
      const foot = modal.querySelector('.peek-foot');
      pop.style.bottom = ((foot ? foot.offsetHeight : 0) + 12) + 'px';
      modal.appendChild(pop);
    } else { pop.style.bottom = ''; pops.appendChild(pop); }
  }
  function closePop(pop) {
    if (!pop || !pop.isConnected) return;
    clearTimeout(pop._t);
    pop.classList.add('gone');
    setTimeout(() => pop.remove(), 200);
    if (myPop === pop) myPop = null;
  }
  function popStart(label) {
    closePop(myPop);
    const pop = document.createElement('div');
    pop.className = 'roll-pop';
    pop.setAttribute('role', 'status');
    pop.innerHTML = D20 + '<div class="rp-body"><div class="rp-label">' + esc(label) + '</div><div class="rp-res">Rolling…</div></div><button type="button" class="rp-x" aria-label="Close">×</button>';
    const spin = animate();
    if (spin) pop.querySelector('.rp-die').classList.add('tumble');
    pop.ready = new Promise(res => { pop._skip = res; setTimeout(res, spin ? 550 : 0); });
    pop.addEventListener('click', e => {
      if (e.target.closest('.rp-x')) return closePop(pop);
      pop._skip(); pop.querySelector('.rp-die').classList.remove('tumble');  // a click skips the tumble
    });
    pop.addEventListener('mouseenter', () => clearTimeout(pop._t));
    pop.addEventListener('mouseleave', () => { if (pop._done) pop._t = setTimeout(() => closePop(pop), 3000); });
    myPop = pop;
    popHost(pop);
    return pop;
  }
  function diceText(r) {
    if (r.kind === 'damage') return esc(r.formula) + ': ' + r.dice.join(' ') + (r.modifier ? ' ' + signed(r.modifier) : '');
    const dice = r.dice.map((d, i) => (i === r.kept_at ? '<u>' + d + '</u>' : d)).join(' / ');
    return 'd20 ' + dice + ' ' + signed(r.modifier) + (r.mode === 'adv' ? ' · Adv' : r.mode === 'dis' ? ' · Dis' : '');
  }
  function popResult(pop, r) {
    pop.ready.then(() => {
      if (!pop.isConnected) return;
      const die = pop.querySelector('.rp-die');
      die.classList.remove('tumble');
      die.querySelector('text').textContent = r.kind === 'damage' ? r.total : r.kept;
      pop.classList.toggle('nat20', r.nat === 20);
      pop.classList.toggle('nat1', r.nat === 1);
      const what = r.kind === 'attack' ? ' to hit' : r.kind === 'damage' ? (r.crit ? ' critical damage' : ' damage') : '';
      const whom = r.to === 'private' ? 'only in this browser' : TO_WORDS[r.to];
      const flag = r.nat === 20 ? 'Natural 20' + (r.kind === 'attack' ? ': critical hit' : '') : r.nat === 1 ? 'Natural 1' + (r.kind === 'attack' ? ': miss' : '') : '';
      pop.querySelector('.rp-label').innerHTML = esc(r.label) + what + ' · ' + whom;
      pop.querySelector('.rp-res').innerHTML = '<b>' + r.total + '</b> <span class="roll-sub">' + diceText(r) + '</span>' + (flag ? '<div class="rp-flag">' + flag + '</div>' : '');
      if (r.damage) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'btn small roll-dmg';
        b.textContent = 'Roll ' + (r.nat === 20 ? 'critical ' : '') + 'damage (' + r.damage + ')';
        if (r.id) b.dataset.after = r.id;
        else b.addEventListener('click', e => { e.stopPropagation(); const d = damage(r.label, r.damage, r.nat === 20); if (d) { remember(d); closePop(pop); popResult(popStart(d.label), asShared(d)); } });
        pop.querySelector('.rp-body').appendChild(b);
      }
      pop._done = true;
      pop._t = setTimeout(() => closePop(pop), r.damage ? 10000 : 6000);
    });
  }
  function popFail(pop, text) {
    pop.ready.then(() => {
      pop.querySelector('.rp-die').classList.remove('tumble');
      pop.classList.add('failed');
      pop.querySelector('.rp-res').textContent = text;
      pop._done = true;
    });
  }
  function notice(li) {
    if (!pops) return;
    const n = document.createElement('div');
    n.className = 'roll-note';
    n.setAttribute('role', 'status');
    const name = li.querySelector('.roll-who b').textContent, total = li.querySelector('.roll-total');
    const av = li.querySelector('.roll-av').cloneNode(true);
    av.className = 'roll-av ' + [...li.classList].filter(c => c.startsWith('hue')).join(' ');
    n.append(av);
    const what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const t = document.createElement('span');
    t.innerHTML = total ? '<b>' + esc(name) + '</b> rolled <b class="' + (li.classList.contains('nat20') ? 'nat20' : li.classList.contains('nat1') ? 'nat1' : '') + '">' + esc(total.textContent) + '</b> · ' + esc(what)
                        : '<b>' + esc(name) + '</b> rolled for the DM';
    n.append(t);
    pops.appendChild(n);
    const notes = pops.querySelectorAll('.roll-note');
    if (notes.length > 3) notes[0].remove();
    setTimeout(() => n.classList.add('gone'), 4000);
    setTimeout(() => n.remove(), 4400);
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && myPop) closePop(myPop); });

  // ---------------------------------------------------------------- rolling
  function characterOf(el) {
    const holder = el.closest('[data-character]');
    if (holder) return holder.dataset.character;
    const panel = el.closest('.peek');
    const m = panel && /^\/characters\/(\d+)/.exec(panel.dataset.url || '');
    return m ? m[1] : '';
  }
  function placeholder(label) {
    if (!log || !logShown()) return null;
    const li = document.createElement('li');
    li.className = 'roll-pending';
    li.textContent = label + ' · sending…';
    log.prepend(li);
    return li;
  }
  function send(data, label) {
    const pending = placeholder(label);
    const pop = logShown() ? null : popStart(label);
    fetch('/rolls', { method: 'POST', body: new URLSearchParams(data), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw Object.assign(new Error(j.error || "askdnd couldn't roll that"), { said: true }); return j; }))
      .then(j => {
        if (log) log.querySelectorAll('.roll-dmg').forEach(b => b.remove());  // damage follows only your newest roll
        if (pending) pending.outerHTML = j.html; else if (log) log.insertAdjacentHTML('afterbegin', j.html);
        tidy();
        const li = log && log.querySelector('.roll-item[data-id="' + j.roll.id + '"]');
        if (li) { li.classList.remove('fresh'); void li.offsetWidth; li.classList.add('fresh'); if (pop) li.querySelector('.roll-dmg')?.remove(); }
        if (pop) popResult(pop, j.roll);
      })
      .catch(err => {
        const text = (err.said ? err.message : "Couldn't reach askdnd") + ': not rolled.';
        if (pop) popFail(pop, text);
        if (pending) {
          pending.className = 'roll-pending failed';
          pending.textContent = label + ' · ' + text + ' ';
          const b = document.createElement('button');
          b.type = 'button'; b.className = 'btn small'; b.textContent = 'Try again';
          b.addEventListener('click', () => { pending.remove(); send(data, label); });
          pending.appendChild(b);
        }
      });
  }
  function rollPrivately(el) {
    const r = el.dataset.roll === 'damage' ? damage(el.dataset.label, el.dataset.dmg, false) : d20(el);
    if (!r) return;
    mode = 'normal';
    remember(r);
    ensureTray();
    if (tray && !tray.hidden && !panelOpen()) {
      renderTray(r);
      tray.classList.remove('bump'); void tray.offsetWidth; tray.classList.add('bump');
    } else {
      renderModes();
      popResult(popStart(r.label), asShared(r));
    }
  }

  document.addEventListener('click', e => {
    const dmg = e.target.closest('.roll-dmg[data-after]');
    if (dmg) {
      e.stopPropagation();
      const item = dmg.closest('.roll-item, .roll-pop');
      const label = (item.querySelector('.roll-what, .rp-label').textContent.split(' to hit')[0] || '').trim() + ' damage';
      document.querySelectorAll('.roll-dmg[data-after="' + dmg.dataset.after + '"]').forEach(b => b.remove());
      if (item.classList.contains('roll-pop')) closePop(item);
      send({ after: dmg.dataset.after }, label);
      return;
    }
    const el = e.target.closest('[data-roll]');
    if (!el || el.closest('.roll-tray')) return;
    e.preventDefault();
    const cid = characterOf(el);
    if (!(gmOn() && side && cid && side.dataset.mine === cid)) return rollPrivately(el);
    const data = { character: cid, kind: el.dataset.roll, label: el.dataset.label || '', mod: el.dataset.mod || '', dmg: el.dataset.dmg || '',
                   adv: el.dataset.adv || '', mode, to };
    mode = 'normal';
    renderModes();
    send(data, data.label + (data.kind === 'attack' ? ' to hit' : data.kind === 'damage' ? ' damage' : ''));
  });
  document.addEventListener('keydown', e => {
    const el = e.target.closest && e.target.closest('[data-roll][tabindex]');
    if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); el.click(); }
  });
  ensureTray();
  document.body.addEventListener('htmx:afterSwap', ensureTray);
})();
