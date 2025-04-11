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
# Add back OpenAIEmbeddings import - needed for ingestion currently
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Qdrant as LangChainQdrant
from langchain_community.retrievers import BM25Retriever
from langchain.schema import Document
import numpy as np
# Remove SentenceTransformer import - no longer used here
# from sentence_transformers import SentenceTransformer, util

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define embedding size for semantic model ("text-embedding-3-small")
SEMANTIC_EMBEDDING_DIMENSION = 1536

class SemanticStore:
    """A more semantic approach to vector storage using improved chunking and embeddings."""
    
    def __init__(self, collection_name: str = "dnd_semantic"):
        """Initialize Semantic vector store using a separate Qdrant collection."""
        self.collection_name = collection_name
        
        # Determine if OpenAI API key is available (used for ingestion embeddings)
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if self.openai_api_key:
            self._embeddings_for_ingestion = OpenAIEmbeddings(
                 model="text-embedding-3-small",
                 openai_api_key=self.openai_api_key
            )
            logging.info("Using OpenAI embeddings during ingestion (TEMPORARY)")
        else:
             self._embeddings_for_ingestion = None
             logging.warning("OPENAI_API_KEY not found. Semantic ingestion requires OpenAI embeddings (currently handled internally).")

        # Embedding dimension is now fixed for the collection
        embedding_dim = SEMANTIC_EMBEDDING_DIMENSION
        
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
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> int:
        """(DEPRECATED - Use chunk_document and add_points) Add documents with internal embedding."""
        logging.warning("Calling deprecated SemanticStore.add_documents with internal embedding.")
        if not self._embeddings_for_ingestion:
             raise RuntimeError("Semantic ingestion requires OpenAI API key for deprecated internal embedding.")
        # Reset BM25 documents and retriever since we're adding new content
        self.bm25_documents = []
        points = []
        doc_id_counter = self.next_id
        total_chunks = 0
        embedding_count = 0
        start_time = datetime.now()
        logging.info(f"[{start_time.strftime('%H:%M:%S')}] Starting semantic processing of {len(documents)} documents")
        for doc in documents:
            original_text = doc["text"]
            metadata = doc["metadata"].copy()
            chunks = self.text_splitter.split_text(original_text)
            total_chunks += len(chunks)
            for i, chunk_text in enumerate(chunks):
                if not chunk_text.strip(): continue
                chunk_metadata = metadata.copy()
                chunk_metadata["chunk_index"] = i
                chunk_metadata["chunk_count"] = len(chunks)
                embedding = self._embeddings_for_ingestion.embed_query(chunk_text)
                embedding_count += 1
                if embedding_count % 50 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Processed {embedding_count}/{total_chunks} embeddings ({(embedding_count/total_chunks*100):.1f}%) - {elapsed:.1f} seconds elapsed")
                point = models.PointStruct(
                    id=doc_id_counter,
                    vector=embedding,
                    payload={"text": chunk_text, "metadata": chunk_metadata}
                )
                points.append(point)
                self.bm25_documents.append(Document(page_content=chunk_text, metadata=chunk_metadata))
                doc_id_counter += 1
        self.next_id = doc_id_counter
        if self.bm25_documents:
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Initializing BM25 retriever with {len(self.bm25_documents)} documents")
            self.bm25_retriever = BM25Retriever.from_documents(self.bm25_documents)
            logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] BM25 retriever initialization complete")
        batch_size = 100
        batch_count = (len(points) + batch_size - 1) // batch_size
        logging.info(f"[{datetime.now().strftime('%H:%M:%S')}] Uploading {len(points)} embeddings to Qdrant in {batch_count} batches")
        for i in range(0, len(points), batch_size):
            batch_num = i // batch_size + 1
            batch = points[i:i + batch_size]
            batch_start = datetime.now()
            logging.info(f"[{batch_start.strftime('%H:%M:%S')}] Uploading batch {batch_num}/{batch_count} ({len(batch)} points)")
            self.client.upsert(collection_name=self.collection_name, points=batch)
            batch_end = datetime.now()
            batch_duration = (batch_end - batch_start).total_seconds()
            logging.info(f"[{batch_end.strftime('%H:%M:%S')}] Batch {batch_num}/{batch_count} complete in {batch_duration:.1f} seconds")
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        logging.info(f"[{end_time.strftime('%H:%M:%S')}] Semantic processing complete - {total_duration:.1f} seconds total")
        logging.info(f"Added {len(points)} semantic chunks from {len(documents)} original documents")
        return len(points)
    
    def chunk_document_with_cross_page_context(
        self, 
        page_texts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Chunks a document spanning multiple pages, preserving context across boundaries.
        Returns a list of chunks, each with its text and metadata (including page origin).
        Does NOT perform embedding or Qdrant upload.
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
        """Adds pre-constructed points (with vectors) to the semantic collection."""
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
    
    def search(self, query_vector: List[float], query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents using hybrid search (dense + sparse retrieval).
           Accepts a pre-computed query_vector for dense search.
           Still needs the original query string for BM25 and keyword boosting.
        """
        logging.info(f"Searching (semantic) for: '{query}'")
        
        if not query_vector:
             logging.error("Semantic search called with an empty query vector.")
             return []
             
        query_normalized = query.lower().strip()
        
        # --- Exact/Partial Heading Match (Unchanged) ---
        try:
            # Get all documents first
            all_documents = self.get_all_documents()
            exact_matches = []
            partial_matches = []
            
            # Extract query words for partial matching
            query_words = set(query_normalized.split())
            stopwords = {'the', 'of', 'and', 'a', 'to', 'in', 'that', 'it', 'with', 'for', 'as', 'on', 'at', 'by', 'from'}
            important_words = query_words - stopwords
            
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
                            heading_words = set(heading_text.split())
                            match_percentage = len(query_words) / len(heading_words) if heading_words else 0
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
                        if section_text == query_normalized:
                            exact_matches.append({
                                "text": doc["text"],
                                "metadata": metadata,
                                "score": 1.0,
                                "match_type": f"exact_{key}"
                            })
                            logging.info(f"Found exact {key} match: {metadata[key]}")
                        elif query_words and all(word in section_text for word in query_words):
                            section_words = set(section_text.split())
                            match_percentage = len(query_words) / len(section_words) if section_words else 0
                            if match_percentage >= 0.5:
                                partial_matches.append({
                                    "text": doc["text"],
                                    "metadata": metadata,
                                    "score": 0.9,
                                    "match_type": f"partial_{key}",
                                    "match_percentage": match_percentage
                                })
                                logging.info(f"Found partial {key} match: {metadata[key]} ({match_percentage:.2f})")
            
            # Combine and prioritize matches
            all_matches = exact_matches + partial_matches
            if all_matches:
                logging.info(f"Found {len(exact_matches)} exact matches and {len(partial_matches)} partial matches for '{query}'")
                all_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
                unique_matches = {}
                for match in all_matches:
                    if match["text"] not in unique_matches:
                        unique_matches[match["text"]] = match
                return list(unique_matches.values())[:limit]
                
        except Exception as e:
            logging.error(f"Error in heading match search: {e}", exc_info=True)
        
        # --- Normal Hybrid Search --- 
        query_terms = set(query_normalized.split())
        important_terms = query_terms - stopwords
        
        # Dense vector search (Uses pre-computed query_vector)
        # query_vector = self._get_embedding(query) # Removed
        
        dense_documents = []
        try:
            # Increase the retrieval limit to get more candidates for reranking
            dense_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit * 5  # Increased to get more candidates before filtering
            )
            
            # Format dense results with keyword filtering
            filtered_out = 0
            for result in dense_results:
                text = result.payload["text"].lower()
                metadata = result.payload["metadata"]
                
                # Apply filtering if the query has important terms
                if len(important_terms) > 0 and len(query_terms) <= 5:
                    term_found = any(term in text for term in important_terms)
                    if not term_found:
                        for key in ["section", "subsection", "heading_path"]:
                            if key in metadata and metadata[key] and any(term in metadata[key].lower() for term in important_terms):
                                term_found = True
                                break
                        if not term_found:
                             for i in range(1, 7):
                                heading_key = f"h{i}"
                                if heading_key in metadata and metadata[heading_key] and any(term in metadata[heading_key].lower() for term in important_terms):
                                    term_found = True
                                    break
                    if not term_found:
                        filtered_out += 1
                        continue
                
                dense_documents.append({
                    "text": result.payload["text"],
                    "metadata": metadata,
                    "score": result.score
                })
            
            if filtered_out > 0:
                logging.info(f"Filtered out {filtered_out} dense results that didn't contain any query terms")
        
        except Exception as e:
            logging.error(f"Error during dense search in semantic store: {e}", exc_info=True)
            dense_documents = [] # Ensure it's empty on error
            
        # Sparse lexical search using BM25 (Requires original query string)
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
                 sparse_documents = []
        else:
             # Attempt to initialize BM25 if not already done
             try:
                logging.info("BM25 retriever not initialized. Attempting lazy initialization...")
                all_docs_payload = self.get_all_documents()
                if all_docs_payload:
                    langchain_docs = [Document(page_content=doc["text"], metadata=doc["metadata"]) for doc in all_docs_payload]
                    self.bm25_retriever = BM25Retriever.from_documents(langchain_docs)
                    logging.info(f"Initialized BM25 retriever with {len(langchain_docs)} documents")
                    # Retry BM25 search
                    sparse_results_bm25 = self.bm25_retriever.get_relevant_documents(query, k=limit * 3)
                    for i, doc in enumerate(sparse_results_bm25):
                        score = 1.0 - (i / len(sparse_results_bm25)) if sparse_results_bm25 else 0
                        doc.metadata["score"] = score
                        sparse_documents.append(doc)
             except Exception as e:
                logging.error(f"Failed to initialize BM25 retriever on demand: {e}")
                sparse_documents = []
        
        # Perform hybrid reranking if possible
        if sparse_documents and dense_documents:
            try:
                return self._hybrid_reranking(dense_documents, sparse_documents, query, limit)
            except Exception as e:
                logging.error(f"Error during hybrid reranking: {e}", exc_info=True)
                # Fallback to dense results if reranking fails
                return dense_documents[:limit]
        
        # Otherwise return just the filtered dense results
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