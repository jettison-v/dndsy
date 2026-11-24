// Comments pinned to a mockup (issue 24, Brett's picks Nov 21, docs/mockups/mockup-comments/). askdnd adds this file to
// every mockup it opens in its sealed frame (app/documents.py `document_file`), older ones too. It does nothing on its own:
// askdnd's Comment button turns comment mode on, and then a click anywhere tells askdnd where (x as a share of the page's
// width, y in pixels from its top) with the words nearest it; askdnd sends back the pins to draw. It talks only to the
// askdnd page holding its frame (app.js "comments on a mockup"), and never to anything else. While a comment is being
// written its pin is drawn where the click landed, marked as not sent (issue 102), and a note sent from askdnd asks it
// for a picture of what the frame shows, which askdnd can't read itself through the seal (issue 103).
(() => {
  if (window.parent === window) return;
  const here = document.currentScript && document.currentScript.src;  // (askdnd's address: the picture's code comes from it)
  let on = false;
  let pins = [];
  let draft = null;  // (the pin of a comment being written: {n, x, y})
  const layer = document.createElement('div');
  layer.setAttribute('data-askdnd-pins', '');
  layer.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483646;pointer-events:none';
  const style = document.createElement('style');
  style.textContent = '.askdnd-pin{position:absolute;width:24px;height:24px;margin:-24px 0 0 -2px;border-radius:50% 50% 50% 2px;' +
    'background:#e8b34b;color:#1b1408;font:700 12px/24px system-ui,sans-serif;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.5);' +
    'pointer-events:auto;cursor:pointer}.askdnd-pin.held{outline:2px solid #fff}.askdnd-pin.lit{transform:scale(1.25)}' +
    '.askdnd-pin.draft{background:#fff3d6;outline:2px dashed #e8b34b;outline-offset:2px;cursor:default}' +
    'html.askdnd-commenting,html.askdnd-commenting *{cursor:crosshair!important}';
  const mount = () => {
    if (!document.body) return false;
    if (!layer.isConnected) { document.body.appendChild(layer); document.head.appendChild(style); }
    return true;
  };
  const wide = () => Math.max(document.documentElement.scrollWidth, 1);
  // A comment made on claude.ai has no spot, only the words it was pinned to (item 39, 6 of 6): it goes by those words
  const byWords = (near) => {
    const want = String(near || '').trim().slice(0, 60);
    if (!want) return null;
    const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let t = walk.nextNode(); t; t = walk.nextNode()) {
      const el = t.parentElement;
      if (!el || el.closest('[data-askdnd-pins], script, style, template, title, noscript')) continue;  // (words a person sees, never a script's)
      if (t.nodeValue && t.nodeValue.includes(want)) {
        const r = el.getBoundingClientRect();
        if (!r.width && !r.height) continue;
        return { x: (r.left + scrollX) / wide(), y: r.top + scrollY };
      }
    }
    return null;
  };
  const pinAt = (p, kind) => {
    const pin = document.createElement('span');
    pin.className = 'askdnd-pin' + kind;
    pin.textContent = String(p.n);
    if (kind === ' draft') pin.dataset.draft = String(p.n); else pin.dataset.n = String(p.n);
    const at = (p.near && byWords(p.near)) || p;
    pin.style.left = (Number(at.x) * wide()) + 'px';
    pin.style.top = Number(at.y) + 'px';
    return pin;
  };
  const draw = () => {
    if (!mount()) return;
    layer.replaceChildren(...pins.map(p => pinAt(p, p.held ? ' held' : '')), ...(draft ? [pinAt(draft, ' draft')] : []));
  };
  // What the frame shows, as a picture (issue 103): drawn here, where the page can be read, and handed to askdnd
  let lib = null;
  const loadLib = () => lib || (lib = new Promise((ok, no) => {
    const s = document.createElement('script');
    s.src = new URL('/static/vendor/html-to-image-1.11.11/html-to-image.js', here || location.href).href;
    s.onload = () => ok(window.htmlToImage); s.onerror = no;
    document.head.append(s);
  }));
  const BLANK = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  async function picture() {
    const h = await loadLib();
    const bg = getComputedStyle(document.body).backgroundColor;
    return h.toJpeg(document.body, {
      quality: 0.85, pixelRatio: 1, width: innerWidth, height: innerHeight, skipFonts: true, imagePlaceholder: BLANK,
      backgroundColor: bg === 'rgba(0, 0, 0, 0)' ? getComputedStyle(document.documentElement).backgroundColor : bg,
      style: { margin: '0', marginTop: -scrollY + 'px', marginLeft: -scrollX + 'px' },
    });
  }
  // The words nearest a click, as the page shows them: the clicked thing's own, or its nearest labelled part's
  // (as the page lays them out, innerText, so words in separate parts never run together, "issue 22Split…"; the clicked
  // part itself, never a whole section around it: Brett's note, Nov 23)
  const said = n => String((n && (n.innerText || n.textContent)) || '').replace(/\s+/g, ' ').trim();
  const near = el => {
    const part = el && el.closest ? el.closest('button, a, label, td, th, li, h1, h2, h3, h4, h5, h6, p, legend, summary, dt, dd') : null;
    let words = said(part);
    for (let up = el; !words && up && up !== document.body; up = up.parentElement) words = said(up);
    return words.length > 80 ? words.slice(0, 77).replace(/\s\S*$/, '') + '…' : words;
  };
  const tell = msg => parent.postMessage(msg, '*');  // (its parent is the askdnd page; the sandbox gives it no origin to name)
  addEventListener('message', e => {
    const d = e.data;
    if (e.source !== parent || !d || typeof d !== 'object') return;
    if (d.askdnd === 'comment-mode') {
      on = !!d.on;
      document.documentElement.classList.toggle('askdnd-commenting', on);
    } else if (d.askdnd === 'pins') {
      pins = Array.isArray(d.pins) ? d.pins.filter(p => p && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y))) : [];
      draw();
    } else if (d.askdnd === 'draft') {
      const p = d.pin;
      draft = p && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)) ? { n: Number(p.n) || '', x: Number(p.x), y: Number(p.y) } : null;
      draw();
    } else if (d.askdnd === 'picture') {
      picture().then(png => tell({ askdnd: 'picture', id: d.id, png }), () => tell({ askdnd: 'picture', id: d.id, png: '' }));
    } else if (d.askdnd === 'show-pin') {
      const p = pins.find(x => Number(x.n) === Number(d.n));
      if (p) scrollTo({ top: Math.max(Number(p.y) - 140, 0), behavior: 'smooth' });
      layer.querySelectorAll('.askdnd-pin').forEach(x => x.classList.toggle('lit', x.dataset.n === String(d.n)));
    }
  });
  document.addEventListener('click', e => {
    const pin = e.target && e.target.closest ? e.target.closest('.askdnd-pin') : null;
    if (pin) {
      e.preventDefault(); e.stopPropagation();
      tell({ askdnd: 'pin-click', n: Number(pin.dataset.n) });
      return;
    }
    if (!on) return;
    e.preventDefault(); e.stopPropagation();  // (in comment mode a click pins, never presses what's under it)
    tell({ askdnd: 'comment-at', x: e.pageX / wide(), y: e.pageY, near: near(e.target) });
  }, true);
  addEventListener('keydown', e => { if (e.key === 'Escape' && on) tell({ askdnd: 'comment-stop' }); });
  addEventListener('resize', () => { if (pins.length) draw(); });
  // (a pin placed by its words moves with them: drawn again once the page's fonts and pictures have settled, and when
  // the page itself grows or reflows, as a mockup drawing its own boards does)
  const settle = () => { if (pins.length) draw(); };
  addEventListener('load', settle);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(settle);
  if (window.ResizeObserver) new ResizeObserver(settle).observe(document.body);
  tell({ askdnd: 'comments-ready' });
})();
