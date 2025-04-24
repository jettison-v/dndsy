import os
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import numpy as np
from datetime import datetime

from qdrant_client import QdrantClient
from qdrant_client.http import models
from dotenv import load_dotenv

from .search_helper import SearchHelper
from embeddings.model_provider import embed_documents

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Constants
EXTERNAL_CONTENT_EMBEDDING_DIMENSION = 1536  # OpenAI embedding dimension
DEFAULT_COLLECTION_NAME = "dnd_external_content"

# Configure logging
logger = logging.getLogger(__name__)

class ExternalContentStore(SearchHelper):
    """
    Vector store for external content such as forum posts, blog articles, etc.
    This store is optimized for content that is crawled from external sources.
    """
    
    DEFAULT_COLLECTION_NAME = DEFAULT_COLLECTION_NAME
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize the External Content store."""
        super().__init__(collection_name)
        
        embedding_dim = EXTERNAL_CONTENT_EMBEDDING_DIMENSION
        
        # Qdrant Client Initialization
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")
        if is_cloud:
            logger.info(f"Connecting to Qdrant Cloud at: {qdrant_host} for {self.collection_name}")
            self.client = QdrantClient(url=qdrant_host, api_key=qdrant_api_key, timeout=60)
        else:
            logger.info(f"Connecting to local Qdrant at: {qdrant_host} for {self.collection_name}")
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = QdrantClient(host=qdrant_host, port=port, timeout=60)
        
        # Create collection if it doesn't exist
        self._create_collection_if_not_exists(embedding_dim)
        
        # Qdrant Point ID Tracking
        try:
            # Get current point count to determine starting ID for new points
            self.next_id = self.client.count(self.collection_name).count
            logger.info(f"Initialized External Content store. Next ID for '{self.collection_name}': {self.next_id}")
        except Exception as e:
            logger.warning(f"Error getting collection count for '{self.collection_name}': {e}. Starting ID count at 0.")
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
            logger.info(f"Created new external content collection: {self.collection_name}")
    
    def _execute_vector_search(self, query_vector: List[float], limit: int) -> List[Dict[str, Any]]:
        """Execute vector search using Qdrant client."""
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit
        )
        
        # Format results
        documents = []
        for result in results:
            documents.append({
                "text": result.payload["text"],
                "metadata": result.payload["metadata"],
                "score": result.score
            })
        return documents
    
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
        """Get documents by filter."""
        results = self._execute_filter_search(filter_conditions, limit=1)
        if results:
            return results[0]
        return None
    
    def _get_all_documents_raw(self, limit: int) -> List[Dict[str, Any]]:
        """Get all documents from store."""
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
    
    def _create_source_filter(self, source: str) -> Dict[str, Any]:
        """Create source filter."""
        return {"source": source}
    
    def add_points(self, points: List[models.PointStruct]) -> int:
        """Add pre-embedded points to the store."""
        if not points:
            return 0
            
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
                logger.info(f"Added batch {batch_num}/{num_batches} ({len(batch)} points) to {self.collection_name}")
                points_added_count += len(batch)
                
                # Update next_id based on the highest ID in the current batch
                max_id_in_batch = max(p.id for p in batch)
                self.next_id = max(self.next_id, max_id_in_batch + 1)
            except Exception as e:
                logger.error(f"Error adding batch {batch_num}/{num_batches} to {self.collection_name}: {e}", exc_info=True)
                raise
        
        logger.info(f"Finished adding {points_added_count} points to {self.collection_name}. Next ID: {self.next_id}")
        return points_added_count
    
    def process_dndbeyond_forum_data(self, threads_dir: str, batch_size: int = 100) -> int:
        """
        Process DnD Beyond forum data from S3 and add to vector store.
        
        Args:
            threads_dir: S3 directory containing thread JSON files
            batch_size: Number of posts to process in a batch
            
        Returns:
            Number of posts added to the store
        """
        from data_ingestion.processor import s3_client, AWS_S3_BUCKET_NAME
        
        if not s3_client:
            logger.error("S3 client not configured. Cannot process forum data.")
            return 0
        
        # List thread files in the directory
        try:
            response = s3_client.list_objects_v2(
                Bucket=AWS_S3_BUCKET_NAME,
                Prefix=threads_dir
            )
            
            if not response.get('Contents'):
                logger.warning(f"No thread files found in {threads_dir}")
                return 0
                
            thread_files = [obj['Key'] for obj in response['Contents'] if obj['Key'].endswith('.json')]
            logger.info(f"Found {len(thread_files)} thread files to process")
            
            total_posts_processed = 0
            current_batch = []
            current_batch_texts = []
            
            for thread_file in thread_files:
                try:
                    # Get thread data from S3
                    thread_response = s3_client.get_object(
                        Bucket=AWS_S3_BUCKET_NAME,
                        Key=thread_file
                    )
                    thread_data = json.loads(thread_response['Body'].read().decode('utf-8'))
                    
                    thread_title = thread_data.get('title', 'Untitled Thread')
                    thread_url = thread_data.get('url', '')
                    posts = thread_data.get('posts', [])
                    
                    logger.info(f"Processing thread: {thread_title} ({len(posts)} posts)")
                    
                    for post in posts:
                        post_content = post.get('content', '')
                        
                        if not post_content.strip():
                            continue
                            
                        # Create metadata for the post
                        metadata = {
                            "source": "dndbeyond_forum",
                            "source_type": "forum_post",
                            "thread_title": thread_title,
                            "thread_url": thread_url,
                            "post_id": post.get('id', ''),
                            "author": post.get('author', 'Unknown'),
                            "date": post.get('date', ''),
                            "processed_at": datetime.now().isoformat()
                        }
                        
                        # Add to current batch
                        current_batch_texts.append(post_content)
                        current_batch.append({
                            "text": post_content, 
                            "metadata": metadata
                        })
                        
                        # Process batch if it reaches the batch size
                        if len(current_batch) >= batch_size:
                            self._process_and_add_batch(current_batch, current_batch_texts)
                            total_posts_processed += len(current_batch)
                            current_batch = []
                            current_batch_texts = []
                            
                except Exception as e:
                    logger.error(f"Error processing thread file {thread_file}: {e}", exc_info=True)
            
            # Process any remaining items in the batch
            if current_batch:
                self._process_and_add_batch(current_batch, current_batch_texts)
                total_posts_processed += len(current_batch)
            
            logger.info(f"Completed processing. Added {total_posts_processed} forum posts to the vector store.")
            return total_posts_processed
            
        except Exception as e:
            logger.error(f"Error processing forum data: {e}", exc_info=True)
            return 0
    
    def _process_and_add_batch(self, batch: List[Dict[str, Any]], texts: List[str]) -> None:
        """Process and add a batch of posts to the vector store."""
        try:
            # Generate embeddings for the batch
            embeddings = embed_documents(texts, store_type="semantic")
            
            if len(embeddings) != len(batch):
                logger.error(f"Embedding count ({len(embeddings)}) doesn't match batch count ({len(batch)})")
                return
            
            # Create points for Qdrant
            points = []
            for i, item in enumerate(batch):
                point_id = self.next_id + i
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector=embeddings[i],
                        payload={
                            "text": item["text"],
                            "metadata": item["metadata"]
                        }
                    )
                )
            
            # Add points to the vector store
            self.add_points(points)
            
        except Exception as e:
            logger.error(f"Error processing batch: {e}", exc_info=True)
    
    def clear_store(self, client: QdrantClient = None):
        """Deletes the collection and recreates it."""
        q_client = client if client else self.client
        if not q_client:
            logger.error(f"Qdrant client not available for clearing collection {self.collection_name}")
            return

        try:
            logger.info(f"Attempting to delete Qdrant collection: {self.collection_name}")
            q_client.delete_collection(collection_name=self.collection_name)
            logger.info(f"Successfully deleted Qdrant collection: {self.collection_name}")
            # Reset internal state after clearing
            self.next_id = 0
            # Immediately recreate the collection after deletion
            logger.info(f"Recreating collection {self.collection_name}...")
            self._create_collection_if_not_exists(EXTERNAL_CONTENT_EMBEDDING_DIMENSION)
        except Exception as e:
            logger.warning(f"Could not delete Qdrant collection '{self.collection_name}': {e}")

    def rebuild_from_forum_data(self) -> int:
        """
        Clears the vector store and rebuilds it from forum data.
        
        Returns:
            Number of posts added to the store
        """
        try:
            # Clear the store first
            self.clear_store()
            
            # Get the directory where threads are stored
            threads_dir = "external-sources/dndbeyond-forums/threads/"
            
            # Process threads
            return self.process_dndbeyond_forum_data(threads_dir=threads_dir)
        except Exception as e:
            logger.error(f"Error rebuilding from forum data: {e}", exc_info=True)
            return 0

    def add_new_forum_data(self) -> int:
        """
        Add new forum data to the vector store without clearing existing data.
        
        Returns:
            Number of new posts added to the store
        """
        try:
            # Get the directory where threads are stored
            threads_dir = "external-sources/dndbeyond-forums/threads/"
            
            # Process only new threads
            # In a real implementation, this would check for new or updated threads
            # For now, it just processes all threads again, assuming Qdrant point IDs
            # will handle duplicates
            return self.process_dndbeyond_forum_data(threads_dir=threads_dir)
        except Exception as e:
            logger.error(f"Error adding new forum data: {e}", exc_info=True)
            return 0 