// On askdnd's own pages: tells the page the extension is on, passes its change requests to the extension, and tells
// it when D&D Beyond saved something, so it reads the numbers again.
window.addEventListener('message', e => {
  if (e.source !== window || !e.data || !e.data.askdndBridge) return;
  if (e.data.askdndBridge === 'ping') window.postMessage({ askdndBridge: 'hello' }, location.origin);
  if (e.data.askdndBridge === 'apply-request') chrome.runtime.sendMessage({ type: 'apply', change: e.data.change, ddbId: e.data.ddbId, ops: e.data.ops });
});
chrome.runtime.onMessage.addListener(m => { if (m.type === 'bridge-update') window.postMessage({ askdndBridge: 'update' }, location.origin); });
window.postMessage({ askdndBridge: 'hello' }, location.origin);
// The extension's key to askdnd: asked for by this page (signed in, so its cookie counts), kept by the extension. It
// can't use askdnd's cookie itself: to Chrome the extension is a third party.
fetch('/bridge/connect', { method: 'POST', headers: { Accept: 'application/json' } })
  .then(r => (r.ok ? r.json() : null)).then(j => { if (j && j.key) chrome.runtime.sendMessage({ type: 'key', key: j.key }); }).catch(() => {});
