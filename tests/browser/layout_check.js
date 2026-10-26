// What breaks when a page is narrower or wider than it was designed at (docs/DESIGN.md › Narrow screens). Run in a
// page, it returns a list of problems, each {kind, where, detail}; empty means the page holds together:
// - "scrolls sideways": the page is wider than the window (and which element pushes it out)
// - "spills": text runs outside a box that should hold it (a menu, a button, a tag, a card)
// - "wraps": a one-line control (a button, tab, tag, chip) broke onto two lines
// - "overlaps": two items in the menu bar sit on top of each other, or something placed on top (a badge, a corner
//   button) covers text beside it
// Used by tests/browser/test_layout.py on every pull request and by scripts/layout_sweep.py for a sweep of real data.
() => {
  const problems = [], seen = new Set();
  const shown = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
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
    const cs = getComputedStyle(el);
    if (cs.overflowX !== 'visible' || cs.textOverflow === 'ellipsis') continue;
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
    const box = el.offsetParent; if (!box) continue;
    const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!n.textContent.trim() || el.contains(n) || n.parentElement.closest('[hidden]') || !shown(n.parentElement)) continue;
      const range = document.createRange(); range.selectNodeContents(n);
      if ([...range.getClientRects()].some(t => rx(t, r))) { add('overlaps', el, `${el.textContent} covers "${n.textContent.trim()}"`); break; }
    }
  }
  return problems;
}
