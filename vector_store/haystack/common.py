"""
Common utilities for Haystack vector store implementations.
This module contains shared functionality used by both Qdrant and Memory backends.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Load environment variables
env_path = Path(__file__).parents[2] / '.env'
load_dotenv(dotenv_path=env_path)

# Define constants
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384  # Dimension for all-MiniLM-L6-v2

def initialize_embedding_model():
    """Initialize and return a sentence transformer embedding model."""
    embedding_model_name = os.getenv("HAYSTACK_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    try:
        sentence_transformer = SentenceTransformer(embedding_model_name)
        logging.info(f"Initialized SentenceTransformer with model: {embedding_model_name}")
        return sentence_transformer, embedding_model_name
    except Exception as e:
        logging.error(f"Error initializing SentenceTransformer: {e}")
        return None, embedding_model_name

def chunk_document_with_cross_page_context(page_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Creates chunks from document pages with improved context awareness.
    Used by both Haystack implementations.
    """
    if not page_texts:
        return []
        
    try:
        chunks = []
        
        # Prepare each page as a separate chunk with complete metadata
        for page_data in page_texts:
            if not page_data.get("text", "").strip():
                continue
                
            text = page_data["text"]
            metadata = page_data["metadata"]
            
            # Create chunks with metadata
            chunks.append({
                "text": text,
                "metadata": metadata
            })
            
        logging.info(f"Created {len(chunks)} chunks from {len(page_texts)} pages")
        return chunks
        
    except Exception as e:
        logging.error(f"Error in haystack chunking: {e}", exc_info=True)
        return []

# Create a custom Secret class to wrap the API key for Qdrant
class SimpleSecret:
    """Wrapper for API keys to make them compatible with Haystack 2.x."""
    def __init__(self, value):
        self._value = value
    
    def resolve_value(self):
        return self._value

def create_source_page_filter(source: str, page: int) -> Dict[str, Any]:
    """Create source/page filter for Haystack implementations."""
    return {
        "source": source,
        "page": page
    } 