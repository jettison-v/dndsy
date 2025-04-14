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
_vector_store_instances = {}

def get_vector_store(vector_store_type=None, force_new=False):
    """
    Factory method to get a vector store instance based on the provided type.
    If no type is provided, uses the environment variable VECTOR_STORE_TYPE.
    
    Args:
        vector_store_type (str, optional): Type of vector store to use. Defaults to None.
        force_new (bool, optional): If True, creates a new instance instead of using cached one. Defaults to False.
        
    Returns:
        VectorStore: An instance of the appropriate vector store class.
    """
    vector_store_type = vector_store_type or os.getenv("VECTOR_STORE_TYPE", "standard")
    
    # If we have a cached instance and don't want to force a new one, return it
    if vector_store_type in _vector_store_instances and not force_new:
        return _vector_store_instances[vector_store_type]
        
    if vector_store_type == "standard":
        from vector_store.standard_store import StandardVectorStore
        store = StandardVectorStore()
    elif vector_store_type == "semantic":
        store = SemanticStore()
    elif vector_store_type == "haystack-qdrant":
        store = HaystackQdrantStore()
    elif vector_store_type == "haystack-memory":
        store = HaystackMemoryStore()
    else:
        logger.warning(f"Unknown vector store type: {vector_store_type}. Defaulting to standard.")
        store = PdfPagesStore()
    
    _vector_store_instances[vector_store_type] = store
    return store 