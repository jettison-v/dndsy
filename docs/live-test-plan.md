# End-to-end live test plan

Run this now and then to prove askdnd still works with the real D&D Beyond (Brett, 2026-10-30). The everyday tests use a stand-in for D&D Beyond, so they can't notice D&D Beyond changing, or timing that only shows on the real site. Seats and rules are in [testing-setup.md](testing-setup.md).

## When to run it

- After each extension update reaches the store
- After a change to the bridge, rolls, the Game Log, the fight or Hit Points
- The day before a session
- Whenever D&D Beyond looks different: it can change without notice

Say "run the live tests" and Claude does part 1, then gives you what's left in part 2.

## Before it starts

- [ ] Nobody is playing, and nobody needs Cathartic or Vi: the runs open, close and change those sheets, and put them back
- [ ] Beta has the change to test: the runs test beta, never unmerged work
- [ ] After an extension update: reopen the seats (`real_table_seats.sh close`, then `open`). They update themselves from the store like any Chrome, so don't `copy` for this: a copy from a profile that hasn't updated yet puts the old version back
- [ ] Open the seats: `real_table_seats.sh open`

## Part 1: automatic, about 12 minutes

On the Mini, in `~/askdnd-tests`, `.venv/bin/python real_table.py` runs everything below.

| Run | What it proves | How often it must pass |
|---|---|---|
| `closed-sheet` | Open a sheet and the pill says Connected; close it and it changes at once | Every time |
| `game-log` | A roll reaches another player's sheet through the Game Log while your sheet is open. With it closed, the table still gets the roll, nothing reaches the Game Log, and the roll window says why | Every time |
| `close-after-roll` | Closing a sheet right after a roll, five times at different moments | Every time from extension 0.9.5 |
| `hit-points` | Damage and healing in askdnd land on the real sheet, are confirmed, and put the number back | Every time |
| `condition` | A condition started in askdnd lands on the real sheet, and ending it there takes it off | Every time |
| `cast` | Cast spends a real slot on D&D Beyond, and Undo gives it back | Every time |
| `resource` | A resource counts down on D&D Beyond and comes back | Every time |
| `coins` | Coins gained in askdnd land on D&D Beyond, and Undo takes them off | Every time |
| `rests` | A Short Rest spends a real Hit Point Die and heals; a Long Rest brings back Hit Points, Hit Point Dice, slots and a resource | Every time |
| `temp-hp` | Temporary Hit Points given in askdnd land on the sheet; damage takes them first and leaves Hit Points be | Every time |
| `death-saves` | Down to 0: Unconscious and the marks start on the sheet; a death save rolled in askdnd marks itself; healing clears the marks and ends Unconscious | Every time |
| `inspiration` | Heroic Inspiration given and spent in askdnd follows on the sheet | Every time |
| `exhaustion` | Exhaustion started in askdnd lands at its level, a new level follows, and ending it takes it off | Every time |
| `inventory` | On Cathartic's sheet: equip and attune the Staff of Healing, spend and give back a charge, use and give back a Crossbow Bolt, drink a Potion of Healing (one fewer, and it heals) and Undo it | Every time |

Part 1 starts by checking that both test sheets are clean (full Hit Points, nothing marked, spent or in force) and ends by checking each is back as it found it. A miss at the start means an earlier run didn't put something back: it's reported, and hit points, death saves and conditions are put right on D&D Beyond so the rest can run.

Run it three times after a bridge change: the timing bugs so far only showed in some runs.

## Every night: the canary

A canary is a small check that runs on its own and warns you before anyone else notices. At 4:00, Mini time, launchd on the Mac Mini runs `real_table_nightly.sh`: it opens the seats, runs part 1 against beta and closes them. Any miss, or seats that won't open, becomes an issue in [Sentry](https://brett-vw.sentry.io/issues/?project=askdnd-v2) titled "Live test part 1: … missed" (environment `live-test`), which alerts Brett like the app's own errors. Each night's output is in `~/askdnd-tests/logs/nightly-<date>.log` on the Mini. The seats are test accounts, so game nights don't matter.

