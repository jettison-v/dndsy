// On D&D Beyond's VTT (/games/<campaign>): passes what vtt-page.js hears about the fight on to the extension
// (background.js), which tells askdnd, for a game askdnd follows only. (vtt-page.js runs in the page itself from the very
// start, as manifest.json says: the VTT connects to its game server before a script this one added would run.) It also
// asks askdnd every few seconds for initiative numbers to set (0.12.0, app/initiative.py): askdnd gives some to the
// DM's page only, and asks anyone else's to ask once a minute.
//
// A quiet badge at the top, under the VTT's own bar (clear of the Initiative Order's footer, bottom left), says askdnd is listening, and what it heard (Brett, 2026-10-29: open about it, and a
// glance shows whether askdnd hears the fight). It only shows: no buttons over D&D Beyond's own controls, and clicks
// go through it to the map. Nothing shows for a game askdnd doesn't follow.
(() => {
  // A message to the extension. After the extension is reloaded or updated, a page opened before it keeps this old
  // script, which can no longer reach it: it stops quietly then (reload the page to bring askdnd back)
  const send = (m, cb) => {
    try {
      if (!chrome.runtime || !chrome.runtime.id) return;
      const p = cb ? chrome.runtime.sendMessage(m, cb) : chrome.runtime.sendMessage(m);
      if (p && p.catch) p.catch(() => {});
    } catch (e) { /* the extension was reloaded: this page's old script is cut off */ }
  };
  const gameId = () => (location.pathname.match(/\/games\/(\d+)/) || [])[1];
  let follows = false, last = null, root = null;
  const esc = v => String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CSS = `:host { all: initial; }
    .badge { position: fixed; left: 50%; top: 64px; transform: translateX(-50%); z-index: 2147483000; pointer-events: none; display: flex; align-items: center; gap: 7px;
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
    const text = !f ? 'hearing this game · no fight now' : f.waiting ? 'hearing the encounter · waiting for Start Combat'
      : `hearing the fight · round ${esc(f.round)}${now ? ` · <b>${esc(now.name)}</b>’s turn` : ''}`;
    root.innerHTML = `<style>${CSS}</style><div class="badge" role="status" title="askdnd hears this fight's order and turns; on the DM's page it sets the initiative numbers rolled or dragged in askdnd, and changes nothing else here"><span class="dot"></span><span class="logo">askdnd</span><span>${text}</span></div>`;
  }
  let heard = false;  // (a fight told while askdnd couldn't be reached is told again once it can)
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-vtt') return;
    if (e.data.type === 'fight') { last = e.data.fight; heard = true; draw(); }
    send({ ...e.data, type: 'vtt-' + e.data.type, gameId: gameId() });
  });
  // Initiative numbers askdnd wants set (the DM's page only gets any): handed to vtt-page.js, which sends them
  let ticking = null;
  const tick = () => {
    clearTimeout(ticking);
    send({ type: 'vtt-tick' }, answer => {
      if (chrome.runtime.lastError || !answer) { ticking = setTimeout(tick, 60000); return; }
      if (Array.isArray(answer.sets) && answer.sets.length) window.postMessage({ askdndBridge: 'to-vtt', type: 'set', sets: answer.sets }, location.origin);
      ticking = setTimeout(tick, Math.max(2, answer.every || 60) * 1000);
    });
  };
  // Does askdnd follow this game? Asked as the page opens, and again when an askdnd page connects the extension (0.12.1:
  // opened first, the VTT page asked before the extension could reach askdnd, and was never heard until reloaded)
  const hello = () => send({ type: 'vtt-hello', gameId: gameId() }, answer => {
    if (chrome.runtime.lastError) return;
    const was = follows;
    follows = !!(answer && answer.followed);
    draw();
    if (!follows || was) return;
    tick();
    if (heard) send({ type: 'vtt-fight', fight: last, gameId: gameId() });
  });
  try {
    chrome.runtime.onMessage.addListener(m => {
      if (m.type === 'vtt-now' && follows) tick();
      if (m.type === 'vtt-again' && !follows) hello();
    });
  } catch (e) { /* cut off */ }
  hello();
})();
