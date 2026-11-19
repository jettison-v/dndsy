# The work flow: build plan (Nov 19)

What Brett agreed on the [Work Flow Map](../artifacts/work-flow-map.html) (reworked Nov 19 from his nine picks on
[Work Flow, Sized to Grow](../artifacts/work-flow-sized.html), and the map's last two picks in chat), built in slices.
Brett chose this before homebrew items (Nov 19): his testing time drops to about an hour a week within a month, and the
lanes are what make that hour enough.

## What's decided

- **Lanes per plan**: Ship (no test from Brett), Look (merged; Brett tries the batch on askdnd.ai after), Careful (one
  round on staging, ships exactly as tested, automatic checks after). Careful = who sees what, sign-in, spending, the
  D&D Beyond bridge and extension, database changes that alter or remove data. Rules pick the lane; one tap moves a plan
  up; Claude may move one up, saying why; down only on Brett's word, kept with who and when.
- **Levels per product**: Start (askdnd), Team, Company. Each check is a setting per lane and level; triggers suggest a
  step up, Brett decides. Nothing D&D-specific in the engine; roles, not people; the full record from day one.
- **Work**: one ordered list with a cut line; Claude takes everything above it; a player's bug lands above it; held
  rows below. Each row's stage is worked out from what's true, never set by hand. One plan per Product Area at a time;
  a plan's scope freezes once planning starts. An issue about something a Roadmap item is about to rebuild goes into
  that item's plan (Claude says so on the issue).
- **Approving a player's note is the OK for its fix** (R17's later OK goes).
- **No deploys 6 hours before a game**, from the session's date; a fix for something broken at the table may go, with
  Brett's OK.
- **Players see plain stages**: Waiting its turn, Being built, Brett is trying it, Live.
- **Names**: For you (everything waiting on Brett), Feedback (what comes in), Work (the one list and its plans),
  Testing (each plan's history, opened from Work).
- **At every level**: privacy tests, tried backups, database changes only add, a Labs switch for risky features, the
  game-night freeze, the full record. An incident moves only its Product Area to Careful for 30 days.
- **Designed to** about 2 hours a week of Brett's testing now, about 1 hour once he works full time.

## Slices, in order

Each slice is one pull request through the full process (tests, the code review at high effort, visual_compare, a
look at every person and width), tried by Brett locally first while the old rule stands, and works on its own.

### 2 · For you, its own page (Small)

- `/manage/for-you` (Manage › askdnd › For you, admins), `testing_page.for_you` moved behind it; Testing loses its
  For you tab and opens on Where it stands. Old links (`/manage/testing?show=foryou`, `?open=` of a For you row) go to
  the new page.
- Grouped by what Brett does: **Try** (checks, by area in the one order, ▶ Start round and ▶ Just this area, with the
  minutes), **Decide** (questions and decisions), **Look at** (fixes to OK while R17 stands, fixes live with no check),
  **From the table** (notes to approve, ideas to place), **From the Roadmap** (steps that are his). Same reader, rows,
  pills and article as today.
- Its count on the menu bar: a **For you** button beside the Admin gear, admins only, its count from `/manage/counts`
  (`for-you`), hidden at zero. Testing's count goes (nothing is Testing's own turn any more).
- Rounds: Start round, End round and the card's last step come back to For you.
- Help, docs/MAP.md, the Design system page if the menu-bar button is new there, tests (pages, refusals, reading,
  layout list, browser round test).

### 3 · Lanes on every plan (Medium)

- `FftArea.lane` (ship, look, careful) and `FftArea.lane_by` / `lane_why`; `rules.set_lane` (up by anyone, down by an
  admin only), an event each. Rules pick the lane from the plan's diff (`scripts/feedback.py lane`: the files it touches
  against a list in app/data/lanes.json: access, auth, spending, ddb_bridge, extension/, migrations that drop or alter).
- R17 goes: approving a player's note is the OK. `merge_ok` retired, with a migration moving any open one to `ready`.
- The game-night freeze: `deploy_check.py` and `feedback.py` refuse a merge inside 6 hours of the next session's date
  unless `--table-fix` with Brett's OK.
- An incident: `feedback.py incident <area>` sets the area's floor to Careful for 30 days, with a line in DECISIONS.md.
- Database changes only add: a test fails a migration that drops or alters a column in the same change as code that
  stops using it. The one-page undo checklist (docs/undo.md).

### 4 · Work, with a cut line (Medium)

- `/manage/work`: Where it stands made its own page; one list of plans in order with a cut line (`FftArea.held`);
  a player's bug lands above it; drag below to hold, drop to park (branch kept, issues back to their area).
- Stage worked out from what's true (`views.stage`): Planning, Waiting on you, Building, Held for game night, Your
  round on staging, Live: try the batch, Done. One plan per Product Area; new notes join its open plan until planning
  starts, then wait for the next. An issue Claude puts into a Roadmap item's plan says so.
- Claude takes everything above the line (R15 changes); goes on while a plan waits on Brett, at most two waiting, never
  two touching the same files; the one-area lock allows it.
- Testing becomes each plan's history, opened from Work. The Roadmap page points to Work.
- **Scheduled work** (Brett, Nov 19: "Scheduled work, such as this mobile sweep, should display somewhere on askdnd.ai so
  we know it is being done … a recurring section on the Work page"): a section listing each recurring job (the weekly
  phone sweep, the Mac Mini's nightly live test and iPhone check, the morning D&D Beyond drift check, the 6 AM feedback
  check) with its schedule, last run, result and what it produced (a pull request, a check), and next run. Each job
  reports its run to askdnd (an `/api/fft` call at its end), so a job that didn't run shows as late.
- **How we work** (Brett, Nov 19: "the methodology used / steps taken in our repeatable development process"): the
  process on Work itself, from the engine's settings: the lanes and what each needs, the deploy control's choices,
  every plan's steps (read it whole, write the plan, build one fix at a time, look at it, review it all, checks tried
  first), what runs on every change and what runs weekly. Made from the same settings the tools follow, so it can't
  drift from what's done.

### 5 · What players see (Small)

- Plain stages on Notes you sent. A notice when an idea joins a Roadmap item and when it ships. A joined note's sender
  follows the one it joined. One line in the send window naming who reads a note.
- `FftIssue.source` (Sentry, nightly tests, the iPhone check, a review, a note). Ask back: a question Claude writes for a
  vague note's sender, sent on by Brett from For you (Send to a player).

### 6 · Staging rounds, Careful only (Medium)

- An "on staging" state; Work shows what's on staging. One round branch holds the round's plans and merges whole
  (`scripts/staging.sh --round`); one database change per round (the script refuses a second). Staging refreshed before
  each round, never during. A staging-only sign-in key for Claude's test account. Tries kept on askdnd.ai with
  staging's version; a pass carries through the merge; a fix mid-round resets only the checks it touched. A check that
  setting names match across staging, askdnd.ai and `.env.example`.

### 7 · Checked live (Small)

- After each deploy, Claude re-runs the plan's checks on askdnd.ai (`deploy_check.py`); bridge work adds the live
  D&D Beyond run (docs/live-test-plan.md) before it counts as done. A problem found names its plan.

## Waits for the Team level

Look work through staging, starting Claude on a schedule, release notes, two plans in one Product Area at once, a
nightly staging refresh, a second tester.

## Built so a Roadmap can follow

Order, the cut line, the lane and the stage belong to the plan (`FftArea`), never the Roadmap item. An item can hold
many plans over time. An item's status is worked out from its plans, never kept by hand.
