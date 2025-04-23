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
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from data_ingestion.processor import DataProcessor

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # Load environment variables first
    load_dotenv()
    
    # Initialize processor with cache_behavior="rebuild" to force regeneration
    processor = DataProcessor(cache_behavior="rebuild")
    
    # Use the convenient rebuild method that handles validation and testing
    success = processor.rebuild_semantic_store(
        validate=True,
        test_search=True,
        sample_size=10
    )
    
    sys.exit(0 if success else 1) 