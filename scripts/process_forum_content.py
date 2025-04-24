#!/usr/bin/env python
"""
Process DnD Beyond Forum Content
-------------------------------
This script processes crawled forum content and adds it to the vector store.
It can either:
1. Process JSON files from a previous crawler run
2. Initiate a new crawl of the forums
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import time

# Add parent directory to path for imports
script_dir = Path(__file__).parent
parent_dir = script_dir.parent
sys.path.append(str(parent_dir))

# Import project modules
from vector_store.dnd_beyond_forum_store import DnDBeyondForumStore
from crawlers.dnd_beyond_forums_crawler import DnDBeyondForumsCrawler, FORUM_SECTIONS

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Default paths
DEFAULT_INPUT_DIR = "data/forum_posts"
DEFAULT_OUTPUT_DIR = "data/processed_forums"

def load_thread_files(input_dir: str) -> List[Dict[str, Any]]:
    """
    Load thread JSON files from the input directory.
    
    Args:
        input_dir: Directory containing thread JSON files
        
    Returns:
        List of thread data dictionaries
    """
    input_path = Path(input_dir)
    
    if not input_path.exists():
        logger.error(f"Input directory does not exist: {input_dir}")
        return []
    
    threads = []
    
    try:
        # Find all JSON files in the directory
        json_files = list(input_path.glob("thread_*.json"))
        logger.info(f"Found {len(json_files)} thread files in {input_dir}")
        
        for file_path in json_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    thread_data = json.load(f)
                    threads.append(thread_data)
            except Exception as e:
                logger.error(f"Error loading thread file {file_path}: {e}")
        
        return threads
        
    except Exception as e:
        logger.error(f"Error loading thread files from {input_dir}: {e}")
        return []

def process_threads(threads: List[Dict[str, Any]], vector_store: DnDBeyondForumStore) -> Dict[str, int]:
    """
    Process thread data and add to vector store.
    
    Args:
        threads: List of thread data dictionaries
        vector_store: Vector store to add data to
        
    Returns:
        Dictionary with stats about processed posts
    """
    if not threads:
        logger.warning("No threads to process")
        return {"threads": 0, "posts": 0, "indexed": 0, "errors": 0}
    
    stats = {
        "threads": len(threads),
        "posts": 0,
        "indexed": 0,
        "errors": 0
    }
    
    for thread in threads:
        try:
            posts = thread.get("posts", [])
            stats["posts"] += len(posts)
            
            if not posts:
                logger.warning(f"Thread {thread.get('thread_id')} has no posts, skipping")
                continue
            
            # Add posts to vector store
            success_count, error_count = vector_store.add_forum_posts(posts)
            stats["indexed"] += success_count
            stats["errors"] += error_count
            
            logger.info(f"Added {success_count} posts from thread {thread.get('thread_id')} to vector store (errors: {error_count})")
            
        except Exception as e:
            logger.error(f"Error processing thread {thread.get('thread_id')}: {e}")
            stats["errors"] += 1
    
    return stats

def run_new_crawl(args):
    """
    Run a new crawl of the DnD Beyond forums.
    
    Args:
        args: Command-line arguments
    
    Returns:
        Dictionary with stats about the crawl
    """
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    
    # Initialize the crawler
    crawler = DnDBeyondForumsCrawler(
        headless=not args.no_headless,
        output_dir=output_dir,
        delay_min=args.delay_min,
        delay_max=args.delay_max
    )
    
    # Run the crawl
    crawler.crawl_forums(
        sections=args.sections,
        max_pages_per_section=args.max_pages,
        max_threads_per_section=args.max_threads
    )
    
    # Return stats from the crawler
    return crawler.stats

def process_forum_content(args):
    """
    Process forum content either from files or a new crawl.
    
    Args:
        args: Command-line arguments
    """
    vector_store = DnDBeyondForumStore()
    start_time = time.time()
    
    # Clear the vector store if requested
    if args.clear_store:
        logger.info("Clearing vector store")
        vector_store.clear_store()
    
    # Check if we're loading from files or running a new crawl
    if args.crawl:
        logger.info("Starting new crawl of DnD Beyond forums")
        stats = run_new_crawl(args)
        input_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    else:
        logger.info("Processing existing forum data")
        input_dir = args.input_dir or DEFAULT_INPUT_DIR
    
    # Load and process thread files
    logger.info(f"Loading thread files from {input_dir}")
    threads = load_thread_files(input_dir)
    
    if threads:
        logger.info(f"Processing {len(threads)} threads")
        processing_stats = process_threads(threads, vector_store)
        
        # Output stats
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        logger.info(f"Completed processing in {elapsed_time:.2f} seconds")
        logger.info(f"Threads: {processing_stats['threads']}")
        logger.info(f"Total posts: {processing_stats['posts']}")
        logger.info(f"Indexed posts: {processing_stats['indexed']}")
        logger.info(f"Errors: {processing_stats['errors']}")
    else:
        logger.error("No threads found to process")

def main():
    """Command-line interface for processing forum content."""
    parser = argparse.ArgumentParser(description="Process DnD Beyond forum content for vector store")
    
    # Input/output options
    parser.add_argument("--input-dir", help=f"Directory containing thread JSON files (default: {DEFAULT_INPUT_DIR})")
    parser.add_argument("--output-dir", help=f"Directory to save output for new crawls (default: {DEFAULT_OUTPUT_DIR})")
    
    # Crawling options
    parser.add_argument("--crawl", action="store_true", help="Run a new crawl instead of processing existing files")
    parser.add_argument("--sections", nargs="+", help=f"Forum sections to crawl. Available: {', '.join(FORUM_SECTIONS)}")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum pages per section for crawling")
    parser.add_argument("--max-threads", type=int, default=10, help="Maximum threads per section for crawling")
    parser.add_argument("--no-headless", action="store_true", help="Disable headless mode for browser")
    parser.add_argument("--delay-min", type=float, default=1.0, help="Minimum delay between requests")
    parser.add_argument("--delay-max", type=float, default=3.0, help="Maximum delay between requests")
    
    # Vector store options
    parser.add_argument("--clear-store", action="store_true", help="Clear the vector store before adding new content")
    
    args = parser.parse_args()
    
    # Process content
    process_forum_content(args)

if __name__ == "__main__":
    main() 