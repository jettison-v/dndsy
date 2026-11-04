// Runs inside a D&D Beyond page, as the signed-in person: a character's sheet (injected by ddb.js), or, for the DM as a
// backup, any other D&D Beyond page (carry.js), where only 2. runs.
// 1. Hears the sheet save: every successful change it sends to character-service is reported (no numbers: askdnd reads
//    the sheet back from D&D Beyond itself).
// 2. Makes askdnd's batches: only the requests askdnd may make (WRITES), only for the character the batch names (on a
//    sheet, the one whose sheet this is, unless the DM's browser is making a closed sheet's change: app/ddb_bridge.py
//    `carried`), with a short-lived token D&D Beyond gives this page from its own sign-in. Nothing is stored.
// 3. Hears rolls made on the sheet: the finished roll the sheet sends to D&D Beyond's game log is passed on to askdnd's
//    Table rolls. And sends the player's askdnd rolls to the game log (app/gamelog.py; Brett, 2026-10-29), as
//    askdnd's own: source "askdnd" and ⓐ in the name, never passed off as D&D Beyond's; askdnd builds each one, this
//    page adds only who is signed in, an id and the time.
// 5. Reads the sheet for askdnd, signed in as the sheet itself reads it, whenever askdnd needs it read: after the sheet
//    saves, after askdnd's change is written, and on the regular pull. D&D Beyond's public copy, which askdnd reads
//    otherwise, can trail a save by minutes (Nov 3: a Soul Coin's use given back on D&D Beyond stayed spent).
// 4. Keeps the open sheet showing what D&D Beyond has (Brett, 2026-10-27: no reloading): after askdnd changes the
//    character, or when askdnd's read of D&D Beyond differs from what this page holds, the page reads the character as
//    the sheet does when it opens and hands it to the sheet's own store, so it can't save an old number back.
(() => {
  if (window.__askdndBridge) return;
  window.__askdndBridge = true;
  const CS = 'https://character-service.dndbeyond.com';
  // The same list as app/ddb_fields.py WRITES (tests/test_ddb_bridge.py checks)
  const WRITES = new Set([
    'PUT /character/v5/life/hp/damage-taken', 'PUT /character/v5/life/death-saves', 'PUT /character/v5/character/inspiration',
    'PUT /character/v5/condition', 'DELETE /character/v5/condition', 'POST /character/v5/character/rest/short',
    'PUT /character/v5/spell/slots', 'PUT /character/v5/spell/pact-magic',
    'PUT /character/v5/action/limited-use', 'PUT /character/v5/inventory/item/quantity', 'PUT /character/v5/inventory/item/equipped',
    'PUT /character/v5/inventory/item/attuned', 'PUT /character/v5/inventory/item/charge', 'PUT /character/v5/inventory/item/move',
    'POST /character/v5/inventory/item', 'DELETE /character/v5/inventory/item', 'PUT /character/v5/spell/prepared',
    'PUT /character/v5/inventory/currency/copper', 'PUT /character/v5/inventory/currency/silver',
    'PUT /character/v5/inventory/currency/electrum', 'PUT /character/v5/inventory/currency/gold',
    'PUT /character/v5/inventory/currency/platinum',
    // (0.10.0: one of the character's creatures' Hit Points, and its maximum: a character value of type 43 only, below)
    'PUT /character/v5/creature/hp', 'PUT /character/v5/custom/value', 'DELETE /character/v5/custom/value',
    // (0.11.0: a familiar kept in step: switched on or off on its Extras, what it is (type 44, below), its name)
    'PUT /character/v5/creature/status', 'PUT /character/v5/creature']);
  // The only character values askdnd may set: a creature's maximum and what it is (D&D Beyond's CREATURE_HIT_POINTS and
  // CREATURE_TYPE_OVERRIDE)
  const CREATURE_VALUES = new Set([43, 44]);
  const sheetId = () => (location.pathname.match(/\/characters\/(\d+)/) || [])[1];
  const onSheet = !!sheetId();  // (elsewhere it only makes batches: nothing of the page is heard or changed)
  const post = m => window.postMessage({ askdndBridge: 'from-page', characterId: sheetId(), ...m }, location.origin);
  let saving = 0;  // the sheet's own changes on their way to D&D Beyond
  const isSave = (method, url) => {
    try { const u = new URL(url, location.href); return u.origin === CS && method !== 'GET'; } catch (e) { return false; }
  };
  const saved = (method, url) => {  // (`fresh`: this page reads the sheet for askdnd once the saves stop)
    try { const u = new URL(url, location.href); post({ type: 'saved', path: u.pathname, fresh: true }); freshSoon(); } catch (e) { /* not a URL */ }
  };
  // The sheet for askdnd, as it is once the sheet's own changes are saved (5.): `why` "saved" or "pull"
  let freshTimer = null;
  const freshSoon = () => { clearTimeout(freshTimer); freshTimer = setTimeout(() => fresh('saved'), 1500); };
  async function fresh(why) {
    let data = null;
    try { await quiet(); data = await character(); } catch (e) { /* askdnd reads the public copy instead */ }
    post({ type: 'fresh', why, data });
  }

  const ofetch = window.fetch;
  const wsend = WebSocket.prototype.send;
  let gameLog = null;  // this sheet's connection to its game's log (askdnd's rolls go out on it)
  if (onSheet) {  // hearing the sheet: its saves and its rolls
    const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) { this.__askdnd = [String(m).toUpperCase(), String(u)]; return open.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function () {
      const x = this;
      if (x.__askdnd && isSave(...x.__askdnd)) {
        saving++;
        x.addEventListener('loadend', () => { saving--; if (x.status >= 200 && x.status < 300) saved(...x.__askdnd); });
      }
      return send.apply(this, arguments);
    };
    window.fetch = async function (input, init) {
      const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      const url = typeof input === 'string' ? input : input.url;
      if (!isSave(method, url)) return ofetch.apply(this, arguments);
      saving++;
      try {
        const res = await ofetch.apply(this, arguments);
        if (res.ok) saved(method, url);
        return res;
      } finally { saving--; }
    };

    // Rolls made on this sheet: the sheet tells D&D Beyond's game log each finished roll; askdnd only listens (the message
    // goes out exactly as the sheet sent it) and passes this character's own on to Table rolls
    const asRoll = m => {
      const j = typeof m === 'string' && m.includes('dice/roll/fulfilled') ? JSON.parse(m) : null;
      return j && j.eventType === 'dice/roll/fulfilled' && j.data ? j : null;
    };
    // The game log also brings this page the rolls made elsewhere in the game: the DM's for a monster (so a player can
    // apply the hit, app/hit_points.py) and a character's made on another page. Each is passed on as it came;
    // askdnd keeps each roll once (app/ddb_bridge.py heard_in_game). Heard from the moment the page opens its connection
    const listening = new WeakSet();
    const listen = ws => {
      if (listening.has(ws)) return;
      listening.add(ws);
      if (String(ws.url).includes('game-log-api')) gameLog = ws;
      ws.addEventListener('message', e => {
        try {
          const j = asRoll(e.data);
          if (j) post({ type: 'heard', message: j });  // (this sheet's own come back too: kept once)
        } catch (err) { /* not a roll */ }
      });
    };
    window.WebSocket = new Proxy(WebSocket, { construct(t, args, nt) { const ws = Reflect.construct(t, args, nt); listen(ws); return ws; } });
    WebSocket.prototype.send = function (m) {
      try {
        const j = asRoll(m);
        if (j && String(j.entityId) === sheetId() && j.source !== 'askdnd') {  // (askdnd's own: Table rolls has it)
          post({ type: 'roll', roll: { id: j.data.rollId, action: j.data.action, rolls: j.data.rolls, scope: j.messageScope, target: j.messageTarget, user: j.userId } });
        }
      } catch (e) { /* not a roll */ }
      listen(this);  // (a connection opened before this script ran)
      return wsend.apply(this, arguments);
    };
  }

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
  // The character as the sheet reads it when it opens (with its custom items)
  const character = async (id = sheetId()) => (await call('GET', '/character/v5/character/' + id + '?includeCustomItems=true')).data || {};

  // Where a field is in a character, as app/ddb_fields.py `pick` reads it (keep the two the same)
  function pick(data, steps) {
    const isDict = x => x && typeof x === 'object' && !Array.isArray(x);
    let v = data;
    for (const s of steps) {
      if (isDict(s) && 'or' in s) { if (v == null) v = s.or; }
      else if (isDict(s) && 'present' in s) v = v != null;
      else if (v == null) continue;
      else if (s === '*') v = isDict(v) ? Object.values(v).filter(Array.isArray).flat() : null;
      else if (typeof s === 'string') v = isDict(v) ? v[s] : null;
      else if ('read' in s) { const o = {}; for (const k of Object.keys(s.read)) o[k] = pick(v, s.read[k]); v = o; }
      else if ('sum' in s) {
        const [where, want, key] = s.sum;
        v = Array.isArray(v) ? v.filter(x => isDict(x) && String(pick(x, where)) === String(want)).reduce((t, x) => t + (x[key] || 0), 0) : null;
      } else {  // the one in a list matching every key given (an id; a character value's type and the creature it's for)
        v = Array.isArray(v) ? (v.find(x => isDict(x) && Object.entries(s).every(([k, w]) => String(x[k]) === String(w))) || null) : null;
      }
      if (v === undefined) v = null;
    }
    return v;
  }
  const same = (a, b) => {
    if (a === b) return true;
    if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every(k => same(a[k], b[k]));
  };

  // ---- the sheet's own store: where the open page keeps the character it shows and saves from
  let store = null;
  function findStore() {  // (from a page element React drew, up to the provider that holds the store: the sheet's own
    if (store) return store;  // part of the page first, since the site's menu and banners are drawn by React too, without it)
    for (const q of ['#character-tools-target *', 'body *']) {
      let tries = 0;
      for (const el of document.querySelectorAll(q)) {
        const k = Object.keys(el).find(n => n.startsWith('__reactFiber$'));
        if (!k) continue;
        for (let f = el[k], n = 0; f && n < 200; f = f.return, n++) {
          const s = f.memoizedProps && f.memoizedProps.store;
          if (s && typeof s.getState === 'function' && typeof s.dispatch === 'function' && s.getState().character) return (store = s);
        }
        if (++tries > 2000) break;
      }
    }
    return null;
  }
  const held = () => { const s = findStore(); return s ? s.getState().character : null; };
  const quiet = async () => {  // never while the sheet's own change is on its way (it would show the number before it)
    for (let i = 0; i < 50 && (saving > 0 || ((findStore() || { getState: () => ({}) }).getState().syncTransaction || {}).active); i++) await new Promise(r => setTimeout(r, 100));
  };
  // Show what D&D Beyond has now. In place, with the store's own "set character" (nothing is written, and no request
  // but the read the sheet makes when it opens); where D&D Beyond's page has changed so the store can't be found or
  // doesn't take it, the sheet reloads as it did before.
  let showing = Promise.resolve();
  function show() {
    showing = showing.then(async () => {
      await quiet();
      const d = await character();
      const s = findStore();
      if (s) {
        s.dispatch({ type: 'character.CHARACTER_SET', payload: d });
        const now = s.getState().character;
        if (now && now.removedHitPoints === d.removedHitPoints && (now.inventory || []).length === (d.inventory || []).length) return 'in place';
      }
      setTimeout(() => location.reload(), 200);
      return 'reloaded';
    }).catch(() => 'not shown');
    return showing;
  }

  // One batch at a time for this sheet: D&D Beyond can drop writes that reach a character at the same moment while
  // still answering OK to each (DDB Importer's experience, its src/updater/syncQueue.ts); askdnd's read-back catches a
  // dropped one, and this stops causing them.
  let queue = Promise.resolve();
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data) return;
    if (e.data.askdndBridge === 'apply') queue = queue.then(() => run(e.data.batch), () => run(e.data.batch));
    if (!onSheet) return;
    if (e.data.askdndBridge === 'show') show();  // askdnd changed this character from another copy of the sheet
    if (e.data.askdndBridge === 'read') fresh('pull');  // the regular pull (5.)
    if (e.data.askdndBridge === 'check') check(e.data.fields || []);
    if (e.data.askdndBridge === 'gamelog') toGameLog(e.data.messages || []);
  });
  // askdnd's rolls into the game log, on this sheet's own connection: only this character's, only in this sheet's game
  function toGameLog(messages) {
    if (!gameLog || gameLog.readyState !== 1) return post({ type: 'gamelog', sent: 0 });
    const q = new URL(gameLog.url).searchParams, user = q.get('userId'), game = q.get('gameId');
    let sent = 0;
    for (const m of messages) {
      if (m.source !== 'askdnd' || String(m.entityId) !== sheetId() || String(m.gameId) !== game || !user) continue;
      const self = m.messageScope === 'userId' && m.messageTarget === 'self';  // (a roll the player keeps to themself)
      const target = self ? user : m.messageTarget;
      const data = { ...m.data, context: { ...m.data.context, messageTarget: target } };
      wsend.call(gameLog, JSON.stringify({ id: crypto.randomUUID(), dateTime: String(Date.now()), userId: user, ...m, data, messageTarget: target }));
      sent++;
    }
    post({ type: 'gamelog', sent });
  }
  // askdnd just read D&D Beyond: if this page holds anything else, it shows D&D Beyond's numbers (a change made on
  // another device, or in another copy of this sheet)
  async function check(fields) {
    const c = held();
    if (!c || !fields.length) return;
    if (fields.some(f => !same(pick(c, f.read), f.value))) show();
  }
  // Each total is checked against what D&D Beyond has right now (signed in, so not a cached copy): already there is
  // skipped (a repeat never doubles a change), still at the old value is written, anything else is someone else's
  // change, and then nothing is written at all.
  // The batch names its character (`ddb`); every request must be for that one.
  async function run(batch) {
    const id = batch.id, who = String(batch.ddb || sheetId() || '');
    const done = m => post({ type: 'applied', batch: id, ddb: who, ...m });
    try {
      if (!who) throw new Error('No character named.');
      for (const op of batch.ops) {
        if (!WRITES.has(op.method + ' ' + op.path)) throw new Error("That isn't a change askdnd may make.");
        if (String(op.body && op.body.characterId) !== who) throw new Error("A request for a different character.");
        if (op.path.endsWith('/custom/value') && !CREATURE_VALUES.has(Number(op.body.typeId))) throw new Error("That isn't a change askdnd may make.");
      }
      const d = await character(who);
      const todo = [], conflicts = [];
      for (const op of batch.ops) {
        const v = pick(d, op.read);
        if (same(v, op.to)) continue;
        if (same(v, op.from)) todo.push(op); else conflicts.push(op.field);
      }
      if (conflicts.length) return done({ ok: false, conflicts, data: d });
      for (const op of todo) await call(op.method, op.path, op.body);
      // askdnd confirms from this read, made right after writing (5.); read again (signed in) while D&D Beyond doesn't show
      // the change yet, a few times, so a slow save isn't taken for a lost one (0.10.0)
      let after = d;
      for (let i = 0; todo.length && i < 4; i++) {
        if (i) await new Promise(r => setTimeout(r, 750));
        after = await character(who).catch(() => null);
        if (after && todo.every(op => same(pick(after, op.read), op.to))) break;
      }
      done({ ok: true, wrote: todo.length > 0, data: after });
      if (todo.length && who === sheetId()) show();  // the sheet shows what D&D Beyond has now, and can't save old numbers back
    } catch (err) {
      done({ ok: false, error: String((err && err.message) || err) });
    }
  }
})();
