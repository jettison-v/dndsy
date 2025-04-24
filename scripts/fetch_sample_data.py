#!/usr/bin/env python
"""
Fetch Sample Data Script
-----------------------
This script fetches sample questions from RPG Stack Exchange
directly using the API and adds them to the vector store.
"""

import os
import sys
import json
import requests
import time
from pathlib import Path
from datetime import datetime
import logging

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

# Stack Exchange API URL
API_BASE_URL = "https://api.stackexchange.com/2.3"

def fetch_questions_by_id(question_ids):
    """
    Fetch specific questions by their IDs.
    These are questions we know exist and have good content.
    """
    url = f"{API_BASE_URL}/questions/{';'.join(map(str, question_ids))}"
    
    params = {
        "site": "rpg",
        "filter": "withbody",
        "order": "desc",
        "sort": "activity"
    }
    
    logger.info(f"Fetching {len(question_ids)} questions by ID")
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    questions = data.get("items", [])
    logger.info(f"Fetched {len(questions)} questions")
    
    return questions

def fetch_answers(question_id):
    """Fetch answers for a specific question."""
    url = f"{API_BASE_URL}/questions/{question_id}/answers"
    
    params = {
        "site": "rpg",
        "filter": "withbody",
        "order": "desc",
        "sort": "votes"
    }
    
    logger.info(f"Fetching answers for question {question_id}")
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    answers = data.get("items", [])
    logger.info(f"Fetched {len(answers)} answers for question {question_id}")
    
    return answers

def html_to_text(html):
    """Convert HTML to plain text (simple version)."""
    import re
    import html as html_module
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    
    # Fix spacing
    text = re.sub(r'\s+', ' ', text)
    
    # Decode HTML entities
    text = html_module.unescape(text)
    
    return text.strip()

def convert_to_forum_format(questions, answers_map):
    """Convert questions and answers to forum format."""
    forum_posts = []
    
    for question in questions:
        question_id = question.get("question_id")
        title = question.get("title", "Untitled Question")
        thread_id = f"rpg-se-{question_id}"
        thread_url = question.get("link")
        
        # Convert timestamp
        timestamp = question.get("creation_date")
        if timestamp:
            timestamp = datetime.fromtimestamp(timestamp).isoformat()
        
        # Process question post
        question_post = {
            "post_id": f"q-{question_id}",
            "author": question.get("owner", {}).get("display_name", "Unknown"),
            "timestamp": timestamp,
            "text": html_to_text(question.get("body", "")),
            "thread_id": thread_id,
            "thread_title": title,
            "forum_section": "RPG Stack Exchange",
            "url": thread_url,
            "title": title,
            "post_type": "question",
            "score": question.get("score", 0)
        }
        forum_posts.append(question_post)
        
        # Process answers
        answers = answers_map.get(question_id, [])
        for answer in answers:
            answer_id = answer.get("answer_id")
            
            # Convert timestamp
            answer_timestamp = answer.get("creation_date")
            if answer_timestamp:
                answer_timestamp = datetime.fromtimestamp(answer_timestamp).isoformat()
            
            answer_post = {
                "post_id": f"a-{answer_id}",
                "author": answer.get("owner", {}).get("display_name", "Unknown"),
                "timestamp": answer_timestamp,
                "text": html_to_text(answer.get("body", "")),
                "thread_id": thread_id,
                "thread_title": title,
                "forum_section": "RPG Stack Exchange",
                "url": f"{thread_url}#{answer_id}",
                "title": title,
                "post_type": "answer",
                "score": answer.get("score", 0),
                "is_accepted": answer.get("is_accepted", False)
            }
            forum_posts.append(answer_post)
    
    return forum_posts

def save_to_file(posts, output_file):
    """Save posts to a JSON file for debugging."""
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2)
    logger.info(f"Saved {len(posts)} posts to {output_file}")

def main():
    """Main function to fetch and process data."""
    # List of interesting question IDs from RPG Stack Exchange
    question_ids = [
        156621,  # "Does Pathfinder 2e have more in common with D&D 5e than it does with Pathfinder 1e?"
        165473,  # "How does Multiclassing rules-as-written reconcile with multiple instances of the same class feature?"
        170185,  # "How do I address a player's complaint that Vancian spell preparation is too restrictive to make Wizards worth playing?"
        176783,  # "What are the major differences in style and system between D&D 5e and Pathfinder 2e?"
        210474,  # "Migrate D&D 5e home made campaign to Pathfinder 2e"
        196220,  # "How can I balance higher spell slots for multi-class characters in a world without traditional Vancian magic?"
        166382,  # "How does multiclassing work with spells from the same list?"
        172193,  # "What's the mechanical benefit to gaining more than 6 expertise skills across multiple classes?"
        208125,  # "How can I simulate a level 20 multiclassed Paladin/Warlock?"
        193631,  # "What are the important considerations when selecting my first spell at level 3 as a Warlock?"
    ]
    
    try:
        # Fetch questions
        questions = fetch_questions_by_id(question_ids)
        
        # Fetch answers for each question
        answers_map = {}
        for question in questions:
            question_id = question.get("question_id")
            time.sleep(1)  # To avoid rate limits
            answers_map[question_id] = fetch_answers(question_id)
        
        # Convert to forum format
        forum_posts = convert_to_forum_format(questions, answers_map)
        
        # Save to file for debugging
        output_dir = Path('data/forum_posts')
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "sample_rpg_se_data.json"
        save_to_file(forum_posts, output_file)
        
        # Add to vector store
        vector_store = DnDBeyondForumStore()
        logger.info(f"Adding {len(forum_posts)} posts to vector store")
        success_count, error_count = vector_store.add_forum_posts(forum_posts)
        logger.info(f"Added {success_count} posts to vector store (errors: {error_count})")
        
    except Exception as e:
        logger.error(f"Error fetching and processing data: {e}", exc_info=True)

if __name__ == "__main__":
    main() 