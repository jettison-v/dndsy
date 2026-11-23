# Writing a check

Brett's picks on Working with Claude (Nov 17, `docs/mockups/working-together/`). A check is a walkthrough Brett follows
on screen, step by step, without guessing. His example of what not to write: *"Name it Test Compass 2, + Add › A roll,
type lots in Or type it, then Save."* It packs five actions into one line, and nothing says that `lots` is a word to
type on purpose.

`app/fft/steps.py` (`walk` draws a step, `step_problems` refuses one) holds every check to these rules when it's written
or given a new version (`feedback.py check new … --step …`, `feedback.py check <id> version … --why …`). Found, Fixed,
Tried (Nov 17) adds three: **try it yourself first** (`feedback.py check <id> preflight pass`, R18: it reaches Brett's
For you only then, and again after each new version); **tie it to the issues it tries the fix of** (`--issue`, so it
comes back to him once they're live); and **name the devices it must pass on** (`--device laptop --device iphone`; the
Mac Mini's own runs are `mac_mini`).

## The shape (Clearer checks, Roadmap item 6, Brett's picks Nov 21)

Every check reads the same way, in this order, so Brett knows what he's testing before he starts (issue 36, Nov 18:
"the number of steps isn't the problem; it's knowing what you're testing and what the result should be"):

1. **Goal**: what was wrong **before** (`--before`) and what's true **now** (`--now`), a short line each. It sits above
   the steps in the check's window, on For you's row (its Now), and a tap away on the round's card (Goal ▸).
   askdnd refuses a new check without both, or without what you should see.
2. **Where**: the page it starts on (`--path`).
3. **Steps** (`--step`, the rules below).
4. **You should see** (`--expect`).

**What it needs** decides its round: a device (`--device laptop`, `--device iphone`), or more than one person
(`--people`: a second person or a second seat at once). For you groups Try by need (On your laptop, On your iPhone,
With more than one person), each with its own ▶ Start round, and a round never mixes them. A round or ▶ Try it can be
started from any device: on another device the card says where to do the steps, and the marks count for the check's
own device (Brett reads the steps on the laptop and taps on the iPhone; issue 104, Nov 23).

## The rules

1. **One action per step**, numbered in the order Brett does them. A step with ", then", "and then" or "then press" is
   refused.
2. **The page it starts on is the check's `path`**: ▶ Try it takes Brett there, so step 1 starts on that page.
3. **What to type goes in backticks**: `` type `Test Compass 2` ``. A step that says "type", "enter" or "write" before an
   unmarked word is refused. The card shows the word in a dashed box.
4. **A button goes in brackets**: `Press [Save].` It's drawn as a button.
5. **A box's name goes in bold**: `In **Or type it**, type `` `lots` ``.`. Name it exactly as the page shows it.
6. **Why it matters goes at the end of the step**: `(why: not a dice roll, on purpose)`. Use it whenever the step is
   wrong on purpose or the reason isn't obvious. It shows under the step.
7. **You should see** (`--expect`) says what's on screen when it works, where, and what it looks like, in full
   sentences (Brett, Nov 17: on its own page as a walkthrough, a check can be longer and plainer than a line in a
   document). Say what not to see too when that's the point ("the page doesn't reload: it doesn't go blank or jump
   to the top").
8. **Why** (`--why`: on a new version, what changed and why) says what Brett found and what changed, in words. Numbers
   (the issue, the change, the check) are never the sentence; askdnd shows the issues it tries by their titles.
9. **A check that makes something runs in VTT Test** (`--makes`, with a `/c/vtt-test/…` path or a VTT Test character's page). ▶ Try
   it takes Brett there, the card says *in a test campaign*, and the round ends back in his own campaign. Anything that
   can't be deleted afterwards (a homebrew item, today) must never be made in the table's campaign.
10. **One check per thing tried**, in an area (`--area`).
11. **Every check can end in ✓ Passed** (Brett on check 42, Nov 17: "This is the test case, it should pass"). A check
    about Can't try…, Change result… or anything else that marks a check stops before the mark (open the reasons,
    look, close it), or tries it on a check added for that, never on itself.
12. **A check points at something that's there** (check 46, Nov 17: "a note a player sent" when none was open). Before
    adding it, look that what its steps need exists where Brett tries it (a player's note, an issue, a spell), and give
    its `path` straight to it (`/manage/feedback?tab=ready&open=i33`), not "find one"; and never at something another
    check of the same round will close (check 13, Nov 18).

## Example

```bash
uv run python scripts/feedback.py check new "A mistake keeps what you typed" --area 2 --issue 14 \
  --path "/c/vtt-test/dm/items/new" --makes --device laptop \
  --before "A mistake in the roll cleared the whole item." --now "It says what's wrong and keeps what you typed." \
  --step "In **Name**, type \`Test Compass 2\`." \
  --step "Press [+ Add]." \
  --step "Press [A roll]." \
  --step "In **Or type it**, type \`lots\`. (why: not a dice roll, on purpose: this check is about the error)" \
  --step "Press [Save]." \
  --expect "A red line under the roll says how to write it (like 2d6 force). The name and the roll are still there as you typed them."
uv run python scripts/feedback.py check 9 preflight pass
```
