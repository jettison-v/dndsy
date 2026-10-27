// On a D&D Beyond character sheet: puts ddb-page.js into the page, passes messages between it and the extension, and
// draws askdnd's panel beside the sheet (in its own shadow root, so neither page's styles reach the other).
(() => {
  const s = document.createElement('script');
  s.src = chrome.runtime.getURL('ddb-page.js');
  (document.head || document.documentElement).appendChild(s);
  s.onload = () => s.remove();
  const sheetId = () => (location.pathname.match(/\/characters\/(\d+)/) || [])[1];

  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-page') return;
    chrome.runtime.sendMessage({ ...e.data, type: e.data.type === 'saved' ? 'ddb-saved' : 'ddb-applied' });  // (the page's own type last would win)
  });
  chrome.runtime.onMessage.addListener(m => {
    if (m.type === 'apply') window.postMessage({ askdndBridge: 'apply', change: m.change, ops: m.ops }, location.origin);
    if (m.type === 'panel-state') draw(m.state, m.error);
  });

  // ---- the panel: askdnd's colors (app.css tokens), the four states
  let host, root, open = sessionStorage.getItem('askdnd-panel') !== 'closed';
  const LABEL = { live: 'Live with D&D Beyond', waiting: 'Waiting for D&D Beyond', not_yet: 'Not on D&D Beyond yet', seen: 'Changed on D&D Beyond' };
  const CLS = { live: 'live', waiting: 'wait', not_yet: 'off', seen: 'seen' };
  const esc = v => String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const CSS = `:host { all: initial; } * { box-sizing: border-box; }
    .tab { position: fixed; top: 140px; right: 0; z-index: 2147483000; background: #d64545; color: #fff; font: 700 12px/1 Inter, system-ui, sans-serif; letter-spacing: .06em; text-transform: uppercase; writing-mode: vertical-rl; padding: 12px 7px; border: 0; border-radius: 8px 0 0 8px; cursor: pointer; }
    .panel { position: fixed; top: 0; right: 0; bottom: 0; width: 320px; z-index: 2147483001; background: #15171a; color: #ebe7df; border-left: 1px solid #34383e; font: 14px/1.5 Inter, system-ui, sans-serif; display: flex; flex-direction: column; box-shadow: -8px 0 24px rgba(0,0,0,.45); }
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
    .item { display: flex; justify-content: space-between; align-items: center; gap: 8px; background: #1f2226; border: 1px solid #34383e; border-radius: 8px; padding: 8px 10px; }
    .note { color: #a29d93; font-size: 12px; }
    button.btn, a.btn { font: 600 13px/1 Inter, system-ui, sans-serif; border-radius: 8px; padding: 8px 11px; border: 1px solid #34383e; background: #272b30; color: #ebe7df; cursor: pointer; text-decoration: none; display: inline-block; }
    button.primary { background: #d64545; border-color: #d64545; color: #fff; } button[disabled] { opacity: .5; cursor: default; }
    .change { display: grid; gap: 6px; padding: 10px 12px; border-radius: 10px; border: 1px solid #34383e; }
    .change.wait { border-color: #e8b34b; } .change.off { border-color: #d64545; } .change.live { border-color: #5bbf7f; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; }
    ul { list-style: none; margin: 0; padding: 0; } li { padding: 6px 0; border-top: 1px solid #2c3036; font-size: 13px; }`;
  function mount() {
    if (host) return;
    host = document.createElement('div'); host.id = 'askdnd-bridge';
    root = host.attachShadow({ mode: 'open' });
    document.documentElement.appendChild(host);
    root.addEventListener('click', e => {
      const t = e.target.closest('[data-act]'); if (!t) return;
      const act = t.dataset.act;
      if (act === 'toggle') { open = !open; sessionStorage.setItem('askdnd-panel', open ? 'open' : 'closed'); chrome.runtime.sendMessage({ type: 'panel-refresh' }); }
      if (act === 'drink') { t.disabled = true; chrome.runtime.sendMessage({ type: 'drink', itemId: +t.dataset.item }); }
      if (act === 'retry') chrome.runtime.sendMessage({ type: 'retry', change: +t.dataset.change });
      if (act === 'undo') chrome.runtime.sendMessage({ type: 'undo', change: +t.dataset.change });
    });
  }
  let again = null;
  function draw(st, error) {
    mount();
    clearTimeout(again);  // while a change waits, ask again every second and a half
    if (st && st.changes.some(c => c.state === 'waiting')) again = setTimeout(() => chrome.runtime.sendMessage({ type: 'panel-refresh' }), 1500);
    if (!open) { root.innerHTML = `<style>${CSS}</style><button class="tab" data-act="toggle" aria-label="Open askdnd">askdnd</button>`; return; }
    let body;
    if (error) body = `<span class="st off">Not connected</span><p class="note">${esc(error)}</p>`;
    else {
      const waiting = st.changes.filter(c => c.state === 'waiting').length, notYet = st.changes.filter(c => c.state === 'not_yet').length;
      const pill = waiting ? ['wait', waiting + ' waiting'] : notYet ? ['off', notYet + ' not on D&D Beyond'] : ['live', 'Live with D&D Beyond'];
      body = `<span class="st ${pill[0]}">${pill[1]}</span>
        <div class="tile ${waiting ? 'wait' : notYet ? 'off' : ''}"><small>Hit points</small><b>${esc(st.hp.current)}</b> <span class="note">/ ${esc(st.hp.max)}</span></div>
        <h3>Healing potions</h3>
        ${st.items.map(it => `<div class="item"><div><b>${esc(it.name)}</b> <span class="note">×${it.quantity}</span><div class="note">Heals ${esc(it.heals)}</div></div>${st.can_act ? `<button class="btn primary" data-act="drink" data-item="${it.id}"${waiting || !it.quantity ? ' disabled' : ''}>Drink</button>` : ''}</div>`).join('') || '<p class="note">No healing potions on the sheet.</p>'}
        ${st.changes.map(c => `<div class="change ${CLS[c.state]}"><span class="st ${CLS[c.state]}">${LABEL[c.state]}</span><div>${c.lines.map(esc).join('<br>')}</div>${c.error ? `<div class="note">${esc(c.error)}</div>` : ''}${c.state === 'not_yet' ? `<div class="acts"><button class="btn primary" data-act="retry" data-change="${c.id}">Try again</button><button class="btn" data-act="undo" data-change="${c.id}">Undo</button></div>` : ''}</div>`).join('')}
        <h3>What changed</h3>
        <ul>${st.log.map(l => `<li><span class="st ${CLS[l.state]}">${l.state === 'seen' ? 'On D&D Beyond' : 'From askdnd'}</span> ${esc(l.text)}</li>`).join('') || '<li class="note">Nothing yet.</li>'}</ul>
        <a class="btn" href="http://localhost:8000/characters/${esc(st.character.id)}/bridge" target="_blank" rel="noopener">Open in askdnd</a>`;
    }
    root.innerHTML = `<style>${CSS}</style><aside class="panel" aria-label="askdnd"><div class="head"><span><b>${esc(st ? st.character.name : 'askdnd')}</b><span class="logo">askdnd</span></span><button class="x" data-act="toggle" aria-label="Close askdnd">✕</button></div><div class="body">${body}</div></aside>`;
  }
  const hello = () => chrome.runtime.sendMessage({ type: 'ddb-tab', ddbId: sheetId() });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hello); else hello();
})();
