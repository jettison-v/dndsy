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

## Progress (kept current on the branch)

- **Slice 1, done** (cb9c09ca): app/fft/models.py (17 tables, migration 8de6dc8271e6 with the two circular links added
  by hand), app/fft/rules.py (R1–R18; `check_state` works a check's state out per device; `pick_next` is R15),
  tests/test_fft_rules.py (each rule, a randomized invariant run, the record matching the rows). Test databases now
  drop tables one per transaction (tests/conftest.py `drop_everything`).
- **Slice 2, done**: app/fft/keys.py (Claude's FEEDBACK_KEY, staging's FFT_RELAY_KEY, the Mini's FFT_MINI_KEY, and
  hashed keys made in the app, each with its scopes; header `X-Fft-Key`, trusted by app/same_site.py), app/fft/api.py
  (`/api/fft`: inbox per listener leaving out Claude's own changes, next, notes and issues with only filed notes and
  approved lines, first names, every text quoted with who wrote it, the page only with `page=1`, a picture only as its
  safe copy; issues, checks, questions, areas and items, deploy, the relay, the Mini's tries; Claude can't close an
  issue as working), app/fft/steps.py (the walkthrough's rules, moved from app/testing.py, which imports them),
  `scripts/fft.py` (tried against the local server end to end), tests/test_fft_api.py (the privacy tests from
  privacy-rules, ported, plus keys and listeners). Left for slice 3: a picture added to a line (`_line` lists none yet).
- **Slices 3 and 4, done together** (approving lives on the Feedback page, so they're one piece): sending
  (app/fft/sending.py, `_feedback_window.html`, app.js "send a note": Send a note with nothing picked, pictures as chips,
  Box, Arrow, Draw and Text with Undo and Clear apart, Hide while I take a screenshot, the truthful line from
  `/feedback/line`; the page's picture as a full copy for its sender and a safe copy with `[data-private]` parts covered,
  marked on Plan, Battle's combos, the note panel and form; the page as drawn with those parts emptied; staging relays
  safe copies with a first name), Manage › askdnd › Feedback (app/fft/feedback_page.py, `fft_feedback.html`,
  `_fft_bits.html`, `_fft_same.html`, `_fft_close.html`: To approve with Undo in the corner card, Same as…, Open, Ready
  to try, Closed, Ideas, the issue page, Close with a reason, Reopen, OK to merge, a player's later line approved), Notes
  you sent's Product Feedback tab (app/your_notes.py on fft notes: whose turn, the lines meant for you, Add to it, Does
  it work now?, new reply). app/fft/views.py holds the words (whose turn, sentences, first-sentence titles, local links).
  Tests: tests/test_fft_pages.py, tests/browser/test_feedback_window.py (rewritten), tests/browser/test_fft_feedback.py.
  Retired with what they tested: tests/test_feedback.py, test_areas.py, test_check_issues.py, test_questions.py, the
  Testing tests that sent through the old window, tests/browser/test_areas_order.py and test_check_rounds.py (slice 5
  brings Testing's). The old app/feedback.py routes the new ones shadow go in slice 6's clean-up; Claude's API doesn't
  list a picture added to a line yet.
- **Slice 5, done**: Manage › askdnd › Testing (app/fft/testing_page.py, `fft_testing.html`): For you as the view of
  everything Brett's in the one order (checks for the device he's on or another he must use, Claude's questions and
  decisions, fixes to OK, then the table's notes and ideas, then Roadmap steps), a check as the card will show it with
  its devices, problems, why and history (struck-through corrections); Claude's and Done. The round (`_fft_card.html`:
  left by default, drags, folds, keys P/F/C; ▶ Start round, ▶ Just this area, ▶ Try it as a round of one through its
  character's eyes; Passed moves on with Undo; End round), Something's wrong… as the note window's check mode (still
  happening or new, stops the check, stops the round; ✗ Another… adds to the same try), Can't try… and Change result…
  windows (`_fft_cant.html`, `_fft_change.html`), questions answered there. Rules: R18 holds a check until Claude's
  own try of that version passes (state `preflight`); a check only the Mac Mini runs is Claude's and the Mini's runs
  count for its device; `add_found`, `note_on_issue`, `still_happening`; a correction withdraws an issue only that try
  found even with the tester's own note on it. base.html shows a waiting corner card on any page. Found on the way:
  Help's FAQ reused the ids `cards` (so every corner card on Help vanished into a folded answer) and `wild-shape`;
  renamed, and the layout check now fails a page that repeats an id. Tests: tests/test_fft_testing.py,
  tests/browser/test_fft_round.py; tests/test_testing.py retired.
- **Slice 6, done** (9f77b56d): Where it stands (the Roadmap's items and their areas in Brett's order, dragged; each
  area's turn and what it means; listening; an open round's End round; Rename, Merge into, Move to another item,
  Archive; rules `order_items`, `order_areas`, `rename_area`, `move_area`, `merge_area`, `archive_area`); live updates
  (app/fft/live.py: any change tells every open page, `realtime.EVERYONE`; Feedback, Testing, Notes you sent, the card
  and the badge refresh); Manage's counts, Needs you and the daily fix email on the new tables; the carry-over
  (app/fft/carry.py, migration 3f9c1a7e5b20, tests/test_fft_carry.py; run on the local copy of beta); app/feedback.py,
  app/testing.py, app/for_claude.py and their templates and CSS retired; scripts/feedback.py is the new CLI (with
  `live`, which deploy_check.py runs). CLAUDE.md, MAP, Help's FAQ, the testing guide and DECISIONS updated.
- **Slice 7, under way**: visual_compare (14 of 72 pictures changed, each one meant to), the code review at high effort
  (two independent reviewers, server and pages: 30 findings, fixed: every player note drawn is now marked private and
  guarded by tests/test_private_marks.py; the page as drawn loses private attributes too; marks land where drawn; Undo
  is a real page and says when it's too late; ✗ Another… alone joins the last failed try; the hidden window, a draft
  and a reload's message are kept; Undo of a pass reopens what it closed; Same as moves a check's hold; R17 for a
  player joining a fix; locks are their owner's; the three days' hand-off runs; a round of one never ends the round it
  joined; an approval names the lines it saw; first names at any depth; the carry-over keeps a player's old page and
  pictures to them; Notes you sent's badge in four reads; tests/test_fft_review.py). Left as they are: a pinch-zoomed
  iPhone's cover may sit off its notes; /manage/counts works For you out per check. Next: Brett's local trial with the
  listener on localhost, then one PR.
- At the merge: run `scripts/deploy_check.py --set-backup-watch` (app/fft joined BACKUP_WATCH).
