import os
from typing import List, Dict, Any, Optional, Tuple
from qdrant_client import QdrantClient
from qdrant_client.http import models
import logging
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

# LangChain imports for improved semantic search
from langchain.text_splitter import RecursiveCharacterTextSplitter
# Add back OpenAIEmbeddings import - needed for internal BM25 init
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Qdrant as LangChainQdrant
from langchain_community.retrievers import BM25Retriever
from langchain.schema import Document
import numpy as np
# Remove SentenceTransformer import - no longer used here
# from sentence_transformers import SentenceTransformer, util
from .search_helper import SearchHelper

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define embedding size for semantic model ("text-embedding-3-small")
SEMANTIC_EMBEDDING_DIMENSION = 1536
DEFAULT_COLLECTION_NAME = "dnd_semantic"

class SemanticStore(SearchHelper):
    """Handles semantic chunking, hybrid search (vector + BM25), and Qdrant interaction for the semantic collection."""
    
    DEFAULT_COLLECTION_NAME = DEFAULT_COLLECTION_NAME
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize Semantic vector store."""
        super().__init__(collection_name)
        
        # Internal embedding client ONLY needed for initial BM25 population fallback
        # if the store is empty and search is called before ingestion.
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self._embeddings_for_bm25_init = None
        if self.openai_api_key:
            try:
                self._embeddings_for_bm25_init = OpenAIEmbeddings(
                     model="text-embedding-3-small", openai_api_key=self.openai_api_key
                )
                logging.debug("Internal OpenAI embeddings initialized for potential BM25 fallback.")
            except Exception as e:
                 logging.warning(f"Failed to initialize internal OpenAI embeddings for BM25 fallback: {e}")
        else:
             logging.warning("OPENAI_API_KEY not found. BM25 lazy initialization might fail if needed before ingestion.")

        embedding_dim = SEMANTIC_EMBEDDING_DIMENSION
        
        # Qdrant Client Initialization
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")
        if is_cloud:
            logging.info(f"Connecting to Qdrant Cloud at: {qdrant_host} for {self.collection_name}")
            self.client = QdrantClient(url=qdrant_host, api_key=qdrant_api_key, timeout=60)
        else:
            logging.info(f"Connecting to local Qdrant at: {qdrant_host} for {self.collection_name}")
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = QdrantClient(host=qdrant_host, port=port, timeout=60)
        
        # Text Splitter for Chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        self._create_collection_if_not_exists(embedding_dim)
        
        # BM25 Retriever State (initialized/updated during add_points or lazy search)
        self.bm25_documents = [] # Stores Langchain Documents for BM25
        self.bm25_retriever = None
        
        # Qdrant Point ID Tracking
        try:
            # Get current point count to determine starting ID for new points
            self.next_id = self.client.count(self.collection_name).count
            logging.info(f"Initialized Semantic store. Next ID for '{self.collection_name}': {self.next_id}")
        except Exception as e:
            logging.warning(f"Error getting collection count for '{self.collection_name}': {e}. Starting ID count at 0.")
            self.next_id = 0
            
    def _create_collection_if_not_exists(self, embedding_dim):
        """Create the collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(col.name == self.collection_name for col in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=embedding_dim,
                    distance=models.Distance.COSINE
                )
            )
            logging.info(f"Created new semantic collection: {self.collection_name}")
    
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
            return []
        
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
        
        # Apply semantic chunking to the combined text
        chunks_text = self.text_splitter.split_text(combined_text)
        
        processed_chunks = []
        chunk_start_pos = 0
        total_chunks = len(chunks_text)
        
        # Find which page each chunk belongs to based on its position in the original text
        for i, chunk_text in enumerate(chunks_text):
            if not chunk_text.strip(): continue
                
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
            chunk_start_pos += len(chunk_text) + (2 if combined_text[chunk_start_pos + len(chunk_text):].startswith("\n\n") else 0) # Account for separators potentially removed by splitter
        
        logging.info(f"Generated {len(processed_chunks)} semantic chunks from {len(page_texts)} pages.")
        return processed_chunks

    def add_points(self, points: List[models.PointStruct]) -> int:
        """Adds pre-computed points to Qdrant and updates the BM25 retriever."""
        if not points:
            return 0

        # Update BM25 retriever with the new documents being added
        new_bm25_docs = []
        for point in points:
             new_bm25_docs.append(Document(
                 page_content=point.payload['text'],
                 metadata=point.payload['metadata']
             ))
             
        # TODO: Decide how to handle BM25 updates. Rebuild completely or append?
        # Rebuilding is simpler but potentially slow for large updates.
        # Appending might be faster but state management is harder. 
        # For now, let's rebuild if new docs exist.
        if new_bm25_docs:
             logging.info(f"Updating BM25 retriever with {len(new_bm25_docs)} new documents...")
             # Option 1: Append (if BM25Retriever supports it well - needs testing)
             # if self.bm25_retriever:
             #     self.bm25_retriever.add_documents(new_bm25_docs)
             # else:
             #     self.bm25_documents.extend(new_bm25_docs)
             #     self.bm25_retriever = BM25Retriever.from_documents(self.bm25_documents)
             
             # Option 2: Rebuild (Simpler for now)
             self.bm25_documents.extend(new_bm25_docs)
             try:
                 self.bm25_retriever = BM25Retriever.from_documents(self.bm25_documents)
                 logging.info(f"Rebuilt BM25 retriever with {len(self.bm25_documents)} total documents.")
             except Exception as e:
                  logging.error(f"Failed to rebuild BM25 retriever: {e}", exc_info=True)
                  # Proceed without BM25 if it fails
                  self.bm25_retriever = None

        batch_size = 100
        num_batches = (len(points) + batch_size - 1) // batch_size
        points_added_count = 0
        
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                    wait=True 
                )
                logging.info(f"Added batch {batch_num}/{num_batches} ({len(batch)} points) to {self.collection_name}")
                points_added_count += len(batch)
                # Update next_id based on the highest ID in the current batch
                max_id_in_batch = max(p.id for p in batch)
                self.next_id = max(self.next_id, max_id_in_batch + 1)
            except Exception as e:
                logging.error(f"Error adding batch {batch_num}/{num_batches} to {self.collection_name}: {e}", exc_info=True)
                raise # Re-raise for now
        
        logging.info(f"Finished adding {points_added_count} points to {self.collection_name}. Next ID: {self.next_id}")
        return points_added_count
    
    def _hybrid_reranking(self, dense_results: List[Dict], sparse_results: List[Document], query: str, k: int = 5):
        """Combines dense (vector) and sparse (BM25) results with keyword boosting."""
        # Combine results, removing duplicates by content
        combined = {}
        
        # Add dense vector search results
        for result in dense_results:
            text = result["text"]
            if text not in combined:
                combined[text] = {
                    "text": text,
                    "metadata": result["metadata"],
                    "dense_score": result["score"],
                    "sparse_score": 0.0,
                    "keyword_score": 0.0  # New score for keyword matching
                }
        
        # Add sparse (BM25) search results
        for doc in sparse_results:
            text = doc.page_content
            if text in combined:
                # Document exists in both - update sparse score
                combined[text]["sparse_score"] = doc.metadata.get("score", 0.0)
            else:
                # New document from sparse search
                combined[text] = {
                    "text": text,
                    "metadata": doc.metadata,
                    "dense_score": 0.0,
                    "sparse_score": doc.metadata.get("score", 0.0),
                    "keyword_score": 0.0  # New score for keyword matching
                }
        
        # Boost scores for exact keyword matches in metadata
        query_terms = set(query.lower().split())
        for doc_key, doc in combined.items():
            metadata = doc["metadata"]
            
            # Check for matches in heading information
            heading_score = 0.0
            for level in range(1, 7):
                heading_key = f"h{level}"
                if heading_key in metadata and metadata[heading_key]:
                    heading_text = metadata[heading_key].lower()
                    # Count how many query terms appear in the heading
                    matches = sum(1 for term in query_terms if term in heading_text)
                    # Boost score based on heading level (h1 gets highest boost)
                    heading_score += matches * (7 - level) * 0.05
            
            # Check section and subsection
            section_score = 0.0
            for key in ["section", "subsection"]:
                if key in metadata and metadata[key]:
                    section_text = metadata[key].lower()
                    matches = sum(1 for term in query_terms if term in section_text)
                    section_score += matches * 0.1
            
            # Combine heading and section scores
            doc["keyword_score"] = heading_score + section_score
        
        # Calculate final score with adjusted weights
        alpha = 0.5  # Reduce weight for dense retrieval (was 0.7)
        beta = 0.3   # Weight for sparse (BM25) retrieval
        gamma = 0.2  # Weight for keyword matching
        
        for doc in combined.values():
            dense_component = alpha * doc["dense_score"]
            sparse_component = beta * doc["sparse_score"]
            keyword_component = gamma * doc["keyword_score"]
            doc["score"] = dense_component + sparse_component + keyword_component
        
        # Sort by combined score and return top k
        results = list(combined.values())
        results.sort(key=lambda x: x["score"], reverse=True)
        
        # Return top k, removing the temporary scoring fields
        final_results = []
        for doc in results[:k]:
            final_results.append({
                "text": doc["text"],
                "metadata": doc["metadata"],
                "score": doc["score"]
            })
        
        return final_results
    
    # Implement abstract methods from SearchHelper
    def _execute_vector_search(self, query_vector: List[float], limit: int) -> List[Dict[str, Any]]:
        """Execute vector search using Qdrant client."""
        # Increase the retrieval limit to get more candidates for reranking
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit * 5  # Increased to get more candidates for reranking/filtering
        )
        
        # Format results
        documents = []
        for result in results:
            documents.append({
                "text": result.payload["text"],
                "metadata": result.payload["metadata"],
                "score": result.score
            })
        return documents[:limit]
    
    def _execute_filter_search(self, filters: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Execute filter search using Qdrant models.Filter."""
        filter_conditions = []
        for key, value in filters.items():
            filter_conditions.append(
                models.FieldCondition(
                    key=f"metadata.{key}",
                    match=models.MatchValue(value=value)
                )
            )
            
        search_filter = models.Filter(must=filter_conditions)
        
        scroll_response = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=search_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
        # Format results
        documents = []
        if scroll_response and scroll_response[0]:
            for point in scroll_response[0]:
                documents.append({
                    "text": point.payload.get("text", ""),
                    "metadata": point.payload.get("metadata", {})
                })
                
        return documents
    
    def _get_document_by_filter(self, filter_conditions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get documents by filter, combine all chunks for the specified page."""
        results = self._execute_filter_search(filter_conditions, limit=100)  # Get all chunks for the page
        
        if not results:
            return None
        
        # Combine all chunks for this page into a single text
        combined_text = ""
        metadata = {}
        image_url = None
        
        # Sort chunks by index if available
        sorted_chunks = sorted(results, key=lambda x: x["metadata"].get("chunk_index", 0))
        
        for chunk in sorted_chunks:
            combined_text += chunk["text"] + "\n\n"
            chunk_metadata = chunk["metadata"]
            
            # Use first chunk's metadata as base
            if not metadata:
                metadata = chunk_metadata
            
            # Get image URL from any chunk (should be the same for all)
            if not image_url and "image_url" in chunk_metadata:
                image_url = chunk_metadata["image_url"]
        
        return {
            "text": combined_text.strip(),
            "metadata": metadata,
            "image_url": image_url
        }
    
    def _get_all_documents_raw(self, limit: int) -> List[Dict[str, Any]]:
        """Implementation of get_all_documents for Qdrant."""
        documents = []
        offset = None
        batch_size = 100
        count = 0
        
        while count < limit:
            response_tuple = self.client.scroll(
                collection_name=self.collection_name,
                limit=min(batch_size, limit - count),
                offset=offset,
                with_vectors=False,
                with_payload=True
            )
            
            points = response_tuple[0]
            next_offset = response_tuple[1]
            
            if not points:
                break
                
            for point in points:
                documents.append({
                    "text": point.payload.get("text", ""),
                    "metadata": point.payload.get("metadata", {})
                })
                count += 1
                
            if next_offset is None or count >= limit:
                break
                
            offset = next_offset
            
        return documents
    
    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Create source/page filter for Qdrant."""
        return {
            "source": source,
            "page": page
        }
    
    # Override the search method to provide the specialized semantic hybrid search
    def search(self, query_vector: List[float], query: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Performs hybrid search: exact match -> dense search -> sparse search -> reranking."""
        logging.info(f"Searching (semantic) for: '{query}'")
        
        if not query_vector:
             logging.error("Semantic search called with an empty query vector.")
             return []
        
        # Let's use our specialized semantic search if we have a query string
        if query:
            # Get dense vector results
            dense_documents = self._execute_vector_search(query_vector, limit=limit * 3)
            
            # Get sparse lexical search results using BM25 (if available)
            sparse_documents = []
            if self.bm25_retriever:
                try:
                    sparse_results_bm25 = self.bm25_retriever.get_relevant_documents(query, k=limit * 3)
                    for i, doc in enumerate(sparse_results_bm25):
                        score = 1.0 - (i / len(sparse_results_bm25)) if sparse_results_bm25 else 0
                        doc.metadata["score"] = score
                        sparse_documents.append(doc)
                except Exception as e:
                    logging.error(f"Error during BM25 search: {e}", exc_info=True)
            
            # Perform hybrid reranking if we have both dense and sparse results
            if sparse_documents and dense_documents:
                try:
                    return self._hybrid_reranking(dense_documents, sparse_documents, query, limit)
                except Exception as e:
                    logging.error(f"Error during hybrid reranking: {e}", exc_info=True)
                    # Fallback to just the dense results
                    return dense_documents[:limit]
            
            # Just return dense results if no sparse results available
            return dense_documents[:limit]
        else:
            # Fallback to standard search if no query string provided
            return super().search(query_vector, query, limit)
    
    def get_details_by_source_page(self, source_name: str, page_number: int) -> Optional[Dict[str, Any]]:
        """Fetches and combines all text chunks for a specific source S3 key and page number."""
        try:
            search_filter = models.Filter(
                must=[
                    models.FieldCondition( 
                        key="metadata.source",
                        match=models.MatchValue(value=source_name)
                    ),
                    models.FieldCondition(
                        key="metadata.page", 
                        match=models.MatchValue(value=page_number)
                    )
                ]
            )
            
            scroll_response = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=search_filter,
                limit=100,  # Retrieve all chunks for this page
                with_payload=True,
                with_vectors=False
            )
            
            if scroll_response and scroll_response[0]:
                # Combine all chunks for this page into a single text
                points = scroll_response[0]
                combined_text = ""
                image_url = None
                total_pages = None
                
                # Sort points by chunk_index to maintain order
                sorted_points = sorted(points, key=lambda p: p.payload.get("metadata", {}).get("chunk_index", 0))
                
                for point in sorted_points:
                    payload = point.payload
                    metadata = payload.get("metadata", {})
                    combined_text += payload.get("text", "") + "\n\n"
                    
                    # Get image_url and total_pages from any chunk (should be the same for all)
                    if not image_url and "image_url" in metadata:
                        image_url = metadata["image_url"]
                    if not total_pages and "total_pages" in metadata:
                        total_pages = metadata["total_pages"]
                
                return {
                    "text": combined_text.strip(),
                    "image_url": image_url,
                    "total_pages": total_pages,
                }
            else:
                logging.warning(f"Semantic store scroll found no match for source: '{source_name}', page: {page_number}")
                return None
        except Exception as e:
            logging.error(f"Error fetching details from Semantic store for '{source_name}' page {page_number}: {e}", exc_info=True)
            return None

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Scrolls through the entire collection to retrieve all documents (payloads)."""
        documents = []
        offset = 0
        limit = 100
        
        while True:
            response_tuple = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_vectors=False,
                with_payload=True
            )
            
            batch = response_tuple[0]
            next_offset = response_tuple[1]

            if not batch:
                break
            
            for point in batch:
                documents.append({
                    "text": point.payload.get("text", ""),
                    "metadata": point.payload.get("metadata", {})
                })
            
            if next_offset is None:
                 break # Reached the end
            offset = next_offset
        
        return documents 