- **The job:** `~/Library/LaunchAgents/ai.askdnd.live-test.plist` (its source is `scripts/ai.askdnd.live-test.plist`). A Mini asleep at 4:00 runs it when it wakes.
- **The Sentry key:** `SENTRY_DSN` in `~/askdnd-tests/.env` on the Mini, readable only by its owner, put there with `scripts/set-secret.sh SENTRY_DSN --mini`. Never in git.
- **Try the alert:** `real_table_nightly.sh --try-alert closed-sheet` on the Mini adds one deliberate miss to a short run. Resolve the issue it makes in Sentry afterwards.
- **After changing the scripts:** the Mini runs its own copies. Copy them again: `scp scripts/real_table.py scripts/real_table_seats.sh scripts/real_table_nightly.sh mac-mini-server:askdnd-tests/`.
- **Turn it off:** `launchctl bootout gui/$(id -u)/ai.askdnd.live-test` on the Mini.

## Part 2: by hand, about 15 minutes

These need a person, or D&D Beyond's VTT, which is a game canvas a script can't read reliably.

1. **A fight.** DM: in the [VTT](https://www.dndbeyond.com/campaigns/8224496), start an encounter with Cathartic, Vi and a monster. The fight band shows the order, and Table rolls opens once on each player's page.
2. **Turns.** Press Next a few times. The band follows, and a hidden monster is hidden from players.
3. **A condition that ends.** Give Cathartic a condition lasting until the end of their next turn. A corner card reminds the player and the DM when it's due. Nothing ends by itself.
4. **The DM's roll.** Roll a monster's damage in the VTT. It appears in Table rolls with **Apply to**, and applying it changes the sheet.
5. **Rolls in the Game Log.** With the Game Log open on D&D Beyond, roll in askdnd. It shows there marked ⓐ, once. The automatic run sees the message pass, not how it looks.
6. **Dying.** Bring a seat's character to 0, roll a death save, heal. The Dying tile, marks and Unconscious all follow.
7. **Dice.** Watch a 3D throw land on the right number, then check that nothing replays after you've been in another tab.
8. **A second device.** Open askdnd on a phone: the pill and Table rolls read properly.

## After a run

- Check [Sentry](https://brett-vw.sentry.io/issues/?project=askdnd-v2): a run can pass while something fails quietly.
- Add a line below.
- A failure caused by D&D Beyond's page changing is a fix to `scripts/real_table.py`. A failure in askdnd becomes a bug with a test that fails without its fix.

## Results

| Date | Extension | Part 1 | Notes |
|---|---|---|---|
| 2026-10-30 | 0.9.4 | closed-sheet, hit-points, condition passed. game-log 3 of 5 | The misses were a closed sheet saying Connected, fixed in 0.9.5, waiting on the store |
| 2026-10-30, evening | 0.9.5 | closed-sheet, game-log, hit-points 3 of 3. close-after-roll 14 of 15, one at 14 seconds. cast, resource, coins, rests new; rests 3 of 4 | In one rests run a Hit Point Die took over 30 seconds and a resource wasn't back in 25, not reproduced in two reruns. A condition stayed on Battle up to about 8 seconds while D&D Beyond confirmed it, so the run now allows 15. Part 2 not run |
| 2026-11-01 | 0.9.5 | Not run | A one-off, not part 1: the DM's seat changed Cathartic's test sheet from D&D Beyond's own page, and the player's seat read each back: hit points, Heroic Inspiration, a spell slot, a limited-use resource, a condition, the character's name. All saved and all were put back. |
| 2026-11-02 | 0.9.5 | Four rounds of the widened part 1 (14 runs): 81 of 87, 83 of 89, 81 of 87, 83 of 89. Not three clean rounds: waits on beta | New runs temp-hp, death-saves, inspiration, exhaustion and inventory all passed on the real sheets at least once; inventory 17 of 17 alone. They found two bugs, fixed in PR 148: Temporary HP's Set stuck at 0, and a change D&D Beyond was slow to show waiting 30+ seconds for its retry (Oct 30's rests). The misses left: beta ran out of database connections under the three seats (Sentry ASKDND-V2-7 to C), so some changes took up to a minute or timed out; PR 148 raises the pool, and the cause underneath is a follow-up. Also seen: D&D Beyond serving an older copy for a moment, and reordering a race's options. The nightly canary's alert reached Sentry (ASKDND-V2-D, deliberate, resolved). After PR 148 is on beta: run part 1 three times again. |
