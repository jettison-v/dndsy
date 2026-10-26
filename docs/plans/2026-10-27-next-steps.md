# Next steps, Oct 27

Where things stand at the end of Oct 26, and what to do next, in order. Each step says what it needs from Brett.

## Where we are

- **On beta:** the tour (all three parts), sharp dice with sound and sized to the window, and the simpler Table rolls
  sidebar (open or closed, one choice on every page).
- **Waiting on review:** PR `tour-polish`. It has Brett's tour feedback, every stop's wording, the artifacts saved in
  `docs/artifacts/`, the design system brought up to date, code review fixes and stylesheet cleanup.
- **Drafts:** #52 (the roadmap with the fight screen first, and the content-sources design) and #40 (the play-state
  mockup, which the fight screen now covers).
- **Parked:** four D&D Beyond test characters (Cathartic Cleric 9, Eric Fighter 1, Spurt Sorcerer 3, Vi Artificer 10),
  fetched and tested but not pushed (`git stash` on this Mac).

## 1. Merge the tour polish (Brett: try it on beta, then OK the merge)

Try it yourself, once merged:
1. **?** › **Take the tour**. The card has a bar along its top and "1 of N" that counts every stop.
2. On Battle, the stops go **Spell Book** (the button, before it opens), **filters**, **Damage and healing** (the
   whole column lit), then **Cast at**.
3. On Sheet, **The bell** lights a bell on a row before Reminders on Battle.
4. On Plan, **Battle combos** opens your first combo. Nothing saves.
5. Press **Esc** mid-tour. It asks **End the tour?**: Esc again keeps going, **End tour** ends it.
6. On a phone, turn Live on. The rolls sheet starts as its bar; tap the arrow to open it.

## 2. Decide the content-sources design (Brett: four answers; about 10 minutes)

`docs/plans/2026-10-26-content-sources.md` on PR #52. It answers "the DM buys a book, then stops using it": a book is
a source in the DM's library, switched on per campaign, adding options, never rules. The four decisions are at its end.
Once they're answered, build the model while the table it replaces (`campaign_content`) is still empty. That's about
a day, with no visible change yet. Getting a book's contents in is a later decision.

## 3. Mock up the fight screen (Brett: review the mockup; design stays in this session)

The first item of Phase 1 in the reordered roadmap: initiative and turns (2.2), with hit points (1.1), the reminders
and the play log on the same screen. Mockup first, with the table's own characters, then build behind the VTT switch
in the test campaign. Close draft #40 then, since its play-state ideas fold into this.

## 4. The test characters, and book text in the test fixtures (no Brett step)

Push the four test characters, with `scripts/ddb_fixture.py` also stripping rules text (descriptions) so new
fixtures carry numbers only. Then re-make the four existing fixtures the same way, so the public repo stops holding
book text. Rewriting git history to remove the old copies is optional and Brett's call. Known gap to fix while there:
the Artificer's Eldritch Cannon shows "50/50".

## Later, already planned

- The layout sweep (`scripts/layout_sweep.py`) at the end of Phase 1.
- Rules answers stay later in the roadmap (Brett, Oct 26).
- Optional: make the repo private (GitHub Pro adds branch protection there), once Railway's GitHub access is checked.
