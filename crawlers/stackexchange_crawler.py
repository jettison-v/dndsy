#!/usr/bin/env python
"""
RPG Stack Exchange Crawler
--------------------------
Simple crawler to fetch D&D questions and answers from RPG Stack Exchange.
Uses their API rather than scraping to avoid anti-bot measures.
"""

import os
import sys
import requests
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any
import argparse

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
API_BASE_URL = "https://api.stackexchange.com/2.3"
DEFAULT_OUTPUT_DIR = "data/forum_posts"
DEFAULT_TAGS = ["dnd-5e", "dnd-2024", "rules-as-written"]  # Focus on D&D 5e and 2024 rules
PAGE_SIZE = 30
RATE_LIMIT_WAIT = 3  # Wait time between API calls in seconds

class StackExchangeCrawler:
    """Crawler for RPG Stack Exchange using their API."""
    
    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR):
        """Initialize the crawler."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self.stats = {
            "questions_fetched": 0,
            "answers_fetched": 0,
            "api_calls": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None
        }
    
    def fetch_questions(self, tags: List[str], max_questions: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch questions with the specified tags.
        
        Args:
            tags: List of tags to filter by
            max_questions: Maximum number of questions to fetch
            
        Returns:
            List of question data dictionaries
        """
        self.stats["start_time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        logger.info(f"Fetching up to {max_questions} questions with tags: {', '.join(tags)}")
        
        all_questions = []
        page = 1
        
        while len(all_questions) < max_questions:
            try:
                # Construct API URL
                url = f"{API_BASE_URL}/questions"
                params = {
                    "site": "rpg",
                    "tagged": ";".join(tags),  # This might be the issue, let's try using just one tag
                    "sort": "votes",  # Get popular questions
                    "order": "desc",
                    "filter": "withbody",  # Include the question body
                    "pagesize": min(PAGE_SIZE, max_questions - len(all_questions)),
                    "page": page
                }
                
                # Change to single tag if using multiple tags doesn't work
                if len(tags) > 1:
                    # Try with just the first tag if multiple tags aren't returning results
                    first_tag_params = params.copy()
                    first_tag_params["tagged"] = tags[0]
                    
                    # Make API request
                    logger.info(f"Making API request with first tag only: GET {url} (page {page}, tag: {tags[0]})")
                    self.stats["api_calls"] += 1
                    response = requests.get(url, params=first_tag_params)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Process questions
                    questions = data.get("items", [])
                    logger.info(f"Fetched {len(questions)} questions with tag {tags[0]} on page {page}")
                    
                    if not questions:
                        # If no results with the first tag, try the original approach
                        logger.info(f"No results with first tag, trying original parameters")
                
                # Make API request
                logger.info(f"Making API request: GET {url} (page {page})")
                self.stats["api_calls"] += 1
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                
                # Check for backoff request
                if "backoff" in data:
                    backoff_time = data["backoff"]
                    logger.warning(f"API requesting backoff of {backoff_time} seconds")
                    time.sleep(backoff_time)
                
                # Process questions
                questions = data.get("items", [])
                logger.info(f"Fetched {len(questions)} questions on page {page}")
                
                if not questions:
                    logger.info("No more questions to fetch")
                    break
                
                all_questions.extend(questions)
                page += 1
                
                # Check if there are more pages
                if not data.get("has_more", False):
                    logger.info("No more pages to fetch")
                    break
                
                # Add a delay to avoid hitting rate limits
                time.sleep(RATE_LIMIT_WAIT)
                
            except Exception as e:
                logger.error(f"Error fetching questions: {e}")
                self.stats["errors"] += 1
                break
        
        # Trim to max_questions if needed
        all_questions = all_questions[:max_questions]
        self.stats["questions_fetched"] = len(all_questions)
        logger.info(f"Fetched a total of {len(all_questions)} questions")
        
        return all_questions
    
    def fetch_answers(self, question_id: int) -> List[Dict[str, Any]]:
        """
        Fetch answers for a specific question.
        
        Args:
            question_id: The question ID
            
        Returns:
            List of answer data dictionaries
        """
        try:
            # Construct API URL
            url = f"{API_BASE_URL}/questions/{question_id}/answers"
            params = {
                "site": "rpg",
                "sort": "votes",
                "order": "desc",
                "filter": "withbody"  # Include the answer body
            }
            
            # Make API request
            logger.info(f"Fetching answers for question {question_id}")
            self.stats["api_calls"] += 1
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Check for backoff request
            if "backoff" in data:
                backoff_time = data["backoff"]
                logger.warning(f"API requesting backoff of {backoff_time} seconds")
                time.sleep(backoff_time)
            
            # Process answers
            answers = data.get("items", [])
            logger.info(f"Fetched {len(answers)} answers for question {question_id}")
            self.stats["answers_fetched"] += len(answers)
            
            # Add a delay to avoid hitting rate limits
            time.sleep(RATE_LIMIT_WAIT)
            
            return answers
            
        except Exception as e:
            logger.error(f"Error fetching answers for question {question_id}: {e}")
            self.stats["errors"] += 1
            return []
    
    def convert_to_forum_format(self, question: Dict[str, Any], answers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Convert Stack Exchange API data to our forum format.
        
        Args:
            question: Question data from API
            answers: Answer data from API
            
        Returns:
            Dictionary in the forum thread format
        """
        # Generate thread ID from question ID
        thread_id = f"rpg-se-{question.get('question_id')}"
        
        # Extract question title and tags
        title = question.get("title", "Untitled Question")
        tags = question.get("tags", [])
        
        # Create thread URL
        question_id = question.get("question_id")
        thread_url = f"https://rpg.stackexchange.com/questions/{question_id}"
        
        # Generate forum post list
        posts = []
        
        # Add question as the first post
        question_post = {
            "post_id": f"q-{question_id}",
            "author": question.get("owner", {}).get("display_name", "Unknown"),
            "timestamp": question.get("creation_date_iso", question.get("creation_date")),
            "text": self._html_to_text(question.get("body", "")),
            "thread_id": thread_id,
            "thread_title": title,
            "forum_section": "RPG Stack Exchange",
            "url": thread_url,
            "title": title,
            "post_type": "question",
            "score": question.get("score", 0)
        }
        posts.append(question_post)
        
        # Add answers as subsequent posts
        for answer in answers:
            answer_id = answer.get("answer_id")
            answer_post = {
                "post_id": f"a-{answer_id}",
                "author": answer.get("owner", {}).get("display_name", "Unknown"),
                "timestamp": answer.get("creation_date_iso", answer.get("creation_date")),
                "text": self._html_to_text(answer.get("body", "")),
                "thread_id": thread_id,
                "thread_title": title,
                "forum_section": "RPG Stack Exchange",
                "url": f"{thread_url}#{answer_id}",
                "title": title,
                "post_type": "answer",
                "score": answer.get("score", 0),
                "is_accepted": answer.get("is_accepted", False)
            }
            posts.append(answer_post)
        
        # Create thread data dictionary
        thread_data = {
            "thread_id": thread_id,
            "title": title,
            "url": thread_url,
            "forum_section": "RPG Stack Exchange",
            "tags": tags,
            "crawled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "posts": posts
        }
        
        return thread_data
    
    def _html_to_text(self, html: str) -> str:
        """
        Convert HTML to plain text (simple version).
        
        Args:
            html: HTML string
            
        Returns:
            Plain text version
        """
        # For a robust implementation, use BeautifulSoup or similar
        # This is a very simple implementation
        import re
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)
        
        # Fix spacing
        text = re.sub(r'\s+', ' ', text)
        
        # Decode HTML entities
        import html as html_module
        text = html_module.unescape(text)
        
        return text.strip()
    
    def save_thread_data(self, thread_data: Dict[str, Any]):
        """
        Save thread data to a JSON file.
        
        Args:
            thread_data: Thread data to save
        """
        if not thread_data:
            return
        
        try:
            thread_id = thread_data["thread_id"]
            output_file = self.output_dir / f"thread_{thread_id}.json"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(thread_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved thread data to {output_file}")
        
        except Exception as e:
            logger.error(f"Error saving thread data: {e}")
    
    def crawl(self, tags: List[str] = DEFAULT_TAGS, max_questions: int = 50):
        """
        Crawl RPG Stack Exchange for questions and answers.
        
        Args:
            tags: List of tags to filter by
            max_questions: Maximum number of questions to fetch
        """
        # Fetch questions
        questions = self.fetch_questions(tags, max_questions)
        
        # Process each question
        for question in questions:
            question_id = question.get("question_id")
            
            # Add ISO format date
            if "creation_date" in question:
                timestamp = question["creation_date"]
                question["creation_date_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp))
            
            # Fetch answers for this question
            answers = self.fetch_answers(question_id)
            
            # Add ISO format dates to answers
            for answer in answers:
                if "creation_date" in answer:
                    timestamp = answer["creation_date"]
                    answer["creation_date_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp))
            
            # Convert to forum format
            thread_data = self.convert_to_forum_format(question, answers)
            
            # Save thread data to file
            self.save_thread_data(thread_data)
        
        # Record end time
        self.stats["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        
        # Save stats
        stats_file = self.output_dir / "crawl_stats.json"
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, indent=2)
        
        logger.info(f"Crawl completed. Stats: {self.stats}")

def main():
    """Command-line interface for the crawler."""
    parser = argparse.ArgumentParser(description="Crawl RPG Stack Exchange for D&D questions")
    parser.add_argument("--tags", nargs="+", default=DEFAULT_TAGS, help=f"Tags to search for (default: {', '.join(DEFAULT_TAGS)})")
    parser.add_argument("--max-questions", type=int, default=50, help="Maximum number of questions to fetch")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory to save output")
    
    args = parser.parse_args()
    
    # Initialize and run crawler
    crawler = StackExchangeCrawler(output_dir=args.output_dir)
    crawler.crawl(tags=args.tags, max_questions=args.max_questions)

if __name__ == "__main__":
    main() 