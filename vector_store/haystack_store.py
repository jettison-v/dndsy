import os
from typing import List, Dict, Any, Optional, Tuple
import logging
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
import numpy as np

# Using direct sentence-transformers instead of haystack embedders
from sentence_transformers import SentenceTransformer
from haystack import Document
from haystack.document_stores.in_memory import InMemoryDocumentStore

# Text splitting for chunking
from langchain.text_splitter import RecursiveCharacterTextSplitter

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define constants
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

class HaystackStore:
    """Handles document storage and retrieval using Haystack-AI."""
    
    DEFAULT_COLLECTION_NAME = "dnd_haystack"
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Haystack vector store."""
        self.collection_name = collection_name
        
        # Initialize document store
        self.document_store = InMemoryDocumentStore()
        
        # Initialize sentence transformer directly instead of using haystack embedders
        self.embedding_model_name = os.getenv("HAYSTACK_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        try:
            self.sentence_transformer = SentenceTransformer(self.embedding_model_name)
            logging.info(f"Initialized SentenceTransformer with model: {self.embedding_model_name}")
        except Exception as e:
            logging.error(f"Error initializing SentenceTransformer: {e}")
            self.sentence_transformer = None
        
        # Text Splitter for Chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Document ID tracking
        self.next_id = 0
        
        logging.info(f"Initialized Haystack store with model: {self.embedding_model_name}")
    
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
            logging.info(f"Successfully added {len(documents)} documents to Haystack store. Next ID: {self.next_id}")
            return len(documents)
        except Exception as e:
            logging.error(f"Error writing documents to Haystack store: {e}", exc_info=True)
            return 0
    
    def search(self, query_vector: List[float], query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Performs hybrid search using Haystack components."""
        logging.info(f"Searching (haystack) for: '{query}'")
        
        if not self.document_store.count_documents():
            logging.warning("No documents in Haystack store. Returning empty results.")
            return []
        
        # Get all documents
        all_documents = self.get_all_documents()
        
        # Basic similarity search with the query
        if self.sentence_transformer is not None:
            try:
                # Generate query embedding
                query_embedding = self.sentence_transformer.encode(query)
                
                # Simple similarity search using dot product
                results = []
                for doc in all_documents:
                    if hasattr(doc.get("embedding", None), "shape"):
                        # Calculate similarity score
                        score = np.dot(query_embedding, doc["embedding"]) / (
                            np.linalg.norm(query_embedding) * np.linalg.norm(doc["embedding"])
                        )
                        results.append({
                            "text": doc["text"],
                            "metadata": doc["metadata"],
                            "score": float(score)
                        })
                
                # Sort by score
                results.sort(key=lambda x: x["score"], reverse=True)
                return results[:limit]
            except Exception as e:
                logging.error(f"Error in embedding search: {e}", exc_info=True)
        
        # Fallback to simple text matching if embedding search fails
        results = []
        for doc in all_documents:
            # Simple text matching - check if query appears in the text
            if query.lower() in doc["text"].lower():
                results.append({
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "score": 0.5  # Default score for text matches
                })
        
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
        
        # Create a consolidated response
        result = {
            "source": source_name,
            "page": page_number,
            "chunks": matching_docs
        }
        
        return result
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Retrieves all documents from the store."""
        # Get all documents from the store
        all_docs = self.document_store.get_all_documents()
        
        # Convert to standard format
        formatted_docs = []
        for doc in all_docs:
            formatted_docs.append({
                "text": doc.content,
                "metadata": doc.meta,
                "embedding": doc.embedding
            })
        
        return formatted_docs 