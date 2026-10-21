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
  // Two layers: the base panel (a side panel, or a centered modal such as the Spell Book) and a
  // top side panel that slides in from the window edge over a modal (Brett, 2026-10-21: a spell's
  // details open beside the Spell Book, not inside it). Each layer keeps its own "← Back" history.
  const layers = {};
  let lastFocus = null;

  function peekPanel(name = 'base') {
    if (layers[name]) return layers[name];
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
    document.body.append(backdrop, panel);
    layers[name] = layer;
    return layer;
  }
  const isOpen = l => l && !l.panel.hidden && l.panel.classList.contains('open');

  function closeLayer(layer) {
    if (!layer || layer.panel.hidden) return;
    if (layer.name === 'base') closeLayer(layers.top);
    layer.panel.classList.remove('open');
    layer.backdrop.hidden = true;
    layer.history = [];
    setTimeout(() => { if (!layer.panel.classList.contains('open')) layer.panel.hidden = true; }, 180);
    const f = layer.name === 'top' ? layer.focus : lastFocus;
    if (f && f.isConnected) f.focus();
  }
  // Escape and "close" take off the topmost layer first.
  function closePeek() { if (isOpen(layers.top)) closeLayer(layers.top); else closeLayer(layers.base); }

  function openPeek(id, opener) { openPanel('/campaign/' + id + '/peek', opener, '/campaign/' + id); }

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
    if (layer.name === 'base' && !back) closeLayer(layers.top);
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
        const prev = layer.history[layer.history.length - 1];
        if (prev) {
          const head = panel.querySelector('.peek-head > div');
          const b = document.createElement('button');
          b.type = 'button'; b.className = 'btn link peek-back';
          b.textContent = '← Back' + (prev.title ? ' to ' + prev.title : '');
          b.addEventListener('click', () => {
            const p = layer.history.pop();
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
        if (close) { close.addEventListener('click', () => closeLayer(layer)); close.focus(); }
        panel.dispatchEvent(new CustomEvent('panel:loaded', { bubbles: true }));
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
  // browser turned it on. While on and the tab is visible, every couple of minutes: on Battle,
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
  // After "Refresh now" or "Refresh everyone": show the new copy. Battle swaps its body; other
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

  // Phones (Battle): Action / Bonus / Reaction as tabs over the three columns. The choice is
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
  // A bookmark or pin press keeps the rows on the page in step without a reload, the way the
  // server does it: the bookmark toggles the Shortlist, and pinning also shortlists.
  document.addEventListener('click', e => {
    const b = e.target.closest('.pick.fav:not(.static), .pick.star:not(.static)'); if (!b) return;
    const pressing = !b.classList.contains('on'), pin = b.classList.contains('star');
    if (pin && !pressing) return;  // unpinning leaves the Shortlist alone
    const fav = pin ? true : pressing, ref = JSON.parse(b.getAttribute('hx-vals') || '{}').ref;
    document.querySelectorAll('.spell-row[data-ref]').forEach(r => {
      if (r.dataset.ref !== ref) return;
      r.dataset.fav = fav ? '1' : '0';
      const h = r.querySelector('.pick.fav:not(.static)');
      if (h && h !== b) { h.classList.toggle('on', fav); h.setAttribute('aria-pressed', fav); }
    });
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


// Rolls. Anything with data-roll opens the roll window next to it: data-roll is the kind (save,
// check, attack, death, damage, heal, dice), data-label names it, data-mod is the bonus, data-dmg
// the dice, data-adv="1" when Advantage always applies, data-adv-why the reasons, data-note a line
// to show. The window offers Normal / Adv / Dis, who sees it and situational bonuses, then turns
// into the result in place (with a short d20 tumble), with the follow-ups: damage after an attack,
// a reroll, an added die. Shift-click rolls straight away.
// - Game Mode on and it's your own character (or plain dice): the server rolls (app/table_rolls.py)
//   and the table sees it in the Table rolls sidebar; others' rolls arrive by polling, and as
//   small notices while the sidebar is collapsed.
// - Otherwise: a private roll in this browser only (crypto random).
(function () {
  const SIDE = 'askdnd.rollsSide.', ANIM = 'askdnd.rollsAnim', TO = 'askdnd.rollsTo';
  const WIDE = 1100;  // narrower than this, the sidebar collapses to its rail
  const D20 = ['save', 'check', 'attack', 'death'];
  const phone = matchMedia('(max-width: 800px)'), calm = matchMedia('(prefers-reduced-motion: reduce)');
  const side = document.getElementById('table-rolls'), log = document.getElementById('roll-log');
  const pops = document.querySelector('.roll-pops');
  const store = {
    get: (k, s) => { try { return (s ? sessionStorage : localStorage).getItem(k); } catch (e) { return null; } },
    set: (k, v, s) => { try { (s ? sessionStorage : localStorage).setItem(k, v); } catch (e) { /* private window */ } },
  };
  const QUIET = 3 * 60 * 1000;  // the collapsed rail slides away after this long with no rolls
  const people = side && side.querySelector('.rs-people'), edge = document.querySelector('.rs-edge');
  let lastActivity = 0, tipEl = null;
  let to = store.get(TO, true) || 'table';  // who sees your rolls; kept for this tab only, so it starts at Table
  let lastId = 0, loaded = false, overlay = false, win = null;

  const num = s => parseInt(String(s || '0').replace('−', '-'), 10) || 0;
  const signed = n => (n >= 0 ? '+' : '−') + Math.abs(n);
  function esc(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }
  const gmOn = () => document.body.classList.contains('gm-on');
  // The animation switch: on or off as chosen on this device; until then, off only if the device asks for less motion
  const animate = () => { const v = store.get(ANIM); return v ? v === 'on' : !calm.matches; };
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
    if (pos !== s.length || !terms.length || terms.reduce((a, t) => a + t[0], 0) > 40) return null;
    return { terms, flat };
  }
  const formulaText = (terms, flat) => terms.map(t => t[0] + 'd' + t[1]).join('+') + (flat ? signed(flat).replace('−', '-') : '');
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
    const many = ev.count > 1 ? ev.count + ' ' + (ev.count_label || 'time') + 's × ' : '';
    const how = ev.on === 'save' ? (ev.save ? ev.save + ' save' : 'save') + (ev.success ? ', ' + SUCCESS[ev.success] : '') : ev.on === 'hit' ? 'on a hit' : '';
    const shown = ev.parts.map(p => { const x = parsePart(p); return x && !x.n ? Math.abs(x.flat) + (x.kind ? ' (' + x.kind + ')' : '') : p; });
    const text = ev.parts.map((p, i) => { const x = parsePart(p); return (i ? (x && !x.n && x.flat < 0 ? ' \u2212 ' : ' + ') : '') + shown[i]; }).join('');
    return many + text + (ev.mod ? ' + spellcasting modifier' : '') + (how && ev.on !== 'hit' ? ' · ' + how : '');
  }

  // Each part, once per instance (3 darts), each on its own line; a critical instance doubles its dice
  function rollParts(parts, crits, each, floor) {
    const lines = [];
    crits.forEach((crit, i) => parts.forEach(pt => {
      const p = parsePart(pt), k = crit ? p.n * 2 : p.n, dice = Array.from({ length: k }, () => die(p.s));
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
      main = spec.parts && spec.parts.length ? rollParts(spec.parts, Array(spec.count || 1).fill(false), spec.each, spec.kind !== 'dice')
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
      e.bonus = { label: opts.label || 'Bardic Inspiration', formula: '1d' + opts.die, dice: [n], total: n };
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
    win.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.target.matches('button')) { e.preventDefault(); const go = win.querySelector('[data-go]'); if (go) go.click(); }
    });
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
      (spec.advWhy || '').split('\n').filter(Boolean).forEach(t => notes.push(/^advantage\b/i.test(t) ? '<b>Advantage</b>' + esc(t.slice(9)) : '<b>Advantage</b> ' + esc(t)));
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
      if (rec.checked === 'D&D Beyond') h += '<p class="rw-note">From D&amp;D Beyond\'s data: not checked against the rules text (askdnd\'s audit only covers the 2024 rules).</p>';
    }
    let other = '';
    if (spec.follow === 'bonus') {
      h += '<div class="rw-row"><span class="rw-label">Die</span>' + seg('Die', [[4, 'd4'], [6, 'd6'], [8, 'd8'], [10, 'd10'], [12, 'd12']], 6) + '</div>'
        + '<div class="rw-row"><span class="rw-label">From</span><input type="text" class="rw-text" data-bonus-label value="Bardic Inspiration" maxlength="40"></div>'
        + '<p class="rw-note">Bardic Inspiration adds its die after you see a d20 roll fail.</p>';
    } else if (spec.kind === 'dice') {
      h += '<div class="rw-row"><span class="rw-label">For</span><input type="text" class="rw-text" data-for placeholder="What the DM asked for (optional)" maxlength="60"></div>';
    } else if (spec.follow !== 'reroll') {
      h += '<details class="rw-add"><summary>Add dice or a bonus</summary>' + pickerHTML({ minus: true }) + '</details>';
    }
    if (spec.shared && !spec.follow) h += '<div class="rw-row"><span class="rw-label">Who sees</span>' + seg('To', [['table', 'Table'], ['dm', 'DM only'], ['self', 'Just me']], to) + '</div>';
    else if (!spec.shared) h += '<p class="rw-note">' + (gmOn() ? 'You don\'t play this character, so only you see this roll.' : 'Only you see this roll (Game Mode is off).') + '</p>';
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
      if (b.dataset.to) { to = b.dataset.to; store.set(TO, to, true); w.querySelectorAll('[data-to]').forEach(x => x.setAttribute('aria-pressed', x === b)); }
      if (b.dataset.die) w.querySelectorAll('[data-die]').forEach(x => x.setAttribute('aria-pressed', x === b));
      if (b.dataset.extra) b.setAttribute('aria-pressed', b.getAttribute('aria-pressed') !== 'true');
      if (b.dataset.ev) { evi = +b.dataset.ev; w.querySelectorAll('[data-ev]').forEach(x => x.setAttribute('aria-pressed', x === b)); summarize(); }
      if (b.hasAttribute('data-go')) {
        const extras = pick ? pick.extras('Bonus') : [];
        const forText = ((w.querySelector('[data-for]') || {}).value || '').trim();
        const ev = rec ? current() : null;
        if (rec && !ev) return;
        const fromRecipe = ev ? (spec.kind === 'attack' ? { dmgParts: ev.parts, count: ev.count, each: ev.count_label || '' }
          : { kind: kindOf(evs[evi]), parts: ev.parts, count: ev.count, each: ev.count_label || '', label: spec.label + (evs.length > 1 ? ' · ' + evs[evi].name : '') }) : {};
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
    const spin = animate();
    if (spin) w.querySelector('.rp-die').classList.add('tumble');
    w._ready = new Promise(res => { w._skip = res; setTimeout(res, spin ? 550 : 0); });
    place(w, w._anchor);
  }
  function showResult(w, e, focus) {
    w._ready.then(() => {
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
  function payload(go) {
    const p = new URLSearchParams();
    if (go.follow) {
      p.set('parent', go.parent); p.set('action', go.follow);
      if (go.follow === 'reroll') p.set('label', go.reason);
      if (go.follow === 'bonus') { p.set('die', go.die); p.set('label', go.bonusLabel || 'Bardic Inspiration'); }
    } else {
      Object.entries({ character: go.cid || '', kind: go.kind, label: go.label, mod: go.mod || '', dmg: go.dmg || '', mode: go.mode, to,
                       count: go.count || 1, each: go.each || '' }).forEach(([k, v]) => p.set(k, v));
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
      const e = go.follow ? privateFollow(go.entry, go.follow, { extras: go.extras, reason: go.reason, die: go.die, label: go.bonusLabel, ctx: go.ctx })
                          : privateRoll(go);
      if (!e) return showFailure(w, "Those dice don't look right.", () => chooser(w._anchor, go));
      return showResult(w, e, go.follow);
    }
    const pending = !go.follow && logShown() && log ? placeholder(go.label) : null;
    fetch('/rolls', { method: 'POST', body: payload(go), headers: { 'X-Requested-With': 'fetch' } })
      .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw Object.assign(new Error(j.error || "askdnd couldn't roll that"), { said: true }); return j; }))
      .then(j => {
        if (pending) pending.remove();
        addToLog(j.html, j.roll.id);
        showResult(w, j.roll, go.follow);
      })
      .catch(err => {
        if (pending) pending.remove();
        showFailure(w, (err.said ? err.message : "Couldn't reach askdnd") + ': not rolled.', () => roll(w, go));
      });
  }
  // A follow-up from the result or the log: damage and an added die ask first; a reroll just rolls.
  function follow(anchor, action, e, shared, cid) {
    const base = { follow: action, parent: e.id, label: e.label, entry: e, shared, cid, kind: action === 'damage' ? 'damage' : e.kind };
    if (action === 'damage') chooser(anchor, { ...base, dmg: e.can.damage, crit: e.nat === 20 });
    else if (action === 'bonus') chooser(anchor, base);
    else { const w = win && win.contains(anchor) ? win : openWin(anchor); roll(w, { ...base, reason: e.can.reroll, ctx: ctxFor(cid), extras: [] }); }
  }
  function specFrom(el) {
    const cid = characterOf(el), kind = el.dataset.roll;
    const shared = gmOn() && !!side && (kind === 'dice' || (!!cid && side.dataset.mine === cid));
    let recipe = null;
    try { recipe = el.dataset.recipe ? JSON.parse(el.dataset.recipe) : null; } catch (err) { recipe = null; }
    return { kind, label: el.dataset.label || '', mod: el.dataset.mod || '', dmg: el.dataset.dmg || '', adv: !!el.dataset.adv, recipe, slot: +el.dataset.slot || 0,
             advWhy: el.dataset.advWhy || '', note: el.dataset.note || '', cid: kind === 'dice' && side ? side.dataset.mine : cid, shared };
  }

  document.addEventListener('click', e => {
    if (!e.target.isConnected) return;  // the window replaced what was clicked (Roll, a follow-up): not a click outside
    if (win && win.contains(e.target)) {
      if (e.target.closest('.rp-x')) { closeWin(); return; }
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
    const el = e.target.closest('[data-roll]');
    if (!el) { if (win && !e.target.closest('[data-manual]')) closeWin(); return; }
    e.preventDefault();
    const spec = specFrom(el);
    if (e.shiftKey) { const w = openWin(el); roll(w, { ...spec, mode: spec.adv ? 'adv' : 'normal', extras: [], ctx: ctxFor(spec.cid) }); }
    else chooser(el, spec);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && win) { closeWin(); return; }
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
    go.addEventListener('click', () => { if (pick.dice()) chooser(go, { kind: 'dice', label: '', dmg: pick.formula(), cid: side.dataset.mine, shared: gmOn() }); });
  }

  // ---------------------------------------------------------------- the sidebar's state
  // Desktop: "open" or "rail", remembered per device for Battle and for everywhere else; below
  // WIDE it starts as the rail and opening it lays it over the page. Phones: a bottom sheet
  // ("open" shows the newest rolls, "rail" just its bar, "full" the whole log and the dice).
  const where = () => (side && side.dataset.battle ? 'play' : 'other');  // 'play': the stored key from before the rename
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
    quietCheck();
  }
  function current() { const b = document.body.classList; return b.contains('rolls-full') ? 'full' : b.contains('rolls-open') ? 'open' : 'rail'; }
  function layout() { overlay = false; setState(!phone.matches && innerWidth < WIDE ? 'rail' : pref()); }
  // The log's first fetch: htmx's "load" trigger on a page that opens with Game Mode on, this
  // when it's turned on later.
  function loadLog() { if (gmOn() && !loaded && log && window.htmx) htmx.trigger(log, 'rolls:load'); }
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
      if (dy < 0) setState(now === 'rail' ? 'open' : 'full', now === 'rail');
      else setState(now === 'full' ? 'open' : 'rail', now !== 'full');
    });
    // Clicking outside an over-the-page sidebar closes it
    document.addEventListener('click', e => {
      if (overlay && current() === 'open' && e.target.isConnected && !side.contains(e.target) && !e.target.closest('[data-roll], .roll-win')) { overlay = false; setState('rail'); }
    });
    let wasWide = innerWidth >= WIDE;
    addEventListener('resize', () => { const wide = innerWidth >= WIDE; if (wide !== wasWide) { wasWide = wide; layout(); } });
    phone.addEventListener('change', layout);
    document.addEventListener('askdnd:gamemode', () => { layout(); loadLog(); });
    const anim = side.querySelector('[data-roll-anim]');
    anim.checked = animate();
    anim.addEventListener('change', () => store.set(ANIM, anim.checked ? 'on' : 'off'));
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
    const li = log.firstElementChild;
    if (li) { li.classList.remove('fresh'); void li.offsetWidth; li.classList.add('fresh'); }
    buildPeople(li ? new Set([li.dataset.person]) : null);
    activity();
  }

  // ---------------------------------------------------------------- the rail: each person's latest roll
  // Collapsed, the sidebar shows one avatar per person (their newest roll in the log) with its total,
  // colored on a natural 20 or 1; a new roll pulses it; hover (or tap) says what it was. After QUIET
  // with no rolls the rail slides away, and comes back with the next roll; the edge tab brings it back.
  function whatOf(li) {
    const name = li.querySelector('.roll-who b').textContent.trim(), total = li.querySelector('.roll-total');
    const what = li.querySelector('.roll-what').textContent.trim().replace(/\s+/g, ' ');
    const when = (li.querySelector('time') || {}).textContent || '';
    return name + ': ' + (total ? what + ' ' + total.textContent : what.charAt(0).toLowerCase() + what.slice(1)) + (when ? ' (' + when + ')' : '');
  }
  function buildPeople(pulse) {
    if (!people || !log) return;
    const seen = new Set();
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
  function activity(at) { lastActivity = Math.max(lastActivity, at || Date.now()); quietCheck(); }
  function quietCheck() {
    const quiet = gmOn() && !!side && loaded && current() === 'rail' && Date.now() - lastActivity > QUIET;
    document.body.classList.toggle('rolls-quiet', quiet);
    if (edge) edge.hidden = !quiet;
  }
  setInterval(quietCheck, 15000);
  if (edge) edge.addEventListener('click', () => activity());
  function placeholder(label) {
    const li = document.createElement('li');
    li.className = 'roll-pending';
    li.textContent = label + ' · sending…';
    log.prepend(li);
    return li;
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
    for (const m of (e.detail.serverResponse || '').matchAll(/data-seq="(\d+)"/g)) lastId = Math.max(lastId, +m[1]);
  });
  if (log) log.addEventListener('htmx:afterSwap', () => {
    const first = !loaded;
    tidy();
    loaded = true;
    if (first) {  // quiet already? The newest roll's time says
      buildPeople();
      log.querySelectorAll('time[data-at]').forEach(t => { lastActivity = Math.max(lastActivity, Date.parse(t.dataset.at) || 0); });
      return quietCheck();
    }
    const fresh = new Set();
    [...log.querySelectorAll('.roll-item[data-seq]')].reverse().forEach(li => {
      if (+li.dataset.seq > before) fresh.add(li.dataset.person);
      if (+li.dataset.seq > before && !li.dataset.mine) {
        if (!othersShown()) notice(li);
        li.classList.remove('fresh'); void li.offsetWidth; li.classList.add('fresh');
      }
    });
    buildPeople(fresh);
    if (fresh.size) activity();
  });
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
    const dmg = li.querySelector('.roll-dmg-line b');
    const t = document.createElement('span');
    t.innerHTML = !total ? '<b>' + esc(name) + '</b> ' + esc(what.charAt(0).toLowerCase() + what.slice(1))
      : dmg && +li.dataset.seq !== +li.dataset.id ? '<b>' + esc(name) + '</b> rolled <b>' + esc(dmg.textContent) + '</b> damage · ' + esc(what.replace(/ to hit$/, ''))
      : '<b>' + esc(name) + '</b> rolled <b class="' + (li.classList.contains('nat20') ? 'nat20' : li.classList.contains('nat1') ? 'nat1' : '') + '">' + esc(total.textContent) + '</b> · ' + esc(what);
    n.append(t);
    pops.appendChild(n);
    const notes = pops.querySelectorAll('.roll-note');
    if (notes.length > 3) notes[0].remove();
    setTimeout(() => n.classList.add('gone'), 4000);
    setTimeout(() => n.remove(), 4400);
  }
})();

