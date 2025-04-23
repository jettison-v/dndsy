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
        Chunks text spanning multiple pages, preserving context across boundaries 
        while ensuring metadata accurately reflects chunk content.
        
        Args:
            page_texts: List of dicts, each containing 'text', 'page', 'metadata'.
        Returns:
            List of chunks, each dict containing 'text' and updated 'metadata'.
        """
        if not page_texts:
            return []
        
        # Sort pages by page number to ensure correct order
        page_texts = sorted(page_texts, key=lambda x: x["page"])
        
        # 1. First, create a combined text document with markers for page boundaries
        combined_text = ""
        page_boundary_positions = {}  # Maps character positions to page info
        
        # 2. Store original documents and positions for later analysis
        original_documents = []
        current_position = 0
        
        for page_info in page_texts:
            # Store page boundary position
            page_boundary_positions[current_position] = page_info
            
            # Add text with a special page marker that won't interfere with chunking
            # but will help us identify page boundaries
            page_marker = f"[[PAGE:{page_info['page']}]]"
            
            # Store original document with positions
            original_documents.append({
                "start_pos": current_position,
                "text": page_info["text"],
                "page": page_info["page"],
                "metadata": page_info["metadata"],
                "page_marker": page_marker
            })
            
            # Add text to combined document
            if combined_text and not combined_text.endswith("\n\n"):
                combined_text += "\n\n"
            
            combined_text += page_marker + " " + page_info["text"]
            current_position = len(combined_text)
        
        # 3. Apply semantic chunking to the combined text
        chunks_text = self.text_splitter.split_text(combined_text)
        
        # 4. Process chunks and determine proper metadata
        processed_chunks = []
        
        for i, chunk_text in enumerate(chunks_text):
            if not chunk_text.strip():
                continue
            
            # Check which page markers are in this chunk to determine content sources
            chunk_pages = []
            primary_page = None
            primary_metadata = None
            
            # Extract page markers from the chunk
            for doc in original_documents:
                page_marker = doc["page_marker"]
                if page_marker in chunk_text:
                    chunk_pages.append(doc["page"])
                    
                    # First page marker is the primary source for metadata
                    if primary_page is None:
                        primary_page = doc["page"]
                        primary_metadata = doc["metadata"].copy()
            
            # If no page markers found (unlikely), use content analysis
            if not primary_page and chunk_text:
                # Find best matching page by content similarity
                best_match = None
                best_match_score = 0
                
                for doc in original_documents:
                    # Simple overlap score - can be improved with more sophisticated measures
                    common_text = set(chunk_text.split()) & set(doc["text"].split())
                    match_score = len(common_text)
                    
                    if match_score > best_match_score:
                        best_match_score = match_score
                        best_match = doc
                
                if best_match:
                    primary_page = best_match["page"]
                    primary_metadata = best_match["metadata"].copy()
                else:
                    # Fallback: use the first page's metadata
                    primary_page = page_texts[0]["page"]
                    primary_metadata = page_texts[0]["metadata"].copy()
            
            # Remove page markers from the final chunk text
            clean_chunk_text = chunk_text
            for doc in original_documents:
                clean_chunk_text = clean_chunk_text.replace(doc["page_marker"], "")
            clean_chunk_text = clean_chunk_text.strip()
            
            if not clean_chunk_text:
                continue
            
            # Create metadata for the chunk
            metadata = primary_metadata
            metadata["chunk_index"] = i
            metadata["chunk_count"] = len(chunks_text)
            metadata["cross_page"] = len(chunk_pages) > 1
            metadata["pages_spanned"] = chunk_pages
            
            # Ensure the metadata's page field matches the primary page
            metadata["page"] = primary_page
            
            processed_chunks.append({
                "text": clean_chunk_text,
                "metadata": metadata
            })
        
        logging.info(f"Generated {len(processed_chunks)} semantic chunks from {len(page_texts)} pages using cross-page aware chunking.")
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
             
        # Rebuild BM25 index if new docs exist
        if new_bm25_docs:
             logging.info(f"Updating BM25 retriever with {len(new_bm25_docs)} new documents...")
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
    
    def _hybrid_reranking(self, dense_results: List[Dict], sparse_results: List[Document], query: str, k: int = 5,
                      alpha: float = 0.5, beta: float = 0.3, gamma: float = 0.2):
        """
        Combines dense (vector) and sparse (BM25) results with keyword boosting.
        
        Args:
            dense_results: Results from vector search
            sparse_results: Results from BM25 search
            query: Original query string
            k: Number of results to return
            alpha: Weight for dense vector score (default 0.5)
            beta: Weight for sparse BM25 score (default 0.3)
            gamma: Weight for keyword boost score (default 0.2)
        """
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
        
        # Calculate final score using the provided weights
        # (alpha for dense, beta for sparse, gamma for keyword)
        logging.info(f"Using weights: alpha={alpha}, beta={beta}, gamma={gamma}")
        
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
    def search(self, query_vector: List[float], query: str = None, limit: int = 5, 
               rerank_alpha: float = 0.5, rerank_beta: float = 0.3, rerank_gamma: float = 0.2,
               fetch_multiplier: int = 3) -> List[Dict[str, Any]]:
        """
        Performs hybrid search: exact match -> dense search -> sparse search -> reranking.
        
        Args:
            query_vector: Embedded query vector
            query: Original query string (needed for BM25 and keyword boosting)
            limit: Number of results to return
            rerank_alpha: Weight for dense vector score in reranking
            rerank_beta: Weight for sparse BM25 score in reranking
            rerank_gamma: Weight for keyword match score in reranking  
            fetch_multiplier: Multiplier for initial retrieval before reranking
        """
        logging.info(f"Searching (semantic) for: '{query}'")
        
        if not query_vector:
             logging.error("Semantic search called with an empty query vector.")
             return []
        
        # Let's use our specialized semantic search if we have a query string
        if query:
            # Get dense vector results
            dense_documents = self._execute_vector_search(query_vector, limit=limit * fetch_multiplier)
            
            # Get sparse lexical search results using BM25 (if available)
            sparse_documents = []
            if self.bm25_retriever:
                try:
                    sparse_results_bm25 = self.bm25_retriever.get_relevant_documents(query, k=limit * fetch_multiplier)
                    for i, doc in enumerate(sparse_results_bm25):
                        score = 1.0 - (i / len(sparse_results_bm25)) if sparse_results_bm25 else 0
                        doc.metadata["score"] = score
                        sparse_documents.append(doc)
                except Exception as e:
                    logging.error(f"Error during BM25 search: {e}", exc_info=True)
            
            # Perform hybrid reranking if we have both dense and sparse results
            if sparse_documents and dense_documents:
                try:
                    return self._hybrid_reranking(
                        dense_documents, 
                        sparse_documents, 
                        query, 
                        limit,
                        alpha=rerank_alpha,
                        beta=rerank_beta,
                        gamma=rerank_gamma
                    )
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
            # Create a filter for the exact page
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
                # No chunks found for this page, try to determine if the page exists in the document
                logging.warning(f"Semantic store: No chunks found for source: '{source_name}', page: {page_number}")
                
                # Check if the document exists by looking for any page from this source
                source_filter = models.Filter(
                    must=[
                        models.FieldCondition( 
                            key="metadata.source",
                            match=models.MatchValue(value=source_name)
                        )
                    ]
                )
                
                # Get a sample of chunks from this document to find metadata
                doc_response = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=source_filter,
                    limit=100,
                    with_payload=True,
                    with_vectors=False
                )
                
                if doc_response and doc_response[0]:
                    # Document exists but this specific page might not have chunks
                    # Get image_url and total_pages from any chunk
                    sample_points = doc_response[0]
                    image_url = None
                    total_pages = None
                    existing_pages = set()
                    
                    for point in sample_points:
                        metadata = point.payload.get("metadata", {})
                        page = metadata.get("page")
                        if page is not None:
                            existing_pages.add(page)
                        
                        if not image_url and "image_url" in metadata:
                            base_url = metadata["image_url"]
                            # Extract base URL up to the page number
                            if base_url and isinstance(base_url, str):
                                image_url_parts = base_url.rsplit('/', 1)
                                if len(image_url_parts) > 1:
                                    # Construct URL for the requested page
                                    image_url = f"{image_url_parts[0]}/{page_number}.png"
                        
                        if not total_pages and "total_pages" in metadata:
                            total_pages = metadata["total_pages"]
                    
                    # Get closest page with content
                    if existing_pages:
                        closest_page = min(existing_pages, key=lambda x: abs(x - page_number))
                        logging.info(f"Page {page_number} not found, closest page with content is {closest_page}")
                        
                        # Return a placeholder with available metadata
                        # This allows navigation to work even if specific page chunks are missing
                        return {
                            "text": f"This page ({page_number}) does not have semantic chunks available. Try using the 'Page Context' view or navigate to nearby pages.",
                            "image_url": image_url,
                            "total_pages": total_pages,
                            "closest_page": closest_page
                        }
                
                # Document doesn't exist or no useful metadata found
                logging.warning(f"Semantic store found no match for source: '{source_name}', page: {page_number}")
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

    def clear_store(self, client: QdrantClient = None):
        """Deletes the entire Qdrant collection associated with this store."""
        q_client = client if client else self.client
        if not q_client:
            logging.error(f"Qdrant client not available for clearing collection {self.collection_name}")
            return

        try:
            logging.info(f"Attempting to delete Qdrant collection: {self.collection_name}")
            q_client.delete_collection(collection_name=self.collection_name)
            logging.info(f"Successfully deleted Qdrant collection: {self.collection_name}")
            # Reset internal state after clearing
            self.next_id = 0
            self.bm25_documents = []
            self.bm25_retriever = None
            # Immediately recreate the collection after deletion
            logging.info(f"Recreating collection {self.collection_name}...")
            self._create_collection_if_not_exists(SEMANTIC_EMBEDDING_DIMENSION)
        except Exception as e:
            logging.warning(f"Could not delete Qdrant collection '{self.collection_name}': {e}")
            
    def validate_metadata_alignment(self, sample_size=5):
        """
        Validates a sample of chunks to ensure metadata matches content.
        
        Args:
            sample_size: Number of chunks to sample for validation
            
        Returns:
            Boolean indicating if validation passed
        """
        # Get all documents
        try:
            all_docs = self._get_all_documents_raw(limit=1000)
            logging.info(f"Retrieved {len(all_docs)} documents for validation sampling")
            
            if not all_docs:
                logging.warning("No documents found for validation")
                return False
                
            # Select random sample
            import random
            import re
            sample_docs = random.sample(all_docs, min(sample_size, len(all_docs)))
            logging.info(f"Validating {len(sample_docs)} random chunks")
            
            valid_count = 0
            issues_count = 0
            
            for doc in sample_docs:
                text = doc["text"]
                metadata = doc["metadata"]
                
                # Check for page number reference patterns in text
                page_patterns = [
                    r"Page (\d+)",
                    r"Pg\.? (\d+)",
                    r"p\.? (\d+)"
                ]
                
                metadata_page = metadata.get("page")
                pages_mentioned = []
                
                # Extract potential page numbers mentioned in text
                for pattern in page_patterns:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        try:
                            page_num = int(match.group(1))
                            pages_mentioned.append(page_num)
                        except (ValueError, IndexError):
                            pass
                
                # Check heading path in metadata
                metadata_headings = metadata.get("heading_path", "")
                if isinstance(metadata_headings, list):
                    metadata_headings = " > ".join(metadata_headings)
                
                # Basic validation logic
                valid = True
                
                # Check if page mentions align with metadata
                if pages_mentioned and metadata_page not in pages_mentioned:
                    valid = False
                    logging.warning(f"Page mismatch - Metadata: {metadata_page}, Mentioned: {pages_mentioned}")
                    logging.warning(f"Text excerpt: {text[:100]}...")
                
                # Check if headings are relevant to content
                heading_words = set(re.findall(r'\b\w+\b', metadata_headings.lower()))
                significant_words = set(word.lower() for word in re.findall(r'\b[A-Za-z]{4,}\b', text))
                
                # Calculate content descriptor overlap
                if heading_words and significant_words:
                    overlap = heading_words.intersection(significant_words)
                    if not overlap and len(heading_words) > 1:
                        logging.warning(f"Heading doesn't match content - Heading: {metadata_headings}")
                        logging.warning(f"Text excerpt: {text[:100]}...")
                        valid = False
                
                if valid:
                    valid_count += 1
                else:
                    issues_count += 1
                    
            logging.info(f"Validation complete: {valid_count}/{len(sample_docs)} chunks valid")
            return issues_count == 0
            
        except Exception as e:
            logging.error(f"Error during validation: {e}")
            return False
    
    def test_semantic_search(self, test_queries=None):
        """Tests the semantic store with sample queries to ensure it's working properly"""
        from llm import embed_query
        
        if test_queries is None:
            test_queries = [
                "How does Circle of the Moon druid wild shape work?",
                "What are the rules for spell components?",
                "Explain the rogue's sneak attack feature"
            ]
        
        success = True
        
        for query in test_queries:
            try:
                # Embed the query
                query_vector = embed_query(query, "semantic")
                
                # Search for results
                results = self.search(query_vector=query_vector, query=query, limit=3)
                
                if results:
                    logging.info(f"Query '{query}' returned {len(results)} results")
                    top_result = results[0]
                    logging.info(f"Top result from: {top_result['metadata'].get('source')} (page {top_result['metadata'].get('page')})")
                    
                    # Check if top result has required metadata
                    required_keys = ["page", "source", "heading_path"]
                    for key in required_keys:
                        if key not in top_result['metadata']:
                            logging.warning(f"Missing required metadata key '{key}' in search result")
                            success = False
                else:
                    logging.warning(f"Query '{query}' returned no results")
                    success = False
                    
            except Exception as e:
                logging.error(f"Error testing query '{query}': {e}")
                success = False
        
        return success 