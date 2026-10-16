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
    // Menus (Manage, account, phone nav)
    const opener = e.target.closest('[data-menu]');
    document.querySelectorAll('.menu, .nav').forEach(m => {
      if (!opener || m.id !== opener.dataset.menu) {
        if (m.classList.contains('nav')) m.classList.remove('open'); else m.hidden = true;
      }
    });
    if (opener) {
      const m = document.getElementById(opener.dataset.menu);
      if (m.classList.contains('nav')) m.classList.toggle('open'); else m.hidden = !m.hidden;
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
    setTimeout(() => { peek.panel.hidden = true; }, 180);
    if (lastFocus) lastFocus.focus();
  }

  function openPeek(id, opener) { openPanel('/campaign/' + id + '/peek', opener, '/campaign/' + id); }

  // Any element with data-panel-url opens that fragment in the same side panel
  // (Battle: "See all", an option's details). data-modal-url opens a centered modal.
  function openPanel(url, opener, fallback, modal) {
    const { panel, backdrop } = peekPanel();
    lastFocus = opener;
    panel.classList.toggle('modal', !!modal);
    backdrop.classList.toggle('dim', !!modal);
    fetch(url, { headers: { 'HX-Request': 'true' } })
      .then(r => (r.ok ? r.text() : Promise.reject(r.status)))
      .then(html => {
        panel.innerHTML = html;
        panel.hidden = false;
        backdrop.hidden = false;
        void panel.offsetWidth; // let the browser place it off-screen first, then slide in
        panel.classList.add('open');
        panel.scrollTop = 0;
        if (window.htmx) htmx.process(panel);  // forms inside the panel (suggestions, edits)
        const close = panel.querySelector('.peek-close');
        if (close) { close.addEventListener('click', closePeek); close.focus(); }
      })
      .catch(() => { if (fallback) location.href = fallback; });
  }
  window.askdndPanel = openPanel;

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-panel-url], [data-modal-url]');
    if (!t || e.target.closest('button[hx-post], form')) return;
    e.preventDefault();
    if (t.dataset.modalUrl) openPanel(t.dataset.modalUrl, t, t.getAttribute('href'), true);
    else openPanel(t.dataset.panelUrl, t, t.getAttribute('href'));
  });
  document.addEventListener('keydown', e => {
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

  // Game Mode (Battle page): a switch per character, off unless this browser turned
  // it on. While on and the tab is visible, ask the server to sync with D&D Beyond
  // every couple of minutes (the server throttles per character) and swap in the
  // updated page body.
  let gmTimer = null;
  function gmKey(id) { return 'askdnd.gameMode.' + id; }
  function gmIsOn(id) { try { return localStorage.getItem(gmKey(id)) === 'on'; } catch (e) { return false; } }
  function gmSetup() {
    const sw = document.querySelector('[data-game-mode]');
    clearInterval(gmTimer); gmTimer = null;
    if (!sw) return;
    const id = sw.dataset.gameMode, on = gmIsOn(id), body = document.getElementById('battle-body');
    sw.setAttribute('aria-checked', on ? 'true' : 'false');
    const now = body && body.querySelector('.gm-now'); if (now) now.hidden = !on;
    const status = body && body.querySelector('.gm-status');
    if (on && status && !status.querySelector('.quiet-warn')) status.textContent = status.textContent.replace(/^Updated/, 'Game Mode on · synced');
    if (on && window.htmx) gmTimer = setInterval(() => {
      if (document.visibilityState === 'visible') htmx.ajax('POST', '/characters/' + id + '/sync', { target: '#battle-body', swap: 'outerHTML' });
    }, (Number(sw.dataset.every) || 150) * 1000);
  }
  document.addEventListener('click', e => {
    const sw = e.target.closest('[data-game-mode]');
    if (!sw) return;
    const id = sw.dataset.gameMode, on = !gmIsOn(id);
    try { localStorage.setItem(gmKey(id), on ? 'on' : 'off'); } catch (err) {}
    if (on && window.htmx) htmx.ajax('POST', '/characters/' + id + '/sync', { target: '#battle-body', swap: 'outerHTML' });
    gmSetup();
  });
  document.body.addEventListener('htmx:afterSettle', e => { if (e.target.id === 'battle-body' || e.detail.target?.id === 'battle-body') { gmSetup(); sortSetup(); } });
  gmSetup();

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
    if (label) label.textContent = shown + ' spell' + (shown === 1 ? '' : 's') + ' shown.';
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
  }, true);
  document.querySelectorAll('[data-planner]').forEach(plannerApply);

  // Flash message from a full page load
  const flash = document.body.dataset.toast;
  if (flash) toast(flash);
})();
