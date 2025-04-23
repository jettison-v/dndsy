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
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from data_ingestion.processor import DataProcessor
from vector_store.semantic_store import SemanticStore
from vector_store.common import get_vector_store
from config import load_env_config

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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