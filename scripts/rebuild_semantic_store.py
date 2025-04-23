#!/usr/bin/env python
"""
Rebuild the semantic vector store from scratch to fix metadata alignment issues.
This script:
1. Clears the existing semantic collection
2. Reprocesses all PDFs using the improved chunking method
3. Validates that metadata matches content
"""

import os
import sys
import json
import logging
import time
import random
from pathlib import Path
import re

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from data_ingestion.processor import DataProcessor
from vector_store.semantic_store import SemanticStore
from vector_store.common import get_vector_store
from config import load_env_config
from llm import embed_query  # For search testing

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def validate_metadata_alignment(semantic_store, sample_size=5):
    """
    Validates a sample of chunks to ensure metadata matches content.
    
    Args:
        semantic_store: Initialized semantic store
        sample_size: Number of chunks to sample for validation
        
    Returns:
        Boolean indicating if validation passed
    """
    # Get all documents
    try:
        all_docs = semantic_store._get_all_documents_raw(limit=1000)
        logger.info(f"Retrieved {len(all_docs)} documents for validation sampling")
        
        if not all_docs:
            logger.warning("No documents found for validation")
            return False
            
        # Select random sample
        sample_docs = random.sample(all_docs, min(sample_size, len(all_docs)))
        logger.info(f"Validating {len(sample_docs)} random chunks")
        
        valid_count = 0
        issues_count = 0
        
        for doc in sample_docs:
            text = doc["text"]
            metadata = doc["metadata"]
            
            # Check for page number reference patterns in text
            page_patterns = [
                r"Page (\d+)",
                r"Pg\.? (\d+)",
                r"p\.? (\d+)"
            ]
            
            metadata_page = metadata.get("page")
            pages_mentioned = []
            
            # Extract potential page numbers mentioned in text
            for pattern in page_patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    try:
                        page_num = int(match.group(1))
                        pages_mentioned.append(page_num)
                    except (ValueError, IndexError):
                        pass
            
            # Check heading path in metadata
            metadata_headings = metadata.get("heading_path", "")
            if isinstance(metadata_headings, list):
                metadata_headings = " > ".join(metadata_headings)
            
            # Basic validation logic
            valid = True
            
            # Check if page mentions align with metadata
            if pages_mentioned and metadata_page not in pages_mentioned:
                valid = False
                logger.warning(f"Page mismatch - Metadata: {metadata_page}, Mentioned: {pages_mentioned}")
                logger.warning(f"Text excerpt: {text[:100]}...")
            
            # Check if headings are relevant to content
            heading_words = set(re.findall(r'\b\w+\b', metadata_headings.lower()))
            significant_words = set(word.lower() for word in re.findall(r'\b[A-Za-z]{4,}\b', text))
            
            # Calculate content descriptor overlap
            if heading_words and significant_words:
                overlap = heading_words.intersection(significant_words)
                if not overlap and len(heading_words) > 1:
                    logger.warning(f"Heading doesn't match content - Heading: {metadata_headings}")
                    logger.warning(f"Text excerpt: {text[:100]}...")
                    valid = False
            
            if valid:
                valid_count += 1
            else:
                issues_count += 1
                
        logger.info(f"Validation complete: {valid_count}/{len(sample_docs)} chunks valid")
        return issues_count == 0
        
    except Exception as e:
        logger.error(f"Error during validation: {e}")
        return False

def test_semantic_search(semantic_store, test_queries=None):
    """Tests the semantic store with sample queries to ensure it's working properly"""
    if test_queries is None:
        test_queries = [
            "How does Circle of the Moon druid wild shape work?",
            "What are the rules for spell components?",
            "Explain the rogue's sneak attack feature"
        ]
    
    success = True
    
    for query in test_queries:
        try:
            # Embed the query
            query_vector = embed_query(query, "semantic")
            
            # Search for results
            results = semantic_store.search(query_vector=query_vector, query=query, limit=3)
            
            if results:
                logger.info(f"Query '{query}' returned {len(results)} results")
                top_result = results[0]
                logger.info(f"Top result from: {top_result['metadata'].get('source')} (page {top_result['metadata'].get('page')})")
                
                # Check if top result has required metadata
                required_keys = ["page", "source", "heading_path"]
                for key in required_keys:
                    if key not in top_result['metadata']:
                        logger.warning(f"Missing required metadata key '{key}' in search result")
                        success = False
            else:
                logger.warning(f"Query '{query}' returned no results")
                success = False
                
        except Exception as e:
            logger.error(f"Error testing query '{query}': {e}")
            success = False
    
    return success

def rebuild_semantic_store():
    """
    Rebuilds the semantic store from scratch to fix metadata alignment issues.
    """
    start_time = time.time()
    logger.info("Starting semantic store rebuild process...")
    
    # 1. Initialize stores
    semantic_store = get_vector_store("semantic")
    if not semantic_store:
        logger.error("Failed to initialize semantic store")
        return False
    
    # Optional: validate current store to document issues
    logger.info("Validating current semantic store for issues...")
    validate_metadata_alignment(semantic_store)
    
    # 2. Delete the existing semantic collection
    try:
        logger.info("Deleting existing semantic collection...")
        semantic_store.client.delete_collection(semantic_store.collection_name)
        logger.info("Successfully deleted semantic collection")
        
        # Recreate empty collection
        semantic_store._create_collection_if_not_exists(embedding_dim=1536)
        logger.info("Created new empty semantic collection")
    except Exception as e:
        logger.error(f"Error deleting semantic collection: {e}")
        return False
    
    # 3. Initialize data processor
    processor = DataProcessor(rebuild_cache=True)
    
    # 4. Process all PDFs with cache behavior set to "rebuild"
    logger.info("Beginning PDF processing with rebuilt semantic store...")
    result = processor.process_all(
        store_types=["semantic"],
        cache_behavior="rebuild"
    )
    
    # 5. Validate the rebuilt store
    if result:
        logger.info("Validating rebuilt semantic store...")
        validation_passed = validate_metadata_alignment(semantic_store, sample_size=10)
        
        # 6. Test search functionality
        logger.info("Testing semantic search functionality...")
        search_passed = test_semantic_search(semantic_store)
        
        if validation_passed and search_passed:
            logger.info("Validation and search tests successful!")
        else:
            logger.warning("Some validation or search tests failed - review logs for details")
    
    duration = time.time() - start_time
    if result:
        logger.info(f"Semantic store rebuild completed successfully in {duration:.2f} seconds!")
        return True
    else:
        logger.error(f"Semantic store rebuild failed after {duration:.2f} seconds")
        return False

if __name__ == "__main__":
    # Load environment variables first
    load_env_config()
    
    success = rebuild_semantic_store()
    sys.exit(0 if success else 1) 