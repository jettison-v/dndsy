# Engineering practices (Nov 13)

Brett, Nov 13: "Even spells and attacks should have IDs instead of text. Are there other development best practices
we should also include? I am not concerned about the token spend or development time. I want to follow all of them.
Things breaking take more time than more robust development would have."

Each practice below gets **a check that enforces it** (a test, a linter, a CI step), so it holds without anyone
remembering it, and a place in the order of work (`docs/DECISIONS.md`, Nov 13): **F** foundations (now: Brett, Nov 13, "Yes, foundations first"; every practice marked F before the structure lock),
**S** structure lock, **C** component library, **D** design review, **R** code review, **H** test hardening,
**N** net-new features. What askdnd already does is marked *have*.

## What robust means (Brett, Nov 13)

"I ask for an enhancement, we mock it up, the enhancement itself might need tweaking, but it does not have a negative
impact to the current system at that point in time or in the future." A change is robust when it does none of these,
and each has the checks that catch it:

| What must not happen | What catches it |
|---|---|
| **A bug in what already worked** (security included) | Linters (F4), the server and browser suites on every push, every button and roll enumerated (test_every_roll, test_refusals, test_links), the review before merge (F6) |
| **A bug in the tests themselves**: a test that passes while the thing is broken, or fails while it works | Markers, never words (test_no_text_refs); asserting outcomes, never timing; a flaky test fixed at its cause; the review reads tests as closely as code; mutation testing on core logic (F8) |
| **A workflow left incomplete**: a path that 404s, a person or state not covered, a doc or the tour not updated | "Before calling a change done" (CLAUDE.md) checked in the review (F6); routes enumerated (test_usage, test_refusals, test_links); a browser test that walks the new flow end to end |
| **The UI or UX quietly getting worse**: something moved, hidden, restyled or slower that nobody asked for | Layout checks at every width (test_layout); the design system; a visual comparison of every main page before and after each change (F7) |
| **Any of the above later**, when the next change lands | Each enhancement leaves a test that fails if it breaks; ratchets only go down; nothing merges red |

## The foundations, in order (F)

