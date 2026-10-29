// On D&D Beyond's VTT (/games/<campaign>): passes what vtt-page.js hears about the fight on to the extension
// (background.js), which tells askdnd, for a game askdnd follows only. It only listens. (vtt-page.js runs in the page
// itself from the very start, as manifest.json says: the VTT connects to its game server before a script this one
// added would run.)
//
// A quiet badge in the corner says askdnd is listening, and what it heard (Brett, 2026-10-29: open about it, and a
// glance shows whether askdnd hears the fight). It only shows: no buttons over D&D Beyond's own controls, and clicks
// go through it to the map. Nothing shows for a game askdnd doesn't follow.
(() => {
  const gameId = () => (location.pathname.match(/\/games\/(\d+)/) || [])[1];
  let follows = false, last = null, root = null;
  const esc = v => String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CSS = `:host { all: initial; }
    .badge { position: fixed; left: 12px; bottom: 12px; z-index: 2147483000; pointer-events: none; display: flex; align-items: center; gap: 7px;
      max-width: min(360px, calc(100vw - 24px)); padding: 5px 11px 5px 8px; border-radius: 999px; background: rgba(21, 23, 26, .82); border: 1px solid #34383e;
      color: #a29d93; font: 500 12px/1.3 Inter, system-ui, sans-serif; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .logo { color: #f08a8a; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; font-size: 11px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: #5bbf7f; flex: none; }
    b { color: #ebe7df; font-weight: 600; }`;
  function draw() {
    if (!follows) return;
    if (!root) {
      const host = document.createElement('div');
      host.id = 'askdnd-vtt';
      root = host.attachShadow({ mode: 'open' });
      document.documentElement.appendChild(host);
    }
    const f = last, now = f && f.order.find(x => x.active);
    const text = !f ? 'hearing this game · no fight now' : `hearing the fight · round ${esc(f.round)}${now ? ` · <b>${esc(now.name)}</b>’s turn` : ''}`;
    root.innerHTML = `<style>${CSS}</style><div class="badge" role="status" title="askdnd hears this fight's order and turns, and never changes anything here"><span class="dot"></span><span class="logo">askdnd</span><span>${text}</span></div>`;
  }
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-vtt') return;
    if (e.data.type === 'fight') { last = e.data.fight; draw(); }
    chrome.runtime.sendMessage({ ...e.data, type: 'vtt-' + e.data.type, gameId: gameId() });
  });
  chrome.runtime.sendMessage({ type: 'vtt-hello', gameId: gameId() }, answer => {
    if (chrome.runtime.lastError) return;
    follows = !!(answer && answer.followed);
    draw();
  });
})();
