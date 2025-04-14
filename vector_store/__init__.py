import os
from typing import Dict, Any, Optional
import logging
from dotenv import load_dotenv

# Import the specific store classes
from .pdf_pages_store import PdfPagesStore
from .semantic_store import SemanticStore
from .haystack.qdrant_store import HaystackQdrantStore
from .haystack.memory_store import HaystackMemoryStore

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global vector store instances
_vector_stores = {}

def get_vector_store(store_type: str = None) -> Any:
    """
    Factory method to get the appropriate vector store.
    
    Args:
        store_type: The type of vector store to use.
                   Options: 'standard' (default), 'semantic', 'haystack-qdrant', 'haystack-memory'
    
    Returns:
        A vector store instance
    """
    global _vector_stores
    
    if store_type is None:
        store_type = os.getenv("DEFAULT_VECTOR_STORE", "semantic") # Default to semantic if not specified
        logger.info(f"No store type specified, using default: {store_type}")
    
    # For backward compatibility
    if store_type == 'haystack':
        store_type = 'haystack-qdrant'
    
    # Return cached instance if available
    if store_type in _vector_stores:
        logger.debug(f"Returning cached vector store instance for type: {store_type}")
        return _vector_stores[store_type]

    # Create and cache new instance
    logger.info(f"Creating new vector store instance for type: {store_type}")
    
    if store_type == "standard":
        _vector_stores[store_type] = PdfPagesStore()
    elif store_type == "semantic":
        _vector_stores[store_type] = SemanticStore()
    elif store_type == "haystack-qdrant":
        _vector_stores[store_type] = HaystackQdrantStore()
    elif store_type == "haystack-memory":
        _vector_stores[store_type] = HaystackMemoryStore()
    else:
        logger.warning(f"Unknown vector store type: {store_type}. Defaulting to semantic.")
        _vector_stores[store_type] = SemanticStore()
        
    return _vector_stores[store_type] 