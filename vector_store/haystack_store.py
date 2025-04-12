import os
from typing import List, Dict, Any, Optional, Tuple
import logging
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
import numpy as np
import pickle
import json

# Using direct sentence-transformers instead of haystack embedders
from sentence_transformers import SentenceTransformer
from haystack import Document
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder, SentenceTransformersTextEmbedder

# Text splitting for chunking
from langchain.text_splitter import RecursiveCharacterTextSplitter

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define constants
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
PERSISTENCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "haystack_store")

class HaystackStore:
    """Handles document storage and retrieval using Haystack-AI."""
    
    DEFAULT_COLLECTION_NAME = "dnd_haystack"
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store."""
        self.collection_name = collection_name
        
        # Create persistence directory if it doesn't exist
        os.makedirs(PERSISTENCE_DIR, exist_ok=True)
        self.persistence_file = os.path.join(PERSISTENCE_DIR, f"{collection_name}_documents.pkl")
        
        # Initialize document store
        self.document_store = InMemoryDocumentStore()
        
        # Initialize sentence transformer directly instead of using haystack embedders
        self.embedding_model_name = os.getenv("HAYSTACK_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        try:
            self.sentence_transformer = SentenceTransformer(self.embedding_model_name)
            logging.info(f"Initialized SentenceTransformer with model: {self.embedding_model_name}")
            
            # Initialize Haystack embedders
            try:
                self.document_embedder = SentenceTransformersDocumentEmbedder(model=self.embedding_model_name)
                self.text_embedder = SentenceTransformersTextEmbedder(model=self.embedding_model_name)
                
                # Warm up embedders
                self.document_embedder.warm_up()
                self.text_embedder.warm_up()
                logging.info("Successfully warmed up Haystack embedders")
            except Exception as e:
                logging.error(f"Failed to initialize Haystack embedders: {e}")
                self.document_embedder = None
                self.text_embedder = None
        except Exception as e:
            logging.error(f"Error initializing SentenceTransformer: {e}")
            self.sentence_transformer = None
            self.document_embedder = None
            self.text_embedder = None
        
        # Text Splitter for Chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Document ID tracking
        self.next_id = 0
        
        # Try to load persisted documents
        self._load_documents()
        
        logging.info(f"Initialized Haystack store with model: {self.embedding_model_name}")
    
    def _save_documents(self):
        """Save documents to disk for persistence."""
        try:
            # Get all documents
            try:
                # Try to use get_all_documents if available
                documents = self.document_store.get_all_documents()
            except (AttributeError, NotImplementedError):
                # Fallback to get_documents
                try:
                    documents = self.document_store.get_documents()
                except (AttributeError, NotImplementedError):
                    # Try one more fallback - using filter_documents with empty filter
                    try:
                        documents = self.document_store.filter_documents({})
                    except (AttributeError, NotImplementedError):
                        logging.error("No compatible method found to get documents from the store for saving")
                        return
            
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
    
    def chunk_document_with_cross_page_context(
        self, 
        page_texts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Chunks text spanning multiple pages, preserving context across boundaries.
        Args:
            page_texts: List of dicts, each containing 'text', 'page', 'metadata'.
        Returns:
            List of chunks, each dict containing 'text' and updated 'metadata'.
        """
        if not page_texts:
            logging.warning("No page texts provided for chunking")
            return []
        
        logging.info(f"Starting cross-page chunking for haystack with {len(page_texts)} pages")
        
        try:
            # Sort pages by page number to ensure correct order
            page_texts = sorted(page_texts, key=lambda x: x["page"])
            
            # Combine text with page markers
            combined_text = ""
            page_markers = {}  # Map character positions to page numbers and original metadata
            
            for page_info in page_texts:
                start_pos = len(combined_text)
                page_markers[start_pos] = page_info # Store original page info (text, metadata, page)
                combined_text += page_info["text"]
                if not combined_text.endswith("\n\n"): combined_text += "\n\n"
            
            logging.info(f"Combined text length: {len(combined_text)} characters")
            
            # Apply semantic chunking to the combined text
            chunks_text = self.text_splitter.split_text(combined_text)
            logging.info(f"Created {len(chunks_text)} raw text chunks")
            
            processed_chunks = []
            chunk_start_pos = 0
            total_chunks = len(chunks_text)
            
            # Find which page each chunk belongs to based on its position in the original text
            for i, chunk_text in enumerate(chunks_text):
                if not chunk_text.strip(): 
                    logging.warning(f"Skipping empty chunk {i}")
                    continue
                    
                # Find which page this chunk starts on
                origin_page_info = None
                nearest_page_pos = -1
                for pos, marker in page_markers.items():
                    if pos <= chunk_start_pos and pos > nearest_page_pos:
                        nearest_page_pos = pos
                        origin_page_info = marker
                
                if not origin_page_info:
                    logging.warning(f"Could not determine source page for chunk {i}, using first page")
                    origin_page_info = page_texts[0]
                
                # Use metadata from the page where this chunk starts
                metadata = origin_page_info["metadata"].copy()
                # Update metadata with chunk info
                metadata["chunk_index"] = i
                metadata["chunk_count"] = total_chunks
                metadata["cross_page"] = True # Indicate it came from cross-page processing
                # Ensure original page number from originating page is kept
                metadata["page"] = origin_page_info["page"]

                processed_chunks.append({
                    "text": chunk_text,
                    "metadata": metadata
                })
                
                # Update start position for the next chunk
                chunk_start_pos += len(chunk_text) + (2 if combined_text[chunk_start_pos + len(chunk_text):].startswith("\n\n") else 0)
            
            logging.info(f"Generated {len(processed_chunks)} semantic chunks from {len(page_texts)} pages for haystack.")
            return processed_chunks
            
        except Exception as e:
            logging.error(f"Error in haystack chunking: {e}", exc_info=True)
            return []

    def add_points(self, points: List[Dict[str, Any]]) -> int:
        """Adds documents to the Haystack document store."""
        if not points:
            logging.warning("No points to add to Haystack store")
            return 0
            
        logging.info(f"Attempting to add {len(points)} points to Haystack store")
        
        # Check if sentence transformer is initialized
        if self.sentence_transformer is None:
            logging.error("SentenceTransformer not initialized")
            return 0
        
        # Convert points to Haystack Documents
        documents = []
        try:
            for i, point in enumerate(points):
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
                    logging.warning(f"Skipping empty document at index {i}")
                    continue
                
                # Generate embedding using sentence-transformers
                embedding = self.sentence_transformer.encode(text)
                    
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
            logging.warning("No valid documents to add to Haystack store")
            return 0
        
        # Write documents to document store
        try:
            logging.info(f"Writing {len(documents)} documents to Haystack store")
            self.document_store.write_documents(documents)
            
            # Save documents to disk for persistence
            self._save_documents()
            
            logging.info(f"Successfully added {len(documents)} documents to Haystack store. Next ID: {self.next_id}")
            return len(documents)
        except Exception as e:
            logging.error(f"Error writing documents to Haystack store: {e}", exc_info=True)
            return 0
    
    def search(self, query_vector: List[float], query: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Performs hybrid search using Haystack components."""
        logging.info(f"Searching (haystack) for: '{query if query else 'vector-only'}'")
        
        if not self.document_store.count_documents():
            logging.warning("No documents in Haystack store. Returning empty results.")
            return []
        
        # Get all documents
        all_documents = self.get_all_documents()
        logging.info(f"Retrieved {len(all_documents)} documents for search")
        
        # Basic similarity search with the query
        if self.sentence_transformer is not None:
            try:
                # If we have query text, use it to generate embedding
                # Otherwise use the provided query_vector
                if query is not None:
                    query_embedding = self.sentence_transformer.encode(query)
                    logging.info(f"Generated query embedding with shape {query_embedding.shape}")
                else:
                    query_embedding = np.array(query_vector)
                    logging.info(f"Using provided query vector with shape {query_embedding.shape}")
                
                # Simple similarity search using dot product
                results = []
                for doc in all_documents:
                    # Get the embedding and ensure it's a numpy array
                    doc_embedding = doc["embedding"]
                    if doc_embedding is None:
                        continue
                    
                    # Convert to numpy array if it's a list
                    if not hasattr(doc_embedding, 'shape'):
                        doc_embedding = np.array(doc_embedding)
                    
                    # Calculate similarity score
                    score = np.dot(query_embedding, doc_embedding) / (
                        np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
                    )
                    
                    results.append({
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": float(score)
                    })
                
                # Sort by score
                results.sort(key=lambda x: x["score"], reverse=True)
                
                # Log top 5 similarity scores for debugging
                if results:
                    logging.info("Top similarity scores:")
                    for i, result in enumerate(results[:5]):
                        logging.info(f"  #{i+1}: {result['score']:.4f}")
                else:
                    logging.warning("No results with similarity scores")
                
                # Return top results without filtering by score threshold
                top_results = results[:limit]
                logging.info(f"Returning top {len(top_results)} results")
                return top_results
            except Exception as e:
                logging.error(f"Error in embedding search: {e}", exc_info=True)
        
        # Fallback to simple text matching if embedding search fails
        logging.info("Falling back to simple text matching")
        results = []
        if query is not None:
            for doc in all_documents:
                # Simple text matching - check if query appears in the text
                if query.lower() in doc["text"].lower():
                    results.append({
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": 0.5  # Default score for text matches
                    })
        
        logging.info(f"Text matching found {len(results)} results")
        return results[:limit]
    
    def get_details_by_source_page(self, source_name: str, page_number: int) -> Optional[Dict[str, Any]]:
        """Retrieves all chunks from a specific page in a specific source."""
        matching_docs = []
        
        # Get all documents from the store
        all_docs = self.get_all_documents()
        
        # Filter documents by source and page
        for doc in all_docs:
            metadata = doc["metadata"]
            if metadata.get("source") == source_name and metadata.get("page") == page_number:
                matching_docs.append(doc)
        
        if not matching_docs:
            return None
        
        # Extract image_url from first document's metadata (they should all have the same)
        image_url = None
        if matching_docs and "metadata" in matching_docs[0] and "image_url" in matching_docs[0]["metadata"]:
            image_url = matching_docs[0]["metadata"]["image_url"]
        
        # Create a consolidated response
        result = {
            "source": source_name,
            "page": page_number,
            "chunks": matching_docs,
            "image_url": image_url  # Add image_url at top level
        }
        
        return result
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Retrieves all documents from the store."""
        try:
            # Try to use get_all_documents if available
            all_docs = self.document_store.get_all_documents()
        except (AttributeError, NotImplementedError):
            # Fallback to get_documents
            try:
                all_docs = self.document_store.get_documents()
            except (AttributeError, NotImplementedError):
                # If neither is available, check if we can find documents through other methods
                logging.warning("Document store doesn't have get_all_documents or get_documents methods")
                # Try one more fallback - using filter_documents with empty filter
                try:
                    all_docs = self.document_store.filter_documents({})
                except (AttributeError, NotImplementedError):
                    # Direct access to internal documents dictionary if all else fails
                    try:
                        # Print available attributes to help debug
                        store_attrs = dir(self.document_store)
                        logging.info(f"Document store attributes: {store_attrs}")
                        
                        # Try common attribute names for document storage
                        if hasattr(self.document_store, "_documents"):
                            all_docs = list(self.document_store._documents.values())
                            logging.info(f"Retrieved {len(all_docs)} documents from _documents")
                        elif hasattr(self.document_store, "documents"):
                            all_docs = list(self.document_store.documents.values())
                            logging.info(f"Retrieved {len(all_docs)} documents from documents")
                        elif hasattr(self.document_store, "_index"):
                            all_docs = list(self.document_store._index.values())
                            logging.info(f"Retrieved {len(all_docs)} documents from _index")
                        elif hasattr(self.document_store, "docs"):
                            all_docs = list(self.document_store.docs.values())
                            logging.info(f"Retrieved {len(all_docs)} documents from docs")
                        else:
                            # Last resort: try to find document-like attributes
                            docs_found = False
                            for attr_name in store_attrs:
                                if attr_name.startswith("_") and attr_name != "__class__":
                                    continue  # Skip most private attrs
                                
                                attr = getattr(self.document_store, attr_name)
                                if isinstance(attr, dict) and len(attr) > 0:
                                    # Check if dictionary values look like documents
                                    sample = next(iter(attr.values()))
                                    if hasattr(sample, "id") and hasattr(sample, "content"):
                                        all_docs = list(attr.values())
                                        logging.info(f"Retrieved {len(all_docs)} documents from {attr_name}")
                                        docs_found = True
                                        break
                        
                            if not docs_found:
                                logging.error("Could not find documents in the document store")
                                return []
                    except Exception as e:
                        logging.error(f"Error accessing internal documents: {e}")
                        return []
        
        # Convert to standard format
        formatted_docs = []
        for doc in all_docs:
            formatted_docs.append({
                "text": doc.content,
                "metadata": doc.meta,
                "embedding": doc.embedding
            })
        
        return formatted_docs

    def search_monster_info(self, monster_type: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Specialized search for finding information about specific monster types.
        
        Args:
            monster_type: The type of monster to search for (e.g., "dragon", "goblin")
            limit: Maximum number of results to return
            
        Returns:
            List of document dictionaries containing monster information
        """
        logging.info(f"Searching for monster information about: '{monster_type}'")
        
        # Get all documents
        all_documents = self.get_all_documents()
        if not all_documents:
            logging.warning("No documents in store to search")
            return []
        
        # First, embed the monster type query for semantic search
        try:
            query_embedding = self.sentence_transformer.encode(f"{monster_type} monster information")
            
            # Calculate similarity scores
            results = []
            for doc in all_documents:
                # Get the embedding and ensure it's a numpy array
                doc_embedding = doc["embedding"]
                if doc_embedding is None:
                    continue
                
                # Convert to numpy array if it's a list
                if not hasattr(doc_embedding, 'shape'):
                    doc_embedding = np.array(doc_embedding)
                
                # Calculate semantic similarity score
                sim_score = np.dot(query_embedding, doc_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
                )
                
                # Check if the document text or metadata contains the monster type
                text = doc["text"].lower()
                metadata = doc["metadata"]
                
                # Boosting factors
                boost = 1.0
                
                # Boost score if monster type appears in the text
                if monster_type.lower() in text:
                    boost += 0.2
                    
                    # Additional boost if it appears multiple times
                    mentions = text.count(monster_type.lower())
                    if mentions > 1:
                        boost += min(0.1 * mentions, 0.3)  # Cap at 0.3 additional boost
                
                # Boost if monster type is in section or heading_path
                section = metadata.get("section", "").lower()
                heading_path = metadata.get("heading_path", "").lower()
                
                if monster_type.lower() in section:
                    boost += 0.3
                
                if monster_type.lower() in heading_path:
                    boost += 0.3
                
                # Boost if it's a stat block (often has monster name in all caps)
                if monster_type.upper() in text:
                    boost += 0.4
                
                # Apply the boost
                final_score = sim_score * boost
                
                results.append({
                    "text": doc["text"],
                    "metadata": metadata,
                    "score": float(final_score)
                })
            
            # Sort by boosted score
            results.sort(key=lambda x: x["score"], reverse=True)
            
            # Log top scores
            if results:
                logging.info(f"Found {len(results)} results for '{monster_type}', returning top {min(limit, len(results))}")
                logging.info("Top scores:")
                for i, result in enumerate(results[:5]):
                    logging.info(f"  #{i+1}: {result['score']:.4f}")
            
            return results[:limit]
        
        except Exception as e:
            logging.error(f"Error searching for monster info: {e}", exc_info=True)
            return [] 