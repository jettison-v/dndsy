#!/usr/bin/env python
"""
DnD Beyond Forums Crawler
-------------------------
This module uses Selenium to crawl the DnD Beyond forums and extract threads and posts.
It handles pagination, login (if needed), and respects rate limits to avoid anti-scraping measures.
"""

import os
import sys
import logging
import time
import random
from pathlib import Path
import json
import re
import datetime
from typing import Dict, List, Any, Optional, Tuple
import hashlib
import argparse

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Import Selenium libraries
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# BeautifulSoup for parsing HTML
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Vector store for forum content
from vector_store.dnd_beyond_forum_store import DnDBeyondForumStore

# Constants
FORUM_BASE_URL = "https://www.dndbeyond.com/forums"
FORUM_SECTIONS = [
    "general-discussion",
    "rules-discussion",
    "character-build-help",
    "game-tales-stories",
    "dungeon-masters-only",
    "unearthed-arcana",
    "plot-hooks-adventures",
]
DEFAULT_OUTPUT_DIR = "data/forum_posts"

class DnDBeyondForumsCrawler:
    """
    A crawler for DnD Beyond forums that uses Selenium to extract content.
    """
    
    def __init__(self, headless: bool = True, output_dir: str = DEFAULT_OUTPUT_DIR, 
                 delay_min: float = 1.0, delay_max: float = 3.0):
        """
        Initialize the crawler.
        
        Args:
            headless: Whether to run the browser in headless mode
            output_dir: Directory to save extracted content
            delay_min: Minimum delay between requests in seconds
            delay_max: Maximum delay between requests in seconds
        """
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.driver = None
        self.vector_store = DnDBeyondForumStore()
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Statistics
        self.stats = {
            "threads_visited": 0,
            "posts_extracted": 0,
            "pages_crawled": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None
        }
    
    def setup_driver(self):
        """Initialize and configure the Selenium WebDriver."""
        try:
            chrome_options = Options()
            if self.headless:
                chrome_options.add_argument("--headless")
            
            # Add additional Chrome options for stability
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--remote-debugging-port=9222")
            
            # Set user agent to avoid detection
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36")
            
            # Install and set up ChromeDriver
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Set page load timeout
            self.driver.set_page_load_timeout(30)
            
            logger.info("WebDriver initialized successfully")
            return True
        
        except Exception as e:
            logger.error(f"Error setting up WebDriver: {e}", exc_info=True)
            return False
    
    def random_delay(self):
        """Sleep for a random amount of time to avoid detection."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)
    
    def close_driver(self):
        """Close the WebDriver if it's open."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("WebDriver closed successfully")
            except Exception as e:
                logger.error(f"Error closing WebDriver: {e}")
            finally:
                self.driver = None
    
    def extract_thread_list(self, forum_section: str, page: int = 1) -> List[str]:
        """
        Extract thread URLs from a forum section page.
        
        Args:
            forum_section: The forum section to crawl
            page: The page number
            
        Returns:
            List of thread URLs
        """
        thread_urls = []
        
        try:
            # Construct the forum section URL with pagination
            url = f"{FORUM_BASE_URL}/{forum_section}"
            if page > 1:
                url += f"?page={page}"
            
            logger.info(f"Fetching thread list from {url}")
            self.driver.get(url)
            self.random_delay()
            
            # Wait for thread list to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".forum-listing-item, .p-body-pageContent"))
            )
            
            # Check if page has threads
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Extract thread links
            thread_elements = soup.select(".forum-listing-item h4 a, .structItem-title a")
            
            for element in thread_elements:
                thread_url = element.get('href')
                if thread_url:
                    if not thread_url.startswith("http"):
                        thread_url = f"https://www.dndbeyond.com{thread_url}"
                    thread_urls.append(thread_url)
            
            logger.info(f"Found {len(thread_urls)} threads on page {page} of {forum_section}")
            self.stats["pages_crawled"] += 1
            
            return thread_urls
        
        except Exception as e:
            logger.error(f"Error extracting thread list from {forum_section} page {page}: {e}", exc_info=True)
            self.stats["errors"] += 1
            return []
    
    def extract_thread_content(self, thread_url: str) -> Optional[Dict[str, Any]]:
        """
        Extract content from a thread.
        
        Args:
            thread_url: URL of the thread
            
        Returns:
            Dictionary with thread metadata and posts
        """
        try:
            logger.info(f"Extracting thread content from {thread_url}")
            self.driver.get(thread_url)
            self.random_delay()
            
            # Wait for thread content to load
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".thread-view, .p-body-main"))
            )
            
            # Check for potential captcha or login wall
            if "Please complete the security check to access" in self.driver.page_source:
                logger.warning(f"Security check detected on {thread_url}. Waiting longer...")
                time.sleep(10)  # Wait longer to see if it resolves
                
                if "Please complete the security check to access" in self.driver.page_source:
                    logger.error("Failed to bypass security check. Consider manual intervention.")
                    self.stats["errors"] += 1
                    return None
            
            # Extract thread information
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            # Get thread title
            thread_title_elem = soup.select_one("h1.p-title-value, .thread-title")
            thread_title = thread_title_elem.text.strip() if thread_title_elem else "Unknown Thread"
            
            # Identify forum section
            forum_section = "unknown"
            breadcrumb = soup.select_one(".breadcrumb, .p-breadcrumbs")
            if breadcrumb:
                section_links = breadcrumb.select("a")
                if section_links and len(section_links) > 1:
                    forum_section = section_links[-1].text.strip()
            
            # Extract thread ID from URL
            thread_id_match = re.search(r'threads/([^/]+)', thread_url)
            thread_id = thread_id_match.group(1) if thread_id_match else hashlib.md5(thread_url.encode()).hexdigest()
            
            # Create thread data structure
            thread_data = {
                "thread_id": thread_id,
                "title": thread_title,
                "url": thread_url,
                "forum_section": forum_section,
                "crawled_at": datetime.datetime.now().isoformat(),
                "posts": []
            }
            
            # Extract posts
            self.extract_posts_from_thread(thread_data, soup)
            
            # Check if thread has multiple pages
            pagination = soup.select_one(".pageNav-main, .pageNavWrapper")
            if pagination:
                page_links = pagination.select("a")
                max_page = 1
                
                for link in page_links:
                    try:
                        page_num = int(link.text.strip())
                        max_page = max(max_page, page_num)
                    except ValueError:
                        pass
                
                # Crawl additional pages if found
                for page in range(2, max_page + 1):
                    page_url = f"{thread_url}/page-{page}"
                    logger.info(f"Fetching additional page {page} of thread")
                    self.driver.get(page_url)
                    self.random_delay()
                    
                    # Wait for page to load
                    WebDriverWait(self.driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".thread-view, .p-body-main"))
                    )
                    
                    page_source = self.driver.page_source
                    soup = BeautifulSoup(page_source, 'html.parser')
                    
                    # Extract posts from this page
                    self.extract_posts_from_thread(thread_data, soup)
                    self.stats["pages_crawled"] += 1
            
            logger.info(f"Extracted {len(thread_data['posts'])} posts from thread '{thread_title}'")
            self.stats["threads_visited"] += 1
            
            return thread_data
        
        except Exception as e:
            logger.error(f"Error extracting thread content from {thread_url}: {e}", exc_info=True)
            self.stats["errors"] += 1
            return None
    
    def extract_posts_from_thread(self, thread_data: Dict[str, Any], soup: BeautifulSoup):
        """
        Extract posts from a thread page.
        
        Args:
            thread_data: Thread data dictionary to append posts to
            soup: BeautifulSoup object of the thread page
        """
        try:
            # Extract posts
            post_elements = soup.select(".message, .block-body, .post")
            
            for post_elem in post_elements:
                try:
                    # Skip quoted posts
                    if post_elem.get("class") and ("bbCodeBlock--quote" in post_elem.get("class") or "quoted-message" in post_elem.get("class")):
                        continue
                    
                    # Extract post ID
                    post_id = post_elem.get("id", "")
                    if not post_id:
                        post_id = post_elem.get("data-content", "")
                    
                    if not post_id:
                        # Generate a unique ID based on content hash
                        content_hash = hashlib.md5(post_elem.text.encode()).hexdigest()
                        post_id = f"post_{content_hash}"
                    else:
                        # Clean up post ID
                        post_id = post_id.replace("post-", "").replace("content-", "")
                    
                    # Extract author
                    author_elem = post_elem.select_one(".message-name, .username, .authorText")
                    author = author_elem.text.strip() if author_elem else "Unknown"
                    
                    # Extract timestamp
                    timestamp_elem = post_elem.select_one(".message-attribution-time, .DateTime, .message-date")
                    timestamp = timestamp_elem.get("datetime", "") if timestamp_elem else ""
                    if not timestamp and timestamp_elem:
                        timestamp = timestamp_elem.text.strip()
                    
                    # Extract post content
                    content_elem = post_elem.select_one(".message-body, .message-content, .post-content")
                    
                    if content_elem:
                        # Remove quote blocks from content
                        for quote in content_elem.select(".bbCodeBlock--quote, .quoted-message"):
                            quote.decompose()
                        
                        # Extract text without HTML
                        content_text = content_elem.get_text(separator="\n", strip=True)
                        
                        # Only add post if it has content
                        if content_text:
                            post_data = {
                                "post_id": post_id,
                                "author": author,
                                "timestamp": timestamp,
                                "text": content_text,
                                "thread_id": thread_data["thread_id"],
                                "thread_title": thread_data["title"],
                                "forum_section": thread_data["forum_section"],
                                "url": f"{thread_data['url']}#post-{post_id}",
                                "title": thread_data["title"]  # Use thread title as post title
                            }
                            
                            thread_data["posts"].append(post_data)
                            self.stats["posts_extracted"] += 1
                
                except Exception as post_error:
                    logger.error(f"Error extracting post: {post_error}")
                    self.stats["errors"] += 1
        
        except Exception as e:
            logger.error(f"Error extracting posts from thread: {e}", exc_info=True)
            self.stats["errors"] += 1
    
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
            logger.error(f"Error saving thread data: {e}", exc_info=True)
    
    def add_to_vector_store(self, thread_data: Dict[str, Any]):
        """
        Add thread posts to the vector store.
        
        Args:
            thread_data: Thread data with posts
        """
        if not thread_data or not thread_data.get("posts"):
            return
        
        try:
            posts = thread_data["posts"]
            success_count, error_count = self.vector_store.add_forum_posts(posts)
            
            logger.info(f"Added {success_count} posts to vector store (errors: {error_count})")
        
        except Exception as e:
            logger.error(f"Error adding posts to vector store: {e}", exc_info=True)
    
    def crawl_forum_section(self, forum_section: str, max_pages: int = 5, max_threads: int = 10):
        """
        Crawl a specific forum section.
        
        Args:
            forum_section: Forum section to crawl
            max_pages: Maximum number of pages to crawl
            max_threads: Maximum number of threads to crawl
        """
        if not self.driver:
            if not self.setup_driver():
                logger.error("Failed to set up WebDriver. Aborting crawl.")
                return
        
        logger.info(f"Starting crawl of forum section: {forum_section}")
        thread_count = 0
        
        for page in range(1, max_pages + 1):
            # Get thread URLs from this page
            thread_urls = self.extract_thread_list(forum_section, page)
            
            # Process each thread
            for thread_url in thread_urls:
                if thread_count >= max_threads:
                    logger.info(f"Reached maximum thread count ({max_threads})")
                    break
                
                thread_data = self.extract_thread_content(thread_url)
                
                if thread_data:
                    # Save thread data to file
                    self.save_thread_data(thread_data)
                    
                    # Add to vector store
                    self.add_to_vector_store(thread_data)
                    
                    thread_count += 1
                
                # Random delay between threads
                self.random_delay()
            
            if thread_count >= max_threads:
                break
            
            # Random delay between pages
            self.random_delay()
        
        logger.info(f"Completed crawl of forum section {forum_section}. Processed {thread_count} threads.")
    
    def crawl_forums(self, sections: List[str] = None, max_pages_per_section: int = 5, 
                    max_threads_per_section: int = 10):
        """
        Crawl multiple forum sections.
        
        Args:
            sections: List of forum sections to crawl. If None, uses all sections.
            max_pages_per_section: Maximum number of pages per section
            max_threads_per_section: Maximum number of threads per section
        """
        # Use all sections if none specified
        if not sections:
            sections = FORUM_SECTIONS
        
        # Initialize driver if not already initialized
        if not self.driver:
            if not self.setup_driver():
                logger.error("Failed to set up WebDriver. Aborting crawl.")
                return
        
        # Record start time
        self.stats["start_time"] = datetime.datetime.now().isoformat()
        
        try:
            for section in sections:
                logger.info(f"Crawling forum section: {section}")
                self.crawl_forum_section(section, max_pages_per_section, max_threads_per_section)
        
        finally:
            # Record end time
            self.stats["end_time"] = datetime.datetime.now().isoformat()
            
            # Save stats
            stats_file = self.output_dir / "crawl_stats.json"
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
            
            # Close driver
            self.close_driver()
            
            logger.info(f"Crawl completed. Stats: {self.stats}")


