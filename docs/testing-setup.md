# Testing with real accounts

askdnd's real-environment test table (Brett, 2026-10-30): three seats, each its own person on D&D Beyond and in askdnd, in **VTT test** on [beta](https://beta.askdnd.ai/c/vtt-test/). Automated tests never touch any of this: they run on your computer with made-up people and a fake D&D Beyond.

Email addresses stay out of this file because the repo is treated as public. Each seat's Google login is the one named below.

## The three seats

| | Player 1 | Player 2 | DM |
|---|---|---|---|
| **Google and D&D Beyond login** | Brett's account | The Cupta Family account | The Jettison Corp account |
| **D&D Beyond username** | Jettison | CatharticPlayer | WeslockePlayer |
| **D&D Beyond role** | Player | Player | Owner of the campaign |
| **Character** | Vi ([sheet](https://www.dndbeyond.com/characters/172836541)) | Cathartic ([sheet](https://www.dndbeyond.com/characters/172986165)) | None |
| **askdnd user** | Brett | Cupta Family | Jettison Corp |
| **Role in VTT test** | Player | Player | DM |
| **Role across askdnd** | Admin | Member | Member |

The D&D Beyond campaign is [VTT test](https://www.dndbeyond.com/campaigns/8224496).

**Player 1 is also an admin.** Admins can do things a player can't, so use Player 2 to check what a player really sees and can do.

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
- Bridge tests only on **Vi** and **Cathartic**, never a real table character's sheet. The test copies in VTT test share real sheets, so the bridge never works on them.
- VTT test is a test campaign: it sees every feature, whatever's switched on for The Adventure Begins.
- Anything that deletes data on beta needs Brett's approval first.

## Claude runs a real fight (planned)

Brett, 2026-10-30: test with the real D&D Beyond, not only the stand-in in the browser tests.

1. **One sign-in.** A saved Chrome profile per seat on Brett's computer (`private/test-profiles/`, gitignored). Brett signs in to D&D Beyond and askdnd in each, once. Claude never enters a password.
2. **The real thing.** A script opens the three seats at once, each with the extension loaded: the DM in the VTT, both players on their sheets and on beta or the local server.
3. **Named runs.** Each run is a list of steps and what should follow, such as "close Cathartic's sheet, roll a save, the pill says so at once". Claude runs them, reads the pages and reports what differed.
4. **Stays apart.** Run by hand, never on GitHub, since it needs the signed-in profiles and D&D Beyond itself. Only Vi and Cathartic, in VTT test.

First runs: a closed sheet, rolls reaching the Game Log, a turn order heard from the VTT, Hit Points through the bridge.

## Before a test

- [ ] The DM and both players have a seat each, and nobody else has a role in VTT test
- [ ] Both players' pills say Connected to D&D Beyond
- [ ] Every tab was reloaded since the last deploy
