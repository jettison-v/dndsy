import os
from typing import List, Dict, Any, Optional, Tuple
import logging
from dotenv import load_dotenv
from pathlib import Path
import numpy as np
import json

# Haystack imports
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack import Document

# Sentence transformer
from sentence_transformers import SentenceTransformer

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define constants
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384  # Dimension for all-MiniLM-L6-v2

# Create a custom Secret class to wrap the API key
class SimpleSecret:
    def __init__(self, value):
        self._value = value
    
    def resolve_value(self):
        return self._value

class HaystackStore:
    """Handles document storage and retrieval using Haystack with Qdrant."""
    
    DEFAULT_COLLECTION_NAME = "dnd_haystack"  # Reverted to original collection name
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store with Qdrant backend."""
        self.collection_name = collection_name
        
        # Initialize sentence transformer model for embeddings
        self.embedding_model_name = os.getenv("HAYSTACK_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        try:
            self.sentence_transformer = SentenceTransformer(self.embedding_model_name)
            logging.info(f"Initialized SentenceTransformer with model: {self.embedding_model_name}")
        except Exception as e:
            logging.error(f"Error initializing SentenceTransformer: {e}")
            self.sentence_transformer = None
        
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
            
            # Initialize retrievers for search
            self.init_retrievers()
            
        except Exception as e:
            logging.error(f"Error initializing QdrantDocumentStore: {e}", exc_info=True)
            
            # Fallback to in-memory for testing
            logging.warning("Falling back to in-memory document store")
            self.document_store = QdrantDocumentStore(
                ":memory:",  # In-memory Qdrant
                index=collection_name,
                embedding_dim=EMBEDDING_DIMENSION
            )
    
    def init_retrievers(self):
        """Initialize retrievers for searching documents."""
        try:
            # In haystack-ai 2.x, we'll simply use our SentenceTransformer model
            # for generating embeddings and the QdrantDocumentStore for search
            logging.info(f"Using SentenceTransformer model: {self.embedding_model_name}")
            
            # No need for additional retrievers - the document store has query methods
        except Exception as e:
            logging.error(f"Error in retriever initialization: {e}", exc_info=True)
    
    def chunk_document_with_cross_page_context(self, page_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Creates chunks from document pages with improved context awareness."""
        if not page_texts:
            return []
            
        try:
            chunks = []
            
            # We'll prepare each page as a separate chunk with complete metadata
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
    
    def add_points(self, points: List[Dict[str, Any]]) -> int:
        """Adds documents to the Haystack document store."""
        if not points:
            logging.warning("No points to add to Haystack store")
            return 0
            
        logging.info(f"Adding {len(points)} documents to Haystack store")
        
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
                logging.info(f"Successfully added {len(documents)} documents to Haystack store")
                return len(documents)
            else:
                logging.warning("No valid documents to add")
                return 0
                
        except Exception as e:
            logging.error(f"Error adding documents: {e}", exc_info=True)
            return 0
    
    def search(self, query_vector: List[float], query: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Performs search using QdrantDocumentStore."""
        logging.info(f"Searching haystack for: '{query if query else 'vector-only'}'")
        
        if not query and query_vector is None:
            logging.warning("No query provided for search")
            return []
            
        try:
            if query and not query_vector:
                # Generate embedding for the query
                if self.sentence_transformer:
                    query_vector = self.sentence_transformer.encode(query).tolist()
                    logging.info(f"Generated query embedding with dimension {len(query_vector)}")
                else:
                    logging.error("SentenceTransformer not initialized, cannot encode query")
                    return []
            
            # Log connection details
            logging.info(f"Searching in collection: {self.collection_name}")
            
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
            
            logging.info(f"Search returned {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logging.error(f"Error during search: {e}", exc_info=True)
            
            # Try a fallback approach with direct Qdrant client if available
            try:
                logging.info("Attempting fallback search approach...")
                # This is just for logging - we're not actually implementing a fallback
                logging.info("No fallback currently implemented")
            except Exception as fallback_error:
                logging.error(f"Fallback search also failed: {fallback_error}")
                
            return []
            
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
    
    def get_all_documents(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Gets all documents from the document store."""
        try:
            # Try to use pagination with get_documents_generator if available
            logging.info(f"Retrieving all documents (limit: {limit})")
            
            try:
                documents = []
                count = 0
                
                # Use the _get_documents_generator method if available
                for doc in self.document_store._get_documents_generator():
                    if count >= limit:
                        break
                    documents.append({
                        "text": doc.content,
                        "metadata": doc.meta
                    })
                    count += 1
                    
                logging.info(f"Retrieved {len(documents)} documents")
                return documents
                
            except (AttributeError, NotImplementedError) as e:
                # Fall back to filter_documents without a filter to get all docs
                logging.info(f"Generator method not available, falling back to filter_documents")
                
                # Use empty filter to get all documents in Haystack 2.x format
                documents = self.document_store.filter_documents(filters={})
                
                # Format documents
                formatted_docs = []
                for doc in documents[:limit]:
                    formatted_docs.append({
                        "text": doc.content,
                        "metadata": doc.meta
                    })
                    
                logging.info(f"Retrieved {len(formatted_docs)} documents using fallback method")
                return formatted_docs
                
        except Exception as e:
            logging.error(f"Error retrieving all documents: {str(e)}", exc_info=True)
            return []
    
    def get_details_by_source_page(self, source: str, page: int) -> Optional[Dict[str, Any]]:
        """Gets detailed information about a specific page from a source document."""
        try:
            # Create filter using Haystack 2.x filter syntax
            # See: https://docs.haystack.deepset.ai/docs/metadata-filtering
            filters = {
                "operator": "AND",
                "conditions": [
                    {"field": "meta.source", "operator": "==", "value": source},
                    {"field": "meta.page", "operator": "==", "value": page}
                ]
            }
            
            logging.info(f"Retrieving details for {source} page {page} using filter: {filters}")
            documents = self.document_store.filter_documents(filters=filters)
            
            if not documents:
                logging.warning(f"No documents found for {source} page {page}")
                return None
                
            # Use the first matching document
            doc = documents[0]
            
            # Get the image URL from metadata if available
            image_url = None
            if hasattr(doc, 'meta') and doc.meta and 'image_url' in doc.meta:
                image_url = doc.meta['image_url']
                
            return {
                "text": doc.content,
                "metadata": doc.meta,
                "image_url": image_url
            }
            
        except Exception as e:
            logging.error(f"Error retrieving page details: {str(e)}", exc_info=True)
            return None 