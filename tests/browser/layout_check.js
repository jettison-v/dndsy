// What breaks when a page is narrower or wider than it was designed at (docs/DESIGN.md › Narrow screens). Run in a
// page, it returns a list of problems, each {kind, where, detail}; empty means the page holds together:
// - "scrolls sideways": the page is wider than the window (and which element pushes it out)
// - "spills": text runs outside a box that should hold it (a menu, a button, a tag, a card)
// - "wraps": a one-line control (a button, tab, tag, chip) broke onto two lines
// - "overlaps": two items in the menu bar sit on top of each other, or something placed on top (a badge, a corner
//   button) covers text beside it
// - "covered": words with something else drawn over them, on the page or in an open window (a sticky header over a row,
//   a card over a list, a help line over a box; Nov 25)
// - "zooms", on a touch screen only: a box you type in with text under 16px, which makes an iPhone zoom the page in
// - "breaks a word": a heading or a bold name wrapped inside a word rather than between words
// - "cuts its hint": a box's placeholder longer than the box
// - "unreadable": words drawn in a scaling picture (an SVG's <text>) under 9px
// - "squeezed": words in a row broke onto a second line although every part of the row would fit on one (Nov 19)
// - "off baseline": two neighbouring parts of a row, on one line, whose words don't share a baseline (Nov 19; a rule since
//   the Live UI Audit)
// - "cut short": a table cell's words cut off with "…" while another cell in the same row has room to spare (Brett, Nov 25:
//   the Roadmap's Next column cut while Item had a wide empty stretch; a table whose columns are all fixed but one)
// - "clipped": something inside a table cell drawn past the cell's edge and cut off (For you's Try it button, Nov 25)
// - "repeats an id": two elements with one id, so a script finds the wrong one (Help's FAQ had id="cards", the corner
//   cards' own: every card on Help landed in a folded answer; Nov 17)
// - "misaligned", only when asked ({rows: true}): rows of one list whose small last item (an icon, a ↗) doesn't line up
//   with the rest. scripts/layout_sweep.py asks; the tests don't yet, since it finds rows on the Character page that
//   wrap differently on a phone (Nov 2), a design question before it can be a rule.
// Used by tests/browser/test_layout.py on every pull request and by scripts/layout_sweep.py for a sweep of real data.
ask => {
  const problems = [], seen = new Set();
  const folded = el => {  // (inside a closed <details>, its summary aside: not drawn, though Chrome still gives it boxes)
    const d = el.closest('details:not([open])'), s = el.closest('summary');
    return !!d && !(s && s.parentElement === d);
  };
  const shown = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && !folded(el); };
  const where = el => {
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      const tour = e.dataset && e.dataset.tour, cls = [...e.classList].filter(c => !/^(on|open|active|show)$/.test(c)).slice(0, 2).join('.');
      parts.unshift(e.id ? `#${e.id}` : tour ? `[data-tour=${tour}]` : `${e.tagName.toLowerCase()}${cls ? '.' + cls : ''}`);
      if (e.id) break;
    }
    return parts.join(' > ');
  };
  const add = (kind, el, detail) => {
    const key = kind + where(el);
    if (seen.has(key)) return;
    seen.add(key); problems.push({ kind, where: where(el), detail: detail.replace(/\s+/g, ' ').trim().slice(0, 80) });
  };
  // Inside something that scrolls or clips on purpose (a wide table, a code block, a carousel of chips)
  const contained = el => {
    for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const o = getComputedStyle(e).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden' || o === 'clip') return true;
    }
    return false;
  };

  // The page wider than the window
  const W = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > W + 1) {
    const out = [...document.body.querySelectorAll('*')].filter(el => shown(el) && el.getBoundingClientRect().right > W + 1
      && getComputedStyle(el).position !== 'fixed' && !contained(el));
    const top = out.filter(el => !out.includes(el.parentElement)).slice(0, 4);
    if (!top.length) {  // no box sticks out: then it's text that can't break (a long web address)
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        if (!n.textContent.trim() || !n.parentElement || contained(n.parentElement) || getComputedStyle(n.parentElement).position === 'fixed') continue;
        const range = document.createRange(); range.selectNodeContents(n);
        if ([...range.getClientRects()].some(r => r.right > W + 1)) { add('scrolls sideways', n.parentElement, `text runs past the edge: ${n.textContent}`); break; }
      }
      if (!problems.length) add('scrolls sideways', document.body, `page ${document.documentElement.scrollWidth}px in a ${W}px window`);
    }
    top.forEach(el => add('scrolls sideways', el, `ends at ${Math.round(el.getBoundingClientRect().right)}px in a ${W}px window: ${el.textContent}`));
  }

  // Text outside its box: boxes that hold text and don't scroll or cut it off on purpose
  const BOXES = '.menu, .peek, .tour-card, .btn, button, .tag, .chip, .ls-chip, .char-btn, .live-pill, .vital, .stand, .section, .roll-item, .move, .ri, .add, td, th';
  const looksLikeABox = el => { const cs = getComputedStyle(el);  // anything drawn as a box: a background or a border
    return !/rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor) || parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0; };
  for (const el of document.body.querySelectorAll('*')) {
    if (!(el.matches(BOXES) || looksLikeABox(el)) || !shown(el) || contained(el)) continue;
    if (el.closest('details:not([open])') && !el.closest('summary')) continue;  // (inside a closed fold: not on the page)
    const cs = getComputedStyle(el);
    if (cs.overflowX !== 'visible' || cs.textOverflow === 'ellipsis') continue;
    if (el.matches('input, textarea, select')) continue;  // (a field scrolls its own words: Safari counts them in scrollWidth, Chromium doesn't)
    if (el.scrollWidth > el.clientWidth + 2 && el.clientWidth > 0) add('spills', el, `${el.scrollWidth - el.clientWidth}px wider than its box: ${el.textContent}`);
  }

  // One-line controls broken over two lines (their own text, not a deliberate second line)
  const ONE_LINE = 'button, .btn, .tag, .chip, .ls-chip, .char-btn, .live-pill, [role=tab], .nav a, .modes a, .econ-tabs button';
  for (const el of document.querySelectorAll(ONE_LINE)) {
    if (!shown(el)) continue;
    const text = el.textContent.trim();
    if (!text || text.length > 40 || el.querySelector('small, br, .meta, .note, div, p')) continue;
    // Its text on lines a full line apart (a count badge or an avatar beside it sits a little higher or lower: fine)
    const cs = getComputedStyle(el), line = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
    const tops = [], walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 1) tops.push(r.top);
    }
    if (tops.length && Math.max(...tops) - Math.min(...tops) >= line * 0.8) add('wraps', el, text);
  }

  // A title or a name broken inside a word (the UI review, Nov 16: a Manage title one letter per line beside its
  // button; a seat's name on Table, a Dice tuning knob's): its words wrap between them, never within one, unless the
  // word alone is wider than the room around it (a long email or web address breaks on purpose)
  for (const el of document.querySelectorAll('main h1, main h2, main h3, main b, .peek h1, .peek h2, .peek h3, .peek b')) {
    if (!el.getBoundingClientRect().height || getComputedStyle(el).visibility === 'hidden') continue;  // (squeezed to no width counts: that's the bug)
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      let broken = '';
      for (const m of n.textContent.matchAll(/[^\s\-–—/]+/g)) {  // (a word, as a line may break after a hyphen or slash)
        const range = document.createRange(); range.setStart(n, m.index); range.setEnd(n, m.index + m[0].length);
        const rects = [...range.getClientRects()].filter(r => r.width > 1), tops = rects.map(r => Math.round(r.top));
        const room = el.parentElement ? el.parentElement.clientWidth : 0, em = parseFloat(getComputedStyle(el).fontSize);
        const wide = room >= 3 * em && rects.reduce((w, r) => w + r.width, 0) > room;  // (room squeezed to a few letters is the bug)
        if (tops.length > 1 && Math.max(...tops) - Math.min(...tops) > 2 && !wide) { broken = m[0]; break; }
      }
      if (broken) { add('breaks a word', el, `"${broken}" runs over two lines: ${el.textContent}`); break; }
    }
  }
  // A box's hint cut off mid-word (the UI review, Nov 16: "Search people, places and thing"): its placeholder fits
  const ruler = document.createElement('canvas').getContext('2d');
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (!shown(el) || el.value || !el.placeholder) continue;
    const cs = getComputedStyle(el);
    ruler.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const room = el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const width = ruler.measureText(el.placeholder).width;
    if (el.tagName === 'INPUT' && width > room + 1) add('cuts its hint', el, `"${el.placeholder}" needs ${Math.round(width)}px of ${Math.round(room)}px`);
  }
  // Words drawn inside a picture that scales with the page (the UI review, Nov 16: the Features chart's labels at 4px
  // on a phone): too small to read
  for (const el of document.querySelectorAll('svg text')) {
    if (!shown(el) || !el.textContent.trim()) continue;
    const ctm = el.getScreenCTM(), px = parseFloat(getComputedStyle(el).fontSize) * (ctm ? Math.hypot(ctm.a, ctm.b) : 1);
    if (px < 9) add('unreadable', el, `${px.toFixed(1)}px: ${el.textContent}`);
  }

  // The menu bar: nothing sits on top of anything else
  const bar = document.querySelector('.topbar-inner');
  if (bar) {
    const items = [...bar.querySelectorAll(':scope > *, .nav > a, .table-nav > *, .bar-end > *')].filter(shown).filter(el => !el.matches('.menu'));
    const flat = items.filter(el => !items.some(o => o !== el && o.contains(el) === false && el.contains(o)));
    for (let i = 0; i < flat.length; i++) for (let j = i + 1; j < flat.length; j++) {
      const a = flat[i].getBoundingClientRect(), b = flat[j].getBoundingClientRect();
      if (flat[i].contains(flat[j]) || flat[j].contains(flat[i])) continue;
      if (a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2) add('overlaps', flat[i], `${flat[i].textContent} / ${flat[j].textContent}`);
    }
  }
  // Something placed on top of a box (position: absolute: a badge, a corner tool) covering the text beside it
  const rx = (a, b) => a.left < b.right - 2 && b.left < a.right - 2 && a.top < b.bottom - 2 && b.top < a.bottom - 2;
  for (const el of document.body.querySelectorAll('*')) {
    if (el.tagName === 'IMG' || getComputedStyle(el).position !== 'absolute' || !shown(el) || el.closest('.menu, .peek, .tour-card, [role=tooltip], [hidden]')) continue;  // (a picture over its fallback letter is meant to)
    const r = el.getBoundingClientRect();
    if (r.width > 400 || r.height > 200) continue;  // a layer, not a badge
    if (r.width <= 1 && r.height <= 1) continue;  // read aloud only (.sr: 1px, clipped), it draws nothing (a file box inside its button; the weekly phone sweep, Nov 23)
    const box = el.offsetParent; if (!box) continue;
    const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim() || el.contains(n) || n.parentElement.closest('[hidden]') || !shown(n.parentElement)) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      if ([...range.getClientRects()].some(t => rx(t, r))) { add('overlaps', el, `${el.textContent} covers "${n.textContent.trim()}"`); break; }
    }
  }
  // A box you type in whose text is under 16px, on a touch screen: Safari on an iPhone or iPad zooms the whole page in
  // when you tap it, and leaves it zoomed (Nov 8)
  if (matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0) {
    const TYPED = 'textarea, select, [contenteditable=""], [contenteditable=true], input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=button]):not([type=submit]):not([type=reset]):not([type=file]):not([type=color]):not([type=hidden]):not([type=image])';
    for (const el of document.body.querySelectorAll(TYPED)) {
      if (!shown(el) || el.disabled || el.readOnly) continue;
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (px < 16) add('zooms', el, `its text is ${px}px, under 16px: tapping it zooms the page`);
    }
  }
  // Rows of one list that are meant to line up and don't: three or more rows built the same way (same tag and class, the
  // same items in the same order), each a flex or grid row of the same width, whose last item is small (an icon, a ↗, a
  // button) and ends at the same place in most rows but not in a few (Nov 2: the Live window's ↗ sat at a different place
  // on some rows). A list that's ragged on purpose has no such majority.
  if (ask && ask.rows) for (const list of document.body.querySelectorAll('*')) {
    const kids = [...list.children].filter(shown);
    if (kids.length < 3 || contained(list)) continue;
    const kind = el => el.tagName + '.' + [...el.classList].filter(c => !/^(on|open|active|here|mine|fresh|ok|warn|bad|off)$/.test(c)).sort().join('.');
    const groups = {};
    for (const k of kids) {
      const d = getComputedStyle(k).display;
      if (!/flex|grid/.test(d)) continue;
      const key = kind(k) + '>' + [...k.children].filter(shown).map(kind).join(',');  // (rows built the same way: same items in the same order)
      (groups[key] = groups[key] || []).push(k);
    }
    for (const rows of Object.values(groups)) {
      if (rows.length < 3) continue;
      const ends = rows.map(r => { const items = [...r.children].filter(shown); const rr = r.getBoundingClientRect();
        const last = items[items.length - 1], lr = last && last.getBoundingClientRect();
        return items.length >= 2 && lr.width <= 48 ? { row: r, width: Math.round(rr.width), right: Math.round(rr.right), end: Math.round(lr.right) } : null; }).filter(Boolean);
      if (ends.length < 3 || new Set(ends.map(e => e.width + ':' + e.right)).size > 1) continue;  // (rows of different widths)
      const counts = {};
      ends.forEach(e => { counts[e.end] = (counts[e.end] || 0) + 1; });
      const [mode, most] = Object.entries(counts).map(([k, n]) => [+k, ends.filter(e => Math.abs(e.end - +k) <= 2).length]).sort((a, b) => b[1] - a[1])[0];
      if (most * 2 <= ends.length || most === ends.length) continue;
      ends.filter(e => Math.abs(e.end - mode) > 2).forEach(e => add('misaligned', e.row, `its last item ends at ${e.end}px, ${most} of ${ends.length} rows at ${mode}px: ${e.row.textContent}`));
    }
  }
  // A row whose words wrap although the row has room (Brett, Nov 19: "alignment is off again … a check for alignment
  // and wrapping that is more robust"): in a flex row, a part's line of words broke onto a second line, yet every part
  // at its natural one-line width would fit in the row. Typically parts sized as equal shares (flex: 1) when their
  // words differ in length. Each part's natural width is measured on a copy laid out beside it, out of the row.
  const inlineLike = el => /^inline/.test(getComputedStyle(el).display);
  const brokenLine = part => {  // (words in one line box of this part, on two lines; a stacked name and sub-line is fine)
    const groups = new Map(), walk = document.createTreeWalker(part, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim() || !shown(n.parentElement)) continue;
      let box = n.parentElement;
      while (box !== part && inlineLike(box)) box = box.parentElement;
      const range = document.createRange(); range.selectNodeContents(n);
      const tops = [...range.getClientRects()].filter(r => r.width > 1).map(r => r.top);
      if (!groups.has(box)) groups.set(box, []);
      groups.get(box).push(...tops);
    }
    for (const [box, tops] of groups) {
      const line = parseFloat(getComputedStyle(box).lineHeight) || parseFloat(getComputedStyle(box).fontSize) * 1.2;
      if (tops.length > 1 && Math.max(...tops) - Math.min(...tops) >= line * 0.8) return true;
    }
    return false;
  };
  for (const row of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(row);
    if (!/flex$/.test(cs.display) || !cs.flexDirection.startsWith('row') || !shown(row) || contained(row)) continue;
    const parts = [...row.children].filter(c => shown(c) && !['absolute', 'fixed'].includes(getComputedStyle(c).position));
    if (parts.length < 2) continue;
    const squeezed = parts.find(brokenLine);
    if (!squeezed) continue;
    let need = 0;
    for (const c of parts) {
      const copy = c.cloneNode(true);
      Object.assign(copy.style, { position: 'absolute', visibility: 'hidden', width: 'max-content', maxWidth: 'none', flex: 'none' });
      copy.removeAttribute('id');
      row.appendChild(copy);
      const ccs = getComputedStyle(c), own = parseFloat(ccs.flexShrink) === 0 ? c.getBoundingClientRect().width : 0;  // (a part that never shrinks keeps its set width: a clock's 3rem)
      need += Math.max(copy.getBoundingClientRect().width, own) + parseFloat(ccs.marginLeft) + parseFloat(ccs.marginRight);
      copy.remove();
    }
    let items = parts.length;
    for (const n of row.childNodes) {  // (loose words are a part of the row too: "Passive" before its skills)
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      need += [...range.getClientRects()].reduce((w, r) => w + r.width, 0);
      items += 1;
    }
    need += (parseFloat(cs.columnGap) || 0) * (items - 1);
    const room = row.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (need <= room - 2) add('squeezed', squeezed, `wraps with ${Math.round(room - need)}px to spare in its row: ${squeezed.textContent}`);
  }
  // Words side by side in a row that don't share a line (Brett, Nov 19: "the vertical alignment between Available and
  // until"): two neighbouring parts of a flex row, on the same line, whose text baselines differ by more than 2px.
  // Typically a bold label and a smaller grey note centred as boxes (align-items: center) instead of on their
  // baselines. A part drawn as a box (a pill, a bordered button) or an icon with no words (✕, ?) is centred on purpose and
  // left out.
  const boxed = el => { const c = getComputedStyle(el); return c.backgroundColor !== 'rgba(0, 0, 0, 0)' && c.backgroundColor !== 'transparent' || parseFloat(c.borderTopWidth) > 0 || el.matches('input, select, textarea, img, svg'); };
  const ctx = document.createElement('canvas').getContext('2d');
  const baseline = part => {  // (where its first words sit: their box's top plus the font's ascent, wherever they are)
    if (!/[\p{L}\p{N}]/u.test(part.textContent)) return null;  // (an icon, ✕ ? ⋯, is centred on purpose: the Live UI Audit)
    const walk = document.createTreeWalker(part, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim() || !shown(n.parentElement)) continue;
      for (let e = n.parentElement; e && e !== part.parentElement; e = e.parentElement) if (boxed(e)) return null;
      const range = document.createRange(); range.selectNodeContents(n);
      const r = [...range.getClientRects()].find(x => x.width > 1);
      if (!r) continue;
      const fs = getComputedStyle(n.parentElement);
      ctx.font = `${fs.fontStyle} ${fs.fontWeight} ${fs.fontSize} ${fs.fontFamily}`;
      return r.top + ctx.measureText('Hg').fontBoundingBoxAscent;
    }
    return null;
  };
  // (A rule since the Live UI Audit lined up the places it found, Nov 19; until then it was asked for, {baseline: true})
  for (const row of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(row);
    if (!/flex$/.test(cs.display) || !cs.flexDirection.startsWith('row') || !shown(row) || contained(row)) continue;
    const parts = [...row.children].filter(c => shown(c) && !['absolute', 'fixed'].includes(getComputedStyle(c).position));
    for (let i = 1; i < parts.length; i++) {
      const a = parts[i - 1], b = parts[i], ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      if (ra.bottom <= rb.top || rb.bottom <= ra.top) continue;  // (on different lines of a wrapping row)
      const ya = baseline(a), yb = baseline(b);
      if (ya === null || yb === null) continue;
      if (Math.abs(ya - yb) > 2) add('off baseline', b, `${Math.round(Math.abs(ya - yb))}px off its neighbour's line: ${a.textContent.trim().slice(0, 30)} | ${b.textContent}`);
    }
  }
  // Table cells: words cut with "…" while a neighbour has room, and anything drawn past a cell's edge (Nov 25)
  const contentWidth = cell => {  // (the width its contents take, on their widest line)
    const range = document.createRange(); range.selectNodeContents(cell);
    return Math.max(0, ...[...range.getClientRects()].map(r => r.right - cell.getBoundingClientRect().left));
  };
  for (const row of document.querySelectorAll('table tr')) {
    if (!shown(row)) continue;
    const cells = [...row.children].filter(c => c.matches('td') && shown(c));
    if (cells.length < 2) continue;
    const pad = c => { const cs = getComputedStyle(c); return parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight); };
    const spare = cells.map(c => c.getBoundingClientRect().width - pad(c) - contentWidth(c));
    cells.forEach((cell, i) => {
      const box = cell.getBoundingClientRect();
      const past = getComputedStyle(cell).overflowX !== 'visible' && [...cell.querySelectorAll('*')].find(el => shown(el)
        && el.children.length === 0 && el.getBoundingClientRect().right > box.right + 1 && !el.closest('.act-menu, [hidden]'));
      if (past) { add('clipped', past, `${Math.round(past.getBoundingClientRect().right - box.right)}px past its cell: ${past.textContent}`); return; }
      for (const el of [cell, ...cell.querySelectorAll('*')]) {
        if (!shown(el)) continue;
        if (getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1) {
          const need = el.scrollWidth - el.clientWidth, room = Math.max(...spare.filter((_, j) => j !== i));
          if (room >= need + 8) add('cut short', el, `cut by ${need}px while a column beside it has ${Math.round(room)}px spare: ${el.textContent}`);
          break;
        }
      }
    });
  }
  // Words something else is drawn over (Brett, Nov 25: issues 124, 126, 129 and 131 reached him because only the menu bar
  // and small badges were checked): a sticky header over a list's first row, a card over the last, a help line over the
  // box below it, chips wrapping under the next row. The middle of each line of words is asked what's on top there. Only
  // the top layer counts (an open window, else the page), and only words that can be seen (inside the screen and every
  // box that clips them).
  const layer = [...document.querySelectorAll('.peek.open, dialog[open]')].filter(shown).pop() || document.body;
  const seenAt = el => {
    let r = { left: 0, top: 0, right: innerWidth, bottom: innerHeight };
    for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const b = e.getBoundingClientRect();
      r = { left: Math.max(r.left, b.left), top: Math.max(r.top, b.top), right: Math.min(r.right, b.right), bottom: Math.min(r.bottom, b.bottom) };
    }
    return r;
  };
  const named = el => el.id ? `#${el.id}` : `${el.tagName.toLowerCase()}${[...el.classList].slice(0, 2).map(c => '.' + c).join('')}`;
  const words = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
  for (let n = words.nextNode(); n; n = words.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el || !shown(el) || el.closest('[hidden], .sr, [aria-hidden=true], [role=tooltip], option, script, style, template')) continue;
    if (parseFloat(getComputedStyle(el).opacity) === 0) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const box = seenAt(el);
    for (const t of range.getClientRects()) {
      if (t.width < 4 || t.height < 4) continue;
      const x = t.left + t.width / 2, y = t.top + t.height / 2;
      if (x < box.left + 1 || x > box.right - 1 || y < box.top + 1 || y > box.bottom - 1) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
      if (hit.closest('.menu, [role=menu], .tour-card, .peek-backdrop, #cards, #check-card')) continue;  // (a menu or card opened over the page on purpose)
      const hb = hit.getBoundingClientRect();
      if (x < hb.left || x > hb.right || y < hb.top || y > hb.bottom) continue;  // (a link's clickable area stretched over its card: drawn by ::after, see-through)
      if (getComputedStyle(hit).position === 'sticky' || hit.closest('thead, [data-sticky]')) {  // (rows scrolled under a header that stays: as meant, once scrolled)
        let box = el.parentElement;
        while (box && box !== document.body && !(box.scrollHeight > box.clientHeight && /auto|scroll/.test(getComputedStyle(box).overflowY))) box = box.parentElement;
        if ((box && box !== document.body ? box.scrollTop : scrollY) > 0) continue;
      }
      add('covered', el, `"${n.textContent.trim()}" under ${named(hit)}${hit.textContent.trim() ? ` ("${hit.textContent.trim().slice(0, 30)}")` : ''}`);
      break;
    }
  }
  const ids = new Map();
  document.querySelectorAll('[id]').forEach(el => { if (el.id) ids.set(el.id, (ids.get(el.id) || 0) + 1); });
  ids.forEach((n, id) => { if (n > 1) add('repeats an id', document.getElementById(id), `#${id} on ${n} elements`); });
  return problems;
}
