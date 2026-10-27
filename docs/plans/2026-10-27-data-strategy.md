# Data strategy: four buckets, books checked once (for Brett's approval, 2026-10-27)

Brett's notes (2026-10-27) set the buckets and the constraint: keep data properly separated so each campaign sees only
what it should, without adding overhead ("I do not want to have to check access to the books every time the game
loads"). This page turns them into a decision. It builds on `docs/plans/2026-10-26-content-sources.md` (the sources
model, drafted Oct 26) and the recommendation in `docs/plans/2026-10-27-next-steps.md`. The readable version is the
"askdnd Data Strategy" page (`docs/artifacts/data-strategy.html`,
https://claude.ai/artifact/PWXtaunHcp3MEEJyJpLWoe).

**In one line:** rules content is one shape (sources hold entries) that each campaign filters by its own list of books;
everything about play and the story stays in its own tables, as today.

## The four buckets

| Bucket | What's in it | Where it lives | Who sees it |
|---|---|---|---|
| **Campaign and character data** | Characters, play state, sessions, recaps, rolls, notes, house rules, the campaign record | Postgres, per campaign (as today) | As today's visibility rules say (character notes: players, never the DM) |
| **Public rules** | The SRD 5.2.1: monsters, spells, magic items, the Rules Glossary | `app/data/srd/`, files in the repo (CC-BY-4.0, attribution on Help › About) | Everyone |
| **Private rules** | Books bought on D&D Beyond: today the 2024 Player's Handbook, Dungeon Master's Guide and Monster Manual | Postgres only, each entry tagged with its book; never in git (`private/books/` stays the offline copy) | Campaigns that have that book switched on |
| **askdnd enhancements** | Our summaries, groupings, corrections and additions: tool corrections, roll recipes, item actions, rule terms, `docs/rules/` | Where each is today (files in `app/data/`, `tool_corrections`), tagged as askdnd's | Everyone |

Two cautions, agreed with Brett:
- **Public means licensed, not just free to read.** Only the SRD comes with a license to store and show it. Content
  that's free to read on D&D Beyond but isn't in the SRD is treated as private rules.
- **Enhancements are in our own words.** A summary, a grouping or a correction of Moonbeam is ours and goes to everyone,
  even when it draws on the DMG. A book's own wording isn't: enhancements never quote a book (the rule `docs/rules/`
  already follows).

## Checked once

- Each campaign keeps **its list of books**, set when the campaign is made and changed by its DM or an admin on
  **Manage › Settings › Books** (each book on or off).
- Every rules lookup already goes through one place (`rules_data.catalog/find`), which merges the SRD with the
  campaign's own content. It filters by the campaign's list there: one cheap filter, no check when a game loads and
  nothing asked of D&D Beyond.
- The default for a new campaign: the SRD plus the 2024 Player's Handbook, Dungeon Master's Guide and Monster Manual
  (what askdnd assumes today, as `ddb_sheet.CORE_SOURCES`).

## The books toggle and D&D Beyond

Checked against Cole's public sheet (2026-10-27): D&D Beyond switches books on **per character, by the player**
(`activeSourceCategories` in the character's settings, plus `useHomebrewContent`). Its campaign data names the DM and
the characters but not the shared books. Every spell and item on a sheet names its book (`sourceId`).

- **Automatic: what a player has.** Spells, prepared spells and inventory come from D&D Beyond, already limited by the
  player's settings there. askdnd shows what's on the sheet; nothing to build.
- **The campaign's books: what askdnd offers.** What isn't on a sheet comes from askdnd's own lookups: Sheet's "All you
  could prepare", the Spell Book, Wild Shape forms, and later stat blocks, items to hand out and rules answers. These
  follow the campaign's list instead of the fixed `CORE_SOURCES`.
- **A sheet with a book the campaign has off** (a Xanathar's spell when Xanathar's is off): it still shows, since it's
  on the sheet, labelled with its book. askdnd removes nothing; the DM rules.

## The shape (from the content-sources draft)

- A **source** is a book, the SRD, or someone's homebrew; it holds **entries** (a monster, spell, item, feat, subclass,
  or a section of rules text), each with a kind, a name, its details as one document, and its page.
- A **campaign's books** are the sources it has on, in order (homebrew, then books, then the SRD); the first that has
  an entry wins and the page says which.
- **A copy in play:** a monster in a fight or an item handed out keeps a copy of its entry, so switching a book off
  never breaks a fight or an inventory.
- The SRD stays files in the repo and is registered as a built-in source.
- Stays concrete (its own tables, as today): characters, play state, rolls, the story.
- Not built: a general "anything" model, plug-ins, schemas per book, access checks during play.

What changes in the code is small: `campaign_content` (empty; nothing writes to it yet) becomes entries of a source, a
campaign gets its list of books, `CORE_SOURCES` gives way to that list, and `catalog/find` keep their signatures. About
a day, with Manage › Settings › Books the only visible change.

## When askdnd runs inventory and spells (Brett's question, 2026-10-27)

Once askdnd keeps play state (1.2 casting spends slots, 1.5 inventory in play), things change during a session that
D&D Beyond never sees. Each lands in a bucket, so there's no gap:

- **What's on the sheet** (D&D Beyond's spells and items): their text comes with the sheet, as today. askdnd stores only
  the play numbers against D&D Beyond's own id: slots spent, charges left, potions used, who holds it. No book text is
  copied, and the books toggle doesn't apply (it's already the player's).
