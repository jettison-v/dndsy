// The bridge's icon in Chrome (Brett, 2026-10-31; a status card since the Bridge Review, Nov 3): for each of your
// characters, whether its sheet is open, what's on its way and what didn't go through, with its sheet and its page in
// askdnd one click each; the table; and this extension's version, saying when a newer one is out.
const links = document.getElementById('links'), state = document.getElementById('state'), foot = document.getElementById('foot');
const own = chrome.runtime.getManifest().version;
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
function link(label, href) {
  const a = el('a', 'go');
  a.href = href; a.target = '_blank'; a.rel = 'noopener';
  a.append(label, el('span', '', '↗'));
  return a;
}
const newer = (a, b) => {  // version a newer than b ("0.9.10" > "0.9.9")
  const x = String(a || '').split('.').map(Number), y = String(b || '').split('.').map(Number);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};
foot.textContent = 'Version ' + own;
(async () => {
  const { key, askdnd } = await chrome.storage.session.get(['key', 'askdnd']);
  if (!key || !askdnd) {
    state.textContent = 'Not connected'; state.className = 'off';
    links.append(el('p', '', 'Open askdnd once in this browser, signed in, to connect.'), link('Open askdnd', 'https://askdnd.ai/'));
    return;
  }
  let j;
  try {
    const r = await fetch(askdnd + '/bridge/links', { headers: { Accept: 'application/json', 'X-Askdnd-Bridge': key } });
    if (!r.ok) throw new Error();
    j = await r.json();
  } catch (e) {
    state.textContent = "askdnd isn't answering"; state.className = 'off';
    links.append(link('Open askdnd', askdnd + '/'));
    return;
  }
  state.textContent = 'Connected to askdnd'; state.className = 'ok';
  for (const c of j.characters) {
    const box = el('div', 'who');
    const sheet = c.how === 'sheet' ? ['ok', 'Sheet open'] : c.how === 'dm' ? ['via', 'Through the DM'] : ['off', 'Sheet closed'];
    const head = el('div', 'who-head');
    head.append(el('b', '', c.name), el('span', 'st ' + sheet[0], sheet[1]));
    box.append(head);
    if (c.failed) box.append(el('p', 'bad', c.failed + (c.failed === 1 ? " change didn't" : " changes didn't") + ' go through: Try again or Undo in askdnd'));
    else if (c.on_way) box.append(el('p', '', c.on_way + (c.on_way === 1 ? ' change' : ' changes') + ' on the way to D&D Beyond'));
    const row = el('div', 'row');
    row.append(link('Sheet', c.sheet), link('In askdnd', askdnd + c.page + (c.failed ? '?live=1' : '')));
    box.append(row);
    links.append(box);
  }
  if (j.table) links.append(link('The table', j.table));
  if (!j.characters.length) links.append(link('Open askdnd', askdnd + '/'));
  if (newer(j.version, own)) foot.textContent = 'Version ' + own + ' · ' + j.version + ' is out: Chrome updates it within a few hours, or restart Chrome';
})();
