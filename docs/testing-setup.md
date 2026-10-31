# Testing with real accounts

askdnd's real-environment test table (Brett, 2026-10-30): three seats, each its own person on D&D Beyond and in askdnd, in **VTT test** on [beta](https://beta.askdnd.ai/c/vtt-test/). The everyday automated tests never touch any of this: they run on your computer with made-up people and a fake D&D Beyond.

Email addresses stay out of this file because the repo is treated as public. Each seat's Google login is the one named below.

## The seats

| | DM | Player 2 | Player 3 |
|---|---|---|---|
| **Chrome profile on the Mac Mini** | Jettison | Cupta Family | Trent |
| **Google and D&D Beyond login** | The Jettison Corp account | The Cupta Family account | The Trent Davis Lawson account |
| **D&D Beyond username** | WeslockePlayer | CatharticPlayer | ViPlayer |
| **D&D Beyond role** | Owner of the campaign | Player | Player |
| **Character** | None at the table: Weslocke (172986973) is on the account but stays unlinked, as DMs at this table don't play one | Cathartic, called CatharticPlayer on D&D Beyond ([sheet](https://www.dndbeyond.com/characters/172986165)) | Vi ([sheet](https://www.dndbeyond.com/characters/172992073)) |
| **Role in VTT test** | DM | Player | Player |
| **Role across askdnd** | Member | Member | Member |

The D&D Beyond campaign is [VTT test](https://www.dndbeyond.com/campaigns/8224496).

**Brett's personal D&D Beyond account is not a seat** (Brett, 2026-10-30): automation could get an account flagged. That account's characters, the first Vi (172836541) and Spurt, are in no testing at all, and Brett's own Chrome profile on the Mini is never copied or driven.

## Setting up a seat

Each seat needs its own Chrome profile, or its own computer, because the bridge works as whoever is signed in to that browser.

1. Sign in to Chrome with that seat's account.
2. Add the [askdnd bridge](https://chromewebstore.google.com/detail/askdnd-bridge/obpgemimnhngpcckodjkcihiahoaefpl).
3. Sign in to [beta](https://beta.askdnd.ai) with the same account, and switch to VTT test.
4. Sign in to D&D Beyond with the same account.
5. Players: open your character's sheet. The Live pill should say **Connected to D&D Beyond**.
6. DM: open the VTT from the [campaign page](https://www.dndbeyond.com/campaigns/8224496).

Any open VTT with the extension gives askdnd the fight, and any player's open sheet carries the DM's rolls, so the DM can see everything without the extension. With it, closing the DM's VTT is what ends the fight.

Reload every askdnd and VTT tab after a deploy.

## Rules

- Automated testing may act like a person on D&D Beyond with these test accounts, or stand in for it (Brett, 2026-10-30): that's part of developing askdnd, not the product. What ships never imitates D&D Beyond's client.
- Bridge tests only on the seats' sheets above, never a real table character's. The test copies in VTT test share real sheets, so the bridge never works on them.
- VTT test is a test campaign: it sees every feature, whatever's switched on for The Adventure Begins.
- Anything that deletes data on beta needs Brett's approval first.

## Claude runs a real fight

Brett, 2026-10-30: test with the real D&D Beyond, not only the stand-in in the browser tests. It runs on the Mac Mini, which is always on and signed in, so nobody has to watch and the MacBook can stay closed.

- **The seats.** `scripts/real_table_seats.sh` copies the three profiles above into `~/askdnd-tests/seats` on the Mini and opens them in real Chrome windows. Chrome refuses to let a script drive its normal profile folder, and sign-ins can't move between computers, so the copies stay on the Mini. Copy again after signing in afresh. The seats update the bridge from the store themselves: reopen them to run the new version. Claude never enters a password.
- **The runs.** `scripts/real_table.py` holds named runs: each does what a person would, watches the pages, and says what it expected and what happened. Run one on the Mini with `.venv/bin/python real_table.py <run>`.
- **The plan.** [live-test-plan.md](live-test-plan.md) is what to run and when, with the checks that still need a person.
- **Stays apart.** Never on GitHub, since it needs the signed-in seats and D&D Beyond itself. It tests what's on beta, not unmerged changes.
- **Don't overlap.** While a run is going, stay off Cathartic and Vi: it opens and closes their sheets.

| Run | What it shows |
|---|---|
| `closed-sheet` | An open sheet connects the pill, and closing it changes the pill at once |
| `game-log` | A roll reaches the Game Log while the sheet is open; with it closed the table still sees the roll, and the roll window says why it isn't in the log |
| `close-after-roll` | Repeats closing a sheet right after a roll, at different moments |
| `hit-points` | Damage and healing in askdnd land on the real sheet and are confirmed |
| `condition` | A condition started and ended in askdnd lands on and leaves the real sheet |

Still by hand: the fight on D&D Beyond's VTT.

First results, 2026-10-30, with extension 0.9.4: `closed-sheet` passed. `game-log` passed in 3 of 5 runs after its test was fixed: the two misses were a closed sheet still saying Connected, fixed in 0.9.5. The rolls themselves reached the other player's sheet every time, and none did with the sheet closed. `close-after-roll` once took over 40 seconds to show Connected after a sheet opened, not explained yet. Rerun all three once 0.9.5 is on the store, after copying the seats again.

## Before a test

- [ ] The DM and both players are the only people with a role in VTT test that the test needs (Brett's own and any second DM stay out of the way)
- [ ] Both players' pills say Connected to D&D Beyond
- [ ] Every tab was reloaded since the last deploy
