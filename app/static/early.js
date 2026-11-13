/* askdnd's first script (no inline scripts: the Content Security Policy runs only askdnd's own files, Nov 13). Loaded
   at the top of <body>, before anything is drawn, for the two things that can't wait for app.js:

   1. The Table rolls sidebar's place, so pages don't shift sideways as they load (Brett, 2026-10-26). The same rules as
      app.js "the sidebar's state", which takes over once it runs: at the table in a campaign (body.at-table); closed
      until opened on this device (a fight opens it once), and closed between 901 and 1099px.
   2. A picture that won't load is taken away (`data-hide-broken`, once each img's own onerror), however early it fails. */
(function (b) {
  try {
    if (b.classList.contains('at-table')) {
      var ls = localStorage, phone = matchMedia('(max-width: 900px)').matches;
      var side = ls.getItem('askdnd.rollsSide'), closed = phone ? side !== 'open' : innerWidth < 1241 || side !== 'open';
      b.classList.add('rolls-on', closed ? 'rolls-closed' : 'rolls-open');
    }
  } catch (e) { /* private window: app.js places it */ }
  document.addEventListener('error', function (e) {
    var t = e.target;
    if (t && t.tagName === 'IMG' && t.hasAttribute('data-hide-broken')) t.remove();
  }, true);  // (an image's error doesn't bubble: caught on its way down)
})(document.body);
