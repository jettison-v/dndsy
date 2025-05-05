import os
from typing import Dict, Any, Optional
import logging
from dotenv import load_dotenv
from config import ENV_PREFIX, get_qdrant_collection_name, get_haystack_memory_dir

# Import the specific store classes
from .pdf_pages_store import PdfPagesStore
from .semantic_store import SemanticStore
from .haystack.qdrant_store import HaystackQdrantStore
from .haystack.memory_store import HaystackMemoryStore
from .search_helper import SearchHelper

load_dotenv()

# Configure logging
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global vector store instances
_vector_store_instances = {}

def get_vector_store(store_type: str, run_id: Optional[str] = None, force_new: bool = False) -> SearchHelper | None:
    """Factory function to get or create vector store instances based on type and run_id."""
    global _vector_store_instances

    # Determine the cache key based on store type and potential run_id (for temp stores)
    cache_key = f"{store_type}_{run_id}" if run_id else store_type

    # Return cached instance if available and not forcing new
    if not force_new and cache_key in _vector_store_instances:
        logger.debug(f"Returning cached vector store instance for key: {cache_key}")
        return _vector_store_instances[cache_key]

    logger.info(f"Creating new vector store instance for type: '{store_type}' (Run ID: {run_id or 'Live'}, Force New: {force_new})")
    store_instance = None
    try:
        if store_type == "pages":
            # --- Use config helper for prefixed collection name --- 
            base_name = PdfPagesStore.DEFAULT_COLLECTION_NAME
            collection_name = get_qdrant_collection_name(base_name)
            if run_id: # If creating a temporary store for a rebuild run
                collection_name = f"{collection_name}_temp_{run_id}" # Append temp suffix
            logger.info(f"Initializing PdfPagesStore with collection: '{collection_name}'")
            store_instance = PdfPagesStore(collection_name=collection_name)
            # -------------------------------------------------------
        elif store_type == "semantic":
            # --- Use config helper for prefixed collection name --- 
            base_name = SemanticStore.DEFAULT_COLLECTION_NAME
            collection_name = get_qdrant_collection_name(base_name)
            if run_id:
                collection_name = f"{collection_name}_temp_{run_id}"
            logger.info(f"Initializing SemanticStore with collection: '{collection_name}'")
            store_instance = SemanticStore(collection_name=collection_name)
            # -------------------------------------------------------
        elif store_type == "haystack-qdrant":
            # --- Use config helper for prefixed collection name --- 
            base_name = HaystackQdrantStore.DEFAULT_COLLECTION_NAME
            collection_name = get_qdrant_collection_name(base_name)
            if run_id:
                collection_name = f"{collection_name}_temp_{run_id}"
            logger.info(f"Initializing HaystackQdrantStore with collection: '{collection_name}'")
            store_instance = HaystackQdrantStore(collection_name=collection_name)
            # -------------------------------------------------------
        elif store_type == "haystack-memory":
            # --- Use config helper for prefixed directory --- 
            base_dir_name = "haystack_store" # Or read from HaystackMemoryStore if it has a default
            persistence_path = get_haystack_memory_dir(base_dir_name)
            if run_id:
                persistence_path = f"{persistence_path}_temp_{run_id}" # Append temp suffix to path
            logger.info(f"Initializing HaystackMemoryStore with path: '{persistence_path}'")
            store_instance = HaystackMemoryStore(persistence_path=persistence_path)
            # -------------------------------------------------
        else:
            logger.error(f"Unknown vector store type requested: {store_type}")
            return None
        
        # Cache the newly created instance
        _vector_store_instances[cache_key] = store_instance
        logger.info(f"Successfully created and cached vector store instance for key: {cache_key}")
        return store_instance

    except Exception as e:
        logger.error(f"Error creating vector store instance for type '{store_type}' (Run ID: {run_id}): {e}", exc_info=True)
        return None 