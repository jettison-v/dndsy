#!/usr/bin/env python
"""
Add Custom Forum Data
--------------------
This script adds custom D&D content directly to the vector store.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
import logging
import uuid

# Add parent directory to path for imports
script_dir = Path(__file__).parent
parent_dir = script_dir.parent
sys.path.append(str(parent_dir))

# Import project modules
from vector_store.dnd_beyond_forum_store import DnDBeyondForumStore

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_custom_forum_posts():
    """Create custom forum posts about D&D topics."""
    current_time = datetime.now().isoformat()
    
    # Create a unique thread ID for each thread
    monk_druid_thread_id = f"custom-thread-{uuid.uuid4()}"
    
    posts = [
        # Thread 1: Monk/Druid Multiclassing
        {
            "post_id": f"q-{uuid.uuid4()}",
            "author": "DnDMulticlassGuru",
            "timestamp": current_time,
            "text": """In the 2024 rules, multiclassing a Monk with a Druid can be particularly effective, especially if you're looking for a nimble nature-focused character with versatility in combat.

Key considerations for a Monk/Druid multiclass:

1. Ability Score Requirements: You'll need Wisdom and Dexterity scores of at least 13 each. Wisdom is used for both Druid spellcasting and Monk's ki abilities, while Dexterity is crucial for Monk's unarmored defense and attacks.

2. Level Distribution: I recommend starting with Monk for the first level to get their proficiencies, then taking at least 2 levels of Druid to access Wild Shape. After that, focus on either class depending on whether you want more spellcasting (Druid) or martial abilities (Monk).

3. Subclass Choices:
   - For Monk: Way of the Open Hand provides combat versatility that synergizes well with Wild Shape.
   - For Druid: Circle of the Moon maximizes your Wild Shape potential, letting you transform into beasts with higher CR.

4. Game Mechanics Benefits:
   - Use Wild Shape for versatility and additional hit points
   - Supplement with Monk's mobility and unarmed combat when not shapeshifted
   - Utilize Druid spells for utility and healing between combats

Has anyone tried this combination in their games?""",
            "thread_id": monk_druid_thread_id,
            "thread_title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "forum_section": "Character Optimization",
            "url": "https://www.dndbeyond.com/forums/custom/monk-druid",
            "title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "post_type": "discussion"
        },
        {
            "post_id": f"a-{uuid.uuid4()}",
            "author": "WildshaperExtraordinaire",
            "timestamp": current_time,
            "text": """I've been playing a Monk 5 / Druid 3 (Circle of the Moon) in our current campaign, and it's incredibly fun.

The Monk's Extra Attack and Stunning Strike combine beautifully with the Druid's Wild Shape. I can shift into a bear for heavy hitting, then pop back to humanoid form when I need mobility or precision strikes.

One thing I've found particularly effective is using the Monk's Step of the Wind to dash as a bonus action while in Wild Shape form. This gives me incredible mobility regardless of which form I'm in.

For ASIs, I focused on maxing Wisdom first (to 18) which benefits both classes, then pushed Dexterity to 16.

Spell selection is crucial - I recommend focusing on non-concentration utility spells since you'll often be using Wild Shape. Healing Word for emergencies, Pass Without Trace for stealth missions, and Absorb Elements for defense have all served me well.

The main drawback is that your ki points and spell slots are limited by your class levels, not character level. But the versatility more than makes up for it.""",
            "thread_id": monk_druid_thread_id,
            "thread_title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "forum_section": "Character Optimization",
            "url": "https://www.dndbeyond.com/forums/custom/monk-druid",
            "title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "post_type": "discussion"
        },
        {
            "post_id": f"a-{uuid.uuid4()}",
            "author": "DungeonMasterDave",
            "timestamp": current_time,
            "text": """As a DM who's had a Monk/Druid in my campaign, I can provide some perspective from the other side of the screen.

This multiclass combination can be very effective but also presents some unique challenges for the DM.

The character essentially becomes a "Swiss Army knife" - they can tank in Wild Shape form, deal precise damage as a Monk, provide some healing and utility, and handle infiltration missions. That versatility means they rarely feel useless, but they won't excel at any one role.

When designing encounters for a party with a Monk/Druid, I recommend:

1. Mix up combat with both single strong enemies (where Wild Shape tanking shines) and groups of weaker foes (where Flurry of Blows excels)

2. Create environmental challenges that reward both forms - obstacles that require climbing, swimming, or squeezing through small spaces are perfect for Wild Shape, while precision challenges like crossing narrow bridges play to Monk strengths

3. Remember that while in Wild Shape, the character can't cast spells but can still use Monk abilities like Stunning Strike and Ki points

4. Include both social and wilderness encounters to let both aspects of the character shine

For Monk/Druid players, I recommend taking the Mobile feat as it greatly enhances both your Wild Shape mobility and your Monk's ability to hit-and-run without opportunity attacks.""",
            "thread_id": monk_druid_thread_id,
            "thread_title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "forum_section": "Character Optimization",
            "url": "https://www.dndbeyond.com/forums/custom/monk-druid",
            "title": "Best Practices for Monk/Druid Multiclass in 2024 Rules",
            "post_type": "discussion"
        }
    ]
    
    return posts

def main():
    """Main function to add custom forum data."""
    try:
        # Create custom forum posts
        forum_posts = create_custom_forum_posts()
        
        # Save to file for debugging
        output_dir = Path('data/forum_posts')
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "custom_forum_data.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(forum_posts, f, indent=2)
        logger.info(f"Saved {len(forum_posts)} posts to {output_file}")
        
        # Add to vector store
        vector_store = DnDBeyondForumStore()
        logger.info(f"Adding {len(forum_posts)} posts to vector store")
        success_count, error_count = vector_store.add_forum_posts(forum_posts)
        logger.info(f"Added {success_count} posts to vector store (errors: {error_count})")
        
    except Exception as e:
        logger.error(f"Error adding custom forum data: {e}", exc_info=True)

if __name__ == "__main__":
    main() 