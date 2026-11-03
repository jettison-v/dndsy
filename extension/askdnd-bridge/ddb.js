// On a D&D Beyond character sheet: puts ddb-page.js into the page, passes messages between it and the extension, and
// draws askdnd's panel beside the sheet (in its own shadow root, so neither page's styles reach the other). Its only
// buttons are for askdnd's own changes (Try again and Undo on one that didn't go through; Bridge Review, Nov 3), in
// askdnd's own panel, never over D&D Beyond's controls.
(() => {
  // A message to the extension. After the extension is reloaded or updated, a page opened before it keeps this old
  // script, which can no longer reach it: it stops quietly then (reload the page to bring askdnd back)
  const send = (m, cb) => {
    try {
      if (!chrome.runtime || !chrome.runtime.id) return;
      const p = cb ? chrome.runtime.sendMessage(m, cb) : chrome.runtime.sendMessage(m);
      if (p && p.catch) p.catch(() => {});
    } catch (e) { /* the extension was reloaded: this page's old script is cut off */ }
  };
  const s = document.createElement('script');
  s.src = chrome.runtime.getURL('ddb-page.js');
  (document.head || document.documentElement).appendChild(s);
  s.onload = () => s.remove();
  const sheetId = () => (location.pathname.match(/\/characters\/(\d+)/) || [])[1];

  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-page') return;
    if (e.data.type === 'gamelog') return;  // (sent, or no game log open: Table rolls has the roll either way)
    send({ ...e.data, type: { saved: 'ddb-saved', roll: 'ddb-roll', heard: 'ddb-heard', fresh: 'ddb-fresh' }[e.data.type] || 'ddb-applied' });  // (the page's own type last would win)
  });
  chrome.runtime.onMessage.addListener((m, sender, reply) => {
    if (m.type === 'apply') { window.postMessage({ askdndBridge: 'apply', batch: m.batch }, location.origin); reply({ took: true }); }  // (so the extension knows this tab is alive)
    if (m.type === 'gamelog') { window.postMessage({ askdndBridge: 'gamelog', messages: m.messages }, location.origin); reply({ took: true }); }
    if (m.type === 'panel-state') draw(m.state, m.error, m.askdnd);
    if (m.type === 'show' || m.type === 'check') window.postMessage({ askdndBridge: m.type, fields: m.fields }, location.origin);  // (ddb-page.js)
    if (m.type === 'read') { window.postMessage({ askdndBridge: 'read' }, location.origin); reply({ took: true }); }  // (the sheet reads itself for askdnd)
  });

  // ---- the panel: askdnd's colors (app.css tokens), the four states
  let host, root, open = sessionStorage.getItem('askdnd-panel') !== 'closed';
  const CLS = { live: 'live', seen: 'seen' };  // (the log's two; a change's own colour is by how it stands: `says`)
  const esc = v => String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CSS = `:host { all: initial; } * { box-sizing: border-box; }
    .tab { position: fixed; top: 140px; left: 0; z-index: 2147483000; background: #d64545; color: #fff; font: 700 12px/1 Inter, system-ui, sans-serif; letter-spacing: .06em; text-transform: uppercase; writing-mode: vertical-rl; transform: rotate(180deg); padding: 12px 7px; border: 0; border-radius: 8px 0 0 8px; cursor: pointer; }
    .panel { position: fixed; top: 0; left: 0; bottom: 0; width: 320px; z-index: 2147483001; background: #15171a; color: #ebe7df; border-right: 1px solid #34383e; font: 14px/1.5 Inter, system-ui, sans-serif; display: flex; flex-direction: column; box-shadow: 8px 0 24px rgba(0,0,0,.45); }
    .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 14px; border-bottom: 2px solid #d64545; background: #0f1113; }
    .head b { color: #fff; } .logo { color: #f08a8a; font-weight: 700; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; margin-left: 6px; }
    .x { background: none; border: 0; color: #a29d93; font-size: 18px; cursor: pointer; }
    .body { padding: 14px; display: grid; gap: 14px; overflow: auto; }
    .st { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; border-radius: 999px; padding: 4px 10px; white-space: nowrap; justify-self: start; }
    .st::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .live { background: rgba(91,191,127,.15); color: #5bbf7f; } .wait { background: rgba(232,179,75,.14); color: #e8b34b; }
    .off { background: rgba(214,69,69,.14); color: #f08a8a; } .seen { background: rgba(126,166,224,.15); color: #7ea6e0; }
    .tile { background: #1f2226; border: 1px solid #34383e; border-radius: 8px; padding: 8px 10px; } .tile small { color: #a29d93; display: block; font-size: 12px; } .tile b { color: #fff; font-size: 20px; }
    .tile.wait { border-color: #e8b34b; background: #1f2226; } .tile.off { border-color: #d64545; background: #1f2226; }
    h3 { margin: 0; font: 700 11px/1 'Roboto Condensed', Inter, sans-serif; letter-spacing: .1em; text-transform: uppercase; color: #e8b34b; }
    .note { color: #a29d93; font-size: 12px; }
    a.btn, button.btn { font: 600 13px/1 Inter, system-ui, sans-serif; border-radius: 8px; padding: 8px 11px; border: 1px solid #34383e; background: #272b30; color: #ebe7df; cursor: pointer; text-decoration: none; display: inline-block; }
    button.btn.primary { background: #d64545; border-color: #d64545; color: #fff; } button.btn:disabled { opacity: .5; cursor: default; }
    .acts { display: flex; gap: 8px; flex-wrap: wrap; }
    .change { display: grid; gap: 6px; padding: 10px 12px; border-radius: 10px; border: 1px solid #34383e; }
    .change.wait { border-color: #e8b34b; } .change.off { border-color: #d64545; } .change.live { border-color: #5bbf7f; }
    ul { list-style: none; margin: 0; padding: 0; } li { padding: 6px 0; border-top: 1px solid #2c3036; font-size: 13px; }`;
  function mount() {
    if (host) return;
    host = document.createElement('div'); host.id = 'askdnd-bridge';
    root = host.attachShadow({ mode: 'open' });
    document.documentElement.appendChild(host);
    // On the left (Brett, 2026-10-27): D&D Beyond opens its own pane on the right (an item, a spell, hit points)
    root.addEventListener('click', e => {
      const t = e.target.closest('[data-act]'); if (!t) return;
      const act = t.dataset.act;
      if (act === 'toggle') { open = !open; sessionStorage.setItem('askdnd-panel', open ? 'open' : 'closed'); send({ type: 'panel-refresh' }); }
      if (act === 'retry' || act === 'dismiss') { t.disabled = true; send({ type: 'panel-act', act, id: t.dataset.id }); }  // (askdnd answers, then the panel is drawn again)
    });
  }
  let again = null;
  function draw(st, error, askdnd) {
    mount();
    clearTimeout(again);  // while something waits, ask again every second and a half
    if (st && st.changes.some(c => c.progress !== 'failed')) again = setTimeout(() => send({ type: 'panel-refresh' }), 1500);
    if (!open) { root.innerHTML = `<style>${CSS}</style><button class="tab" data-act="toggle" aria-label="Open askdnd">askdnd</button>`; return; }
    let body;
    if (error) body = `<span class="st off">Not connected</span><p class="note">${esc(error)}</p>`;
    else {
      // The words every place uses (Bridge Review, Nov 3): Connected; On its way (Trying again, 2 of 3); Didn't go through
      const failed = st.changes.filter(c => c.progress === 'failed').length, onWay = st.changes.length - failed;
      const pill = failed ? ['off', failed + " didn't go through"] : onWay ? ['wait', onWay + ' on its way'] : ['live', 'Connected'];
      body = `<span class="st ${pill[0]}">${pill[1]}</span>
        <div class="tile ${onWay ? 'wait' : failed ? 'off' : ''}"><small>Hit points</small><b>${esc(st.hp.current)}</b> <span class="note">/ ${esc(st.hp.max)}</span></div>
        ${st.changes.map(c => { const f = c.progress === 'failed', cls = f ? 'off' : 'wait'; return `<div class="change ${cls}"><span class="st ${cls}">${esc(c.says)}</span><div>${esc(c.label)}</div>${f && c.error ? `<div class="note">${esc(c.error)}</div>` : ''}${f ? `<div class="acts"><button class="btn primary" data-act="retry" data-id="${esc(c.id)}">Try again</button><button class="btn" data-act="dismiss" data-id="${esc(c.id)}">Undo</button></div>` : ''}</div>`; }).join('')}
        ${st.to_make.length ? `<div class="change off"><b>Or make it on D&amp;D Beyond yourself</b><div>${st.to_make.map(esc).join('<br>')}</div><span class="note">askdnd ticks it off when D&amp;D Beyond has it.</span></div>` : ''}
        <h3>What changed</h3>
        <ul>${st.log.map(l => `<li><span class="st ${CLS[l.state] || 'live'}">${l.state === 'seen' ? 'On D&D Beyond' : 'From askdnd'}</span> ${esc(l.text)}</li>`).join('') || '<li class="note">Nothing yet.</li>'}</ul>
        ${askdnd ? `<a class="btn" href="${esc(askdnd)}/characters/${esc(st.character.id)}/battle?live=1" target="_blank" rel="noopener">Open in askdnd</a>` : ''}`;
    }
    root.innerHTML = `<style>${CSS}</style><aside class="panel" aria-label="askdnd"><div class="head"><span><b>${esc(st ? st.character.name : 'askdnd')}</b><span class="logo">askdnd</span></span><button class="x" data-act="toggle" aria-label="Close askdnd">✕</button></div><div class="body">${body}</div></aside>`;
  }
  const hello = () => send({ type: 'ddb-tab', ddbId: sheetId() });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hello); else hello();
  // The DM as a backup (carry.js): a sheet is a D&D Beyond page too, so a DM with only the party's sheets open still
  // makes the changes of a closed one, every few seconds (askdnd says how often; once a minute in anyone else's browser)
  const tick = () => send({ type: 'carry-tick' }, answer => {
    if (chrome.runtime.lastError) return setTimeout(tick, 60000);
    setTimeout(tick, Math.max(5, (answer && answer.every) || 60) * 1000);
  });
  setTimeout(tick, 5000);
  // Someone using the sheet keeps the bridge awake (at most once a minute; its saves are heard on their own)
  let usedAt = Date.now();
  ['pointerdown', 'keydown'].forEach(k => document.addEventListener(k, () => {
    if (Date.now() - usedAt > 60000) { usedAt = Date.now(); send({ type: 'ddb-active' }); }
  }, { passive: true, capture: true }));
})();
