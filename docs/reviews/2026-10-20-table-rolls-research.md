# Table rolls: what other tools do, and what players like and dislike (2026-10-20)

Research for shared rolls in askdnd (everyone at the table sees each roll), before mocking it up. Mockups:
the "askdnd table rolls ideas" canvas (Claude artifact). Sources at the end; forum threads are anecdotes,
not surveys.

## What others do

| Tool | How rolls are shared | Notes |
|---|---|---|
| D&D Beyond Game Log | A shared log in a side panel of the campaign; rolls from sheets land there with 3D dice | The log is where groups look, but it's a panel you have to open |
| Foundry VTT | Chat log on the right; a roll-mode menu under it: Public, GM only, Blind (only the GM sees), Self | Modules exist because "private" rolls still leak a "rolled privately" card or dice animation to everyone |
| Roll20 | Chat log on the right; roll templates format a roll as a card; hover a total for the dice | Long-standing requests: show the character's name, not the player's |
| Owlbear Rodeo dice extensions | Native dice (no history); Witchdice (shared history, Discord); Rumble! (chat log keeps every roll); Bones! (pops up briefly; hidden rolls tell the table a roll happened, not the result) | Different answers to history vs. clutter |
| Avrae (Discord) with D&D Beyond | Rolls appear in a Discord channel in real time | Reports of rolls arriving late or never |
| dddice, Rollwarden (extensions) | Hover a roll for ADV / DIS buttons; Alt-click for Advantage | Choosing Advantage at the moment of rolling, not in a separate menu |

## What players like

- **A shared, lasting history** with who rolled what and when. It builds trust ("I saw it").
- **The total, big, with the dice visible**: both d20s on Advantage, which one counted.
- **Roll modes**: to the table, to the DM only, just me. A hidden roll can tell the table *that* a roll happened.
- **Choosing Advantage right where you roll**, not hunting through a menu.
- **Animated dice are fun**, as long as they're quick and each player can turn them off.
- **The character's name** on the roll, not the player's.

## What players dislike

- **Rolls that don't arrive** or hang ("…" until a refresh). This erodes trust faster than anything.
- **A log that doesn't follow the newest roll**, or hides the total or the individual dice.
- **"Private" rolls that leak** (a card or animation others still see) or that are unclear about who can see them.
- **Slow animations you can't skip**, which drag out combat.
- **A log tucked away in a panel**, and roll spam burying what matters.

## What this suggests for askdnd

1. A **Table rolls** log on the left (unused space today), newest at the top, following new rolls. Character
   portrait and name, the total large, the dice small, Advantage shown as both dice.
2. It **collapses** to a narrow rail (portraits with each one's last total, a dot for new rolls). Manually, and
   automatically when the window is narrow. The choice is remembered on that device.
3. When the log isn't visible, a roll shows a **short pop-up** near where you rolled: a brief d20 tumble (well
   under a second, skippable, off for people who prefer reduced motion), then the result. Other players' rolls
   arrive as small notices that fade.
4. **Who sees it** is chosen per roll, defaulting to the table: Table, DM only, Just me. A DM-only roll tells
   the table "Cole rolled for the DM" without the number.
5. **Reliable first**: a roll shows "sending…" until the server has it, and never silently disappears.
6. **Where it shows**: decided 2026-10-20 (Brett): everywhere while the Live control's Game Mode is on, open on
   Play and collapsed to the rail elsewhere. (The other options were Play only, or the whole Character page.)

## Sources

- D&D Beyond forums: [bugs with the new digital dice roller](https://www.dndbeyond.com/forums/d-d-beyond-general/bugs-support/236730-bugs-with-new-digital-dice-roller?comment=21), [the forum dice roller is still broken](https://www.dndbeyond.com/forums/d-d-beyond-general/bugs-support/182421-the-forum-dice-roller-is-still-broken), [dice not working](https://www.dndbeyond.com/forums/d-d-beyond-general/bugs-support/242782-dice-not-working), [rolls not showing on Discord](https://www.dndbeyond.com/forums/d-d-beyond-general/bugs-support/161704-rolls-not-showing-on-discord)
- Foundry VTT: [Dice article (roll modes)](https://foundryvtt.com/article/dice/), [roll mode constants](https://foundryvtt.com/api/v13/variables/CONST.DICE_ROLL_MODES.html), modules [Actually Private Rolls](https://foundryvtt.com/packages/fh-actually-private-rolls), [Invisi-Rolls](https://foundryvtt.com/packages/invisi-rolls), [Blind Skill Rolls](https://foundryvtt.com/packages/blind-skill-rolls), [Dice So Nice](https://www.foundryvtt-hub.com/package/dice-so-nice/)
- Roll20: [roll templates help](https://help.roll20.net/hc/articles/360037256754), [forum: character names on rolls](https://app.roll20.net/forum/permalink/1097/)
- Owlbear Rodeo: [dice extensions guide](https://obr-extensions-guide.onrender.com/DiceReview.html)
- Avrae: [D&D Beyond dice sync docs](https://avrae.readthedocs.io/en/latest/_sources/ddb.rst.txt)
- Extensions: [dddice for D&D Beyond](https://docs.dddice.com/docs/integrations/dnd-beyond), [Rollwarden](https://addons.mozilla.org/en-US/firefox/addon/rollwarden/)
- Animation speed: [a userstyle to hide D&D Beyond's dice](https://userstyles.world/style/8614/hide-dndbeyond-dice-for-struggles-with-animations), [Baldur's Gate 3 discussion](https://steamcommunity.com/app/1086940/discussions/0/3808408747680864140)
