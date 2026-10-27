# askdnd bridge (a local proof)

askdnd's panel beside your own D&D Beyond sheet. It hears the sheet's changes the moment they save, and makes
askdnd's changes there, as you; askdnd counts a change only once it has read it back from D&D Beyond
(app/ddb_bridge.py; docs/mockups/ddb-overlay.html). The proof covers one action: drinking a Potion of Healing.

Load it (Chrome):
1. chrome://extensions, switch on **Developer mode** (top right).
2. **Load unpacked**, and pick this folder (`extension/askdnd-bridge`).
3. Sign in to askdnd on http://localhost:8000 and to D&D Beyond, in the same Chrome. Opening any askdnd page connects
   the extension (it gets its own key to askdnd, so it works even when Chrome blocks third-party cookies); after
   askdnd restarts, open an askdnd page again.
4. Open your character's D&D Beyond sheet: the askdnd panel slides in on the right (the red **askdnd** tab brings it
   back). askdnd's own tab is `http://localhost:8000/characters/<id>/bridge`.

What it may do: two D&D Beyond requests only (hit points, an item's count), only for the sheet that's open, only when
you click. It stores nothing; D&D Beyond gives the sheet a 5-minute token from your own sign-in. Unofficial: D&D Beyond
offers no way for other tools to change a sheet, so a change on their side can break it. When it does, askdnd shows
"Not on D&D Beyond yet", never a wrong number.