// Lists (DESIGN.md › Lists and filters; _lists.html): any [data-list] root. Chips are OR within a group
// and AND across groups, each with a live count (greyed out at zero); a search looks through every row
// and pauses the filters. Filters, sort and lens are remembered per list in this browser and forgotten
// after a day without use. The Spell Book adds its "Averages at" lens on top (below).
(function () {
  const DAY = 864e5, KEY = r => 'askdnd:list:' + r.dataset.list;
  const vals = (f, g) => { const v = f[g]; return Array.isArray(v) ? v : (v ? [v] : []); };
  const fOf = row => row._f || (row._f = (() => { try { return JSON.parse(row.dataset.f || '{}'); } catch (e) { return {}; } })());
  function load(root) {
    let s = null;
    try { s = JSON.parse(localStorage.getItem(KEY(root)) || 'null'); } catch (e) { s = null; }
    if (!s || Date.now() - (s.at || 0) > DAY) s = { sel: {} };
    let force = {};
    try { force = JSON.parse(root.dataset.lsForce || '{}'); } catch (e) { force = {}; }
    Object.entries(force).forEach(([g, vs]) => { s.sel[g] = [...new Set([...(s.sel[g] || []), ...vs])]; });
    root._ls = { sel: s.sel || {}, sort: s.sort || '', lens: s.lens || '', more: !!s.more, q: '' };
    const sort = root.querySelector('[data-ls-sort]'); if (sort && root._ls.sort) sort.value = root._ls.sort;
    const lens = root.querySelector('[data-ls-lens]');
    if (lens && root._ls.lens && [...lens.options].some(o => o.value === root._ls.lens)) lens.value = root._ls.lens;
    const more = root.querySelector('[data-ls-more]'); if (more) more.open = root._ls.more;
  }
  function save(root) {
    const st = root._ls;
    try { localStorage.setItem(KEY(root), JSON.stringify({ at: Date.now(), sel: st.sel, sort: st.sort, lens: st.lens, more: st.more })); } catch (e) { /* private window */ }
  }
  function apply(root) {
    const st = root._ls, sel = st.sel, q = st.q.trim().toLowerCase();
    const rows = [...root.querySelectorAll('[data-ls-row]')];
    const on = Object.keys(sel).filter(g => (sel[g] || []).length);
    const passes = (f, skip) => on.every(g => g === skip || vals(f, g).some(v => sel[g].includes(v)));
    rows.forEach(r => { r.hidden = q ? !(r.dataset.name || '').includes(q) : !passes(fOf(r)); });
    root.querySelectorAll('[data-ls-group]').forEach(chip => {
      const g = chip.dataset.lsGroup, v = chip.dataset.lsValue, pressed = (sel[g] || []).includes(v);
      const n = rows.filter(r => passes(fOf(r), g) && vals(fOf(r), g).includes(v)).length;
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
    const box = root.querySelector('[data-ls-rows]'), sort = st.sort || 'level';
    root.dispatchEvent(new CustomEvent('list:before-sort', { bubbles: true, detail: { rows } }));
    const name = r => r.dataset.name || '';
    const sorted = rows.slice().sort((a, b) => sort === 'name' ? name(a).localeCompare(name(b))
      : sort === 'avg' ? ((+b.dataset.sortAvg || -1) - (+a.dataset.sortAvg || -1)) || name(a).localeCompare(name(b))
      : (+a.dataset.level - +b.dataset.level) || name(a).localeCompare(name(b)));
    box.querySelectorAll('.ls-grouphead').forEach(h => h.remove());
    let last = null;
    sorted.forEach(r => {
      if (sort === 'level' && !r.hidden && r.dataset.groupLabel !== last) {
        last = r.dataset.groupLabel;
        const h = document.createElement('div');
        h.className = 'ls-grouphead';
        h.textContent = last;
        box.appendChild(h);
      }
      box.appendChild(r);
    });
    const shown = rows.filter(r => !r.hidden).length, noun = root.dataset.noun || 'item';
    const sum = root.querySelector('[data-ls-summary]'); if (sum) sum.textContent = shown + ' ' + noun + (shown === 1 ? '' : 's');
    const empty = root.querySelector('[data-ls-empty]'); if (empty) empty.hidden = shown > 0;
    root.classList.toggle('ls-is-searching', !!q);
    const sn = root.querySelector('[data-ls-searching]'); if (sn) sn.hidden = !q;
    save(root);
  }
  window.askdndList = { apply };
  const rootOf = el => el.closest && el.closest('[data-list]');
  document.addEventListener('click', e => {
    const root = rootOf(e.target); if (!root || !root._ls) return;
    const st = root._ls, search = root.querySelector('[data-ls-search]');
    const clearSearch = () => { st.q = ''; if (search) search.value = ''; };
    if (e.target.closest('[data-ls-clear]')) { st.sel = {}; clearSearch(); apply(root); return; }
    if (e.target.closest('[data-ls-clear-search]')) { clearSearch(); apply(root); if (search) search.focus(); return; }
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
      const fold = root.querySelector('[data-ls-fold]'); if (fold && !matchMedia('(max-width: 700px)').matches) fold.open = true;
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
        set('[data-sb-dice]', a.dice + (level && at > level ? ' · at ' + ORD(at) : ''));
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
