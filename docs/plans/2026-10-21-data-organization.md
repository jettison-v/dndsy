# How askdnd organizes its data: plan (DONE, 2026-10-23)

Status: **done 2026-10-23**: decided 2026-10-22, all four steps built and on beta (the final organization is in `docs/ARCHITECTURE.md` › Data) (Brett's answers on the "askdnd campaigns and roles" page; see "Decisions" at the end).
Built after roadmap step 11's Inventory and Features lists and a round of Brett's small feedback. Once decided, the final version of
"The organization" below moves into `docs/ARCHITECTURE.md` (Data) with a line in `docs/DECISIONS.md`, and this file
is marked as done.

## Goals (Brett, 2026-10-21)

1. **The tool's knowledge is separate from anyone's data.** Rules data (roll recipes, Beasts, rules terms, class
   rules) belongs to the tool and is the same for everyone.
2. **A DM's changes never edit the tool's knowledge.** They're stored with the campaign's data, point at what they
   change, and apply only there.
3. **Characters are separate from campaigns.** A character can move to another campaign; what it did in the old one
   stays part of that campaign's history.
4. **More than one campaign** in the same askdnd.

## Where things stand today

| Goal | Today | Gap |
|---|---|---|
| 1. Tool knowledge apart | Already true: rules data lives in the code (`app/data/*.json`, `rules_terms.py`, `class_rules.py`), versioned in git and deployed, never in the database | None |
| 2. DM changes linked, not edits | The only kind today, sheet corrections (Manage › Characters), are rows that point at what they correct | They apply to every campaign; there's nowhere for a campaign's house rules |
| 3. Characters apart | A character reaches its campaign through its story page (`characters.entity_id` → `entities.campaign_id`) | Moving means moving the story page and its history; no record of when a character joined or left |
| 4. Several campaigns | Tables with campaign data carry `campaign_id`, and `campaign_members` exists | About 25 places use "the first campaign"; the DM tick and Reviewer access are per account, not per campaign |

## The organization (proposed)

Four layers, from most general to most specific. Each layer may point at the ones above it, never the other way.

```
1. Tool knowledge (in the code: git, deploys)
     roll recipes · Beasts · rules terms · class rules · places list
          ▲ points at (by key, e.g. "spell:Magic Missile")
2. Tool-wide data (database)
     users (name, email, tool role: owner / admin / member)
     tool corrections (how askdnd reads D&D Beyond; today's sheet corrections)
     spending limit, credit top-ups, job runs, version history
          ▲
3. Campaigns (database, every row has campaign_id)
     campaigns
     campaign_members     user × campaign → role (DM / reviewer / player), joined, left
     campaign_characters  character × campaign → its story page, joined, left, Wild Shape keeps
     house_rules          campaign × tool item → the DM's change, why, who, when
     story: entries (NPCs, places…), sessions, recaps, events, glossary, corrections,
            suggestions, speaker labels, note sources, table rolls
          ▲
4. Characters (database, every row has character_id; no campaign)
     characters (name, player, D&D Beyond link, current Wild Shape form)
     D&D Beyond copy · stars and reminders · player notes · item notes
```

### Why each piece is where it is

- **Tool knowledge stays in the code.** It's audited (`docs/rules/rolls-audit.md`), reviewed like code, and the
  same for every campaign. Putting it in the database would let one campaign's edit change everyone's.
- **A change is a row that points at the thing it changes.** "Effective value" = the tool's knowledge, then a
  tool-wide correction, then the campaign's house rule (the most specific wins). Removing the row brings the
  tool's value back. Every row says who, when and why, and version history keeps old values.
- **Two kinds of change, two scopes.** *Tool corrections* fix how askdnd reads D&D Beyond (a parser mistake: wrong
  for everyone, so tool-wide). *House rules* are a DM's ruling (Magic Missile rolls once for all darts; what a
  Druid keeps in Wild Shape): right for one table, so per campaign.
- **Characters own their own data; campaigns own what happened.** The D&D Beyond copy, notes, stars and reminders
  belong to the character and travel with it. Story pages, events, recaps and rolls belong to the campaign where
  they happened, so they stay when a character leaves.
- **Membership has dates.** `campaign_characters` and `campaign_members` keep `joined` and `left` instead of
  deleting rows, so "who was in this campaign in session 12" stays answerable.
- **Roles are per campaign.** Being DM, reviewer or player is about a table, so it lives on `campaign_members`. The
  tool keeps only what's about the whole tool: owner and admin (setup, people, billing).
- **The DM never sees players' notes:** a person can't see the notes of characters in a campaign they DM now,
  wherever those characters are (decision 3).

### What changes in each existing table

