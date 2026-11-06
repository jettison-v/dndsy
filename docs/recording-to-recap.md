# From a game night's recording to the table's recap

Brett's steps, start to finish. The raw recording and its transcript never leave your Mac: the **askdnd Processor**
(a small app on your Mac) removes the table talk, and only the game goes to askdnd, which drafts the recap and keeps
nothing else. Then you review the draft and publish it, and the table sees it on Story › Previously on….

## Before the game

1. **Wear headphones.** Without them Zoom's audio leaks back into your mic and every line is heard twice
   (DECISIONS, Oct 14).
2. **Record the session in MacWhisper**, which transcribes it and labels who's speaking.

## After the game: on your Mac

3. **Export from MacWhisper.** Export **Segments** as **.json**, with **speaker names**, **timestamps** and
   **milliseconds** on. Save it anywhere (Downloads is fine).
4. **Open askdnd Processor** from Applications (or the Dock). It opens a page in your browser
   (`http://127.0.0.1:8765`) that only your Mac can reach. If it says Ollama isn't running, press **Start Ollama**.
5. **Add the session.** Drop the .json file on the page, set **Session date** to the day you played, and press
   **Add session**. (Tick **Replace if this date already exists** only to start a date over.)
6. **Step 1, Filter.** Press **Filter this session**. It removes Zoom's echo, then the model on your Mac marks the
   table talk. A full session takes about 15–20 minutes; leave the page open.
7. **Step 2, Review the cuts.** Each box is a stretch marked as table talk. Open any you're unsure of and press
   **Keep** if it has game in it (a rules call, a plan, something that happened). You're the judge; a quick skim is
   enough.
8. **Step 3, Save.** Press **Save final transcript**. It's kept on your Mac with your Keep choices applied.
9. **Step 4, Send to askdnd.** Press **Send to askdnd**. Only the filtered transcript goes, to askdnd (it sends to beta.askdnd.ai, the same askdnd as askdnd.ai); askdnd
   finds the session by its date (or makes it), drafts the recap with Claude in about a minute, and doesn't keep the
   transcript. The page then says when it was sent and links to the draft.

## After the game: on askdnd

10. **Review the draft.** Manage › Sessions (or the link from step 9). Read it, fix anything wrong (your fixes teach
    later drafts), and **Publish**. Before the next game is ideal, so the table's Previously on… is ready.
11. **Go in order.** Each draft builds on the recaps published before it, so a session drafted before the ones ahead
    of it are published knows less of the story. Publishing a session starts the draft of the next one by itself
    (the DM guide's Tips, Manage › DM guide).

## Where things are

| What | Where |
|---|---|
| The Processor app | Applications › askdnd Processor (rebuilt by `scripts/install-processor-app.sh` if it's ever missing) |
| A session's cleaned-up transcript | `~/Code/dndsy/transcripts/work/<date>/final.txt` (the Processor's **Show in Finder**) |
| The MacWhisper export it started from | `~/Code/dndsy/transcripts/raw/<date>.json` |
| Its log, if something goes wrong | `~/Library/Logs/askdnd-processor.log` |

`transcripts/` is never committed to git and never uploaded: only step 9's filtered text leaves the Mac.

## If something goes wrong

- **"No UPLOAD_TOKEN in your local .env yet"**: the key the Processor sends with is missing. Ask Claude (it's set
  with `scripts/set-secret.sh UPLOAD_TOKEN`, the same value on askdnd and your Mac).
- **"Couldn't reach askdnd"**: check the internet, then press Send to askdnd again; nothing was lost.
- **The filter seems stuck**: its progress is in the log above. If it has stopped, open the session and press
  **Filter again**.

## Aug 29, 2026 ("The brig of the Leviathan")

Already filtered, reviewed and saved on Oct 15 (`transcripts/work/2026-08-29/final.txt`), while the Processor was
being built; it was never sent, so on askdnd it says **Not drafted · Send from the Processor**. To draft it: open the
Processor, click **2026-08-29**, and press **Send to askdnd** (step 9). Its draft will know the story as far as it's
published by then, so it reads best once the sessions before it are published.
