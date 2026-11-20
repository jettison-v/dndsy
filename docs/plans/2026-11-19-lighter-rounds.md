# A lighter round (Brett picked all three, Nov 19)

Brett, Nov 19: "I feel like starting a round makes you less efficient because it interrupts you and pauses
deployments. Can you think of a better workflow? Maybe it warns when I am going to be stopping something?"

## How it works today

- **▶ Try it** on one check opens a round of one (app/fft/testing_page.py `go`); **▶ Start round** opens a sitting of
  several checks.
- While any round is open, nothing of Claude's merges, in any Product Area (R11; `rules.may_merge`: "Brett's round is
  open"). Claude only sorts and titles what he sends.
- A round doesn't pause Railway itself; only **Deploys: Paused** does (the Game-night freeze job). On Nov 19 the pause
  came from check 27's own steps, which had him press Paused on the live site. Checks no longer ask that.

## The change (Brett's pick: all three)

1. **A round holds only what it's testing**: its own Product Area(s). Claude's work in other areas still merges and
   deploys. R11's reasons, nothing changing under him while he tests and issues found together fixed together, are
   both about the area he's in.
2. **▶ Try it on one check holds nothing.** Only ▶ Start round, a sitting, holds its areas.
3. **A heads-up before holding anything.** Start round and Deploys › Paused first say what they'd stop, for example
   "1 change of Claude's is about to go live: Live UI Audit batch 2, about 5 minutes. [Start anyway] [Let it go live
   first]". Let it go live first starts the round once it's live. askdnd knows what's in flight from the pull requests
   attached to issues (`feedback.py issue <id> pr <url>`) and from auto-merge.

All three are built: items 1 and 2 (`FftRound.holds`, `rules.holding_round`, `may_merge` by area), and item 3 as Brett's pick A on docs/mockups/round-heads-up/ (a window first, only when something would wait; a line in Paused's reason box).

## Where it's tracked

The Roadmap (docs/roadmap.html), "A lighter round", marked Yours; and a question in For you.
