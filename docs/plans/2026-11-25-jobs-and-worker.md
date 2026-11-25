# Jobs and a worker (Roadmap item 43; the backend look-back's LB1 and LB2, Brett's picks Nov 25)

A second opinion, asked for by Brett ("If you feel like you need another opinion, get one"): an independent design from
the code as it is, compared with the look-back's recommendation. They agree; this is the plan we build from.

## The table: `jobs` (model `Job`, app/jobs.py)
`job_runs` is the backup's, so the new table is `jobs` (one add-only migration).

- `id`, `kind` (`ddb_refresh`, `draft_notes`, `read_transcript`, `revise`, `draft_recap`; a new payload shape is a new
  kind), `queue` (`ddb` or `draft`: each one lane, one job at a time), `state` (`queued`, `running`, `done`, `failed`,
  `cancelled`), `payload` (ids only, never transcript text), `dedup_key` (`ddb:char:7`, `draft:session:12`),
  `campaign_id`, `label`, `requested_by`, `priority` (10 Refresh now, 0 a page, -5 unwatched), `run_at` (not before;
  backoff), `attempts`, `max_attempts`, `created_at`, `started_at`, `heartbeat_at`, `finished_at`, `claimed_by`
  (`host:pid` or `web-fallback`), `version`, `error`, `result`.
- Indexes: the claim `(queue, priority DESC, run_at, id) WHERE state='queued'`; dedup `UNIQUE (dedup_key) WHERE state IN
  ('queued','running')`; the reaper `(heartbeat_at) WHERE state='running'`; the queue page `(campaign_id, created_at DESC)`.
- Kept: `ddb_refresh` 24 hours after it finishes, done drafts 90 days, failures 30 days (an hourly sweep).

## Claim, heartbeat, retry
- Claim in a short transaction (`FOR UPDATE SKIP LOCKED`), never held while the work runs; only kinds this code knows.
- Heartbeat every 15 s on its own connection; lease 60 s. Finishing is fenced (`WHERE id AND state='running' AND
  attempts=n`), so a reaped worker can't overwrite a later attempt.
- The reaper (every 30 s): a stale or overrun job goes back to `queued` while attempts are left, else `failed`.
- `ddb_refresh`: 3 attempts, 10 s then 60 s, 60 s timeout. Drafts: 2 attempts (only after an interruption), 15 min.
- Drafts are idempotent: `extraction_runs.job_id` (added); `main.mark_interrupted_runs` touches only rows without one.

## Enqueuing, live updates
- `jobs.enqueue(db, kind, payload, dedup_key, …)`: `INSERT … ON CONFLICT … DO UPDATE SET priority=GREATEST(…)` and a
  `pg_notify('askdnd_jobs', queue)` in the same transaction. Routes stay plain `def`.
- `jobs.refresh_character` adds nothing when the sheet was tried within `min_age`; the job's body is the existing
  `live.maybe_refresh` (`read_released` then `store`), the bridge's logic untouched.
- The worker doesn't listen, so `realtime.publish` gets a notify-only switch (`NOTIFY_ALWAYS`). A stored sheet already
  announces itself; each job's state change announces `{"type": "job", …}` for the Sessions row and the sync queue.

## Where things run
- Stay in web: `realtime.listen`, `speed.loop`, `release_when_live`. Stay as they are: `digest`, `nudge`, `sentry_in`
  (short, advisory-locked). `unwatched.tick` enqueues instead of reading.
- `JOBS_RUNNER=inline` (default locally, in tests, on staging) runs the lanes on threads inside web; production web is
  `worker`. The worker writes `ToolSetting("jobs_worker")` every 15 s; `/health` reports it.
- With no worker for 90 s, the `ddb` lane runs in web; drafts wait and say so ("Waiting for the worker"), Sentry after 5 min.
- A worker deploy: Railway overlaps them (SKIP LOCKED makes that safe); on SIGTERM it stops claiming, finishes refreshes,
  gives a draft up to 300 s, then puts it back (fenced) for the new worker. It never runs migrations; it waits for the
  database's head.

## Railway (Brett's OK: a second paid service)
`askdnd-worker`, production only, `uv run python -m app.worker`, no HTTP healthcheck, restart on failure, one replica;
reference variables (`${{askdnd-v2.X}}`) for the database, Anthropic, Sentry, S3; `JOBS_POOL=4`;
`RAILWAY_DEPLOYMENT_DRAINING_SECONDS=300`. `WORKER_WATCH` in scripts/deploy_check.py (as `BACKUP_WATCH`), job bodies'
imports lazy so most web deploys don't rebuild it.

## Build order (each mergeable, with its tests)
1. Migration, `Job`, app/jobs.py (enqueue, claim, finish, reap, sweep). Ship.
2. app/worker.py, the inline runner, heartbeat, `NOTIFY_ALWAYS`. Ship.
3. The Railway service and `WORKER_WATCH`; production web to `JOBS_RUNNER=worker`. Brett's OK (cost).
4. `ddb_refresh`: the routes enqueue instead of reading; the fallback lane; a 1 s gap and a 30 s back-off on D&D Beyond
   errors. Careful: Brett's local try and a live test on the Mac Mini.
5. `unwatched.tick` enqueues.
6. Drafts onto the queue (Careful: spending); `ExtractionRun.job_id`; `mark_interrupted_runs` narrowed.
7. Backstage › Sync queue (Roadmap item 44): waiting, running, done, failed, with Retry and Cancel (a mockup first).
