import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
import logging
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

# LangChain imports for improved semantic search
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Qdrant as LangChainQdrant
from langchain_community.retrievers import BM25Retriever
from langchain.schema import Document
import numpy as np
from sentence_transformers import SentenceTransformer, util

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class SemanticStore:
    """A more semantic approach to vector storage using improved chunking and embeddings."""
    
    def __init__(self, collection_name: str = "dnd_semantic"):
        """Initialize Semantic vector store using a separate Qdrant collection."""
        self.collection_name = collection_name
        
        # Determine which embedding model to use based on environment
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            # Use OpenAI's text embeddings if API key is available
            self.use_openai = True
            self.embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                openai_api_key=openai_api_key
            )
            embedding_dim = 1536  # OpenAI's embedding dimension
            logging.info("Using OpenAI embeddings for semantic search")
        else:
            # Fallback to sentence-transformers (local model)
            self.use_openai = False
            # Using a better model for semantic search than the previous one
            self.model = SentenceTransformer('all-MiniLM-L6-v2')
            embedding_dim = self.model.get_sentence_embedding_dimension()
            logging.info("Using sentence-transformers embeddings for semantic search")
        
        # Initialize Qdrant client for local or cloud (reusing config from main store)
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        
        # Determine if it's a cloud URL
        is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")

        if is_cloud:
            logging.info(f"Connecting to Qdrant Cloud at: {qdrant_host} for semantic store")
            self.client = QdrantClient(
                url=qdrant_host, 
                api_key=qdrant_api_key, 
                timeout=60
            )
        else:
            logging.info(f"Connecting to local Qdrant at: {qdrant_host} for semantic store")
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = QdrantClient(host=qdrant_host, port=port, timeout=60)
        
        # Initialize text splitter for semantic chunking
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=150,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        # Create collection if it doesn't exist
        self._create_collection_if_not_exists(embedding_dim)
        
        # Initialize BM25 retriever for hybrid search
        self.bm25_documents = []
        self.bm25_retriever = None
        
        # Track the highest ID used so far to avoid overwriting points
        try:
            collection_info = self.client.get_collection(self.collection_name)
            collection_count = self.client.count(self.collection_name).count
            self.next_id = collection_count  # Start from the next available ID
            logging.info(f"Initialized Semantic store with collection: {self.collection_name}")
            logging.info(f"Starting from ID: {self.next_id} for new documents")
        except Exception as e:
            logging.warning(f"Error getting collection info: {e}")
            self.next_id = 0
        
        logging.info(f"Initialized Semantic store with collection: {collection_name}")
    
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
    
    def _get_embedding(self, text):
        """Generate embedding based on the configured method."""
        if self.use_openai:
            # OpenAI embeddings through LangChain
            return self.embeddings.embed_query(text)
        else:
            # Local sentence-transformers
            return self.model.encode(text).tolist()
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add documents to the vector store using semantic chunking."""
        if not documents:
            return
        
        # Reset BM25 documents and retriever since we're adding new content
        self.bm25_documents = []
        
        # Prepare points for batch insertion
        points = []
        doc_id_counter = self.next_id  # Start from the next available ID
        total_chunks = 0
        embedding_count = 0
        start_time = datetime.now()
        
        logging.info(f"[{start_time.strftime('%H:%M:%S')}] Starting semantic processing of {len(documents)} documents")
        
        for doc in documents:
            original_text = doc["text"]
            metadata = doc["metadata"].copy()
            
            # Use LangChain's recursive text splitter for better chunking
            # This creates semantically meaningful chunks with context preservation
            chunks = self.text_splitter.split_text(original_text)
            total_chunks += len(chunks)
            
            for i, chunk_text in enumerate(chunks):
                # Skip empty chunks
                if not chunk_text.strip():
                    continue
                
                # Update metadata with chunk info
                chunk_metadata = metadata.copy()
                chunk_metadata["chunk_index"] = i
                chunk_metadata["chunk_count"] = len(chunks)
                
                # Generate embedding
                embedding = self._get_embedding(chunk_text)
                embedding_count += 1
                
                if embedding_count % 50 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {embedding_count}/{total_chunks} embeddings ({(embedding_count/total_chunks*100):.1f}%) - {elapsed:.1f} seconds elapsed")
                
                # Create point for Qdrant
                point = models.PointStruct(
                    id=doc_id_counter,
                    vector=embedding,
                    payload={
                        "text": chunk_text,
                        "metadata": chunk_metadata
                    }
                )
                points.append(point)
                
                # Also add to BM25 documents for hybrid search
                self.bm25_documents.append(
                    Document(
                        page_content=chunk_text,
                        metadata=chunk_metadata
                    )
                )
                
                doc_id_counter += 1
        
        # Update the next_id for future additions
        self.next_id = doc_id_counter
        
        # Initialize BM25 retriever with the documents
        if self.bm25_documents:
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing BM25 retriever with {len(self.bm25_documents)} documents")
            self.bm25_retriever = BM25Retriever.from_documents(
                self.bm25_documents
            )
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] BM25 retriever initialization complete")
        
        # Insert points in batches
        batch_size = 100
        batch_count = (len(points) + batch_size - 1) // batch_size  # Ceiling division
        
        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Uploading {len(points)} embeddings to Qdrant in {batch_count} batches")
        
        for i in range(0, len(points), batch_size):
            batch_num = i // batch_size + 1
            batch = points[i:i + batch_size]
            batch_start = datetime.now()
            
            logging.info(f"[{batch_start.strftime('%H:%M:%S')}] Uploading batch {batch_num}/{batch_count} ({len(batch)} points)")
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch
            )
            
            batch_end = datetime.now()
            batch_duration = (batch_end - batch_start).total_seconds()
            logging.info(f"[{batch_end.strftime('%H:%M:%S')}] Batch {batch_num}/{batch_count} complete in {batch_duration:.1f} seconds")
        
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        logging.info(f"[{end_time.strftime('%H:%M:%S')}] Semantic processing complete - {total_duration:.1f} seconds total")
        logging.info(f"Added {len(points)} semantic chunks from {len(documents)} original documents")
    
    def add_document_with_cross_page_chunking(self, page_texts: List[Dict[str, Any]]) -> None:
        """
        Add a document with cross-page chunking for semantic processing.
        
        This method combines text from multiple pages, applies semantic chunking
        across page boundaries, but maintains page attribution by tracking which 
        chunk starts on which page.
        
        Args:
            page_texts: List of dictionaries containing page text and metadata,
                       with each dictionary representing a single page.
        """
        if not page_texts:
            return
        
        # Sort pages by page number to ensure correct order
        page_texts = sorted(page_texts, key=lambda x: x["page"])
        
        # Combine text with page markers
        combined_text = ""
        page_markers = {}  # Map character positions to page numbers
        
        for page_info in page_texts:
            page_num = page_info["page"]
            page_text = page_info["text"]
            
            # Mark the starting position of this page's text
            start_pos = len(combined_text)
            page_markers[start_pos] = page_info
            
            # Add page text with a separator
            combined_text += page_text
            
            # Add a newline separator between pages (optional)
            if not combined_text.endswith("\n\n"):
                combined_text += "\n\n"
        
        # Apply semantic chunking to the combined text
        chunks = self.text_splitter.split_text(combined_text)
        
        # Initialize for batch insertion
        points = []
        doc_id_counter = self.next_id
        total_chunks = len(chunks)
        embedding_count = 0
        start_time = datetime.now()
        
        # Reset BM25 documents for this new content
        self.bm25_documents = []
        
        logging.info(f"[{start_time.strftime('%H:%M:%S')}] Starting cross-page semantic processing with {total_chunks} chunks")
        
        # Find which page each chunk belongs to based on its position in the original text
        chunk_start_pos = 0
        for i, chunk_text in enumerate(chunks):
            if not chunk_text.strip():
                continue
                
            # Find which page this chunk starts on
            page_info = None
            nearest_page_pos = 0
            
            for pos, marker in page_markers.items():
                if pos <= chunk_start_pos and pos >= nearest_page_pos:
                    nearest_page_pos = pos
                    page_info = marker
            
            if not page_info:
                logging.warning(f"Could not determine source page for chunk {i}, using first page")
                page_info = page_texts[0]
            
            # Use metadata from the page where this chunk starts
            metadata = page_info["metadata"].copy()
            
            # Update metadata with chunk info
            metadata["chunk_index"] = i
            metadata["chunk_count"] = total_chunks
            metadata["cross_page"] = True
            
            # Generate embedding
            embedding = self._get_embedding(chunk_text)
            embedding_count += 1
            
            if embedding_count % 50 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {embedding_count}/{total_chunks} embeddings ({(embedding_count/total_chunks*100):.1f}%) - {elapsed:.1f} seconds elapsed")
            
            # Create point for Qdrant
            point = models.PointStruct(
                id=doc_id_counter,
                vector=embedding,
                payload={
                    "text": chunk_text,
                    "metadata": metadata
                }
            )
            points.append(point)
            
            # Also add to BM25 documents for hybrid search
            self.bm25_documents.append(
                Document(
                    page_content=chunk_text,
                    metadata=metadata
                )
            )
            
            # Update for next chunk
            chunk_start_pos += len(chunk_text)
            doc_id_counter += 1
        
        # Update the next_id for future additions
        self.next_id = doc_id_counter
        
        # Initialize BM25 retriever with the documents
        if self.bm25_documents:
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing BM25 retriever with {len(self.bm25_documents)} documents")
            self.bm25_retriever = BM25Retriever.from_documents(
                self.bm25_documents
            )
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] BM25 retriever initialization complete")
        
        # Insert points in batches
        batch_size = 100
        batch_count = (len(points) + batch_size - 1) // batch_size  # Ceiling division
        
        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Uploading {len(points)} cross-page embeddings to Qdrant in {batch_count} batches")
        
        for i in range(0, len(points), batch_size):
            batch_num = i // batch_size + 1
            batch = points[i:i + batch_size]
            batch_start = datetime.now()
            
            logging.info(f"[{batch_start.strftime('%H:%M:%S')}] Uploading batch {batch_num}/{batch_count} ({len(batch)} points)")
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch
            )
            
            batch_end = datetime.now()
            batch_duration = (batch_end - batch_start).total_seconds()
            logging.info(f"[{batch_end.strftime('%H:%M:%S')}] Batch {batch_num}/{batch_count} complete in {batch_duration:.1f} seconds")
        
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        logging.info(f"[{end_time.strftime('%H:%M:%S')}] Cross-page semantic processing complete - {total_duration:.1f} seconds total")
        logging.info(f"Added {len(points)} semantic chunks from {len(page_texts)} pages with cross-page chunking")
    
    def _hybrid_reranking(self, dense_results, sparse_results, query, k=5):
        """Combine and rerank results from dense and sparse retrievers."""
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
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents using hybrid search (dense + sparse retrieval)."""
        logging.info(f"Searching for: '{query}'")
        
        # First, try direct exact match against section headings
        # This addresses specific cases like "Circle of the Moon" where we want exact matches
        query_normalized = query.lower().strip()
        try:
            # Get all documents first
            all_documents = self.get_all_documents()
            exact_matches = []
            partial_matches = []
            
            # Extract query words for partial matching
            query_words = set(query_normalized.split())
            important_words = query_words.copy()
            # Filter out common words/stopwords for the important word check
            stopwords = {'the', 'of', 'and', 'a', 'to', 'in', 'that', 'it', 'with', 'for', 'as', 'on', 'at', 'by', 'from'}
            important_words = important_words - stopwords
            
            for doc in all_documents:
                metadata = doc.get("metadata", {})
                
                # Check headings
                for i in range(1, 7):
                    heading_key = f"h{i}"
                    if heading_key in metadata and metadata[heading_key]:
                        heading_text = metadata[heading_key].lower().strip()
                        
                        # Check for exact title match
                        if heading_text == query_normalized:
                            exact_matches.append({
                                "text": doc["text"],
                                "metadata": metadata,
                                "score": 1.0,  # Maximum score for exact matches
                                "match_type": "exact_heading"
                            })
                            logging.info(f"Found exact heading match: {metadata[heading_key]}")
                        
                        # Check for strong partial match (all query words present)
                        elif query_words and all(word in heading_text for word in query_words):
                            # Calculate match quality based on how much of the heading is matched
                            heading_words = set(heading_text.split())
                            match_percentage = len(query_words) / len(heading_words) if heading_words else 0
                            
                            # Strong match if the query words cover at least 75% of heading words
                            if match_percentage >= 0.75:
                                partial_matches.append({
                                    "text": doc["text"],
                                    "metadata": metadata,
                                    "score": 0.95,  # High score for complete partial matches
                                    "match_type": "strong_partial_heading",
                                    "match_percentage": match_percentage
                                })
                                logging.info(f"Found strong partial heading match: {metadata[heading_key]} ({match_percentage:.2f})")
                
                # Check section and subsection
                for key in ["section", "subsection", "heading_path"]:
                    if key in metadata and metadata[key]:
                        section_text = metadata[key].lower().strip()
                        
                        # Exact section match
                        if section_text == query_normalized:
                            exact_matches.append({
                                "text": doc["text"],
                                "metadata": metadata,
                                "score": 1.0,  # Maximum score for exact matches
                                "match_type": f"exact_{key}"
                            })
                            logging.info(f"Found exact {key} match: {metadata[key]}")
                        
                        # Partial section match (especially for heading paths which can be longer)
                        elif query_words and all(word in section_text for word in query_words):
                            section_words = set(section_text.split())
                            match_percentage = len(query_words) / len(section_words) if section_words else 0
                            
                            if match_percentage >= 0.5:  # Lower threshold for sections/paths which can be longer
                                partial_matches.append({
                                    "text": doc["text"],
                                    "metadata": metadata,
                                    "score": 0.9,  # Good score for partial section matches
                                    "match_type": f"partial_{key}",
                                    "match_percentage": match_percentage
                                })
                                logging.info(f"Found partial {key} match: {metadata[key]} ({match_percentage:.2f})")
            
            # Combine and prioritize matches
            all_matches = exact_matches + partial_matches
            if all_matches:
                logging.info(f"Found {len(exact_matches)} exact matches and {len(partial_matches)} partial matches for '{query}'")
                
                # Sort by score (highest first)
                all_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
                
                # Deduplicate by text content
                unique_matches = {}
                for match in all_matches:
                    if match["text"] not in unique_matches:
                        unique_matches[match["text"]] = match
                
                return list(unique_matches.values())[:limit]
                
        except Exception as e:
            logging.error(f"Error in heading match search: {e}", exc_info=True)
            # Continue with regular search if exact match fails
        
        # If no exact/partial matches or exception, continue with normal search
        # Extract important query terms for filtering
        query_terms = set(query_normalized.split())
        important_terms = query_terms - {'the', 'of', 'and', 'a', 'to', 'in', 'that', 'it', 'with', 'for', 'as', 'on', 'at', 'by', 'from'}
        
        # Dense vector search
        query_vector = self._get_embedding(query)
        
        # Increase the retrieval limit to get more candidates for reranking
        dense_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit * 5  # Increased to get more candidates before filtering
        )
        
        # Format dense results with keyword filtering
        dense_documents = []
        filtered_out = 0
        for result in dense_results:
            text = result.payload["text"].lower()
            metadata = result.payload["metadata"]
            
            # For class/subclass searches, strictly require term presence
            # Only apply filtering if the query has important terms and seems to be a specific search
            if len(important_terms) > 0 and len(query_terms) <= 5:
                # Check if any important term is present in text or metadata fields
                term_found = any(term in text for term in important_terms)
                
                # Also check in metadata fields like headings and sections
                if not term_found:
                    for key in ["section", "subsection", "heading_path"]:
                        if key in metadata and metadata[key]:
                            if any(term in metadata[key].lower() for term in important_terms):
                                term_found = True
                                break
                    
                    for i in range(1, 7):
                        heading_key = f"h{i}"
                        if heading_key in metadata and metadata[heading_key]:
                            if any(term in metadata[heading_key].lower() for term in important_terms):
                                term_found = True
                                break
                
                # Skip results that don't contain any important query terms
                if not term_found:
                    filtered_out += 1
                    continue
            
            dense_documents.append({
                "text": result.payload["text"],
                "metadata": metadata,
                "score": result.score
            })
        
        if filtered_out > 0:
            logging.info(f"Filtered out {filtered_out} results that didn't contain any query terms")
        
        # Sparse lexical search using BM25 (if available)
        sparse_documents = []
        if self.bm25_retriever:
            # Get more BM25 results for better coverage
            sparse_documents = self.bm25_retriever.get_relevant_documents(query, k=limit * 3)
            # Add score to metadata for hybrid reranking
            for i, doc in enumerate(sparse_documents):
                # Normalize scores (higher is better, decreasing with index)
                score = 1.0 - (i / len(sparse_documents)) if sparse_documents else 0
                doc.metadata["score"] = score
        
        # If we have both types of results, use hybrid reranking
        if sparse_documents and dense_documents:
            return self._hybrid_reranking(dense_documents, sparse_documents, query, limit)
        
        # If BM25 retriever is not available, initialize it with existing documents
        elif not self.bm25_retriever and not sparse_documents:
            try:
                # Try to initialize BM25 with existing documents
                logging.info("BM25 retriever not initialized. Attempting to initialize with existing documents...")
                all_docs = self.get_all_documents()
                if all_docs:
                    langchain_docs = []
                    for doc in all_docs:
                        metadata = doc["metadata"].copy()
                        langchain_docs.append(Document(
                            page_content=doc["text"],
                            metadata=metadata
                        ))
                    
                    self.bm25_retriever = BM25Retriever.from_documents(langchain_docs)
                    logging.info(f"Initialized BM25 retriever with {len(langchain_docs)} documents")
                    
                    # Try again with the newly initialized BM25 retriever
                    sparse_documents = self.bm25_retriever.get_relevant_documents(query, k=limit * 3)
                    for i, doc in enumerate(sparse_documents):
                        score = 1.0 - (i / len(sparse_documents)) if sparse_documents else 0
                        doc.metadata["score"] = score
                    
                    return self._hybrid_reranking(dense_documents, sparse_documents, query, limit)
            except Exception as e:
                logging.error(f"Failed to initialize BM25 retriever: {e}")
        
        # Otherwise return just the dense results
        return dense_documents[:limit]
    
    def get_details_by_source_page(self, source_name: str, page_number: int) -> Optional[Dict[str, Any]]:
        """Fetch details (text, image_url) for a specific source document and page."""
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
        """Get all documents from the vector store."""
        documents = []
        offset = 0
        limit = 100
        
        while True:
            batch = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_vectors=False
            )[0]
            
            if not batch:
                break
            
            for point in batch:
                documents.append({
                    "text": point.payload["text"],
                    "metadata": point.payload["metadata"]
                })
            
            offset += limit
        
        return documents 