# Testing with real accounts

askdnd's real-environment test table (Brett, 2026-10-30; a fourth seat, Levi, Nov 3): four seats, each its own person on D&D Beyond and in askdnd, in **VTT test** on [beta](https://beta.askdnd.ai/c/vtt-test/). The everyday automated tests never touch any of this: they run on your computer with made-up people and a fake D&D Beyond.

Email addresses stay out of this file because the repo is treated as public. Each seat's Google login is the one named below.

## The seats

| | DM | Player 2 | Player 3 | Player 4 |
|---|---|---|---|---|
| **Chrome profile on the Mac Mini** | Jettison | Family | Trent | None: made in its own seat window (below) |
| **Google and D&D Beyond login** | The Jettison Corp account | The Family account | The Trent Davis Lawson account | Levi's account (Brett, Nov 3) |
| **D&D Beyond username** | WeslockePlayer | CatharticPlayer | ViPlayer | Levi's |
| **D&D Beyond role** | Owner of the campaign | Player | Player | Player |
| **Character** | None at the table: Weslocke (172986973) is on the account but stays unlinked, as DMs at this table don't play one | Cathartic, called CatharticPlayer on D&D Beyond ([sheet](https://www.dndbeyond.com/characters/172986165)). Roscoe Norell (Druid 6 Land / Warlock 2) is on the same account on D&D Beyond only: Levi took over his testing, and askdnd let him go on Nov 5 | Vi ([sheet](https://www.dndbeyond.com/characters/172992073)) | Levi Shadowquick, Druid 6 (Circle of the Land) / Warlock 2 ([sheet](https://www.dndbeyond.com/characters/173148163)), for Wild Shape |
| **Role in VTT test** | DM | Player | Player | Player |
| **Role across askdnd** | Member | Member | Member | Member |

