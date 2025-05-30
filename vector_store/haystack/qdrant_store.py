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

class HaystackQdrantStore(SearchHelper):
    """Handles document storage and retrieval using Haystack with Qdrant backend."""
    
    DEFAULT_COLLECTION_NAME = "dnd_haystack_qdrant"
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store with Qdrant backend."""
        super().__init__(collection_name)
        
        # Initialize sentence transformer model for embeddings
        self.sentence_transformer, self.embedding_model_name = initialize_embedding_model()
        
        # --- Initialize Haystack QdrantDocumentStore --- 
        qdrant_url = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        qdrant_api_key = os.getenv("QDRANT_API_KEY", None)
        is_cloud = qdrant_url.startswith("http") or qdrant_url.startswith("https")
        self.qdrant_client_for_admin = None # Client for admin tasks like index creation

        try:
            # Initialize Haystack Document Store
            if is_cloud:
                logging.info(f"Initializing Qdrant Cloud document store at {qdrant_url}")
                secure_api_key = SimpleSecret(qdrant_api_key) if qdrant_api_key else None
                self.document_store = QdrantDocumentStore(
                    url=qdrant_url,
                    api_key=secure_api_key,
                    index=collection_name,
                    embedding_dim=EMBEDDING_DIMENSION,
                    recreate_index=False
                )
                # Also create direct client for admin tasks
                self.qdrant_client_for_admin = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=60)
            else:
                logging.info(f"Initializing Qdrant document store at {qdrant_url}:{qdrant_port}")
                self.document_store = QdrantDocumentStore(
                    url=qdrant_url,
                    port=qdrant_port,
                    index=collection_name,
                    embedding_dim=EMBEDDING_DIMENSION,
                    recreate_index=False,
                    hnsw_config={"m": 16, "ef_construct": 64},
                    api_key=None
                )
                # Also create direct client for admin tasks
                self.qdrant_client_for_admin = QdrantClient(host=qdrant_url, port=qdrant_port, timeout=60)
            
            logging.info(f"Successfully initialized QdrantDocumentStore for collection: {collection_name}")
            # Ensure payload indices exist
            self._ensure_payload_indices_exist()

        except Exception as e:
            logging.error(f"Error initializing QdrantDocumentStore: {e}", exc_info=True)
            logging.warning("Haystack Qdrant Store initialization failed.")
            self.document_store = None # Ensure store is None on failure
            self.qdrant_client_for_admin = None
    
    def _ensure_payload_indices_exist(self):
        """Checks for and creates necessary payload indices if they don't exist."""
        if not self.qdrant_client_for_admin:
            logging.warning("Direct Qdrant client not available, cannot ensure payload indices.")
            return

        try:
            collection_info = self.qdrant_client_for_admin.get_collection(collection_name=self.collection_name)
            existing_indices = collection_info.payload_schema or {}
            
            # Check and create index for meta.source
            source_field = "meta.source" # Use 'meta' prefix for Haystack
            if source_field not in existing_indices:
                logging.info(f"Creating keyword payload index for {source_field} in {self.collection_name}")
                self.qdrant_client_for_admin.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=source_field,
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
            else:
                 logging.debug(f"Index for {source_field} already exists.")
            
            # Check and create index for meta.page
            page_field = "meta.page" # Use 'meta' prefix for Haystack
            if page_field not in existing_indices:
                logging.info(f"Creating integer payload index for {page_field} in {self.collection_name}")
                self.qdrant_client_for_admin.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=page_field,
                    field_schema=models.PayloadSchemaType.INTEGER
                )
            else:
                 logging.debug(f"Index for {page_field} already exists.")

        except Exception as e:
            logging.error(f"Error ensuring payload indices exist for {self.collection_name}: {e}", exc_info=True)

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
        """Get a document by source and page number using direct Qdrant query.
        
        Note: This method uses a direct Qdrant client query instead of relying 
        solely on Haystack's self.document_store.filter_documents because 
        testing revealed issues with retrieving documents based on exact 
        source/page filters via the Haystack abstraction, even when indices were present.
        Using the direct client ensures reliable lookup for the source panel.
        """
        if not self.qdrant_client_for_admin:
            logging.error("Direct Qdrant client not available for get_details_by_source_page.")
            return None
            
        try:
            # Create filter for exact match using Qdrant models
            search_filter = models.Filter(
                must=[
                    models.FieldCondition( 
                        key="meta.source", # Target Haystack's meta field
                        match=models.MatchValue(value=source)
                    ),
                    models.FieldCondition(
                        key="meta.page",   # Target Haystack's meta field
                        match=models.MatchValue(value=page)
                    )
                ]
            )
            
            # Use the direct Qdrant client's scroll method
            scroll_response, _ = self.qdrant_client_for_admin.scroll(
                collection_name=self.collection_name,
                scroll_filter=search_filter,
                limit=100,  # Retrieve all chunks for this page
                with_payload=True,
                with_vectors=False
            )
            
            if scroll_response:
                # Combine all chunks for this page into a single text
                points = scroll_response
                combined_text = ""
                metadata = {}
                image_url = None
                total_pages = None
                
                # Sort points by chunk_index to maintain order (if available)
                # Haystack doesn't add chunk_index, so sorting might not be needed/possible
                # sorted_points = sorted(points, key=lambda p: p.payload.get("meta", {}).get("chunk_index", 0))
                
                for point in points: # Use unsorted points if chunk_index isn't present
                    payload = point.payload
                    meta = payload.get("meta", {})
                    combined_text += payload.get("content", "") + "\n\n"
                    
                    # Use first point's metadata as base
                    if not metadata:
                        metadata = meta # Use the whole 'meta' dict
                    
                    # Get image_url and total_pages from any chunk
                    if not image_url and "image_url" in meta:
                        image_url = meta["image_url"]
                    if not total_pages and "total_pages" in meta:
                        total_pages = meta["total_pages"]
                
                # Return combined document
                return {
                    "text": combined_text.strip(),
                    "metadata": metadata, # Return the Haystack meta dict
                    "image_url": image_url,
                    "total_pages": total_pages
                }
            else:
                # No points found for this specific page using direct query
                logging.warning(f"Direct Qdrant query found no documents for source: {source}, page: {page}")
                # Attempt fallback using only source filter (similar to original logic)
                source_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="meta.source",
                            match=models.MatchValue(value=source)
                        )
                    ]
                )
                
                any_docs_response, _ = self.qdrant_client_for_admin.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=source_filter,
                    limit=100,
                    with_payload=True,
                    with_vectors=False
                )

                if any_docs_response:
                    # Found documents from same source, extract metadata
                    image_url = None
                    total_pages = None
                    sample_points = any_docs_response

                    for point in sample_points:
                        meta = point.payload.get("meta", {})
                        # Get image_url pattern
                        if not image_url and "image_url" in meta:
                            base_url = meta["image_url"]
                            if base_url and isinstance(base_url, str):
                                image_url_parts = base_url.rsplit('/', 1)
                                if len(image_url_parts) > 1:
                                    image_url = f"{image_url_parts[0]}/{page}.png"
                        
                        # Get total pages
                        if not total_pages and "total_pages" in meta:
                            total_pages = meta["total_pages"]
                        
                        if image_url and total_pages:
                            break
                            
                    return {
                        "text": f"Page {page} is not explicitly indexed in the Haystack store for this document. Try navigating to other pages.",
                        "metadata": {"source": source, "page": page}, # Basic metadata
                        "image_url": image_url,
                        "total_pages": total_pages,
                        "available_in_store": False
                    }
                else:
                    # No documents found even for just the source
                    logging.warning(f"Direct Qdrant query found no documents for source '{source}' at all.")
                    return None
                    
        except Exception as e:
            logging.error(f"Error in get_details_by_source_page (direct Qdrant query): {e}", exc_info=True)
            return None

    def clear_store(self, client: Any = None):
        """Deletes the entire Qdrant collection associated with this Haystack store."""
        # Use the internal direct client instance for clearing
        q_client = self.qdrant_client_for_admin
        
        if not q_client:
            logging.error(f"Direct Qdrant client not available for clearing Haystack collection: {self.collection_name}. Cannot clear.")
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
            # Ensure indices are created on the newly recreated collection
            self._ensure_payload_indices_exist()
        except Exception as e:
            logging.warning(f"Could not delete or recreate Qdrant collection '{self.collection_name}' for Haystack: {e}") 