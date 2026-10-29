// Runs inside D&D Beyond's VTT page (/games/<campaign>; manifest.json, in the page's own world from the start), as the
// signed-in person. Only listens (Brett, 2026-10-29: askdnd hears the initiative order, never writes it): the VTT's
// game server sends this page the whole game when it connects (SYNC) and then each change as a named action
// (docs/plans/2026-10-24-play-state.md). The fight's part is kept here, the way the VTT keeps it, and passed on to
// askdnd whenever it changes: the order, the round, whose turn. Nothing is ever sent to D&D Beyond.
//
// Who's in the fight comes in two steps, as in the VTT: someone added to the encounter waits in a group (mid-fight,
// "Pending") with their initiative, and joins the order when the DM adds them to combat, the order sorted again
// (Brett, 2026-10-29: two characters added mid-fight were missed while only the order itself was followed). So the
// groups are followed too. Each action does what the VTT's own does (its reducer, read Oct 29); one askdnd doesn't
// know is kept in `log`, and the next SYNC (any VTT page opening) puts everything right.
(() => {
  if (window.__askdndVtt) return;
  const V = window.__askdndVtt = { fight: null, groups: {}, tokens: {}, log: [] };
  const post = m => window.postMessage({ askdndBridge: 'from-vtt', ...m }, location.origin);
  const FIGHT = /COMBAT|INITIATIVE|ENCOUNTER|TURN|TOKEN|MULTI_SELECT_DELETE/;

  // What askdnd is told: each in the order with its name, its picture, a character's D&D Beyond id, and whether the DM hid it
  function told() {
    const f = V.fight;
    if (!f) return null;
    const counts = {};
    f.combatants.forEach(x => { const t = V.tokens[x.tokenId] || {}; counts[t.entityId] = (counts[t.entityId] || 0) + 1; });
    return { round: f.round, turn: f.turn, order: f.combatants.map(x => {
      const t = V.tokens[x.tokenId] || {};
      return { key: x.tokenId, name: (t.name || '?') + (counts[t.entityId] > 1 && t.nameSuffix ? ' ' + t.nameSuffix : ''),
        kind: t.type === 'CHARACTER' ? 'character' : 'monster', ddb_id: t.type === 'CHARACTER' ? String(t.entityId) : null,
        initiative: x.initiative, hidden: !!t.hidden, active: x.tokenId === f.activeId,
        image: t.customImageUrl || t.imageUrl || t.fallbackImageUrl || null };  // (the picture the VTT draws it with)
    }) };
  }
  let last = '';
  function tell() { const t = told(); const s = JSON.stringify(t); if (s === last) return; last = s; post({ type: 'fight', fight: t }); }

  const num = v => (v === null || v === undefined || v === '' ? null : Number(v));
  function keepToken(id, t) {
    if (!t) return;
    const known = V.tokens[id] || (V.tokens[id] = {});
    for (const k of ['name', 'type', 'entityId', 'hidden', 'nameSuffix', 'customImageUrl', 'imageUrl', 'fallbackImageUrl']) if (t[k] !== undefined) known[k] = t[k];
  }
  function fromGame(game) {
    V.tokens = {};
    for (const [id, t] of Object.entries((game.tokens && game.tokens.entities) || {})) keepToken(id, t);
    const e = game.encounter || {};
    V.groups = JSON.parse(JSON.stringify(e.groups || {}));
    V.fight = e.combat && e.combat.combatants ? { round: e.round, turn: e.turn, activeId: e.combat.activeId,
      combatants: e.combat.combatants.map(x => ({ tokenId: String(x.tokenId), initiative: num(x.initiative), initiativeBonus: num(x.initiativeBonus) })) } : null;
  }

  // The VTT's order: higher initiative first, then the higher bonus, then monsters before characters, then by name;
  // whose turn it is stays theirs (its turn number follows them)
  function sort() {
    const f = V.fight;
    if (!f) return;
    const name = x => (V.tokens[x.tokenId] || {}).name || '', monster = x => (V.tokens[x.tokenId] || {}).type === 'MONSTER';
    f.combatants.sort((a, b) => a.initiative !== b.initiative ? (b.initiative || 0) - (a.initiative || 0)
      : a.initiativeBonus !== b.initiativeBonus ? (b.initiativeBonus || 0) - (a.initiativeBonus || 0)
      : monster(a) !== monster(b) ? (monster(a) ? -1 : 1) : name(a).localeCompare(name(b)));
    const i = f.combatants.findIndex(x => x.tokenId === f.activeId);
    if (i >= 0) f.turn = i + 1;
  }
  const entryOf = tokenId => {  // the group entry a token is in: {group, key, entry}
    for (const [group, entries] of Object.entries(V.groups)) for (const [key, entry] of Object.entries(entries || {}))
      if ((entry.tokenIds || []).map(String).includes(String(tokenId))) return { group, key, entry };
    return null;
  };
  function removeFromFight(tokenId) {  // as the VTT does: whose turn moves on if it was theirs
    const f = V.fight;
    if (!f) return;
    const n = f.combatants.findIndex(x => x.tokenId === tokenId);
    if (n < 0) return;
    const active = f.combatants.findIndex(x => x.tokenId === f.activeId);
    if (n < active) f.turn -= 1;
    if (f.activeId === tokenId) {
      if (n === f.combatants.length - 1) { f.round += 1; f.turn = 1; f.activeId = f.combatants[0].tokenId; } else f.activeId = f.combatants[n + 1].tokenId;
    }
    f.combatants.splice(n, 1);
    if (!f.combatants.length) V.fight = null;
  }
  function deleted(id) {  // a token taken off the map leaves the fight, or the group it waited in
    if (id === null || id === undefined || typeof id === 'object') return;
    id = String(id);
    delete V.tokens[id];
    if (V.fight && V.fight.combatants.some(x => x.tokenId === id)) removeFromFight(id);
    else { const at = entryOf(id); if (at) { at.entry.tokenIds = at.entry.tokenIds.filter(t => String(t) !== id); if (!at.entry.tokenIds.length) delete V.groups[at.group][at.key]; if (!Object.keys(V.groups[at.group]).length) delete V.groups[at.group]; } }
  }
  function addToEncounter(ids) {  // someone added from the map: waiting (mid-fight, "Pending") until added to combat
    for (const id of ids.map(String)) {
      if (entryOf(id)) continue;
      const t = V.tokens[id] || {}, fighting = !!V.fight;
      const group = fighting ? 'Pending' : (t.type === 'MONSTER' ? 'Enemy' : 'Party Member');
      const key = t.type === 'MONSTER' && !fighting ? String(t.entityId) : id;
      const g = V.groups[group] || (V.groups[group] = {});
      if (g[key]) g[key].tokenIds.push(id); else g[key] = { tokenIds: [id], initiative: null, initiativeBonus: null };
    }
  }

  function apply(a) {
    const f = V.fight, p = a.payload;
    switch (a.type) {
      case 'INCREMENT_COMBAT_TURN':
        if (!f || !f.combatants.length) return true;
        if (f.turn >= f.combatants.length) { f.round += 1; f.turn = 1; } else f.turn += 1;
        f.activeId = f.combatants[f.turn - 1].tokenId; return true;
      case 'DECREMENT_COMBAT_TURN':
        if (!f || !f.combatants.length) return true;
        if (f.turn <= 1) { f.round -= 1; f.turn = f.combatants.length; } else f.turn -= 1;
        f.activeId = f.combatants[f.turn - 1].tokenId; return true;
      case 'END_COMBAT': V.fight = null; return true;
      case 'CLEAR_ENCOUNTER': V.fight = null; V.groups = {}; return true;
      case 'START_COMBAT': {
        const combatants = [];
        for (const entries of Object.values(V.groups)) for (const e of Object.values(entries || {}))  // (only tokens still on the map)
          for (const t of e.tokenIds || []) if (V.tokens[t]) combatants.push({ tokenId: String(t), initiative: num(e.initiative), initiativeBonus: num(e.initiativeBonus) });
        if (!combatants.length) return true;
        V.fight = { round: 1, turn: 1, activeId: null, combatants };
        sort(); V.fight.activeId = V.fight.combatants[0].tokenId; V.fight.turn = 1; return true;
      }
      case 'ADD_TO_ENCOUNTER': if (Array.isArray(p)) addToEncounter(p); return true;
      case 'ADD_TO_COMBAT': {  // the waiting ones join the order, with the initiative set for them
        if (!f || !Array.isArray(p)) return true;
        for (const id of p.map(String)) {
          if (f.combatants.some(x => x.tokenId === id)) continue;
          const at = entryOf(id), e = at ? at.entry : {};
          f.combatants.push({ tokenId: id, initiative: num(e.initiative), initiativeBonus: num(e.initiativeBonus) });
        }
        delete V.groups.Pending;
        sort(); return true;
      }
      case 'UPDATE_INITIATIVE': {
        if (!Array.isArray(p)) return true;
        let moved = false;
        for (const x of p) {
          const e = V.groups[x.group] && V.groups[x.group][x.key];
          if (e) e.initiative = x.initiative;
          if (!f || x.initiative === null || x.syncCombatants === false) continue;
          const ids = new Set(((e && e.tokenIds) || [x.key]).map(String));
          f.combatants.forEach(c => { if (ids.has(c.tokenId)) { c.initiative = num(x.initiative); moved = true; } });
        }
        if (moved) sort();
        return true;
      }
      case 'UPDATE_INITIATIVE_BONUS':
        if (Array.isArray(p)) for (const x of p) { const e = V.groups[x.group] && V.groups[x.group][x.key]; if (e) e.initiativeBonus = x.initiativeBonus; }
        return true;
      case 'REMOVE_FROM_ENCOUNTER': {
        if (!p) return true;
        const key = String(p.entityKey);
        if (f && f.combatants.some(x => x.tokenId === key)) removeFromFight(key);
        else if (V.groups[p.group]) { delete V.groups[p.group][key]; if (!Object.keys(V.groups[p.group]).length) delete V.groups[p.group]; }
        return true;
      }
      case 'UNGROUP_ENCOUNTER_ENTITY': {
        const g = p && V.groups[p.group], e = g && g[p.entityKey];
        if (!e) return true;
        for (const t of e.tokenIds) g[t] = { tokenIds: [t], initiative: e.initiative || null, initiativeBonus: e.initiativeBonus || null, ungrouped: true };
        delete g[p.entityKey]; return true;
      }
      case 'SET_ENCOUNTER_GROUP': {
        const from = p && V.groups[p.currentGroup], e = from && from[p.entityKey];
        if (!e) return true;
        const to = V.groups[p.newGroup] || (V.groups[p.newGroup] = {}), key = String(p.entityKey).split('_')[0];
        to[key] = { ...e, tokenIds: [...((to[key] && to[key].tokenIds) || []), ...e.tokenIds] };
        delete from[p.entityKey]; if (!Object.keys(from).length) delete V.groups[p.currentGroup]; return true;
      }
      case 'TOKEN_ADD': if (p && p.id) keepToken(String(p.id), p); return true;
      case 'TOKEN_DELETE': deleted(p); return true;  // (its id)
      case 'MULTI_SELECT_DELETE': if (Array.isArray(p)) p.forEach(deleted); return true;  // (map items' ids, tokens among them)
    }
    if (/^TOKEN_/.test(a.type || '')) {  // a token changed on the map: its name, its hiding
      if (p && p.id) keepToken(String(p.id), p);
      return true;
    }
    return false;
  }
  const listen = ws => {
    if (!String(ws.url).includes('games.dndbeyond.com')) return;
    ws.addEventListener('message', e => {
      if (typeof e.data !== 'string' || e.data[0] !== '{') return;
      let a;
      try { a = JSON.parse(e.data); } catch (err) { return; }
      if (a.type === 'SYNC' && a.payload && a.payload.game) { fromGame(a.payload.game); tell(); return; }
      if (!FIGHT.test(a.type || '')) return;
      try {
        if (!apply(a)) V.log.push(a.type);  // (one askdnd doesn't know: the next SYNC puts it right)
      } catch (err) { V.log.push(a.type + ': ' + err.message); }
      if (V.log.length > 50) V.log.shift();
      tell();
    });
  };
  window.WebSocket = new Proxy(WebSocket, { construct(t, args, nt) { const ws = Reflect.construct(t, args, nt); listen(ws); return ws; } });
})();
