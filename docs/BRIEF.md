# askdnd v2 — Product Brief (DRAFT)

_Last updated 2026-10-14 · Status: scoping complete; architecture next._

## Why v2 exists
Our table plays D&D 2024 on Zoom using D&D Beyond characters and its VTT. Sessions are sometimes two months apart, and most of us are novices, including a first-time DM. That leads to three problems:
1. **We forget the story.** Taking notes during play kills the fun and immersion.
2. **We forget our characters.** What we picked, how it works, and why we built it that way (for example, which wild shapes a Moon Druid/Monk has prepared and what each is good for).
3. **Rules lookups stall play.** Five minutes of searching and debating instead of playing.

v1 (now at legacy.askdnd.ai) was a learning project about RAG and vector databases. Showing the rulebook page next to an answer was its best feature when it worked, but retrieval often surfaced irrelevant pages, answers lacked real analysis, and it had no game context and no awareness of official clarifications or community consensus.

**v2 is a companion that keeps the table in the story.** It's also Brett's way to learn how modern AI-assisted building and project setup work.

## Users
- **4 players + 1 DM** (the DM runs the NPCs). Private tool; not public.
- The DM sees everything players see, **except players' character notes** (see below). No DM-only features for now.
- Each player has their own login, because character notes, chat memory and visibility rules depend on who's asking.
- Used through a web page, mostly on a computer alongside Zoom and D&D Beyond, sometimes on a phone.

## What it does

### 1. Pre-session refresher (top priority)
Before each session, every player gets:
- **"Previously on…"**: a recap of the story so far, with the most recent session in the most detail.
- **Character briefing**: their current abilities explained in plain language (spells, wild shapes, class features, items), plus their own past notes on why they made each choice.

### 2. Campaign memory
- Sessions are recorded and transcribed with MacWhisper, which labels speakers. Expect imperfect audio such as Zoom echo.
- **Privacy: only the extracted story is kept.** Raw transcripts contain personal banter. A first pass runs locally on Brett's Mac (Ollama) to strip clearly off-topic stretches before anything goes to a cloud AI service. The cloud step pulls out story events, NPCs, places, quests and loot. Raw transcripts are never stored in the app.
- It builds a running campaign record that anyone at the table can browse or ask about ("who was the dwarf at the bridge?").
- Backfill for the current campaign comes from Brett's notes plus the one recorded session (the most recent). Recaps of earlier sessions will be thinner than later ones.
- **Supports multiple campaigns.** A new campaign may start soon; nothing is tied to this one.

### 3. Character companion
- Reads each character from D&D Beyond (characters set to public).
- Base feature: an **extended briefing** on what you have and how it works. Not a fixed template; it covers whatever matters for that character:
  - Wild shapes: when each form shines, its strengths and weaknesses, and what changes when you transform
  - Spells: what each does, what it needs (concentration, range, components), and what can't be cast in Wild Shape
  - **Inventory and magic items**, especially the easily forgotten ones (charges, how each works)
  - What's available on your **action, bonus action and reaction**, including combinations the rules allow
  - Class features and resources (Focus Points, Wild Shape uses), and what a long rest restores
- **Inform, don't advise.** It says what's possible and how it works, never "you should do X." The choices stay with the player.
- Differentiator: a per-player chat that remembers *why* you built your character this way. Notes can be seeded from Brett's existing ones and added at each level-up.
- **Visibility: character notes are visible to all players but NOT the DM.**

### 4. Rules answers
- Fast, analyzed answers to mechanics questions for the 2024 PHB, DMG and Monster Manual, citing the right book page and showing the page image.
- Draws on official clarifications (errata, Sage Advice) and community consensus. It labels these as such and filters out 2014-rules discussion.
- Uses the character and campaign context when it's relevant ("can *I* do this?").
- The DM makes every call. The tool informs the DM's ruling and helps players contribute to it; it never rules.

## Evidence from the 2026-08-29 session
- ~10 minutes at the start went to a rules debate (Sculpt Spells vs. Faerie Fire) and reading features aloud. Similar lookups came up throughout: bag of holding size, detect magic, perception vs. investigation.
- Players said directly: "I always forget to use my hat and my cloak," "I have so much cool stuff in my inventory and never use it," "I forget all my things."
- The recap was fuzzy after a 2–3 month gap ("Remember how we got past this the first time?"), and nobody could recall who told the party about the Leviathan's library.

## What it won't do
- Tell players what to do. It explains options and choices, not tactics or optimization.
- Replace D&D Beyond as the character sheet or the VTT.
- Serve the public. Users are the table only, which also keeps licensing exposure low for book content.

## Success looks like
- A player opens it 10 minutes before a session after two months away and arrives knowing the story and their character.
- A mid-session rules question is settled in under a minute, with the page on screen.
- Nobody takes notes during play.

## First milestone (target: next session, ~3 weeks out)
**The refresher for the current campaign**: the local transcript filter, story extraction, a "previously on…" recap, and a character briefing (Brett's Moon Druid/Monk first, then everyone's). Data is organized for multiple campaigns from day one, but only the current campaign is supported at launch; a new campaign isn't confirmed. Rules answers stay on legacy.askdnd.ai until v2's version is better.

## Later
- Clean up or retire legacy (dependency security alerts). Secondary priority.

## Decisions log (scoping)
- Transcripts: MacWhisper with speaker labels; only one session recorded so far. Speaker labels need mapping to real people.
- Privacy: keep only the extracted story; filter locally (Ollama) first.
- Character notes: visible to all players, hidden from the DM.
- Tim's character is No Name, formerly Sarkas (his fey wife stole his name). Characters and NPCs need name aliases.
- New campaign: unconfirmed; support multiple campaigns in the data model, but don't build UI for it yet.

## What the existing notes give us (reviewed 2026-10-14)
- **Campaign notes (~5,600 words):** links to the 4 player characters (Cole, Trah, Sarkas, Big C), lore reveals from before session 17, and detailed notes for **sessions 17–25** (Mar–Aug 2025), ending on a cliffhanger (Priestess Myna missing, party unrested). Written from Cole's point of view, so it needs a neutral rewrite for the table's recap. Speculation is marked with ←.
- **Character notes (~6,400 words, Cole only):** wild shape cards in a **When / Pros / Cons / key stat differences** format, spell picks with reasoning, a level and multiclass plan, a battle-turn routine, and pasted rules text. That card format is the **template for every player's briefing**.
- Some notes contain rules slips (e.g. Moonbeam's save and fail outcomes are swapped). The briefing can flag where notes disagree with the 2024 rules.

## Open questions
- [ ] Gap: ~5+ sessions between session 25 (Aug 2025) and Aug 2026. Plan: the DM's recap at the start of the next recorded session.
