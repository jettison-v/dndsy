import os
from typing import Dict, Any, Optional
import logging
from dotenv import load_dotenv

# Import the specific store classes
from .pdf_pages_store import PdfPagesStore
from .semantic_store import SemanticStore
from .haystack_store import HaystackStore

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
                   Options: 'standard' (default), 'semantic', 'haystack'
    
    Returns:
        A vector store instance
    """
    global _vector_stores
    
    if store_type is None:
        store_type = os.getenv("DEFAULT_VECTOR_STORE", "semantic") # Default to semantic if not specified
        logger.info(f"No store type specified, using default: {store_type}")
    
    # Return cached instance if available
    if store_type in _vector_stores:
        logger.debug(f"Returning cached vector store instance for type: {store_type}")
        return _vector_stores[store_type]

    # Create and cache new instance
    logger.info(f"Creating new vector store instance for type: {store_type}")
    if store_type == "standard": # Keep 'standard' as the key for now, maps to PdfPagesStore
        try:
            store = PdfPagesStore() # Instantiate the renamed class
            _vector_stores[store_type] = store
            return store
        except Exception as e:
            logger.error(f"Failed to initialize PdfPagesStore: {e}", exc_info=True)
            raise
    elif store_type == "semantic":
        try:
            store = SemanticStore()
            _vector_stores[store_type] = store
            return store
        except Exception as e:
            logger.error(f"Failed to initialize SemanticStore: {e}", exc_info=True)
            raise
    elif store_type == "haystack":
        try:
            store = HaystackStore()
            _vector_stores[store_type] = store
            return store
        except Exception as e:
            logger.error(f"Failed to initialize HaystackStore: {e}", exc_info=True)
            raise
    else:
        logger.error(f"Unknown vector store type requested: {store_type}")
        raise ValueError(f"Unknown vector store type: {store_type}") 