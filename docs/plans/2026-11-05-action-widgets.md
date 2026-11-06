# Action widgets: one spec for every combat workflow

Brett, Nov 5: "categorize … these encounter/combat workflows, which have different flavors combining slot usage, pool
usage, rolls, manual value typing, selectors … build a set of reusable widgets from a component library in the design
system. It should be modular and keyed off values about an action, not a separate build for each one." Not before
the Nov 6 game; after it, ahead of slice 3 (Your turn's bar) and Prepare for your turn, which both reuse it.

## Why

Tonight's pass over the party found three gaps, and each was a one-off window missing a case: a feat's free cast
(the Cast window), Shadow Arts' Focus Point (a spell paid for with a resource), Lay On Hands (a pool, not a count).
Every new class feature has meant a new window or a new branch in one. That doesn't scale to 13 classes, their
subclasses, feats and magic items.

## What askdnd has today, by flavor

| Window (file) | Spends | Chooses | Types | Rolls | Changes |
|---|---|---|---|---|---|
| Use one / Give one back (resources.py) | a use, a slot, a charge, an item | | how many (a pool, new) | | the count |
| Cast (casting.py) | a slot, Pact slot, free use, a feature's resource | the way; a summon's choice, a familiar's form and kind | a name | the spell's roll | Concentration, a creature |
| The roll window (table_rolls.py, app.js) | | advantage, who sees it, Unarmed ways | | attack, damage, save, check | Table rolls |
| Hit points (hit_points.py) | | damage or healing, its type, defenses to cross | the amount | | HP, temp HP, Concentration's DC, 0 HP |
| Rest (rests.py) | Hit Point Dice | what comes back (ticked) | | the dice | uses, slots, HP, Concentration |
| Shift (shifting.py) | a Wild Shape use | the form; keep or take temp HP | | | form, temp HP |
| Using an item (item_use.py) | the item | yourself or someone | | its healing | HP, a condition |
| Give (giving.py) | the item | who | how many | | two sheets |
| Ready (readying.py) | | the action | the trigger | | Readied row |
| Hide (hiding.py) | | | | Stealth | Hidden, its DC |
| Inspiration, Conditions, Death saves, Initiative | | what, how long | the number | the save | the sheet |

Not built yet, and the same shapes: Font of Magic (Sorcery Points to and from slots), Arcane Recovery (choose slots up
to a total), Metamagic (spend and change a spell), Bardic Inspiration (give a die to someone), Divine Smite on a hit,
Deflect Attack (reduce a roll, then maybe spend to redirect), Action Surge, Rage, Lucky.

## One spec

An action is data: what it costs, then steps from a small vocabulary. Each window becomes the same shell drawing the
steps in order.

- **cost**: Action, Bonus Action, Reaction, Magic action, free; a trigger for a Reaction.
- **steps**, any of:
  - **Spend**: a resource and an amount: fixed (1 Focus Point), chosen (How many, 1 to what's left), or a slot (the
    lowest level, which kinds, the higher ones that do nothing more).
  - **Choose**: one of a list: a form, a target at the table, a damage type, a way, an element, a Metamagic option.
  - **Enter**: a number or a few words (damage taken, a trigger, a name).
  - **Roll**: a formula and its kind, Advantage, who sees it, what a hit adds.
  - **Convert**: one resource into another by a table (Wild Resurgence, Font of Magic, Arcane Recovery).
  - **Apply**: what changes: HP up or down, temp HP, a condition starts or ends, Concentration, a creature, a count.
- Every step says what it changes on D&D Beyond, says so where it starts when the sheet can't be reached, and comes
  back with Undo.

Where the specs come from, the first answer winning (as corrections already work): the campaign's correction,
askdnd's correction, a rule (class_rules, kept as a table of features, not code), D&D Beyond's own data (limited uses,
activation, slots). A new class case is then a line of data: Shadow Arts is `{spell: Darkness, spend: Focus Points 1}`.

## The widgets (the design system)

One **Use window** shell (title, cost line, the steps, one primary button, Cancel, the said line), and a widget per
step: **Spend** (pips for a few, a stepper for a pool, slot levels as a choice), **Choose** (chips, or pictures for
forms and targets), **Enter** (a number with − and +, typed), **Roll** (dice, Advantage, who sees), **Preview** (what
will change: "Focus Points 6 → 5 · Concentrating on Darkness"), **Checklist** (a rest). Each on Manage › Design
system with its states, and a test that every window is built from them (like the inline-style test).

## Tests that come for free

The generic test from tonight (tests/test_party_sheets.py: every window each party sheet offers opens) grows into:
every spec in the table opens, offers its steps, sends the change it says, and Undoes it. The live test's
`*-every` runs do the same on the real D&D Beyond.

## How it lands, after the game

1. The spec and the shell, behind one window first (Use one / Give one back), drawn the same as today.
2. Cast, then Hit points, then the rest, one at a time, each with its tests unchanged.
3. Then new features are rows of data: Font of Magic, Arcane Recovery, Metamagic, Bardic Inspiration.
4. Your turn's bar and Prepare for your turn draft a turn as a list of these specs.

## Beyond combat: other pieces worth one component each

- **Figure**: a picture by kind and framing, with initials when there's none and the DM's Draw one prompt (World,
  Party, the fight band, creatures, the menu bar).
- **Counts and marks**: one way to show a count (pips up to 6, then a number, a pool as 23/30), one badge (conditions,
  Adv, tags), one sync mark (on its way, didn't go through). Today they're several styles, which the design grade
  calls out.
- **Windows**: the side panel, the small window and the large modal as one shell in three sizes.
- **Lists**: the list pattern (filters, search, rows) for World, spells, items, the item browser.
- **An entry by kind**: layout A's shape and at-a-glance rows already come from a table (`entity_pages.SHAPES`); the
  same for creatures and characters.
- **Story text**: the scroll, one component for recaps, entries and quests.
