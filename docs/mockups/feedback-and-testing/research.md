# Feedback, manual testing and defects: how established tools model them

Research for the Found, Fixed, Tried mockup (Nov 17, 2026), read from vendors' documentation. TestRail's and Testmo's
help sites refused direct reads (403); their points come from search excerpts of their own help pages.

## Test management

- **TestRail.** Case (in a Suite) → Run (or a Plan of runs, under a Milestone) → Test (the case inside the run) →
  Results (a history per test). Statuses Passed, Blocked, Untested, Retest, Failed, plus up to 7 custom; set by hand,
  never derived from defects. Add Result is one dialog; its Defects field takes several ids, and Push files a Jira issue
  from it. A result can be edited only within an admin-set window, with its own permission for others' results. Retest
  is a process step: the fixed defect goes back to the tester who failed it.
  support.testrail.com/hc/en-us/articles/7077819312404-Results
- **Xray (Jira).** Test, Test Execution and Test Plan are Jira issues; a Test Run is a Test inside an Execution, with
  step results. Statuses TODO, EXECUTING, PASS, FAIL, ABORTED (custom RETEST suggested). The run's status is worked out
  from its steps and can be overridden. Defects per step or per run, new or existing, several each. Retest: a new (often
  cloned) Execution; old runs stay, and coverage reads the latest. docs.getxray.app/display/XRAY/Retesting+with+Xray
- **Zephyr (Scale, Squad).** Test Case → Test Cycle → Test Execution; statuses Not Executed, In Progress, Pass, Fail,
  Blocked. Defects per execution or step. "Start a New Test Execution" archives the previous result; Squad's history
  logs every status, assignee, defect and comment change with who and when.
- **Qase.** Results Passed, Failed, Blocked, Skipped, Invalid; custom statuses marked positive or negative, a negative
  one starting the defect flow; statuses can be hidden, never deleted, so history keeps its meaning. One dialog with
  "create or attach defect". Defects Open → In Progress → Resolved, or Invalid; one defect may cover many failures.
  Retest clears the current result and keeps the failure in history. Closed runs are locked. Two-way sync with Jira,
  Linear and Azure DevOps. docs.qase.io/en/articles/5563702-test-runs, docs.qase.io/en/articles/5563710-defects
- **Testmo.** Untested, Passed, Failed, Retest, Blocked, Skipped, plus custom; a result needs a status, a note, an
  attachment or a linked issue.

## Issue trackers

- **Jira.** Statuses in three categories (To Do, In Progress, Done); Resolution a separate field (Done, Won't Do,
  Duplicate); a Reopen that doesn't clear it leaves reopened issues looking resolved. Service Management flips a request
  to Waiting for customer when an agent comments, and back when the customer replies.
- **Linear.** Status categories Triage, Backlog, Unstarted, Started, Completed, Canceled (plus Duplicate). Triage is
  an inbox (integrations, people outside the team, Asks) with Accept, Decline (with a reason), Mark as duplicate
  (merging attachments and requests) and Snooze; waiting for information is a comment, left in Triage. Pull request
  events move issues (opened → In Review, merged → Done). linear.app/docs/triage
- **GitHub Issues.** Open or closed with a reason (completed, not planned, duplicate); "fixes #n" in a merged pull
  request closes the issue; Projects add a custom Status.

## Feedback intake

- **Marker.io.** Annotated screenshot with console, network and environment, optional replay; a Member form and a
  short Guest form; each report becomes an issue in the connected tracker, synced both ways; reporters get "Issue
  resolved" email and a feedback page; internal comments hidden from guests.
- **BugHerd.** Feedback pinned to an element; columns Feedback (untriaged) → Backlog → Todo → Doing → Done ("not yet
  verified by the task owner") → Archive; guests see only their own.
- **Usersnap.** Open, In progress, Review, Done (custom up to 10); highlighter, pen, arrow, blackout, comment; email
  reply to the reporter, internal comments.
- **Jam.** Capture only: a link with the screenshot or recording, logs and device; sent to Jira, Linear or GitHub; no
  workflow of its own.
- **Sentry User Feedback.** A widget (description, screenshot, email, replay of the last 60 seconds) into its own
  inbox and issue category; linked to errors and replays; can create or link a Jira or GitHub issue.
- **Canny** (ideas). Open, Under Review, Planned, In Progress, Complete, Closed; votes measure demand; merging joins
  votes and comments; a status change emails voters. **Productboard**: raw Notes (Unprocessed → Processed → Archived)
  linked to Features, one note to many.

## What they agree on

1. Five layers kept apart: the report (with its evidence), triage, the issue (the work), the test case, and its
   results.
2. Failing is one action: status, words, evidence and "a new issue or one already filed", as many as found.
3. Failed is set by the tester, never worked out from the issues.
4. Results are append-only; a retest adds a result, the failure stays in history, and the latest result is where it
   stands. Corrections are a new result, or an edit only within a short window with its own permission.
5. A fix flows forward (a merged change marks the issue fixed) and sends the test back to whoever failed it; trying it
   again stays a person's step.
6. Closing needs a reason (fixed, not planned, duplicate, can't reproduce), and reopening clears it.
7. "Needs info" is a waiting state that flips back on a reply; internal comments stay apart from what the reporter
   sees.
8. Ideas have their own intake (votes, merging, "tell me when it ships").
9. For a company: a who/what/when log per object, permissions to override results, state maps for Jira and GitHub
   sync, and states that can be retired but never deleted.