| Table | Change |
|---|---|
| `characters` | Gains its own `name` (from its story page). `entity_id` moves to `campaign_characters`. `wild_shape_keep` (a DM's ruling) moves to `campaign_characters` |
| `campaign_characters` (new) | `campaign_id`, `character_id`, `entity_id` (its story page in that campaign), `joined_on`, `left_on`, `wild_shape_keep` |
| `campaign_members` | Role adds reviewer; gains `joined_on`, `left_on` |
| `users` | `access` becomes the tool role (owner / admin / member); `is_dm` and reviewer move to `campaign_members` |
| `sheet_overrides` | Renamed `tool_corrections`, gains `reason`; unchanged meaning (tool-wide) |
| `house_rules` (new) | `campaign_id`, `target_kind` (recipe, sheet item, rules term…), `target_key`, `field`, `value`, `reason`, `set_by`, timestamps |
| `player_notes` | Gains an optional `campaign_id` (a personal quest belongs to a campaign; combos and leveling plans don't) |
| `campaigns` | `monthly_limit_usd` moves to a tool-wide setting (one Anthropic account pays for all) |
| Everything with `campaign_id` today | Unchanged |

## D&D Beyond (Brett asked, 2026-10-22: will syncing stay efficient?)

D&D Beyond's own model matches this shape: a person owns characters; a campaign has a DM and the characters
that joined it, one campaign at a time. askdnd syncs characters by their D&D Beyond id, and a character's
D&D Beyond data can say which D&D Beyond campaign it's in (we drop that today). So step 1 adds
`campaigns.ddb_campaign_id`, and the character refresh keeps the D&D Beyond campaign id. When a character's
D&D Beyond campaign doesn't match its askdnd campaign, askdnd asks the admin whether to move it (never
automatically, since a campaign's history depends on who was there).

## How we'd build it (four steps, each shippable on its own)

Each step: a migration that copies today's data into the new shape (production has one campaign and four
characters, so it's a straight copy), a manual backup first (on top of the nightly one), tests, and a check on beta.
Each migration can be undone.

1. **Characters separate from campaigns.** Add `campaign_characters`, copy each character's link to its campaign and
   story page, give characters their own name, move Wild Shape keeps. Change the ~33 places that go from a
   character to its story page to go through the membership. Nothing visible changes. (Largest step.)
   **Done 2026-10-22** (migration 9a5b7c1d4e60): `Character.membership` is the campaign it's in now (one at a time,
   enforced by the database), `Character.entity` its story page there; renaming the story page renames the
   character; version history of Wild Shape keeps moved with them; personal quests carry their campaign; characters
   and campaigns store their D&D Beyond campaign id. The "move it?" prompt for a mismatch comes with step 4, which
   adds moving.
2. **Roles per campaign.** Copy the DM tick and Reviewer access into `campaign_members`; `access.allows()` asks
   about a person *in a campaign*. The access chart on Manage › People shows tool roles and campaign roles.
   Manage › People groups people by their role in the current campaign (DM, Reviewers, Players, then people
   with no role in it), and removed people sit in a collapsed section at the bottom (Brett, 2026-10-22).
   (~66 access checks, most through a few helpers.)
   **Done 2026-10-23** (migration ab6c8d2e5f71): `users.access` is member or admin; `campaign_members.role` is DM,
   reviewer or player with joined and left dates (one current row per person and campaign). The checks in
   `app/auth.py` take a campaign (the first one until step 4), and notes are hidden from the DM of the character's
   current campaign. Manage › People: Role and Admin per person, grouped DM · Reviewers · Players · No role,
   removed people folded; the chart has Player · Reviewer · DM · Admin columns. A person with no role in a
   campaign can still read it until step 4 makes the campaign part of every page.
3. **Tool corrections and house rules.** Rename sheet corrections, add `house_rules` and one module that works out
   the effective value (tool knowledge → correction → house rule) for recipes, sheet items and rules terms. First
   use: a Manage › House rules page where the DM can, say, roll Magic Missile once for all darts. The roll window
   shows "House rule" when one applies.
   **Done 2026-10-23** (migration bc7d9e3f6a82): `tool_corrections` (with a Why column on Manage › Characters) and
   `house_rules`; `app/house_rules.py` applies them (recipes through `house_rules.spell()`, sheet items and rules
   terms through `house_rules.sheet_overrides()`). Manage › House rules (the campaign's DM and admins) offers two
   kinds: **one roll for all** (spells whose instances roll without attack rolls: Magic Missile) and **a ruling**
   (a note on any spell with a recipe, shown in the roll window). Removing one brings the 2024 rules back; History
   restores. House rules on sheet items and rules terms work in the code but have no page yet.
4. **More than one campaign.** A campaign switcher in the menu bar (remembered per person); story addresses carry
   the campaign (`/c/main/sessions/20`), old addresses redirect to your current campaign. Party, Live and Table
   rolls show the current campaign's characters. Admin: create a campaign, add people and characters to it, move a
   character (ends one membership, starts another).
   **Done 2026-10-23** (migration cd8e0f4a7b93): app/campaign_paths.py serves every page under `/c/<slug>/` and
   sends old story addresses (/, /sessions, /campaign, /map) to the person's current campaign
   (`users.current_campaign_id`); `web.campaign(db)` and access checks use that campaign. The switcher (menu bar;
   More on phones) appears for people in more than one campaign; people see only campaigns they have a role in,
   admins all. Character pages open for their player, admins and the character's table. Manage › Campaigns:
   create (D&D Beyond campaigns seen on characters are offered, name prefilled), edit, add a new character, move
   a character (a story page from an earlier stay is reused), and characters whose D&D Beyond campaign differs
   are offered a move, never moved. Personal quests show in their own campaign. The spending limit moved to
   `tool_settings` (decision 7). The transcript upload takes an optional `campaign` slug (the Mac's filter
   doesn't send one yet, so uploads go to the first campaign).

Steps 1–3 don't change what anyone sees much; step 4 is where the second campaign appears.

## Decisions (Brett, 2026-10-22)

1. **A character's name:** one name on the character, shown in every campaign. Story aliases stay on each
   campaign's story page.
2. **Reviewer:** per campaign.
3. **Notes the DM can't see:** only characters in campaigns they DM **now** (not the recommendation: someone
   who stops DMing a campaign can read its players' notes afterwards, like any player).
4. **Personal quests:** belong to the campaign they were written in. Combos and leveling plans stay with the character.
5. **Wild Shape keeps:** per campaign (a DM ruling).
6. **Campaign in the address:** yes, `/c/<campaign>/…` for story pages; old addresses open your current campaign.
7. **Spending limit:** one for the tool.
8. **Order:** the four steps as listed (characters, roles, house rules, more campaigns).
9. **Step 10 vs step 11:** Inventory and Features lists first, then Brett's next batch of small feedback, then step 10.
