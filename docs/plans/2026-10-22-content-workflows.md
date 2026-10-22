# Who writes the campaign: content workflows (decided 2026-10-22)

Brett's goal: campaign content is accurate and **owned by the DM**, helped by three inputs: the DM's own writing,
imported transcripts (most of the work), and players' corrections. Audit and diagrams: the "askdnd content
workflows" page; answers below are Brett's (all eight matched the recommendation).

## The rule

**The DM writes the canon; everything else proposes.** What the table reads (recaps, key moments, entries,
glossary) changes only when the DM (or a reviewer or admin) writes it or accepts a proposal. Transcripts, players
and Claude propose; the DM decides when Claude helps.

## Gaps found (2026-10-22)

1. Nothing could be created by hand: entries only came from transcripts or imports; no key moment or session
   without Claude.
2. Accepting a transcript's entry update (or a redraft) replaced the whole description, even one the DM wrote.
3. Two suggestion pipes: entry facts (Merge · Reject) and recap or glossary suggestions (Use · Done · Dismiss).
4. Recaps and key moments needed Reviewer access; the DM tick alone didn't allow it.
5. No housekeeping: change kind, open or close a quest, publish or hide, merge duplicates, delete.
6. A correction to a published recap only showed under it.
7. Players never heard what happened to their suggestions.

## Decisions

1. The rule above: yes.
2. **The DM includes Reviewer** (in their campaign once step 10 makes roles per campaign; until then the DM tick
   grants what Reviewer grants).
3. **One inbox** on Manage for every suggestion (entry facts, recap and glossary suggestions, transcript drafts
   waiting for review), with the same four actions: **Accept**, **Edit then accept**, **Ask Claude to work it in**,
   **Dismiss**. Transcript reviews keep their own page and are listed there.
4. **"What the table knows" stays visible** until a fact is worked into the description (or marked Done).
5. **Protect the DM's words:** each description and recap records who wrote it last. A transcript update or
   redraft of DM-written text arrives as a marked-up edit that keeps the DM's words; nothing is replaced wholesale.
6. **DM tools, all of them:** + New entry on each Campaign tab, merge duplicates, change kind, open or close a
   quest, publish or hide, delete (History restores), add a key moment to an entry, add a session by hand with no
   transcript or Claude.
7. **Published recaps:** a player's correction is acted on by editing the recap or asking Claude to redraft with
   it, then republishing; the correction is marked Used.
8. **Players see the outcome:** Used, Added or Not used, on the entry and in their own list (no notifications).

## Build order (before roadmap step 10)

1. **DM tools** (decision 6) and the DM-includes-Reviewer access change (decision 2). Done 2026-10-22: + New entry,
   Details (kind, quest, hidden), + Add a key moment, merge, delete (not player characters), Add session › Save as the
   recap; the DM tick now grants everything Reviewer does.
2. **One inbox** (decisions 3, 7, 8). Done 2026-10-22: Manage › Suggestions became **Manage › Inbox** (still at
   `/suggestions`): the table's suggestions with Accept · Edit · Ask Claude to work it in · Dismiss (sessions: Edit the
   recap · Ask Claude to redraft with it · I fixed it · Dismiss; glossary: edit or add the term in place), Claude's
   description drafts (Check it opens the entry's Edit window), and sessions to review. Players see Waiting, Added,
   Used or Not used in the entry's panel and on **Your suggestions** (`/your-suggestions`, account menu).
3. **Protect the DM's words** (decision 5).