def main():
    """Command-line interface for the crawler."""
    parser = argparse.ArgumentParser(description="Crawl DnD Beyond forums")
    parser.add_argument("--sections", nargs="+", help=f"Forum sections to crawl. Available: {', '.join(FORUM_SECTIONS)}")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory to save output")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum pages per section")
    parser.add_argument("--max-threads", type=int, default=10, help="Maximum threads per section")
    parser.add_argument("--no-headless", action="store_true", help="Disable headless mode")
    parser.add_argument("--delay-min", type=float, default=1.0, help="Minimum delay between requests")
    parser.add_argument("--delay-max", type=float, default=3.0, help="Maximum delay between requests")
    
    args = parser.parse_args()
    
    # Validate sections
    if args.sections:
        for section in args.sections:
            if section not in FORUM_SECTIONS:
                logger.warning(f"Unknown forum section: {section}. Available sections: {', '.join(FORUM_SECTIONS)}")
    
    # Initialize and run crawler
    crawler = DnDBeyondForumsCrawler(
        headless=not args.no_headless,
        output_dir=args.output_dir,
        delay_min=args.delay_min,
        delay_max=args.delay_max
    )
    
    crawler.crawl_forums(
        sections=args.sections,
        max_pages_per_section=args.max_pages,
        max_threads_per_section=args.max_threads
    )


if __name__ == "__main__":
    main() 