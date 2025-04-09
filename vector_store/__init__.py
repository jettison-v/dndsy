import os
from typing import Dict, Any, Optional
import logging
from vector_store.qdrant_store import QdrantStore
from vector_store.semantic_store import SemanticStore

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
                   Options: 'standard' (default), 'semantic'
    
    Returns:
        A vector store instance
    """
    global _vector_stores
    
    # Default to environment variable or fallback to standard
    if store_type is None:
        store_type = os.getenv("DEFAULT_VECTOR_STORE", "standard")
    
    # Validate store_type
    if store_type not in ["standard", "semantic"]:
        logger.warning(f"Invalid store_type '{store_type}'. Falling back to 'standard'.")
        store_type = "standard"
    
    # Instantiate and cache the vector store if needed
    if store_type not in _vector_stores:
        if store_type == "standard":
            _vector_stores[store_type] = QdrantStore(collection_name="dnd_knowledge")
            logger.info("Initialized standard vector store")
        elif store_type == "semantic":
            _vector_stores[store_type] = SemanticStore(collection_name="dnd_semantic")
            logger.info("Initialized semantic vector store")
    
    return _vector_stores[store_type] 