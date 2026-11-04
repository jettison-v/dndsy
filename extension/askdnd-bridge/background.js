// The extension's go-between: middleware between askdnd and D&D Beyond (app/ddb_bridge.py says how it repairs itself).
// It finds the open D&D Beyond sheets from the tabs (Chrome may stop this worker at any time, so it keeps nothing it
// can't find again), collects each sheet's outbox from askdnd and has the sheet make it, reports what D&D Beyond
// saved, and tells askdnd every minute that it's on. Stores only its key to askdnd, and which askdnd gave it.
// The DM as a backup (app/ddb_bridge.py `carried`): in a DM's browser, any open D&D Beyond page makes the changes of a
// character whose own sheet is closed, for the sheets askdnd names (`carry`).
// The askdnd sites it works with (manifest.json's own list; the store's copy leaves out localhost: scripts/build_extension.py)
const SITES = ['https://beta.askdnd.ai', 'https://askdnd.ai', 'http://localhost:8000'];
const ddbIdOf = url => ((url || '').match(/^https:\/\/www\.dndbeyond\.com\/characters\/(\d+)/) || [])[1];
const gameOf = url => ((url || '').match(/^https:\/\/www\.dndbeyond\.com\/games\/(\d+)/) || [])[1];
const DDB_PAGES = 'https://www.dndbeyond.com/*';

// The D&D Beyond games askdnd follows for this person (its campaigns with the bridge): only those are told about,
// so nothing about any other game they open leaves this browser. Asked again every 5 minutes.
async function followed() {
  const { games } = await chrome.storage.session.get('games');
  if (games && Date.now() - games.at < 5 * 60 * 1000) return games.ids;
  const ids = (await api('GET', '/bridge/games')).games || [];
  await chrome.storage.session.set({ games: { ids, at: Date.now() } });
  return ids;
}
// The sheets and VTT pages open now, by tab, to tell askdnd when the last one closes (Chrome forgets a closed tab's
// address, and may stop this worker, so they're kept in session storage)
async function opened(tabId, what) {
  const { tabsOpen = {} } = await chrome.storage.session.get('tabsOpen');
  const was = tabsOpen[tabId];
  tabsOpen[tabId] = what;
  await chrome.storage.session.set({ tabsOpen });
  // The tab making a batch was reloaded or moved on: its answer won't come, so the next one needn't wait half a minute
  // (0.10.0; a sheet reloaded mid-write held every change for that character until then)
  for (const [ddbId, tab] of busy) if (tab === tabId) busy.delete(ddbId);
  // The tab went from one sheet to another page (another character of the same account, its campaign): the sheet it
  // showed is closed once no other tab has it (0.10.0; Nov 3: two sheets of one account both said Connected for a while)
  if (was && was.sheet && was.sheet !== what.sheet && !(await sheetTabs(was.sheet)).filter(t => t.id !== tabId).length) {
    clearTimeout(quiet.get(was.sheet));
    api('POST', '/bridge/closed/' + was.sheet).catch(() => {});
  }
}
chrome.tabs.onRemoved.addListener(async tabId => {
  const { tabsOpen = {} } = await chrome.storage.session.get('tabsOpen');
  const was = tabsOpen[tabId];
  for (const [ddbId, tab] of busy) if (tab === tabId) busy.delete(ddbId);  // (its answer won't come)
  if (!was) return;
  delete tabsOpen[tabId];
  await chrome.storage.session.set({ tabsOpen });
  // (Chrome may still list the tab that's closing: it doesn't count)
  const others = tabs => tabs.filter(t => t.id !== tabId);
  if (was.sheet && !others(await sheetTabs(was.sheet)).length) {
    clearTimeout(quiet.get(was.sheet));
    api('POST', '/bridge/closed/' + was.sheet).catch(() => {});
  }
  const vtts = was.game ? others(await chrome.tabs.query({ url: 'https://www.dndbeyond.com/games/' + was.game + '*' })) : [];
  if (was.game && !vtts.length) api('POST', '/bridge/fight/' + was.game, { closed: true }).catch(() => {});  // no VTT here hears that fight now
  if (!others(await chrome.tabs.query({ url: DDB_PAGES })).length) carry(tabId);  // no D&D Beyond page here now: the DM isn't
});