- **What askdnd puts into play** (loot the DM hands out, an item from homebrew): picked from the campaign's books, so
  the toggle applies at that moment. It becomes campaign data: a **copy in play** with its book and entry, a copy of the
  entry's details, and its numbers (quantity, charges, attuned). Private book text in it stays in that campaign, in the
  database, never in git. Switching the book off later keeps the copy, labelled with its book.
- **Given to another character:** the copy, or the play numbers, move to them. D&D Beyond can't be written to, so askdnd
  reminds both players to update their sheets there. When the item shows up on a sheet later, the D&D Beyond merge
  (1.7) links it to askdnd's copy instead of counting it twice, and lists it under "what changed".
- **Spells:** spells known and prepared stay D&D Beyond's (they change when you level up or prepare). askdnd spends slots
  and tracks concentration. The only spells that arrive through askdnd come on items (a scroll, a wand): they're part of
  that item's copy.
- **An unidentified item** (a potion the party hasn't tried): the DM hands out the real entry and players see only what
  they've learned, like monsters (2.6).

## Decisions for Brett

1. **The four buckets** as above. *Recommended.*
2. **Rules content is one shape** (sources hold entries); play and story stay concrete. *Recommended.*
3. **Checked once:** a campaign's list of books, set when it's made and changed by its DM or an admin; no checks when a
   game loads. *Recommended.*
4. **The books toggle:** each book on or off per campaign (default: the SRD and the 2024 core books); off hides its
   entries from lookups and keeps copies already in play; a character's own sheet always shows, labelled. *Recommended.*
5. **Enhancements are askdnd's,** shown to everyone, always in our own words. *Recommended.*
6. **A book belongs to a person** (the DM's library), usable in any campaign they DM. *Recommended.*
7. **A book's optional rules become house rules** the DM switches on, not rules that apply by themselves. *Recommended.*
8. **Build the model now** (about a day, while `campaign_content` is empty); getting a book's content in is decided
   later, when the DM first wants one. *Recommended.*
9. **What askdnd puts into play is campaign data with its own copy;** what's on a D&D Beyond sheet gets only its play
   numbers in askdnd, and the merge links the two when an item reaches the sheet. *Recommended.*

Open for later: how a book's content gets in (typed, imported from a file made on the Mac, or read from D&D Beyond), and
what a second group could see (VTT 7.1).
