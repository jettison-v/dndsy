"""
Haystack implementation using InMemoryDocumentStore with file persistence.
"""

import os
import logging
from typing import List, Dict, Any, Optional
import pickle
import numpy as np
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Import from common utilities
from .common import (
    initialize_embedding_model, chunk_document_with_cross_page_context,
    create_source_page_filter, EMBEDDING_DIMENSION
)

# Haystack imports
from haystack import Document
from haystack.document_stores.in_memory import InMemoryDocumentStore

# Import base class
from ..search_helper import SearchHelper

# Load environment variables
env_path = Path(__file__).parents[2] / '.env'
load_dotenv(dotenv_path=env_path)

# Define the persistence directory
PERSISTENCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                              "data", "haystack_store")

class HaystackMemoryStore(SearchHelper):
    """Handles document storage and retrieval using Haystack with in-memory persistence."""
    
    DEFAULT_COLLECTION_NAME = "dnd_haystack_memory"
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store with in-memory persistence."""
        super().__init__(collection_name)
        
        # Create persistence directory if it doesn't exist
        os.makedirs(PERSISTENCE_DIR, exist_ok=True)
        self.persistence_file = os.path.join(PERSISTENCE_DIR, f"{collection_name}_documents.pkl")
        
        # Initialize document store
        self.document_store = InMemoryDocumentStore()
        
        # Initialize sentence transformer model for embeddings
        self.sentence_transformer, self.embedding_model_name = initialize_embedding_model()
        
        # Document ID tracking
        self.next_id = 0
        
        # Try to load persisted documents
        self._load_documents()
        
        logging.info(f"Initialized Haystack Memory store with model: {self.embedding_model_name}")
        
    def _save_documents(self):
        """Save documents to disk for persistence."""
        try:
            # Get all documents
            documents = []
            try:
                # Try various methods to get all documents
                for doc in self.document_store._get_documents_generator():
                    documents.append(doc)
            except (AttributeError, NotImplementedError):
                # Fallback to filter_documents
                documents = self.document_store.filter_documents({})
            
            with open(self.persistence_file, 'wb') as f:
                pickle.dump({
                    'documents': documents,
                    'next_id': self.next_id
                }, f)
            logging.info(f"Saved {len(documents)} documents to {self.persistence_file}")
        except Exception as e:
            logging.error(f"Error saving documents to disk: {e}", exc_info=True)
    
    def _load_documents(self):
        """Load documents from disk if available."""
        if os.path.exists(self.persistence_file):
            try:
                with open(self.persistence_file, 'rb') as f:
                    data = pickle.load(f)
                    documents = data.get('documents', [])
                    self.next_id = data.get('next_id', 0)
                
                if documents:
                    self.document_store.write_documents(documents)
                    logging.info(f"Loaded {len(documents)} documents from {self.persistence_file}")
                else:
                    logging.warning(f"No documents found in {self.persistence_file}")
            except Exception as e:
                logging.error(f"Error loading documents from disk: {e}", exc_info=True)
                self.next_id = 0
        else:
            logging.info(f"No persistence file found at {self.persistence_file}")
            self.next_id = 0
    
    def chunk_document_with_cross_page_context(self, page_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Creates chunks from document pages with improved context awareness."""
        return chunk_document_with_cross_page_context(page_texts)
    
    def add_points(self, points: List[Dict[str, Any]]) -> int:
        """Adds documents to the Haystack document store."""
        if not points:
            logging.warning("No points to add to Haystack Memory store")
            return 0
            
        logging.info(f"Adding {len(points)} points to Haystack Memory store")
        
        # Convert points to Haystack Documents
        documents = []
        try:
            for point in points:
                doc_id = str(self.next_id)
                self.next_id += 1
                
                # Handle both dictionary format and PointStruct format
                if hasattr(point, 'payload'):
                    # It's a PointStruct (from the Qdrant client)
                    text = point.payload.get("text", "")
                    metadata = point.payload.get("metadata", {})
                else:
                    # It's a dictionary format
                    text = point.get("text", "")
                    metadata = point.get("metadata", {})
                
                if not text.strip():
                    logging.warning(f"Skipping empty document at index {self.next_id-1}")
                    continue
                
                # Generate embedding using sentence-transformers
                embedding = None
                if self.sentence_transformer:
                    try:
                        embedding = self.sentence_transformer.encode(text).tolist()
                    except Exception as e:
                        logging.error(f"Error generating embedding: {e}")
                    
                documents.append(
                    Document(
                        id=doc_id,
                        content=text,
                        meta=metadata,
                        embedding=embedding
                    )
                )
            
            logging.info(f"Created {len(documents)} Haystack Document objects with embeddings")
        except Exception as e:
            logging.error(f"Error creating Haystack Documents: {e}", exc_info=True)
            return 0
        
        if not documents:
            logging.warning("No valid documents to add to Haystack Memory store")
            return 0
        
        # Write documents to document store
        try:
            logging.info(f"Writing {len(documents)} documents to Haystack Memory store")
            self.document_store.write_documents(documents)
            
            # Save documents to disk for persistence
            self._save_documents()
            
            logging.info(f"Successfully added {len(documents)} documents to Haystack Memory store. Next ID: {self.next_id}")
            return len(documents)
        except Exception as e:
            logging.error(f"Error writing documents to Haystack Memory store: {e}", exc_info=True)
            return 0
    
    # Implement abstract methods from SearchHelper
    def _execute_vector_search(self, query_vector: List[float], limit: int) -> List[Dict[str, Any]]:
        """Execute vector search using Haystack document store."""
        if not self.document_store.count_documents():
            logging.warning("No documents in Haystack Memory store. Returning empty results.")
            return []
        
        # Get all documents
        all_documents = self._get_all_documents_raw(1000)  # Practical limit for in-memory comparison
        
        # Convert query_vector to numpy array for calculations
        query_embedding = np.array(query_vector)
        
        # Simple similarity search using dot product
        results = []
        for doc in all_documents:
            # Skip if no embedding
            if "embedding" not in doc or doc["embedding"] is None:
                continue
            
            # Convert to numpy array for calculation
            doc_embedding = np.array(doc["embedding"])
            
            # Calculate similarity score (cosine similarity)
            score = np.dot(query_embedding, doc_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
            )
            
            results.append({
                "text": doc["text"],
                "metadata": doc["metadata"],
                "score": float(score)
            })
        
        # Sort by score and return top results
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    
    def _execute_filter_search(self, filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Execute filter search by comparing metadata fields."""
        all_documents = self._get_all_documents_raw(1000)  # Get all documents and filter in memory
        
        # Manual filtering based on metadata
        results = []
        for doc in all_documents:
            metadata = doc["metadata"]
            match = True
            
            # Check each filter condition
            for key, value in filters.items():
                if key not in metadata or metadata[key] != value:
                    match = False
                    break
            
            if match:
                results.append(doc)
                if len(results) >= limit:
                    break
        
        return results
    
    def _get_document_by_filter(self, filter_conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get a document by filter."""
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
        """Get all documents using in-memory document store."""
        try:
            documents = []
            count = 0
            
            # Use the Haystack Document format
            haystack_docs = self.document_store.filter_documents({})
            
            for doc in haystack_docs[:limit]:
                documents.append({
                    "text": doc.content,
                    "metadata": doc.meta,
                    "embedding": doc.embedding
                })
                count += 1
                if count >= limit:
                    break
                    
            return documents
            
        except Exception as e:
            logging.error(f"Error retrieving all documents: {e}", exc_info=True)
            return []
    
    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Create source/page filter."""
        return create_source_page_filter(source, page)
    
    # Additional Haystack-specific method
    def search_monster_info(self, monster_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search specifically for monster information."""
        try:
            logging.info(f"Searching for monster type: {monster_type}")
            
            # Get all documents
            all_documents = self._get_all_documents_raw(1000)
            
            # Filter documents manually
            results = []
            for doc in all_documents:
                metadata = doc["metadata"]
                text = doc["text"].lower()
                
                # Check if document is from Monster Manual and contains the monster type
                if (metadata.get("source") == "source-pdfs/2024 Monster Manual.pdf" and
                    monster_type.lower() in text):
                    results.append({
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": 1.0  # Fixed score for text matches
                    })
                    
                if len(results) >= limit:
                    break
            
            logging.info(f"Found {len(results)} monster info results for '{monster_type}'")
            return results
            
        except Exception as e:
            logging.error(f"Error searching for monster info: {str(e)}", exc_info=True)
            return []

    def get_details_by_source_page(self, source: str, page: int) -> Optional[Dict[str, Any]]:
        """Get a document by source and page."""
        try:
            filter_conditions = self._create_source_page_filter(source, page)
            document = self._get_document_by_filter(filter_conditions)
            
            if document:
                logging.info(f"Found document for {source} page {page}")
                return document
            else:
                logging.warning(f"No document found for {source} page {page}")
                
                # Try to find any document from this source to get metadata
                any_docs = self._get_documents_for_source(source)
                if any_docs:
                    # We have some documents from this source but not for this page
                    # Extract total_pages and construct image_url
                    image_url = None
                    total_pages = None
                    
                    # Find the first document with useful metadata
                    for doc in any_docs:
                        doc_metadata = doc.get('metadata', {})
                        
                        # Get image_url pattern
                        if not image_url and 'image_url' in doc_metadata:
                            base_url = doc_metadata['image_url']
                            # Extract base URL up to the page number
                            if base_url and isinstance(base_url, str):
                                image_url_parts = base_url.rsplit('/', 1)
                                if len(image_url_parts) > 1:
                                    # Construct URL for the requested page
                                    image_url = f"{image_url_parts[0]}/{page}.png"
                        
                        # Get total_pages
                        if not total_pages and 'total_pages' in doc_metadata:
                            total_pages = doc_metadata['total_pages']
                            
                        if image_url and total_pages:
                            break
                    
                    # Return a placeholder with the metadata we have
                    return {
                        "text": f"Page {page} is not available in the Memory store for this document. Try navigating to other pages.",
                        "metadata": {"source": source, "page": page},
                        "image_url": image_url,
                        "total_pages": total_pages,
                        "available_in_store": False
                    }
                
                return None
        except Exception as e:
            logging.error(f"Error retrieving page details: {e}", exc_info=True)
            return None

    def _get_documents_for_source(self, source: str) -> List[Dict[str, Any]]:
        """Get all documents from a specific source."""
        try:
            # Get all documents
            all_docs = self._get_all_documents_raw(1000)
            
            # Filter for this source
            return [doc for doc in all_docs if doc.get('metadata', {}).get('source') == source]
        except Exception as e:
            logging.error(f"Error retrieving documents for source {source}: {e}", exc_info=True)
            return []

    def clear_store(self, client: Any = None):
        """Clears the in-memory store and deletes the persistence file."""
        # client parameter is ignored for memory store
        try:
            # Delete the persistence file if it exists
            if os.path.exists(self.persistence_file):
                os.remove(self.persistence_file)
                logging.info(f"Deleted haystack persistence file: {self.persistence_file}")
            else:
                 logging.info(f"No persistence file to delete: {self.persistence_file}")
            
            # Reinitialize the underlying Haystack InMemoryDocumentStore
            self.document_store = InMemoryDocumentStore()
            # Reset the document ID counter
            self.next_id = 0
            logging.info("Successfully cleared and reinitialized Haystack Memory store.")
            
        except Exception as e:
            logging.error(f"Error clearing Haystack Memory store: {e}", exc_info=True) 