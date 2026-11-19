# Undo a bad deploy

One page, for when something broke on askdnd.ai (Brett's picks, Nov 19: "it broke at the table"). Undoing is safe
because database changes only add (tests/test_migrations_add_only.py): the code before a deploy still runs on the
database after it.

## If you're on your own (Brett)

1. Open [railway.app](https://railway.app) › the **askdnd** project › the **askdnd-v2** service › **Deployments**.
2. Find the deployment just below the newest one (the last one that worked).
3. Press its **⋯** › **Rollback**. It takes a minute or two.
4. Open [askdnd.ai](https://askdnd.ai) and check that the broken thing works again.
5. Send a note in askdnd saying what broke (\ on any page). Claude picks it up from there.

Turn on the **game-night freeze** (Manage › askdnd › Testing › Where it stands) if a game is close, so nothing new
deploys on top.

## What Claude does

1. Roll back as above, or redeploy the last good commit (`railway redeploy` for that deployment).
2. Tell Found, Fixed, Tried which commit went: `uv run python scripts/feedback.py deploy <commit> --rollback`. Its
   fixes go back to Claude, and their checks leave Brett's For you (R9).
3. Mark the incident: `uv run python scripts/feedback.py incident <the Product Area> "what broke"`. Only that Product
   Area is Careful for 30 days (its fix gets Brett's round first). Add a line to docs/DECISIONS.md.
4. Fix it at the top of the list, then check askdnd.ai (`scripts/deploy_check.py`) and tell the people who sent notes.

## What not to do

- Don't undo a database change by hand. The old code runs on the new database; leave the added columns alone.
- Don't push a quick fix on top of a broken deploy during a game unless Brett says so (a `[table-fix]` commit).
