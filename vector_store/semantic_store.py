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
                    "sparse_score": 0.0
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
                    "sparse_score": doc.metadata.get("score", 0.0)
                }
        
        # Calculate final score (weighted combination)
        alpha = 0.7  # Weight for dense retrieval (can be tuned)
        for doc in combined.values():
            doc["score"] = (alpha * doc["dense_score"]) + ((1 - alpha) * doc["sparse_score"])
        
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
        # Dense vector search
        query_vector = self._get_embedding(query)
        
        dense_results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit * 2  # Get more results for reranking
        )
        
        # Format dense results
        dense_documents = []
        for result in dense_results:
            dense_documents.append({
                "text": result.payload["text"],
                "metadata": result.payload["metadata"],
                "score": result.score
            })
        
        # Sparse lexical search using BM25 (if available)
        sparse_documents = []
        if self.bm25_retriever:
            sparse_documents = self.bm25_retriever.get_relevant_documents(query)
            # Add score to metadata for hybrid reranking
            for i, doc in enumerate(sparse_documents):
                # Normalize scores (higher is better, decreasing with index)
                score = 1.0 - (i / len(sparse_documents)) if sparse_documents else 0
                doc.metadata["score"] = score
        
        # If we have both types of results, use hybrid reranking
        if sparse_documents and dense_documents:
            return self._hybrid_reranking(dense_documents, sparse_documents, query, limit)
        
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