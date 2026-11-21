// Comments pinned to a mockup (issue 24, Brett's picks Nov 21, docs/mockups/mockup-comments/). askdnd adds this file to
// every mockup it opens in its sealed frame (app/documents.py `document_file`), older ones too. It does nothing on its own:
// askdnd's Comment button turns comment mode on, and then a click anywhere tells askdnd where (x as a share of the page's
// width, y in pixels from its top) with the words nearest it; askdnd sends back the pins to draw. It talks only to the
// askdnd page holding its frame (app.js "comments on a mockup"), and never to anything else.
(() => {
  if (window.parent === window) return;
  let on = false;
  let pins = [];
  const layer = document.createElement('div');
  layer.setAttribute('data-askdnd-pins', '');
  layer.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483646;pointer-events:none';
  const style = document.createElement('style');
  style.textContent = '.askdnd-pin{position:absolute;width:24px;height:24px;margin:-24px 0 0 -2px;border-radius:50% 50% 50% 2px;' +
    'background:#e8b34b;color:#1b1408;font:700 12px/24px system-ui,sans-serif;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.5);' +
    'pointer-events:auto;cursor:pointer}.askdnd-pin.held{outline:2px solid #fff}.askdnd-pin.lit{transform:scale(1.25)}' +
    'html.askdnd-commenting,html.askdnd-commenting *{cursor:crosshair!important}';
  const mount = () => {
    if (!document.body) return false;
    if (!layer.isConnected) { document.body.appendChild(layer); document.head.appendChild(style); }
    return true;
  };
  const wide = () => Math.max(document.documentElement.scrollWidth, 1);
  const draw = () => {
    if (!mount()) return;
    layer.replaceChildren(...pins.map(p => {
      const pin = document.createElement('span');
      pin.className = 'askdnd-pin' + (p.held ? ' held' : '');
      pin.textContent = String(p.n);
      pin.dataset.n = String(p.n);
      pin.style.left = (Number(p.x) * wide()) + 'px';
      pin.style.top = Number(p.y) + 'px';
      return pin;
    }));
  };
  // The words nearest a click, as the page shows them: the clicked thing's own, or its nearest labelled part's
  const near = el => {
    const part = el && el.closest ? el.closest('button, a, label, td, th, li, h1, h2, h3, h4, h5, p, legend, [data-screen], section, article') : null;
    const words = ((part || el || {}).textContent || '').replace(/\s+/g, ' ').trim();
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
  tell({ askdnd: 'comments-ready' });
})();