1. Dependency and code scanning: Dependabot, pip-audit, CodeQL, secret scanning. **Built** (#326).
2. A strict Content Security Policy and a cross-site (Origin) check on every change. **Built** (#329 the policy, #331 the Origin check and blocks reported to Sentry).
3. Migrations run up and down in CI on a fresh database, and the models match it. **Built** (#330).
4. Linters: ruff's bugbear, simplify, pyupgrade and security rules; ESLint for app.js (no redeclared or implicit
   globals, the bug of Nov 13); Stylelint for app.css; djLint for templates. **Built**: ruff (#331); ESLint, Stylelint and djLint (tools/lint, pyproject.toml).
5. A preview for each pull request on Railway (Brett switches it on in Railway's dashboard; Claude wires the rest). **Skipped** (Nov 13): a preview's random address can't use Google sign-in, starts with an empty database, and with no base environment copies production (the legacy app and the nightly backup job, which could save an empty backup that a staging refresh then loads). Local first and staging.askdnd.ai cover it. Revisit only with Base Environment = staging, Focused PR Environments on, and a way to sign in.
6. The automated code review at high effort on every PR before it merges, its findings fixed. **Built** (Nov 13): before
   merging any pull request, Claude runs the code review at high effort on its diff, fixes what it finds (or says why
   not), and writes the outcome in the pull request's **Review** section (.github/pull_request_template.md). The
   review checks the diff against "What robust means" above and CLAUDE.md's "Before calling a change done".
7. A visual comparison: every main page drawn before and after a change (main against the branch, same data, same
   widths), and the differences shown to Brett before merge. Kept off GitHub (the repo is public: no pictures of pages
   with the party's sheets); run locally or on the Mac Mini. **Built** (Nov 13): `uv run python scripts/visual_compare.py`
   draws every main page for a player and an admin at laptop and phone width, plus states a page only shows sometimes
   (the connection band), on main and on the branch, and writes private/visual/report.html with only what changed
   (before, after, the change in red). main against itself: 62 of 62 the same. Run it before merging anything people see,
   and show Brett the report's changed pages.
8. Mutation testing on core logic (the roll plan, hit points, rules data, access): small deliberate bugs put into the
   code, and the tests must catch each one; a bug they miss is a missing test.

Each lands as its own pull request, with its check on in CI the day it lands.

## 1. Identity: everything has a key, nothing is found by its words

- **Game things by ID** (R, started in S): every spell, attack, feature, item, condition and creature carries a stable
  key, D&D Beyond's own definition id where there is one (the sheet has them: 72 places in app/ddb_sheet.py read
  them), else the rules data's slug (`srd:fireball`, `phb-2024:sneak-attack`). Battle rows, roll plans, recipes,
  riders, Search's index, Table rolls' rows (`TableRoll.detail["ref"]`) and corrections carry the key; the name is
  only for showing. Today about 68 lookups go by name (`name == "Unarmed Strike"`, a recipe found by its spell's
  name, a magic weapon by its name without the base); each moves to the key, with a name-to-key map built once on
  import for data that comes without one. Check: the ratchet in tests/test_no_text_refs.py gains a "game things by
  name" count that only goes down.
- **UI by marker** (F, *started*): `data-*` on every piece a test or script refers to; tests/menu.py and
  tests/browser/pages.py. Check: tests/test_no_text_refs.py.
- **Not translation** (Brett, Nov 13: not needed now; the point is never referencing text): no string catalog for
  now. If askdnd is ever translated, keys and markers already make it a matter of the words alone.

## 2. Code structure

- **app.js as modules** (R): today one 5,000-line script in shared scopes, where a new `place()` silently replaced the
  roll card's (Nov 13). Split into ES modules by feature (the roll card, Search, the table, Live…), each with its own
  scope and an explicit export; vendored, no build step needed. Check: ESLint (no redeclared or implicit globals, no
  unused), run in CI.
- **Types** (R, then every change): Python type checking with pyright in CI, strict for new and touched modules;
  JSON columns (`Campaign.fight`, `Character.companions`, `TableRoll.detail`…) described by pydantic models and
  validated on write; app.js checked with `// @ts-check` and JSDoc types. Check: CI fails on a type error.
- **Boundaries** (R): routes call services, services call the database; the rules engine (roll_plan, hit_points,
  measure…) stays pure (no database, no request). Check: import-linter contracts in CI.
- **Linters and formatters** (F): ruff with more rule sets (bugbear, simplify, pyupgrade, security), ESLint and
  Prettier for JS, Stylelint for CSS (tokens only, *partly have* in the design test), djLint for templates. Check: CI.

## 3. Data

- **Migrations tested** (F): every migration runs up and down on a copy of a recent backup in CI, and the models
  match the database (alembic's compare). Check: a CI job.
- **Constraints in the database** (R): foreign keys, NOT NULL and unique where the code assumes them, so bad data
  can't be written even by a bug.
- **Restore drill** (H): the nightly backup restored and checked automatically once a week (*have* the backup and the
  restore script). Check: a scheduled job that alerts on a miss.

## 4. Security and privacy

- **Content Security Policy** (F): askdnd loads nothing from elsewhere (*have*: vendored scripts), so a strict CSP
  header can say so and stop injected scripts. Check: a test on the headers (*have* SAFE_HEADERS).
- **CSRF** (F): the session cookie is SameSite=Lax (*have*); add an Origin check on every change, so a form posted
  from another site is refused. Check: tests/test_refusals.py gains a cross-site case.
- **Dependencies** (F): Dependabot for Python and the GitHub Actions, pip-audit and GitHub's CodeQL and secret
  scanning in CI. Check: CI.
- **Rate limits** (R) on sign-in, feedback, Claude and OpenAI calls (*have* the spending limit).
- *Have*: refusals tested for every route, privacy scrubbing in error reports, the public-repo guard, hidden is as if
  it didn't exist.

## 5. Accessibility

- **Automated checks** (D): axe-core on every page in the layout tests (the same pages, every role), failing on
  serious issues; keyboard-only tests for the menus, the roll card and windows; focus kept and returned; contrast
  (*have* in the design test since the faint grey fix).

## 6. Tests

- *Have*: server and browser tests, branch coverage over 90%, the every-roll walk, layout at every width, refusals.
- **Fast and parallel** (F, *done*: 9 min to 1.5).
- **Factories, not copied setups** (H): one builder per kind of thing (a character, a campaign, a fight) with sensible
  defaults, replacing hand-written setups in each file.
- **Property-based tests** (H) with Hypothesis for the rules math: hit points (damage, temporary, resistance), moves
  and measuring, dice, a roll's parts adding up.
- **Visual regression** (D): Playwright screenshots of each component and page compared to approved ones, so a
  design change is seen and approved, not discovered.
- **Query budgets** (H): a test that fails when a page makes more database queries than its budget (catches N+1).
- **Contract tests with the extension** (*have* EXTENSION_READS; H: the message shapes as JSON schemas).
- **Flaky tests tracked** (*have* second tries listed; H: a flaky test opens an issue and is fixed at its cause).
- **Mutation testing** (H, occasionally): mutmut on the rules engine to check the tests catch real changes.

## 7. Delivery

- **A preview per pull request** (F): Railway's PR environments give each PR its own address (with staging's data),
  so Brett tries a change there instead of on his computer or after merging. Check: the PR links its preview.
- **Code review before merge** (from now): every PR gets the automated code review at high effort and its findings
  fixed before it merges, plus the design checklist (CLAUDE.md › Before calling a change done).
- **Feature switches** (*have* Labs and Features) for anything risky; **a freeze** before game nights.
- **Deploys** (*have* deploy_check, the after-deploy live test, Sentry); add an uptime monitor (Sentry) and a
  one-command rollback.

## 8. Performance

- **Budgets** (D): page weight, time to first paint and to interactive, measured in the browser tests per page.
- **A game-night load test** (H): five people, live connections, a fight, rolls, for an evening's worth, against
  staging (*have* timing on slow requests).

## 9. Documentation

- **CLAUDE.md split by area** (R): the root file keeps the rules; each area's details move to a CLAUDE.md in its
  folder, read when working there, so nothing is missed in a file this long.
- *Have*: DECISIONS, the design system, plans, the roadmap, the library of pages.
