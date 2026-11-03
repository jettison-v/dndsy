// On askdnd's own pages: tells the page the extension is on, passes its change requests to the extension, and tells
// it when D&D Beyond saved something, so it reads the numbers again.
// A message to the extension. After the extension is reloaded or updated, a page opened before it keeps this old
// script, which can no longer reach it: it stops quietly then (reload the page to bring askdnd back)
const version = chrome.runtime.getManifest().version;  // (the page records it: body[data-bridge-version])
const send = m => {
  try {
    if (!chrome.runtime || !chrome.runtime.id) return;
    const p = chrome.runtime.sendMessage(m);
    if (p && p.catch) p.catch(() => {});
  } catch (e) { /* the extension was reloaded: this page's old script is cut off */ }
};
window.addEventListener('message', e => {
  if (e.source !== window || !e.data || !e.data.askdndBridge) return;
  if (e.data.askdndBridge === 'ping') window.postMessage({ askdndBridge: 'hello', version }, location.origin);
  if (e.data.askdndBridge === 'wake') send({ type: 'wake' });  // the bridge woke: pull now
  if (e.data.askdndBridge === 'deliver') send({ type: 'deliver', ddbId: e.data.ddbId });  // something was queued here
  if (e.data.askdndBridge === 'gamelog') send({ type: 'gamelog', ddbId: e.data.ddbId, messages: e.data.messages });  // a roll for the game log
});
chrome.runtime.onMessage.addListener(m => { if (m.type === 'bridge-update') window.postMessage({ askdndBridge: 'update' }, location.origin); });
window.postMessage({ askdndBridge: 'hello', version }, location.origin);
// The extension's key to askdnd: asked for by this page (signed in, so its cookie counts), kept by the extension. It
// can't use askdnd's cookie itself: to Chrome the extension is a third party.
fetch('/bridge/connect', { method: 'POST', headers: { Accept: 'application/json' } })
  .then(r => (r.ok ? r.json() : null)).then(j => { if (j && j.key) send({ type: 'key', key: j.key }); }).catch(() => {});
