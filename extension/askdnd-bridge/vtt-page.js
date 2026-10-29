// Runs inside D&D Beyond's VTT page (/games/<campaign>; manifest.json, in the page's own world from the start), as the
// signed-in person. Only listens (Brett, 2026-10-29: askdnd hears the initiative order, never writes it): the VTT's
// game server sends this page the whole game when it connects (SYNC) and then each change as a named action
// (docs/plans/2026-10-24-play-state.md). The fight's part is kept here: the order, the round and whose turn, passed on
// to askdnd whenever it changes. Nothing is ever sent to D&D Beyond.
//
// How each change is followed: Next and back and the fight ending are what the VTT does with them (the turn moves on,
// past the last one into the next round). A change that re-sorts the order (starting the fight, adding or removing
// someone, a new initiative) takes the order the VTT itself worked out, from the page, a moment later; if the page
// doesn't show it, the order is sorted as the VTT does, highest initiative first (then the higher bonus), keeping whose
// turn it is.
(() => {
  if (window.__askdndVtt) return;
  const V = window.__askdndVtt = { fight: null, tokens: {} };
  const post = m => window.postMessage({ askdndBridge: 'from-vtt', ...m }, location.origin);
  const REORDER = new Set(['START_COMBAT', 'ADD_TO_COMBAT', 'ADD_TO_ENCOUNTER', 'REMOVE_FROM_ENCOUNTER', 'UPDATE_INITIATIVE',
    'UPDATE_INITIATIVE_BONUS', 'SET_ENCOUNTER_GROUP', 'UNGROUP_ENCOUNTER_ENTITY']);
  const copy = c => ({ activeId: c.activeId, combatants: c.combatants.map(x => ({ tokenId: x.tokenId, initiative: x.initiative, initiativeBonus: x.initiativeBonus })) });

  // What askdnd is told: each in the order with its name, a character's D&D Beyond id, and whether the DM hid it
  function told() {
    const f = V.fight;
    if (!f) return null;
    const counts = {};
    f.combatants.forEach(x => { const t = V.tokens[x.tokenId] || {}; counts[t.entityId] = (counts[t.entityId] || 0) + 1; });
    return { round: f.round, turn: f.turn, order: f.combatants.map(x => {
      const t = V.tokens[x.tokenId] || {};
      return { key: x.tokenId, name: (t.name || '?') + (counts[t.entityId] > 1 && t.nameSuffix ? ' ' + t.nameSuffix : ''),
        kind: t.type === 'CHARACTER' ? 'character' : 'monster', ddb_id: t.type === 'CHARACTER' ? String(t.entityId) : null,
        initiative: x.initiative, hidden: !!t.hidden, active: x.tokenId === f.activeId };
    }) };
  }
  let last = '';
  function tell() { const t = told(); const s = JSON.stringify(t); if (s === last) return; last = s; post({ type: 'fight', fight: t }); }

  function fromGame(game) {
    const ents = (game.tokens && game.tokens.entities) || {};
    V.tokens = {};
    for (const [id, t] of Object.entries(ents)) V.tokens[id] = { name: t.name, type: t.type, entityId: t.entityId, hidden: t.hidden, nameSuffix: t.nameSuffix };
    const e = game.encounter;
    V.fight = e && e.combat && e.combat.combatants ? { round: e.round, turn: e.turn, ...copy(e.combat) } : null;
  }
  // The order as the VTT drew it: its own combat, found in the page (read only)
  function pageCombat() {
    const seen = new Set();
    for (const el of document.querySelectorAll('body *')) {
      const k = Object.keys(el).find(x => x.startsWith('__reactFiber$'));
      if (!k) continue;
      for (let f = el[k]; f && !seen.has(f); f = f.return) {
        seen.add(f);
        for (let h = f.memoizedState, i = 0; h && typeof h === 'object' && i < 80; h = h.next, i++) {
          const v = h.memoizedState;
          if (v && typeof v === 'object' && 'activeId' in v && Array.isArray(v.combatants) && (!v.combatants[0] || 'tokenId' in v.combatants[0])) return v;
        }
      }
    }
    return null;
  }
  function sorted(f) {
    const active = f.activeId;
    f.combatants.sort((a, b) => (Number(b.initiative) || 0) - (Number(a.initiative) || 0) || (Number(b.initiativeBonus) || 0) - (Number(a.initiativeBonus) || 0));
    const i = f.combatants.findIndex(x => x.tokenId === active);
    if (i >= 0) f.turn = i + 1;
  }
  function apply(a) {
    const f = V.fight, p = a.payload;
    switch (a.type) {
      case 'INCREMENT_COMBAT_TURN':
        if (!f || !f.combatants.length) return;
        if (f.turn >= f.combatants.length) { f.round += 1; f.turn = 1; } else f.turn += 1;
        f.activeId = f.combatants[f.turn - 1].tokenId; return;
      case 'DECREMENT_COMBAT_TURN':
        if (!f || !f.combatants.length) return;
        if (f.turn <= 1) { f.round -= 1; f.turn = f.combatants.length; } else f.turn -= 1;
        f.activeId = f.combatants[f.turn - 1].tokenId; return;
      case 'END_COMBAT': case 'CLEAR_ENCOUNTER': V.fight = null; return;
      case 'START_COMBAT': V.fight = { round: 1, turn: 1, activeId: null, combatants: [] }; return;  // (its order: from the page)
      case 'UPDATE_INITIATIVE':
        if (f && Array.isArray(p)) p.forEach(x => f.combatants.forEach(c => { if (c.tokenId === String(x.key) && x.initiative !== null) c.initiative = x.initiative; }));
        return;
      case 'REMOVE_FROM_ENCOUNTER':
        if (f && p) f.combatants = f.combatants.filter(c => c.tokenId !== String(p.entityKey));
    }
  }
  // A token added or renamed on the map: its name for the order
  function token(a) {
    const p = a.payload;
    if (!p || typeof p !== 'object') return;
    const list = Array.isArray(p) ? p : [p];
    for (const t of list) {
      if (!t || !t.id) continue;
      const known = V.tokens[t.id] || (V.tokens[t.id] = {});
      for (const k of ['name', 'type', 'entityId', 'hidden', 'nameSuffix']) if (t[k] !== undefined) known[k] = t[k];
    }
  }
  let settle = null;
  function reorder() {  // the VTT redraws a moment after the action: take its order then
    clearTimeout(settle);
    settle = setTimeout(() => {
      const c = pageCombat();
      if (c && V.fight) { Object.assign(V.fight, copy(c)); const i = V.fight.combatants.findIndex(x => x.tokenId === V.fight.activeId); if (i >= 0) V.fight.turn = i + 1; }
      else if (V.fight) sorted(V.fight);
      tell();
    }, 400);
  }
  const listen = ws => {
    if (!String(ws.url).includes('games.dndbeyond.com')) return;
    ws.addEventListener('message', e => {
      if (typeof e.data !== 'string' || e.data[0] !== '{') return;
      let a;
      try { a = JSON.parse(e.data); } catch (err) { return; }
      if (a.type === 'SYNC' && a.payload && a.payload.game) { fromGame(a.payload.game); tell(); return; }
      if (/TOKEN/.test(a.type || '')) token(a);
      apply(a);
      if (REORDER.has(a.type)) reorder(); else tell();
    });
  };
  window.WebSocket = new Proxy(WebSocket, { construct(t, args, nt) { const ws = Reflect.construct(t, args, nt); listen(ws); return ws; } });
})();
