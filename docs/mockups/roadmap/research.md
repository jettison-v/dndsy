# Roadmaps players can see, vote on and comment on: what established tools do

Research for the Roadmap mockup (Nov 17, 2026), read from vendors' own documentation.

## The tools

- **Productboard Portal.** Cards (a public name and description over an internal feature) in tabs and sections.
  A visitor answers "How important is this to you?" (Critical, Important, Nice-to-have, Not important; wording
  editable), adds details; the vote becomes an insight linked to the feature and feeds a Customer Importance Score
  (one person counts once, latest value). "Submit idea" goes privately to the team, not onto a card. Productboard
  left open voting forums because duplicates piled up, top-voted features went unused (each voter imagined a different
  one), ideas outran capacity and the forum never ended; its portal has Under consideration, Planned, Launched.
  support.productboard.com/hc/en-us/articles/360056315454, productboard.com/blog/how-feature-voting-forums-failed-us
- **Canny.** Posts on boards with statuses (Open, Under Review, Planned, In Progress, Complete, Closed); the public
  roadmap shows exactly three; shipped work moves to a changelog. One vote per person; importance ("vote priority") is
  set only by admins, for signal quality. Internal comments; merging moves votes and comments (and notifies no one);
  private boards; a status change emails all voters by default. help.canny.io/en/articles/3828148-the-roadmap
- **Jira Product Discovery.** Ideas with insights (evidence) and a Delivery tab linking Jira work, with progress
  rolled up; a Votes field with a per-person budget; formula fields for scores; published read-only views for
  stakeholders, choosing which fields show.
- **Aha! Ideas.** Ideas promoted to features (followers notified when it ships); one vote per idea by default,
  optional caps, proxy votes by staff for customers.
- **Featurebase** (also Upvoty, ProductLift). Statuses with fixed types underneath (Reviewing, Planned, Active,
  Completed, Canceled), so names can be reworded; status updates notify subscribers; a reported pitfall: dragging a
  card between columns notified everyone automatically.
- **Linear** (internal). Initiatives contain projects contain issues; health from each project's written update; within
  a priority you drag to set the exact order, so the order on screen is the plan.
- **GitHub's public roadmap.** Issues on a board by quarter plus Exploratory; release-phase labels; issues read-only,
  feedback in Discussions; shipped items closed with a changelog link; "not a commitment".
- **Now / Next / Later** (ProdPad). Columns are confidence, not time: Now validated and being built, Next being
  shaped, Later problem areas likely to change; items written as problems or outcomes; dates only where real.

## Lessons for a small table (about 5 people, one owner, one AI developer)

1. Keep the item apart from feedback: players vote and comment on a few owner-written items; their own suggestions go
   to a private inbox until adopted.
2. Ask "how important is this to you?" (three or four levels, one per person, changeable) rather than a bare upvote;
   with five people a count says little, importance and a sentence of why say a lot. No vote budgets.
3. Votes inform, the owner decides: sequence by the owner's manual order (drag), and the AI developer works from the
   top. No automatic scoring at this size.
4. Few statuses with a fixed type underneath, so wording can change without breaking logic; a "Not doing" with a reason.
5. No dates: Now / Next / Later.
6. Close the loop on purpose: notify voters and commenters when an item changes status, with a short note, as a
   deliberate step, never as a side effect of a drag; on Done, link to what shipped and let them try it.
7. Owner-only notes and internal text beside the public name and description, so build notes and the AI's plan never
   reach players.
8. Plan merge and close-with-a-reason from day one, and notify the people a merge affects.
