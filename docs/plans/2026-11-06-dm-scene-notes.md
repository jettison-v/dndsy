# The DM's scene notes (the DM's request, Nov 6)

The DM asked for what D&D Beyond's new Maps feature gives a DM for each scene: a page of prep notes beside the map,
in a set shape. Brett passed it on with a screenshot (not kept in git) and one rule: **it's the DM's alone, kept secret
from everyone, Brett and every other admin included.**

## What a scene's notes hold (the shape she sent)

| Section | What the DM writes |
|---|---|
| Intro | **Read-aloud text** (shown as a boxed scroll, to read to the table), then the key information the DM needs to get started |
| Purpose | How this place drives the story forward; the big decision or goal here |
| Outcomes | What the players should get from it; the consequences of success, and of failure |
| Location info | Setting details, environmental factors, secrets, traps, lore, treasure |
| Activities and interactions | What the players can do here, and what might happen to them |
| Scene summaries | The name and a short description of each scene in this area |
| Scene links | Links to other scenes, typed with `@` |

Each section starts with its prompts as faint hints, so a blank scene shows the DM what goes where.

## Where it fits in what's planned

- **3.6 Scenes and Slice 6, the map** (docs/plans/2026-11-02-vtt-build-plan.md): a scene is a map plus these notes; the
  DM opens a scene's notes beside its map at the table.
- **4.6 Session prep**: the scenes the DM readies for the next session, in order.
- **What exists to build on**: World places (a scene can be one place's, so its pictures and the Map tab carry over),
  the `@` name picker from suggestions (for Scene links and for naming people and places in the notes), and the story
  scroll (for the read-aloud box).
- **Before Slice 6 or after?** The notes can come first, as a DM-only page per place, and the map joins them in
  Slice 6. To decide in the whole-table walkthrough.

## Who sees them: the DM only

A new level of privacy, stricter than a hidden World entry (which the DM, reviewers and admins see):

- **Only the campaign's DM** reads or changes them. Not players, not reviewers, not admins, not Brett.
- **View as** never shows them, even as the DM; tests/test_refusals.py and a test like the visibility tests guard it
  (a standing rule, from Brett, Nov 6).
- **Claude never reads them**: they aren't sent to Claude for drafting recaps or anything else, and Claude doesn't
  open them when looking into the database.
- **Read-aloud text becomes the table's only when the DM shows it** (4.1 Show to the table).
- What's honest to say: they live in askdnd's database and its nightly backups like everything else, so whoever runs
  the servers could in principle reach them. askdnd itself never shows them to anyone but the DM.

## Open questions for the DM

1. One set of notes per place, or several scenes per place (the template's Scene summaries suggests several)?
2. Should the read-aloud box have a "Show to the table" button that puts it on everyone's screen?
3. Anything from D&D Beyond's version she'd want that this leaves out (a checklist, monsters for the scene)?