async function api(method, path, body) {
  const { key, askdnd } = await chrome.storage.session.get(['key', 'askdnd']);  // from askdnd.js
  if (!key || !askdnd) throw new Error('Open askdnd once in this browser, signed in, to connect the extension.');
  const r = await fetch(askdnd + path, { method, headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Askdnd-Bridge': key }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) await chrome.storage.session.remove('key');  // askdnd restarted: an askdnd page reconnects it
  if (!r.ok) throw new Error(j.error || j.detail || 'askdnd answered ' + r.status + '.');
  return j;
}
async function sheetTabs(ddbId) {
  const tabs = await chrome.tabs.query({ url: 'https://www.dndbeyond.com/characters/*' });
  return ddbId ? tabs.filter(t => ddbIdOf(t.url) === String(ddbId)) : tabs;
}
async function toAskdndTabs(msg) {
  const { askdnd } = await chrome.storage.session.get('askdnd');
  if (askdnd) for (const t of await chrome.tabs.query({ url: askdnd + '/*' })) chrome.tabs.sendMessage(t.id, msg).catch(() => {});
}
async function refreshPanels(ddbId) {
  let st = null, error = null;
  try { st = await api('GET', '/bridge/by-ddb/' + ddbId); } catch (err) { error = String(err.message || err); }
  const { askdnd } = await chrome.storage.session.get('askdnd');
  for (const t of await sheetTabs(ddbId)) chrome.tabs.sendMessage(t.id, st ? { type: 'panel-state', state: st, askdnd } : { type: 'panel-state', error }).catch(() => {});
  return st;
}

// A word to askdnd that was on its way as the last tab closed tells it the sheet is open, after the tab's own word that
// it closed (a real fight, 2026-10-30: one run in three kept saying Connected): say it again
async function stillClosed(ddbId) {
  if ((await sheetTabs(ddbId)).length) return false;
  await api('POST', '/bridge/closed/' + ddbId).catch(() => {});
  return true;
}

// The DM as a backup: askdnd hears that a D&D Beyond page is open in this browser (`pages`; none, once the last one
// closes, and `except` is a tab closing now) and names the closed sheets with a change for it to make. In anyone but a
// campaign's DM's browser it names none. Answers how soon to ask again. However many pages tick, it asks one at a time
// and at most every CARRY_GAP (`now`: askdnd just queued a change, or the last page closed, so it asks once this one's
// answered). Only an answer counts toward the gap: nothing to ask yet (no page, no key) doesn't hold the next one back.
const CARRY_GAP = 4000;
let carryOut = null, carryAt = 0, carryEvery = 0;
async function carry(except, now) {
  if (except === undefined && !now) {
    if (carryOut) return carryOut;
    if (Date.now() - carryAt < CARRY_GAP) return carryEvery;
  } else if (carryOut) await carryOut.catch(() => {});
  carryOut = carryOnce(except).then(every => {
    if (every === null) return 0;
    carryAt = Date.now(); carryEvery = every;
    return every;
  }).finally(() => { carryOut = null; });
  return carryOut;
}
async function carryOnce(except) {  // how soon to ask again, or null when askdnd wasn't asked
  const pages = (await chrome.tabs.query({ url: DDB_PAGES })).filter(t => t.id !== except).length;
  if (!pages && except === undefined) return null;  // ("none" is said once, as the last page closes)
  let r;
  try { r = await api('POST', '/bridge/carry', { pages }); } catch (err) { return null; }
  await chrome.storage.session.set({ carrying: r.sheets || [] });
  for (const id of r.sheets || []) deliver(String(id));
  return r.every || 0;
}
const carrying = async ddbId => ((await chrome.storage.session.get('carrying')).carrying || []).includes(String(ddbId));

const busy = new Map();  // sheets with a batch out right now (one at a time per character), and the tab making it
const awake = t => !t.discarded && !t.frozen;  // never a tab Chrome has put to sleep (it can't run the change)
async function deliver(ddbId, tabId) {
  if (!ddbId || busy.has(ddbId)) return;
  // The tab you clicked in first, then visible ones
  const order = (a, b) => (b.id === tabId) - (a.id === tabId) || (b.active - a.active) || (b.lastAccessed || 0) - (a.lastAccessed || 0);
  let tabs = (await sheetTabs(ddbId)).filter(awake).sort(order);
  const sheet = tabs.length > 0;
  // Its sheet isn't open here: in the DM's browser, any D&D Beyond page makes it, for a sheet askdnd named
  if (!sheet && await carrying(ddbId)) tabs = (await chrome.tabs.query({ url: DDB_PAGES })).filter(awake).sort(order);
  if (!tabs.length) return;  // waits in askdnd until the sheet is open somewhere
  busy.set(ddbId, null);
  try {
    const { batch } = await api('POST', '/bridge/outbox/' + ddbId);
    if (!batch) { busy.delete(ddbId); if (sheet) await stillClosed(ddbId); return; }
    for (const t of tabs) {  // the first copy of the sheet that answers takes it (a tab left from before the extension
      try {                  // was reloaded, or one Chrome froze, doesn't)
        const r = await chrome.tabs.sendMessage(t.id, { type: 'apply', batch });
        if (r && r.took) { busy.set(ddbId, t.id); setTimeout(() => busy.delete(ddbId), 30000); return; }  // its answer comes back as 'ddb-applied'
      } catch (err) { /* no one there: try the next */ }
    }
    await api('POST', '/bridge/delivered/' + batch.id, { ok: false, error: sheet ? "No open D&D Beyond sheet answered. Reload the character's sheet." : "No open D&D Beyond page answered. Reload it." });
    busy.delete(ddbId);
  } catch (err) { busy.delete(ddbId); }
}
// Reading the sheet after it saves: once the clicks stop (fast changes, 1 → 5, are one read of the end, not a read
// per click that D&D Beyond may not show yet), and once more a few seconds later in case D&D Beyond was slow to serve
// the last save (Brett, 2026-10-27: 1 → 5 was caught as 1 → 3 until a refresh)
const QUIET_MS = 1500, AGAIN_MS = 5000;
const quiet = new Map();
function heardSoon(ddbId, tabId) {
  clearTimeout(quiet.get(ddbId));
  quiet.set(ddbId, setTimeout(async () => {
    await heard(ddbId, false, tabId);
    quiet.set(ddbId, setTimeout(() => heard(ddbId, true, tabId), AGAIN_MS));
  }, QUIET_MS));
}
// `data`: the sheet as it just read itself, signed in (ddb-page.js 5.); without it askdnd reads D&D Beyond's public copy
async function heard(ddbId, pull, tabId, data) {
  if (!(await sheetTabs(ddbId)).length) return;  // (its last tab closed since this was asked for)
  const st = await api('POST', '/bridge/heard/' + ddbId + (pull ? '?pull=1' : ''), data ? { data } : undefined).catch(() => null);
  if (await stillClosed(ddbId)) return;
  // What askdnd just read from D&D Beyond: an open copy of the sheet holding anything else shows D&D Beyond's numbers
  // (not the copy that just saved: it has its own change)
  if (st && st.check) for (const t of await sheetTabs(ddbId)) if (t.id !== tabId) chrome.tabs.sendMessage(t.id, { type: 'check', fields: st.check }).catch(() => {});
  await refreshPanels(ddbId); toAskdndTabs({ type: 'bridge-update' });
  return deliver(ddbId, tabId);
}
// A sheet opened or someone used it: askdnd keeps the bridge awake (and reads the sheet when its copy is old)
const active = ddbId => api('POST', '/bridge/active', { sheet: ddbId }).catch(() => {});
// Every 30 seconds: tell askdnd the extension is on, and pull each open sheet (a save the extension missed, or an
// answer that never reached askdnd, is corrected here)
async function hello() {
  const sheets = [...new Set((await sheetTabs()).map(t => ddbIdOf(t.url)).filter(Boolean))];
  let h;
  try { h = await api('POST', '/bridge/hello', { sheets }); } catch (err) { return; /* not connected yet */ }
  carry();
  if (!h.awake || !h.awake.awake) return;  // asleep (no one is using askdnd or a sheet): no background pulls
  for (const id of sheets) pull(id);
}
// A pull: an open copy of the sheet reads itself for askdnd; a page from before this version can't, and askdnd reads
// the public copy
async function pull(ddbId) {
  for (const t of (await sheetTabs(ddbId)).filter(awake)) {
    try { const r = await chrome.tabs.sendMessage(t.id, { type: 'read' }); if (r && r.took) return; } catch (err) { /* the next */ }
  }
  return heard(ddbId, true);
}
// A batch made, on a sheet or by the DM's browser on any D&D Beyond page (`ddbId`: the character it was for)
async function applied(ddbId, m, tabId) {
  // Every other open copy of this sheet shows the old numbers, and D&D Beyond's page would save them back over the
  // new ones on its next change: each shows D&D Beyond's numbers now, in place (the tab that wrote does it itself)
  if (m.wrote) for (const t of await sheetTabs(ddbId)) if (t.id !== tabId) chrome.tabs.sendMessage(t.id, { type: 'show' }).catch(() => {});
  await api('POST', '/bridge/delivered/' + m.batch, { ok: m.ok, error: m.error, conflicts: m.conflicts, data: m.data }).catch(() => {});
  busy.delete(ddbId);
  await refreshPanels(ddbId); toAskdndTabs({ type: 'bridge-update' });
  return deliver(ddbId);  // the next batch, if any
}
chrome.alarms.create('askdnd-bridge', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'askdnd-bridge') hello(); });
chrome.runtime.onStartup.addListener(hello);
chrome.runtime.onInstalled.addListener(hello);

chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (m.type === 'vtt-hello') {  // a VTT page opened: does askdnd follow its game? (its badge shows only then)
    const game = gameOf(sender.tab && sender.tab.url);
    followed().then(async ids => {
      const yes = !!game && ids.includes(game);
      if (yes) await opened(sender.tab.id, { game });
      reply({ followed: yes });
    }, () => reply({ followed: false }));
    return true;  // (answers later)
  }
  if (m.type === 'vtt-tick') {  // a VTT page asks for initiative numbers to set (0.12.0; askdnd gives the DM's page any)
    const game = gameOf(sender.tab && sender.tab.url);
    followed().then(async ids => {
      if (!game || !ids.includes(game)) return reply({ sets: [], every: 60 });
      reply(await api('POST', '/bridge/vtt/' + game).catch(() => ({ sets: [], every: 60 })));
    }, () => reply({ sets: [], every: 60 }));
    return true;
  }
  if (m.type === 'carry-tick') {  // any D&D Beyond page (carry.js, or a sheet's ddb.js): how soon it asks again
    if (sender.tab && !ddbIdOf(sender.tab.url)) opened(sender.tab.id, { page: true });  // (a sheet is kept as a sheet)
    carry().then(every => reply({ every }), () => reply({ every: 0 }));
    return true;
  }
  (async () => {
    if (m.type === 'key') {  // from an askdnd page (Chrome says which site sent it, not the page)
      const askdnd = sender.origin || (sender.tab && new URL(sender.tab.url).origin);
      if (!SITES.includes(askdnd)) return;
      await chrome.storage.session.set({ key: m.key, askdnd }); hello(); for (const t of await sheetTabs()) refreshPanels(ddbIdOf(t.url)); return;
    }
    if (m.type === 'deliver') return (await sheetTabs(String(m.ddbId))).length ? deliver(String(m.ddbId)) : carry(undefined, true);  // askdnd's own tab queued something (no sheet here: the DM's browser may make it)
    if (m.type === 'gamelog') {  // a roll made in askdnd, for the game log: from one open copy of the sheet only
      const askdnd = sender.origin || (sender.tab && new URL(sender.tab.url).origin);
      if (!SITES.includes(askdnd)) return;
      for (const t of (await sheetTabs(String(m.ddbId))).filter(t => !t.discarded).sort((a, b) => (b.active - a.active) || (b.lastAccessed || 0) - (a.lastAccessed || 0))) {
        try { const r = await chrome.tabs.sendMessage(t.id, { type: 'gamelog', messages: m.messages }); if (r && r.took) return; } catch (err) { /* not there: the next */ }
      }
      return;
    }
    if (m.type === 'wake') return hello();
    if (m.type === 'vtt-now') {  // askdnd's own tab changed the order: the VTT pages here ask at once
      for (const t of await chrome.tabs.query({ url: 'https://www.dndbeyond.com/games/*' })) chrome.tabs.sendMessage(t.id, { type: 'vtt-now' }).catch(() => {});
      return;
    }
    if (m.type === 'carry-applied' && m.ddb) return applied(String(m.ddb), m, sender.tab && sender.tab.id);
    // D&D Beyond's VTT open in this browser: the fight as it changes (vtt-page.js; askdnd only listens), for a game
    // askdnd follows only
    if (m.type === 'vtt-fight') {
      const game = gameOf(sender.tab && sender.tab.url);
      if (game && (await followed().catch(() => [])).includes(game)) return api('POST', '/bridge/fight/' + game, { fight: m.fight }).catch(() => {});
      return;
    }
    const here = ddbIdOf(sender.tab && sender.tab.url);  // the rest come from a D&D Beyond sheet
    if (!here) return;
    // A sheet opened or used: the bridge is awake (askdnd reads the sheet if its copy is a few minutes old)
    if (m.type === 'ddb-tab') { await opened(sender.tab.id, { sheet: here }); await active(here); await refreshPanels(here); hello(); return deliver(here, sender.tab.id); }
    if (m.type === 'ddb-active') return active(here);
    if (m.type === 'panel-refresh') return refreshPanels(here);
    // Try again or Undo on a change that didn't go through, from the panel beside the sheet (Bridge Review, Nov 3)
    if (m.type === 'panel-act' && /^\d+$/.test(String(m.id)) && (m.act === 'retry' || m.act === 'dismiss')) {
      await api('POST', '/bridge/' + m.act + '/' + m.id).catch(() => {});
      await refreshPanels(here); toAskdndTabs({ type: 'bridge-update' });
      return deliver(here, sender.tab.id);
    }
    if (m.type === 'ddb-saved') return m.fresh ? null : heardSoon(here, sender.tab.id);  // (a fresh read follows: 'ddb-fresh')
    if (m.type === 'ddb-fresh') return m.data ? heard(here, m.why === 'pull', sender.tab.id, m.data) : heardSoon(here, sender.tab.id);
    if (m.type === 'ddb-roll') return api('POST', '/bridge/roll/' + here, m.roll).catch(() => {});  // into Table rolls, "on D&D Beyond"
    if (m.type === 'ddb-heard') return api('POST', '/bridge/others-roll/' + here, m.message).catch(() => {});  // someone else's roll in the game
    if (m.type === 'ddb-applied') return applied(String(m.ddb || here), m, sender.tab.id);  // (the DM's browser can make another character's on a sheet)
  })();
});
