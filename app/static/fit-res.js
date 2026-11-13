/* Battle's Resources row takes its short names before the page is drawn, when the whole ones need two lines: the same
   rule as app.js fitRes, which takes over (Nov 7: done only after the first paint, the row shrank and moved Battle's
   tiles). Loaded right after the row (_battle_body.html), as a file of askdnd's own (no inline scripts, Nov 13). */
(function (r) {
  try {
    if (!r || matchMedia('(max-width: 640px)').matches) return;
    var i = r.querySelector('.res-insp'), line = (i && i.offsetHeight) || 28;
    if (r.offsetHeight > line * 1.5) r.classList.add('short');
  } catch (e) { /* app.js fits it */ }
})(document.currentScript && document.currentScript.parentElement.querySelector('.res-row:not(.slots)'));
