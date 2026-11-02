// On any D&D Beyond page but a character's sheet (the campaign page, the VTT, the home page): the DM as a backup
// (app/ddb_bridge.py `carried`; Brett, 2026-11-02). It puts ddb-page.js into the page, which here only makes askdnd's
// batches, and tells the extension every few seconds that a D&D Beyond page is open here, so a DM's browser makes the
// changes of a character whose own sheet is closed. In anyone else's browser askdnd answers that there's nothing to
// carry, and it asks only once a minute. Nothing about the page itself is sent, and nothing is drawn on it.
(() => {
  if (window.top !== window) return;
  // A message to the extension. After the extension is reloaded or updated, a page opened before it keeps this old
  // script, which can no longer reach it: it stops quietly then
  const alive = () => { try { return !!(chrome.runtime && chrome.runtime.id); } catch (e) { return false; } };
  const send = (m, cb) => {
    try {
      if (!alive()) return;
      const p = cb ? chrome.runtime.sendMessage(m, cb) : chrome.runtime.sendMessage(m);
      if (p && p.catch) p.catch(() => {});
    } catch (e) { /* the extension was reloaded: this page's old script is cut off */ }
  };
  const s = document.createElement('script');
  s.src = chrome.runtime.getURL('ddb-page.js');
  (document.head || document.documentElement).appendChild(s);
  s.onload = () => s.remove();

  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-page' || e.data.type !== 'applied') return;
    send({ ...e.data, type: 'carry-applied' });
  });
  chrome.runtime.onMessage.addListener((m, sender, reply) => {
    if (m.type === 'apply') { window.postMessage({ askdndBridge: 'apply', batch: m.batch }, location.origin); reply({ took: true }); }
  });
  // How soon to ask again: askdnd says (every few seconds while this browser carries for a campaign), else a minute
  const tick = () => {
    if (!alive()) return;
    send({ type: 'carry-tick' }, answer => {
      if (chrome.runtime.lastError) return setTimeout(tick, 60000);
      setTimeout(tick, Math.max(5, (answer && answer.every) || 60) * 1000);
    });
  };
  tick();
})();
