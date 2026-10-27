// Runs inside the D&D Beyond sheet's own page (injected by ddb.js), as the signed-in person.
// 1. Hears the sheet save: every successful change it sends to character-service is reported (no numbers: askdnd reads
//    the sheet back from D&D Beyond itself).
// 2. Makes askdnd's changes: only the two requests askdnd may make (OPS), only for the character whose sheet this is,
//    with a short-lived token D&D Beyond gives this page from its own sign-in. Nothing is stored. Then the sheet
//    reloads, so it shows what D&D Beyond now has and can't save an old number over it.
(() => {
  if (window.__askdndBridge) return;
  window.__askdndBridge = true;
  const CS = 'https://character-service.dndbeyond.com';
  const OPS = new Set(['/character/v5/life/hp/damage-taken', '/character/v5/inventory/item/quantity']);
  const sheetId = () => (location.pathname.match(/\/characters\/(\d+)/) || [])[1];
  const post = m => window.postMessage({ askdndBridge: 'from-page', characterId: sheetId(), ...m }, location.origin);
  const saved = (method, url) => {
    try { const u = new URL(url, location.href); if (u.origin === CS && method !== 'GET') post({ type: 'saved', path: u.pathname }); } catch (e) { /* not a URL */ }
  };

  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__askdnd = [String(m).toUpperCase(), String(u)]; return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function () {
    const x = this;
    if (x.__askdnd) x.addEventListener('loadend', () => { if (x.status >= 200 && x.status < 300) saved(...x.__askdnd); });
    return send.apply(this, arguments);
  };
  const ofetch = window.fetch;
  window.fetch = async function (input, init) {
    const res = await ofetch.apply(this, arguments);
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (res.ok) saved(method, typeof input === 'string' ? input : input.url);
    return res;
  };

  let token = null, until = 0;
  async function auth() {
    if (token && Date.now() < until) return token;
    const r = await ofetch('https://auth-service.dndbeyond.com/v1/cobalt-token', { method: 'POST', credentials: 'include' });
    if (!r.ok) throw new Error('Sign in to D&D Beyond in this browser.');
    const j = await r.json();
    token = j.token; until = Date.now() + Math.max(30, (j.ttl || 60) - 30) * 1000;
    return token;
  }
  // One change at a time for this sheet: D&D Beyond can drop writes that reach a character at the same moment while
  // still answering OK to each (DDB Importer's experience, its src/updater/syncQueue.ts); the read-back catches a
  // dropped one, and this stops causing them.
  let queue = Promise.resolve();
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'apply') return;
    queue = queue.then(() => run(e.data), () => run(e.data));
  });
  async function run({ change, ops }) {
    try {
      for (const op of ops) {
        if (!OPS.has(op.path)) throw new Error("That isn't a change askdnd may make.");
        if (String(op.body && op.body.characterId) !== sheetId()) throw new Error("A different character's sheet is open.");
      }
      // What D&D Beyond has right now (signed in, so not a cached copy): if it isn't what askdnd worked the change out
      // from, someone changed it meanwhile, and writing would put an old number back. Make nothing; askdnd reads again.
      const now = await ofetch(CS + '/character/v5/character/' + sheetId(), { headers: { Accept: 'application/json', Authorization: 'Bearer ' + await auth() } });
      if (!now.ok) throw new Error("Couldn't read the sheet from D&D Beyond (" + now.status + ').');
      const d = (await now.json()).data || {};
      for (const op of ops) {
        const f = op.from || {};
        const item = f.item ? (d.inventory || []).find(i => i.id === f.item) : null;
        const same = f.item ? item && item.quantity === f.quantity : d.removedHitPoints === f.removedHitPoints && (d.temporaryHitPoints || 0) === f.temporaryHitPoints;
        if (!same) throw new Error('D&D Beyond changed since askdnd read it. Nothing was changed: try again.');
      }
      for (const op of ops) {
        const r = await ofetch(CS + op.path, { method: 'PUT', headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: 'Bearer ' + await auth() }, body: JSON.stringify(op.body) });
        if (!r.ok) throw new Error('D&D Beyond refused it (' + r.status + ').');
      }
      post({ type: 'applied', change, ok: true });
      setTimeout(() => location.reload(), 400);
    } catch (err) {
      post({ type: 'applied', change, ok: false, error: String((err && err.message) || err) });
    }
  }
})();