The D&D Beyond campaign is [VTT test](https://www.dndbeyond.com/campaigns/8224496).

**Player 2 plays Cathartic in askdnd** (VTT test › Manage › Table › Played by): the automated runs open that seat's own character and expect it to be Cathartic (Nov 3: every run that needs a connected sheet missed while the seat played another character). The live test's setup check now says so before any run.

**The twins and the classes nobody plays** (Brett, Nov 5; the Test Table Setup page, `docs/artifacts/test-roster-setup.html`): each seat's D&D Beyond account also holds copies of the party and one character per class the party doesn't play, all in VTT test and public. In a test campaign a person plays several (Manage › Table keeps each one given); the menu bar still opens the seat's own, the first by id, so the runs find it as before.

| Seat | Its own | Twins | Classes |
|---|---|---|---|
| Player 2 (CatharticPlayer) | Cathartic | Cole (twin), 173216268 | Test Ranger (Hunter 5), 173222995 |
| Player 3 (ViPlayer) | Vi | Trah (twin), 173231727 | Test Bard (Lore 5), 173222716; Test Rogue (Assassin 9), 173222824 |
| Player 4 (Levi's account) | Levi Shadowquick | Big C (twin), 173220725; No Name (twin), 173230905 | Test Barbarian (Berserker 5), 173222366; Test Fighter (Champion 5), 173222510 |

All four twins are in (No Name's and Trah's on Nov 5, evening); `twins-level` checks each still matches its real character.

What each one's live run reaches (`TWINS` in scripts/real_table.py; docs/live-test-plan.md):

| Character | Classes | Resource spent and given back | Cast and Undo |
|---|---|---|---|
| Cole (twin) | Druid 6 (Moon) / Monk 2 | Focus | A spell slot |
| No Name (twin) | Monk 6 (Shadow) / Warlock 2 | Focus | Pact Magic |
| Big C (twin) | Paladin 6 / Sorcerer 2 | Channel Divinity | A spell slot |
| Trah (twin) | Wizard 7 (Evoker) / Fighter 1 | Second Wind | A spell slot |
| Test Ranger | Ranger 5 (Hunter) | Hunter's Mark (Favored Enemy) | A spell slot |
| Test Bard | Bard 5 (Lore) | Bardic Inspiration | A spell slot |
| Test Rogue | Rogue 9 (Assassin) | None | None |
| Test Barbarian | Barbarian 5 (Berserker) | Rage | None |
| Test Fighter | Fighter 5 (Champion) | Second Wind | None |

**Brett's personal D&D Beyond account is not a seat** (Brett, 2026-10-30): automation could get an account flagged. That account's characters are in no testing at all (its first Vi and Spurt were taken out of askdnd's VTT test on Nov 5), and Brett's own Chrome profile on the Mini is never copied or driven.

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
- VTT test is a test campaign (it holds the test copies) with Sync with D&D Beyond, Labs and askdnd's VTT switched on (Manage › Settings, since Nov 3: a test campaign switches nothing on by itself). A new Labs feature is switched on there to try it.
- Anything that deletes data on beta needs Brett's approval first.

## Claude runs a real fight

Brett, 2026-10-30: test with the real D&D Beyond, not only the stand-in in the browser tests. It runs on the Mac Mini, which is always on and signed in, so nobody has to watch and the MacBook can stay closed.

- **The seats.** `scripts/real_table_seats.sh` copies the three profiles above into `~/askdnd-tests/seats` on the Mini and opens them, with Levi's, in real Chrome windows. Chrome refuses to let a script drive its normal profile folder, and sign-ins can't move between computers, so the copies stay on the Mini. Copy again after signing in afresh. Levi's seat (`seats/player4`) has no profile to copy: it was made in a seat window on Nov 3, so its sign-ins are made in its own window and copy leaves it alone. Every seat signs in to askdnd at **beta.askdnd.ai**, the address the runs use (a sign-in at askdnd.ai is a separate one). The seats update the bridge from the store themselves: reopen them to run the new version. Claude never enters a password.
- **The runs.** `scripts/real_table.py` holds named runs: each does what a person would, watches the pages, and says what it expected and what happened. Run one on the Mini with `.venv/bin/python real_table.py <run>`.
- **The plan.** [live-test-plan.md](live-test-plan.md) is what to run and when, with the checks that still need a person.
- **Stays apart.** Never on GitHub, since it needs the signed-in seats and D&D Beyond itself. It tests what's on beta, not unmerged changes.
- **Vi's Backpack** (Nov 7): an empty Backpack on Vi's sheet, added for the `coins` run, which moves a gold into it and back. Leave it there.
- **Don't overlap.** While a run is going, stay off Cathartic, Vi and Levi: it opens and closes their sheets.

| Run | What it shows |
|---|---|
| `closed-sheet` | An open sheet connects the pill, and closing it changes the pill at once |
| `game-log` | A roll reaches the Game Log while the sheet is open; with it closed the table still sees the roll, and the roll window says why it isn't in the log |
| `close-after-roll` | Repeats closing a sheet right after a roll, at different moments |
| `hit-points` | Damage and healing in askdnd land on the real sheet and are confirmed |
| `condition` | A condition started and ended in askdnd lands on and leaves the real sheet |
| `cast`, `resource`, `coins`, `rests` | Slots, uses, coins and rests made in askdnd land on the real sheet and are put back |
| `temp-hp`, `death-saves`, `inspiration`, `exhaustion`, `inventory` | Temporary Hit Points, death saves, Heroic Inspiration, Exhaustion and items made in askdnd land on the real sheet and are put back |
| `wild-shape` | Levi shifts into a form: a Wild Shape use and the form's Temporary Hit Points land on the real sheet, Battle is the form's, and Undo puts all three back |
| `pact-cast`, `cross-cast`, `short-rest`, `in-form` | Levi's two kinds of spellcasting: Hex on a Pact slot, Entangle on a Pact slot and Hex on a Druid slot (each spends only its own kind), a Short Rest bringing back the Pact slot and one Wild Shape use but not a Druid slot, and a form's Cast saying it can't cast, Leave keeping the Temporary Hit Points |
| `creature-hp` | Vi's Homunculus: D&D Beyond's maximum set to the rule's, damage and healing from askdnd on its Extras, then put back. Waits for extension 0.10.0 on the seats (left out of part 1 until then) |

The full list, and what each must do, is in [live-test-plan.md](live-test-plan.md). Part 1 also runs every night at 4:00 (live-test-plan.md › Every night).

**Added for the runs (2026-11-02):** Cathartic's test sheet carries 3 Potions of Healing and a Staff of Healing (D&D Beyond's 2024 items), for the inventory run. If they go missing or run short, the run adds them back on D&D Beyond before it starts.

Still by hand: the fight on D&D Beyond's VTT.

First results, 2026-10-30, with extension 0.9.4: `closed-sheet` passed. `game-log` passed in 3 of 5 runs after its test was fixed: the two misses were a closed sheet still saying Connected, fixed in 0.9.5. The rolls themselves reached the other player's sheet every time, and none did with the sheet closed. `close-after-roll` once took over 40 seconds to show Connected after a sheet opened, not explained yet. Rerun all three once 0.9.5 is on the store, after copying the seats again.

## Before a test

- [ ] The DM and both players are the only people with a role in VTT test that the test needs (Brett's own and any second DM stay out of the way)
- [ ] Both players' pills say Connected to D&D Beyond
- [ ] Every tab was reloaded since the last deploy
