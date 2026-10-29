// On D&D Beyond's VTT (/games/<campaign>): passes what vtt-page.js hears about the fight on to the extension
// (background.js), which tells askdnd. It only listens. (vtt-page.js runs in the page itself from the very start, as
// manifest.json says: the VTT connects to its game server before a script this one added would run.)
(() => {
  const gameId = () => (location.pathname.match(/\/games\/(\d+)/) || [])[1];
  window.addEventListener('message', e => {
    if (e.source !== window || !e.data || e.data.askdndBridge !== 'from-vtt') return;
    chrome.runtime.sendMessage({ ...e.data, type: 'vtt-' + e.data.type, gameId: gameId() });
  });
})();
