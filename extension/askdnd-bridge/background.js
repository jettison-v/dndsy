// The extension's go-between. It finds the open D&D Beyond sheets from the tabs themselves (Chrome may stop this
// worker at any time, so it keeps nothing it can't find again), makes askdnd's calls for the panel (signed in as you
// on askdnd), and sends askdnd's changes to the right sheet. It stores nothing.
const ASKDND = 'http://localhost:8000';
const ddbIdOf = url => ((url || '').match(/^https:\/\/www\.dndbeyond\.com\/characters\/(\d+)/) || [])[1];

async function api(method, path, body) {
  const { key } = await chrome.storage.session.get('key');  // from askdnd.js; kept while Chrome is open
  if (!key) throw new Error('Open askdnd (localhost:8000) once in this browser to connect the extension.');
  const r = await fetch(ASKDND + path, { method, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Askdnd-Bridge': key }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) await chrome.storage.session.remove('key');  // askdnd restarted: open it again to reconnect
  if (!r.ok) throw new Error(j.error || j.detail || 'askdnd answered ' + r.status + '.');
  return j;
}
async function sheetTabs(ddbId) {
  return (await chrome.tabs.query({ url: 'https://www.dndbeyond.com/characters/*' })).filter(t => ddbIdOf(t.url) === String(ddbId));
}
async function toAskdndTabs(msg) {
  for (const t of await chrome.tabs.query({ url: ASKDND + '/*' })) chrome.tabs.sendMessage(t.id, msg).catch(() => {});
}
async function refreshPanels(ddbId) {  // every open tab of this sheet; returns askdnd's state (or null)
  let st = null, error = null;
  try { st = await api('GET', '/bridge/by-ddb/' + ddbId); } catch (err) { error = String(err.message || err); }
  for (const t of await sheetTabs(ddbId)) chrome.tabs.sendMessage(t.id, st ? { type: 'panel-state', state: st } : { type: 'panel-state', error }).catch(() => {});
  return st;
}
async function apply(ddbId, change, ops, tabId) {  // through the tab you clicked in, else any copy of the sheet
  const tabs = await sheetTabs(ddbId);
  const tab = tabs.find(t => t.id === tabId) || tabs[0];
  if (!tab) {
    await api('POST', '/bridge/result/' + change, { ok: false, error: "Open the character's D&D Beyond sheet in this browser." }).catch(() => {});
    toAskdndTabs({ type: 'bridge-update' });
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: 'apply', change, ops });
}

chrome.runtime.onMessage.addListener((m, sender) => {
  (async () => {
    if (m.type === 'key') { await chrome.storage.session.set({ key: m.key }); for (const t of await chrome.tabs.query({ url: 'https://www.dndbeyond.com/characters/*' })) refreshPanels(ddbIdOf(t.url)); return; }
    const here = ddbIdOf(sender.tab && sender.tab.url);  // set when the message comes from a D&D Beyond sheet
    if (m.type === 'apply') return apply(m.ddbId, m.change, m.ops);  // from askdnd's own tab
    if (!here) return;
    if (m.type === 'ddb-tab' || m.type === 'panel-refresh') return refreshPanels(here);
    if (m.type === 'ddb-saved') {
      const st = await refreshPanels(here);
      if (st) { await api('POST', '/bridge/changed/' + st.character.id).catch(() => {}); await refreshPanels(here); toAskdndTabs({ type: 'bridge-update' }); }
      return;
    }
    if (m.type === 'ddb-applied') {
      // Every other open copy of this sheet still shows the old numbers, and D&D Beyond's page would save them back over
      // the new ones on its next change: reload them all (the tab that made the change reloads itself)
      if (m.ok) for (const t of await sheetTabs(here)) if (t.id !== sender.tab.id) chrome.tabs.reload(t.id);
      await api('POST', '/bridge/result/' + m.change, { ok: m.ok, error: m.error }).catch(() => {});
      await refreshPanels(here); toAskdndTabs({ type: 'bridge-update' });
      return;
    }
    // From the panel beside the sheet
    try {
      const st = await api('GET', '/bridge/by-ddb/' + here);
      if (m.type === 'drink') { const ch = await api('POST', `/bridge/drink/${st.character.id}/${m.itemId}`); await refreshPanels(here); await apply(here, ch.id, ch.ops, sender.tab.id); }
      if (m.type === 'retry') { const c = st.changes.find(x => x.id === m.change); if (c) await apply(here, c.id, c.ops, sender.tab.id); }
      if (m.type === 'undo') await api('POST', '/bridge/dismiss/' + m.change);
    } catch (err) {
      chrome.tabs.sendMessage(sender.tab.id, { type: 'panel-state', error: String(err.message || err) }).catch(() => {});
      return;
    }
    await refreshPanels(here); toAskdndTabs({ type: 'bridge-update' });
  })();
});
