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

## 2. Settle the data strategy (Brett: decide; about 20 minutes, before anything is built)

Brett, Oct 26: leaning toward an abstracted data model, without adding complexity. The content-sources design
(`docs/plans/2026-10-26-content-sources.md`, PR #52) is the starting point. Tomorrow's job is to walk through it in plain
terms and settle it.

**Recommendation: abstract the *content*, keep everything else concrete.** One shape holds every piece of rules content
(monster, spell, item, rule, Wild Shape form): a **source** (the SRD, a book the DM owns, the DM's own creations) holds
**entries**, each with a kind, a name and its details as one document. A campaign switches sources on in its own
order. The SRD becomes just the first source, read from its files as today. That's two tables and one lookup function
(`rules_data.find`, which already exists), not a table per kind.

What stays concrete, because it's read and changed constantly and an abstraction would only hide it: characters, play
state (HP, slots, conditions), rolls, the story. Those keep their own tables.

What to avoid, because it is the extra complexity: a general "anything" model (attributes as rows), plug-ins, or
versioned schemas per book. The details document per entry covers a new kind of thing without a new table.

The questions to answer together:
1. Is "content is abstract, play and story are concrete" the right line?
2. The design's four decisions: sources belong to a person (the DM's library); switching a book off hides it but keeps
   copies already in play; a book's optional rules become house rules; build the model now, the import later.
3. Where a book's text may live (the private database only), and what a second group could see later.

Once settled, build the model while the table it replaces (`campaign_content`) is still empty: about a day, with no
visible change yet.

## 2b. The private repository (Brett: two settings; about 5 minutes)

Brett made the repo private on Oct 26. Two things change:
- **GitHub Actions minutes.** Private repos get 2,000 minutes a month on GitHub Free (3,000 on Pro). Last week's pace
  (about 210 test runs at roughly 4-5 billed minutes each) is about 4,000 a month. When minutes run out with no
  spending limit, the tests stop running, and Railway won't deploy beta without them. Recommendation: GitHub Pro
  ($4 a month, which also brings branch protection to a private repo) plus an Actions spending limit of about $10, and
  Claude adds a setting that cancels an older run when a newer push replaces it (fewer wasted minutes).
- **Railway** reads the repo through its GitHub app. Today's deploy after the switch is the check that it still has
  access.

## 3. Mock up the fight screen (Brett: review the mockup; design stays in this session)

The first item of Phase 1 in the reordered roadmap: initiative and turns (2.2), with hit points (1.1), the reminders
and the play log on the same screen. Mockup first, with the table's own characters, then build behind the VTT switch
in the test campaign. Close draft #40 then, since its play-state ideas fold into this.

## 4. The test characters, and book text in the test fixtures (no Brett step)

Push the four test characters, with `scripts/ddb_fixture.py` also stripping rules text (descriptions) so new
fixtures carry numbers only. Then re-make the four existing fixtures the same way, so the repo stops holding book text
(it's private for now; this keeps it safe to make public again). Rewriting git history to remove the old copies is
optional and Brett's call. Known gap to fix while there:
the Artificer's Eldritch Cannon shows "50/50".

## Later, already planned

- The layout sweep (`scripts/layout_sweep.py`) at the end of Phase 1.
- Rules answers stay later in the roadmap (Brett, Oct 26).
