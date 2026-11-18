# Found, Fixed, Tried: the build plan

Brett, Nov 17: "Yes, build it": one branch (`found-fixed-tried`), Brett tries it locally, then one merge replaces
today's Feedback and Testing. The design is the v2 brief (`docs/mockups/feedback-and-testing/index.html`, rules R1–R18,
trust T1–T8) and its 16 screens (`docs/mockups/found-fixed-tried/index.html`), after the audit
(`docs/artifacts/found-fixed-tried-audit.html`) and an independent review. Read those first; this plan is how they're
built.

## What Brett wants (the measure of every slice)

1. Log a bug or an enhancement easily, from any page.
2. Order the work Claude does.
3. Try what Claude built and say whether it's what he meant.

All inside askdnd. The rules are many so that he never has to think about them: every pill answers "is it mine?".

## How it ships

- **One branch, nothing merged until the end.** Today's Feedback and Testing keep working on askdnd.ai while it's built.
  This area of the code is frozen on main meanwhile (Fixes and polish work goes on elsewhere).
- **Claude tests it end to end** (server tests for every rule and privacy guard, browser tests with several people, a
  laptop and a phone), then **Brett tries it locally** on the copy of beta, with Claude's listener pointed at
  localhost, then **one merge**.
- **Old tables stay** (`feedback`, `feedback_pictures`, `checks`, `areas`, `claude_inbox`) until Brett has used the new
  tool for a few days: undoing the merge brings the old tool back with nothing lost. A later small change drops them.
- **Open work carries over** once, at merge: open notes become notes and issues, open checks become checks (v1), areas
  and their order become areas under items.

## In the first release / held back

In: sending a note (kinds, pictures, markup with Text, Undo apart, hide for a screenshot, safe copy), approving
(issue, same as, idea, answered question, decline; Undo), Notes you sent (The Story, Product Feedback, open counts,
replies, Does it work now?), Feedback (To approve, Open, Ready to try, Closed, Ideas; the issue page; Same as; Close
with a reason; Reopen; Move to area), Testing (For you as the view of everything Brett's; a check with versions and
per-device state; the round and its card; Something's wrong…; Change result; Can't try…; a check's history; questions
and decisions answered in For you; Where it stands as the one queue by item, with items and areas ordered there until
the Roadmap page exists), Claude's side (the API with first names and quoted words, a read mark per listener,
`feedback.py next`, checks tried automatically before they reach Brett), live updates on these pages.

Held back until Brett has lived with it: the Roadmap page itself (paused; its items exist, ordered on Where it stands),
the player side of the Roadmap, an area in a chat of its own, offering to re-try passed checks after changes, Jira or
Linear export.

## The model (app/fft/, its own tables, `fft_` prefix, `workspace_id` on every row)

| Table | What it is |
|---|---|
| `fft_items` | A Roadmap item: title, place (the one order), standing (Fixes and polish), whose next step and what. |
| `fft_areas` | A batch of Claude's work under one item: title, place within the item, round number, lock (owner, until). |
| `fft_notes` | What anyone sent: sender (user), kind (problem, idea, question), words, page, context (no emails), pictures (full and safe copy), state (waiting for you, filed, declined), the issue or idea it filed into. |
| `fft_note_lines` | A note's conversation, one row each (never a rewritten list): who, to whom, words, approved or not. |
| `fft_issues` | The work: title, area, state (to fix, fixing, asks, merge OK, ready to try, closed + reason), reopened, the PR, kind (problem; an idea is an issue of kind idea on its own list). |
| `fft_checks` / `fft_check_versions` | What to try: the check (area, required devices, retired) and each version (steps, expect, page, why). |
| `fft_tries` / `fft_try_issues` | One go at a check: who, device, where, app version, check version, result (passed, failed, can't try + why/blocked-by), replaces (a correction), round; each issue it names, blocking or not, new or still happening. |
| `fft_rounds` | A sitting: who, opened, ended (by hand, or idle 12 hours). |
| `fft_questions` | Something Claude asks: about an issue, check, area or a document (a decision), choices, Claude's pick, the answer (naming the question). |
| `fft_events` | Every change: who (person or actor), what, the thing, from, to, when. Append-only; private words held by reference so they can be erased. |
| `fft_listeners` | A read mark per listener (the main chat; later an area's own), so none takes another's items. |
| `fft_keys` | A hashed key per actor and place, with what it may do (Claude on askdnd.ai, staging's relay, the Mac Mini). |

States are kept on the rows for speed and **written only through `app/fft/rules.py`**, which applies R1–R18 and
appends the event in the same transaction; a test replays the events and checks they reproduce every row.

## The rules in code (app/fft/rules.py)

One function per event (send, approve, join, decline, file, fix_merged, rollback, try_passed, try_failed,
try_corrected, cant_try, move, close, reopen, ask, answer, round_open, round_end, pick_next…), each enforcing its
rule and refusing what the rule forbids (R11: no merge OK while a round is open, except an issue that stops the
round; R14: a mark made against a stale state is refused with what changed). A table-driven test walks every
combination of check, issue and try states through every event (R3–R8 especially), and a property test checks the
invariants: no check left Failed with no open blocking issue; a pass never closes a non-blocking issue or one still
failing elsewhere; nothing unapproved is ever readable by an actor key.

## Trust and privacy (T1–T8), tests first

The tests parked on branch `privacy-rules` (unapproved words never reach Claude's inbox, API, a check's history or an
area's list; no emails or full names; the page only on request; the staging relay always waits for approval; who
wrote each line) are ported to the new API before it's written. Added: a safe copy of every page picture (a player's
character notes blurred at capture), shown to approvers and Claude; scoped keys; a read mark per listener.

## Slices (each committed on the branch, tests green at each)

1. **The model, the rules, the record**: tables and migration; rules.py with R1–R18; events; the table-driven and
   property tests; T1, T2, T7.
2. **Claude's side**: the API (first names, quoted and labelled words, approved only), keys, listeners and their read
   marks, `feedback.py` rewritten (inbox, wait, next, note, issue, check, try, ask, area), checks tried automatically
   before they reach Brett.
3. **Sending, approving, Notes you sent**: the feedback window (kinds with nothing picked, pictures, markup with Text,
   Undo apart, hide for a screenshot on Mac and iPhone, the safe copy, the truthful send line), approving with Undo,
   Same as with its preview, the player's view.
4. **Feedback's pages**: the lists, the issue page, Close with a reason, Reopen, Move to area.
5. **Testing**: For you, the check (versions, devices), the round and its card (left, draggable, folds, keys, End
   round, Passed moves on with Undo), Something's wrong…, Change result, Can't try…, history, questions and decisions.
6. **Where it stands and the rest**: the one queue by item, the open round's lock, listening on or off, rename, merge,
   move, archive; live updates on every page; the menu's counts; the carry-over of open work.
7. **The full review**: the code review at high effort, visual_compare, the layout checks at every width (and WebKit),
   browser tests with several people; then Brett's local trial; then one PR and the merge.

## Docs that change with it

docs/MAP.md (Feedback for Claude, Testing in askdnd: replaced by one section), CLAUDE.md (the loop: `feedback.py
next`), Help's About and FAQ, the DM guide where it mentions feedback, docs/testing-guide.md, docs/DECISIONS.md.
