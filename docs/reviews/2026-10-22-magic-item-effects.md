# Magic items and status effects: a holistic scan (2026-10-22)

Brett asked whether the new Status row (built for the Ring of Invisibility) can hold every condition, and which other
items have effects askdnd should account for. This scans **every magic item in the 2024 Dungeon Master's Guide**
(347, from the offline copy in `private/books/`, by pattern: names and counts only, nothing copied) and **every
magic item the party carries** (D&D Beyond), and records what askdnd does with each.

## What the 347 items do to the person using them

| Effect | Items | What askdnd does |
|---|---:|---|
| A **Magic action** to use | 123 | Curated items get named actions; others with "take a Magic action" get a **Use:** option in See all (new) |
| A **Bonus Action** to use | 44 | Same, with Bonus action cost |
| A **Reaction** | 14 | Not yet: Arrow-Catching Shield, Ring of Evasion, Gloves of Missile Snaring… (next: same as above, Reaction column) |
| Lasts a while once started (an on/off state) | 80 | **Status row** for the ones that change your rolls or movement (new; see below) |
| Has **charges** | 69 | Shown with pips on the item and its Use option (already) |
| **Casts a spell** | 53 | Use an item (scrolls, charged items); not yet in the Spell Book (follow-up) |
| A bonus to AC, saves or attacks | 47 | Already in D&D Beyond's numbers, which askdnd reads |
| **Advantage** on some of your rolls | 28 | Already shown with an Adv badge when D&D Beyond lists it as a modifier |
| Resistance or Immunity to damage | 22 | Shown on the item; not summarized on Battle (follow-up) |
| A Fly, Swim or Climb Speed | 17 | Passive ones in D&D Beyond's speeds; timed ones as the **Flying** effect (new) |
| Gives a **target** a condition | 10 | Informational (the target is the DM's) |
| Gives **you** a condition | 9 | Invisible from 5 items (Ring and Cloak of Invisibility, both potions, Dust of Disappearance); the rest are side effects (Wand of Wonder, Hat of Many Spells) |
| Immunity or Advantage against a condition | 6 | Shown on the item (Periapt of Proof against Poison…) |

The 51 items that combine an action with a duration are the ones a tracked state helps most: Boots of Speed, Winged
Boots, Wings of Flying, Cloak of Invisibility, Potion of Growth, Potion of Gaseous Form, Ring of Invisibility, Flame
Tongue, Animated Shield, Helm of Brilliance, among others.

## The party's magic items (from D&D Beyond)

| Character | Item | Effect | askdnd now |
|---|---|---|---|
| Cole | Ring of Invisibility | Magic action → Invisible; Bonus Action ends it | Turn Invisible / Become visible on Battle; Invisible pill; Advantage offered |
| Cole | Stone of Good Luck | +1 to checks and saves | In D&D Beyond's numbers |
| Cole | Insignia of Claws | Unarmed Strike bonus | In the attack numbers |
| Cole | Potion of Healing | Bonus Action, heals | Use an item with its roll |
| Cole | Demon Armor | Needs attunement (not attuned) | Not active until attuned; the panel says so |
| Trah | Dragon-Touched Focus, Hat of Wizardry, Lifewell Tattoo | Charged powers, spells | Use an item with charges |
| Trah | Cloak of Billowing | Bonus Action (cosmetic) | **Use:** option in See all (new) |
| Trah | Scrolls, Keoghtom's Ointment, potions, Dust of Sneezing and Choking | Consumables | Use an item |
| Trah | Wand of Enemy Detection | Needs attunement (not attuned) | Not active until attuned |
| No Name | Potion of Growth | Enlarged for 10 minutes | Use an item + **Used it: Enlarged** (new) |
| No Name | Potion of Water Breathing | 24 hours underwater | Use an item + **Used it: Water Breathing** (new) |
| No Name | Elemental Gems, Feather Tokens | Consumables | Use an item |
| No Name | Sylvan Talon Dagger | Needs attunement (not attuned) | Not active until attuned |
| Big C | Hammer of Thunderbolts | Charged powers | Charges shown; its actions aren't options yet (follow-up: curate) |
| Big C | Necklace of Prayer Beads | Casts spells from beads | Use an item with charges |
| Big C | Belt of Hill Giant Strength | Sets Strength | In D&D Beyond's numbers |
| Big C | Potion of Water Breathing | 24 hours underwater | Use an item + **Used it: Water Breathing** (new) |

## What was built with this scan

- **Status row on Battle** for all 15 conditions (Blinded … Unconscious, Exhaustion by level 1–6) and three item
  effects (**Enlarged**, **Water Breathing**, **Flying**). Players add them with **+ Condition**; items add them with
  their action or a **Used it:** button. Everyone at the table sees them; only the player changes them.
- **Roll window**: each condition lists what it changes for that roll, without choosing for you: Advantage (Invisible
  on attacks and Initiative; Enlarged on Strength checks and saves), Disadvantage (Poisoned, Prone, Restrained,
  Blinded, Frightened, Grappled; Incapacitated on Initiative), and notes (auto-fail Strength and Dexterity saves when
  Paralyzed, Stunned, Petrified or Unconscious; −2 per Exhaustion level on every d20 Test; Enlarged's extra 1d4).
- **Curated items** (`app/data/item_actions.json`, our summaries): Ring and Cloak of Invisibility, Winged Boots, Wings
  of Flying, Potions of Invisibility and Greater Invisibility, Dust of Disappearance, Potion of Growth, Potion of
  Water Breathing.

## Follow-ups worth doing (not built)

1. **Read conditions from D&D Beyond.** Its character data has a `conditions` list (empty for all four today). Showing
   those as read-only pills needs D&D Beyond's condition numbers, which can't be checked until someone has one; do it
   the first time a player sets a condition there.
2. **Reaction items** (14) as options in the Reaction column, the same way as Magic actions.
3. **Spells cast from items** (53) in the Spell Book, marked with the item and its charges.
4. **Curate the party's charged items** whose actions aren't options yet (Hammer of Thunderbolts).
5. **Boots of Speed** (doubled Speed, Opportunity Attacks against you at Disadvantage) as an effect, if the party finds a pair.
