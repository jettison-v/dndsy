// The bridge's icon in Chrome (Brett, 2026-10-31): your sheet, your character in askdnd and the table, one click each.
const links = document.getElementById('links'), state = document.getElementById('state');
function add(label, href) {
  const a = document.createElement('a');
  a.href = href; a.target = '_blank'; a.rel = 'noopener';
  a.append(label);
  const arrow = document.createElement('span'); arrow.textContent = '↗'; a.append(arrow);
  links.append(a);
}
(async () => {
  const { key, askdnd } = await chrome.storage.session.get(['key', 'askdnd']);
  if (!key || !askdnd) {
    state.textContent = 'Not connected';
    const p = document.createElement('p'); p.textContent = 'Open askdnd once in this browser, signed in, to connect.'; links.append(p);
    add('Open askdnd', 'https://beta.askdnd.ai/');
    return;
  }
  try {
    const r = await fetch(askdnd + '/bridge/links', { headers: { Accept: 'application/json', 'X-Askdnd-Bridge': key } });
    if (!r.ok) throw new Error();
    const j = await r.json();
    state.textContent = 'Connected';
    for (const c of j.characters) { add(c.name + ' on D&D Beyond', c.sheet); add(c.name + ' in askdnd', askdnd + c.page); }
    if (j.table) add('The table', j.table);
    if (!j.characters.length) add('Open askdnd', askdnd + '/');
  } catch (e) {
    state.textContent = 'Not connected';
    add('Open askdnd', askdnd + '/');
  }
})();
