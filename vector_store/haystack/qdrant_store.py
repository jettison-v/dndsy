"""
Haystack implementation using Qdrant as the backend.
"""

import os
import logging
from typing import List, Dict, Any, Optional
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

# Import QdrantClient for type checking in clear_store
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

# Import from common utilities
from .common import (
    initialize_embedding_model, chunk_document_with_cross_page_context,
    SimpleSecret, create_source_page_filter, EMBEDDING_DIMENSION
)

# Haystack imports
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack import Document

# Import base class
from ..search_helper import SearchHelper

# Load environment variables
env_path = Path(__file__).parents[2] / '.env'
load_dotenv(dotenv_path=env_path)

# Define collection name using environment variable with fallback
DEFAULT_COLLECTION_NAME = os.getenv("QDRANT_HAYSTACK_COLLECTION", "dnd_haystack_qdrant")

class HaystackQdrantStore(SearchHelper):
    """Handles document storage and retrieval using Haystack with Qdrant backend."""
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store with Qdrant backend."""
        super().__init__(collection_name)
        
        # Initialize sentence transformer model for embeddings
        self.sentence_transformer, self.embedding_model_name = initialize_embedding_model()
        
        # Initialize Qdrant document store
        try:
            # Check if we should use Qdrant in-memory, local disk, or remote
            qdrant_url = os.getenv("QDRANT_HOST", "localhost")
            qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
            qdrant_api_key = os.getenv("QDRANT_API_KEY", None)
            
            # Local Qdrant or in-memory (for development/testing)
            if qdrant_url == "localhost" or qdrant_url == "127.0.0.1":
                logging.info(f"Initializing Qdrant document store at {qdrant_url}:{qdrant_port}")
                self.document_store = QdrantDocumentStore(
                    url=qdrant_url,
                    port=qdrant_port,
                    index=collection_name,
                    embedding_dim=EMBEDDING_DIMENSION,
                    recreate_index=False,
                    hnsw_config={"m": 16, "ef_construct": 64},
                    api_key=None  # No API key for local
                )
            # Qdrant Cloud
            elif qdrant_url.startswith("http") or qdrant_url.startswith("https"):
                logging.info(f"Initializing Qdrant Cloud document store at {qdrant_url}")
                logging.debug(f"API key present: {qdrant_api_key is not None}")
                # Wrap API key in our SimpleSecret class
                secure_api_key = SimpleSecret(qdrant_api_key) if qdrant_api_key else None
                self.document_store = QdrantDocumentStore(
                    url=qdrant_url,
                    api_key=secure_api_key,  # Use our wrapped API key
                    index=collection_name,
                    embedding_dim=EMBEDDING_DIMENSION,
                    recreate_index=False
                )
            
            logging.info(f"Successfully initialized QdrantDocumentStore for collection: {collection_name}")
            
        except Exception as e:
            logging.error(f"Error initializing QdrantDocumentStore: {e}", exc_info=True)
            
            # Fallback to in-memory for testing
            logging.warning("Falling back to in-memory document store")
            self.document_store = QdrantDocumentStore(
                ":memory:",  # In-memory Qdrant
                index=collection_name,
                embedding_dim=EMBEDDING_DIMENSION
            )
    
    def chunk_document_with_cross_page_context(self, page_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Creates chunks from document pages with improved context awareness."""
        return chunk_document_with_cross_page_context(page_texts)
    
    def add_points(self, points: List[Dict[str, Any]]) -> int:
        """Adds documents to the Haystack document store."""
        if not points:
            logging.warning("No points to add to Haystack Qdrant store")
            return 0
            
        logging.info(f"Adding {len(points)} documents to Haystack Qdrant store")
        
        # Convert points to Haystack Documents
        documents = []
        try:
            for point in points:
                # Handle different formats
                if hasattr(point, 'payload'):
                    text = point.payload.get("text", "")
                    metadata = point.payload.get("metadata", {})
                else:
                    text = point.get("text", "")
                    metadata = point.get("metadata", {})
                
                if not text.strip():
                    continue
                
                # Create Haystack Document
                doc = Document(
                    content=text,
                    meta=metadata,
                )
                documents.append(doc)
            
            # Write documents to store
            if documents:
                # Generate embeddings here before writing if needed
                if self.sentence_transformer:
                    # For each document that doesn't have an embedding, generate one
                    for doc in documents:
                        if not hasattr(doc, 'embedding') or doc.embedding is None:
                            try:
                                # Generate embedding and make sure it's a list
                                doc.embedding = self.sentence_transformer.encode(doc.content).tolist()
                            except Exception as embed_error:
                                logging.error(f"Error generating embedding: {embed_error}")
                
                # Write documents with embeddings
                self.document_store.write_documents(documents)
                logging.info(f"Successfully added {len(documents)} documents to Haystack Qdrant store")
                return len(documents)
            else:
                logging.warning("No valid documents to add")
                return 0
                
        except Exception as e:
            logging.error(f"Error adding documents: {e}", exc_info=True)
            return 0
    
    # Implement abstract methods from SearchHelper
    def _execute_vector_search(self, query_vector: List[float], limit: int) -> List[Dict[str, Any]]:
        """Execute vector search using Haystack document store."""
        # Search documents with embeddings using native QdrantDocumentStore methods
        documents = self.document_store._query_by_embedding(
            query_embedding=query_vector,
            top_k=limit
        )
        
        # Format results
        formatted_results = []
        for doc in documents:
            formatted_results.append({
                "text": doc.content,
                "metadata": doc.meta,
                "score": doc.score if hasattr(doc, 'score') else 0.0
            })
        
        return formatted_results
    
    def _execute_filter_search(self, filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Execute filter search using Haystack filter syntax."""
        # Convert simple filter dict to Haystack format
        haystack_filter = self._convert_to_haystack_filter(filters)
        
        documents = self.document_store.filter_documents(filters=haystack_filter)
        
        # Format results
        formatted_results = []
        for doc in documents[:limit]:
            formatted_results.append({
                "text": doc.content,
                "metadata": doc.meta
            })
            
        return formatted_results
    
    def _get_document_by_filter(self, filter_conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get a document by filter using Haystack filter syntax."""
        results = self._execute_filter_search(filter_conditions, limit=1)
        if results:
            doc = results[0]
            return {
                "text": doc["text"],
                "metadata": doc["metadata"],
                "image_url": doc["metadata"].get("image_url")
            }
        return None
    
    def _get_all_documents_raw(self, limit: int) -> List[Dict[str, Any]]:
        """Get all documents using Haystack document store."""
        try:
            documents = []
            count = 0
            
            # Try with generator if available
            for doc in self.document_store._get_documents_generator():
                if count >= limit:
                    break
                documents.append({
                    "text": doc.content,
                    "metadata": doc.meta
                })
                count += 1
                
            return documents
            
        except (AttributeError, NotImplementedError):
            # Fall back to filter_documents without a filter
            documents = self.document_store.filter_documents(filters={})
            
            # Format documents
            formatted_docs = []
            for doc in documents[:limit]:
                formatted_docs.append({
                    "text": doc.content,
                    "metadata": doc.meta
                })
                
            return formatted_docs
    
    def _convert_to_haystack_filter(self, simple_filter: Dict[str, Any]) -> Dict[str, Any]:
        """Convert simple filter dict to Haystack filter syntax."""
        if not simple_filter:
            return {}
            
        conditions = []
        for key, value in simple_filter.items():
            conditions.append({
                "field": f"meta.{key}",
                "operator": "==",
                "value": value
            })
            
        return {
            "operator": "AND",
            "conditions": conditions
        }
    
    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Create source/page filter specific to Haystack."""
        return create_source_page_filter(source, page)
    
    # Additional Haystack-specific method
    def search_monster_info(self, monster_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search specifically for monster information."""
        try:
            logging.info(f"Searching for monster type: {monster_type}")
            
            # Create a filter for monsters section and monster type
            filters = {
                "operator": "AND",
                "conditions": [
                    # Only search in the Monster Manual
                    {"field": "meta.source", "operator": "==", "value": "source-pdfs/2024 Monster Manual.pdf"},
                    # Text contains the monster type
                    {"field": "content", "operator": "contains", "value": monster_type}
                ]
            }
            
            # Use filter_documents method from QdrantDocumentStore
            documents = self.document_store.filter_documents(filters=filters)
            
            # Format results
            results = []
            for doc in documents[:limit]:  # Limit number of results
                results.append({
                    "text": doc.content,
                    "metadata": doc.meta,
                    "score": 1.0  # Fixed score since we're using filters
                })
                
            logging.info(f"Found {len(results)} monster info results for '{monster_type}'")
            return results
            
        except Exception as e:
            logging.error(f"Error searching for monster info: {str(e)}", exc_info=True)
            return []
    
    def get_details_by_source_page(self, source: str, page: int) -> Optional[Dict[str, Any]]:
        """Get a document by source and page number."""
        try:
            # Create filter for exact match using Haystack 2.x filter format
            haystack_filter = {
                "operator": "AND",
                "conditions": [
                    {"field": "meta.source", "operator": "==", "value": source},
                    {"field": "meta.page", "operator": "==", "value": page}
                ]
            }
            
            # First attempt to get document by direct filter
            results = self.document_store.filter_documents(filters=haystack_filter)
            
            if results:
                # Combine all documents for this page
                combined_text = ""
                metadata = {}
                image_url = None
                total_pages = None
                
                for i, doc in enumerate(results):
                    if i == 0:  # Use metadata from first document
                        metadata = doc.meta
                        image_url = metadata.get("image_url")
                        total_pages = metadata.get("total_pages")
                    combined_text += doc.content + "\n\n"
                
                # Return combined document
                result = {
                    "text": combined_text.strip(),
                    "metadata": metadata,
                    "image_url": image_url,
                    "total_pages": total_pages
                }
                return result
            else:
                logging.warning(f"No documents found for source: {source}, page: {page}")
                
                # Try to get documents from the same source to extract metadata
                source_filter = {
                    "operator": "AND",
                    "conditions": [
                        {"field": "meta.source", "operator": "==", "value": source}
                    ]
                }
                
                any_docs = self.document_store.filter_documents(filters=source_filter)
                
                if any_docs:
                    # Found documents from same source, extract metadata
                    image_url = None
                    total_pages = None
                    
                    # Get the first document with useful metadata
                    for doc in any_docs:
                        meta = doc.meta
                        
                        # Get image_url pattern
                        if not image_url and "image_url" in meta:
                            base_url = meta["image_url"]
                            # Extract base URL up to the page number
                            if base_url and isinstance(base_url, str):
                                image_url_parts = base_url.rsplit('/', 1)
                                if len(image_url_parts) > 1:
                                    # Construct URL for the requested page
                                    image_url = f"{image_url_parts[0]}/{page}.png"
                        
                        # Get total pages
                        if not total_pages and "total_pages" in meta:
                            total_pages = meta["total_pages"]
                        
                        if image_url and total_pages:
                            break
                    
                    # Return placeholder with available metadata
                    return {
                        "text": f"Page {page} is not indexed in the Qdrant store for this document. Try navigating to other pages.",
                        "metadata": {"source": source, "page": page},
                        "image_url": image_url,
                        "total_pages": total_pages,
                        "available_in_store": False
                    }
                
                return None
        except Exception as e:
            logging.error(f"Error in get_details_by_source_page: {e}", exc_info=True)
            return None

    def clear_store(self, client: Any = None):
        """Deletes the entire Qdrant collection associated with this Haystack store."""
        # Use the passed Qdrant client if available, otherwise log error.
        # Haystack's QdrantDocumentStore doesn't seem to expose a reliable delete method.
        q_client = client # Expecting a QdrantClient instance here
        
        if not q_client:
            logging.error(f"Qdrant client instance was not provided to clear Haystack collection: {self.collection_name}. Cannot clear.")
            return
        
        if not isinstance(q_client, QdrantClient):
             logging.error(f"Invalid client type passed to HaystackQdrantStore.clear_store: {type(q_client)}. Expected QdrantClient.")
             return

        try:
            collection_name = self.document_store.index # Get collection name from Haystack store
            logging.info(f"Attempting to delete Qdrant collection for Haystack store: {collection_name}")
            q_client.delete_collection(collection_name=collection_name)
            logging.info(f"Successfully deleted Qdrant collection: {collection_name}")
            # Immediately recreate the collection after deletion
            # Note: Haystack's QdrantDocumentStore handles creation on init if missing,
            # but recreating explicitly ensures it exists before potential add_points.
            # We need the embedding dimension here.
            logging.info(f"Recreating collection {collection_name}...")
            q_client.recreate_collection(
                 collection_name=collection_name,
                 vectors_config=models.VectorParams(size=EMBEDDING_DIMENSION, distance=models.Distance.COSINE)
            )
            logging.info(f"Recreated collection {collection_name} via Qdrant client.")
        except Exception as e:
            logging.warning(f"Could not delete or recreate Qdrant collection '{self.collection_name}' for Haystack: {e}") 