# Writing a check

Brett's picks on Working with Claude (Nov 17, `docs/mockups/working-together/`). A check is a walkthrough Brett follows
on screen, step by step, without guessing. His example of what not to write: *"Name it Test Compass 2, + Add › A roll,
type lots in Or type it, then Save."* It packs five actions into one line, and nothing says that `lots` is a word to
type on purpose.

`app/testing.py` (`walk` draws a step, `step_problems` refuses one) holds every check to these rules, from both ways a
check is made: `feedback.py check add --do …` and `feedback.py set <id> done --do …`.

## The rules

1. **One action per step**, numbered in the order Brett does them. A step with ", then", "and then" or "then press" is
   refused.
2. **The page it starts on is the check's `path`**: Go takes Brett there, so step 1 starts on that page.
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
8. **Why** (the check's word, `--said`, and a fixed note's reply) says what Brett found and what changed, in words.
   Numbers (the note, the change, the check) are never the sentence; askdnd shows them one click down.
9. **A check that makes something runs in VTT Test** (`--makes`, with a `/c/vtt-test/…` path or a VTT Test character's
   page). Go takes Brett there, the card says *In VTT Test*, and the round ends back in his own campaign. Anything that
   can't be deleted afterwards (a homebrew item, today) must never be made in the table's campaign.
10. **One check per thing tried**, in an area (`--area-id`), with `--place` giving its order in that area's pages.

## Example

```bash
uv run python scripts/feedback.py check add "A mistake keeps what you typed" --area "DM Tools" --area-id 2 --place 2 \
  --path "/c/vtt-test/dm/items/new" --makes --minutes 2 \
  --do "In **Name**, type \`Test Compass 2\`." \
  --do "Press [+ Add]." \
  --do "Press [A roll]." \
  --do "In **Or type it**, type \`lots\`. (why: not a dice roll, on purpose: this check is about the error)" \
  --do "Press [Save]." \
  --expect "A red line under the roll says how to write it (like 2d6 force). The name and the roll are still there as you typed them."
```
