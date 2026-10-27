// Runs inside the D&D Beyond sheet's own page (injected by ddb.js), as the signed-in person.
// 1. Hears the sheet save: every successful change it sends to character-service is reported (no numbers: askdnd reads
//    the sheet back from D&D Beyond itself).
// 2. Makes askdnd's batches: only the two requests askdnd may make (OPS), only for the character whose sheet this is,
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
  async function auth(fresh) {
    if (!fresh && token && Date.now() < until) return token;
    const r = await ofetch('https://auth-service.dndbeyond.com/v1/cobalt-token', { method: 'POST', credentials: 'include' });
    if (!r.ok) throw new Error('Sign in to D&D Beyond in this browser.');
    const j = await r.json();
    token = j.token; until = Date.now() + Math.max(30, (j.ttl || 60) - 30) * 1000;
    return token;
  }
  async function call(method, path, body) {  // signed in as this person; a refused token is renewed once
    for (const fresh of [false, true]) {
      const r = await ofetch(CS + path, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: 'Bearer ' + await auth(fresh) }, body: body ? JSON.stringify(body) : undefined });
      if (r.status === 401 && !fresh) continue;
      if (!r.ok) throw new Error('D&D Beyond answered ' + r.status + '.');
      return r.json().catch(() => ({}));
    }
  }
  const HP = '/character/v5/life/hp/damage-taken';
  const valueNow = (d, op) => op.path === HP
    ? { removedHitPoints: d.removedHitPoints, temporaryHitPoints: d.temporaryHitPoints || 0 }
    : { item: op.to.item, quantity: ((d.inventory || []).find(i => i.id === op.to.item) || {}).quantity };
  const same = (a, b) => Object.keys(b).every(k => a[k] === b[k]);

  // One batch at a time for this sheet: D&D Beyond can drop writes that reach a character at the same moment while
  // still answering OK to each (DDB Importer's experience, its src/updater/syncQueue.ts); askdnd's read-back catches a
  // dropped one, and this stops causing them.
  let queue = Promise.resolve();
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'apply') return;
    queue = queue.then(() => run(e.data.batch), () => run(e.data.batch));
  });
  // Each total is checked against what D&D Beyond has right now (signed in, so not a cached copy): already there is
  // skipped (a repeat never doubles a change), still at the old value is written, anything else is someone else's
  // change, and then nothing is written at all.
  async function run(batch) {
    const id = batch.id;
    try {
      for (const op of batch.ops) {
        if (!OPS.has(op.path)) throw new Error("That isn't a change askdnd may make.");
        if (String(op.body && op.body.characterId) !== sheetId()) throw new Error("A different character's sheet is open.");
      }
      const d = (await call('GET', '/character/v5/character/' + sheetId())).data || {};
      const todo = [], conflicts = [];
      for (const op of batch.ops) {
        const v = valueNow(d, op);
        if (same(v, op.to)) continue;
        if (same(v, op.from)) todo.push(op); else conflicts.push(op.field);
      }
      if (conflicts.length) return post({ type: 'applied', batch: id, ok: false, conflicts });
      for (const op of todo) await call('PUT', op.path, op.body);
      post({ type: 'applied', batch: id, ok: true, wrote: todo.length > 0 });
      if (todo.length) setTimeout(() => location.reload(), 400);  // show what D&D Beyond has now; never save old numbers back
    } catch (err) {
      post({ type: 'applied', batch: id, ok: false, error: String((err && err.message) || err) });
    }
  }
})();
