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
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from .search_helper import SearchHelper
from embeddings.model_provider import embed_documents, embed_query

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Constants
DND_BEYOND_FORUM_EMBEDDING_DIMENSION = 1536  # OpenAI embedding dimension
DEFAULT_COLLECTION_NAME = "dnd_beyond_forum"

# Configure logging
logger = logging.getLogger(__name__)

class DnDBeyondForumStore(SearchHelper):
    """
    Vector store for DnD Beyond forum content.
    This store is optimized for content that is crawled from DnD Beyond forums.
    """
    
    DEFAULT_COLLECTION_NAME = DEFAULT_COLLECTION_NAME
    
    def __init__(self, collection_name: str = DEFAULT_COLLECTION_NAME):
        """Initialize the DnD Beyond Forum store."""
        super().__init__(collection_name)
        
        # Internal embedding client for OpenAI
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self._embeddings = None
        if self.openai_api_key:
            try:
                self._embeddings = OpenAIEmbeddings(
                     model="text-embedding-3-small", openai_api_key=self.openai_api_key
                )
                logger.debug("OpenAI embeddings initialized for DnD Beyond Forum store.")
            except Exception as e:
                 logger.warning(f"Failed to initialize OpenAI embeddings for DnD Beyond Forum store: {e}")
        else:
             logger.warning("OPENAI_API_KEY not found. DnD Beyond Forum store embeddings might fail.")

        embedding_dim = DND_BEYOND_FORUM_EMBEDDING_DIMENSION
        
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
        
        self._create_collection_if_not_exists(embedding_dim)
        
        # Qdrant Point ID Tracking
        try:
            # Get current point count to determine starting ID for new points
            self.next_id = self.client.count(self.collection_name).count
            logger.info(f"Initialized DnD Beyond Forum store. Next ID for '{self.collection_name}': {self.next_id}")
        except Exception as e:
            logger.warning(f"Error getting collection count for '{self.collection_name}': {e}. Starting ID count at 0.")
            self.next_id = 0
    
    def _create_collection_if_not_exists(self, embedding_dim: int):
        """Create the Qdrant collection if it doesn't exist already."""
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            collection_names = [collection.name for collection in collections]
            
            if self.collection_name not in collection_names:
                logger.info(f"Creating new Qdrant collection: {self.collection_name}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=embedding_dim,
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"Successfully created collection {self.collection_name}")
            else:
                logger.info(f"Collection {self.collection_name} already exists")
        except Exception as e:
            logger.error(f"Error creating/checking collection {self.collection_name}: {e}", exc_info=True)
            raise
    
    def _create_source_page_filter(self, source: str, page: Optional[int] = None) -> Dict[str, Any]:
        """Create a filter dictionary for source and optional page."""
        if page is not None:
            return {"source": source, "page": page}
        return {"source": source}
    
    # Search implementation
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
    
    def _get_all_documents_raw(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all documents from the store."""
        try:
            scroll_response = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                with_payload=True,
                with_vectors=False
            )
            
            documents = []
            if scroll_response and scroll_response[0]:
                for point in scroll_response[0]:
                    documents.append({
                        "id": point.id,
                        "text": point.payload.get("text", ""),
                        "metadata": point.payload.get("metadata", {})
                    })
            
            return documents
        except Exception as e:
            logger.error(f"Error getting all documents: {e}", exc_info=True)
            return []
    
    def get_details_by_source_page(self, source: str, page: int) -> Optional[Dict[str, Any]]:
        """Get a document by source and page number."""
        filter_conditions = self._create_source_page_filter(source, page)
        return self._get_document_by_filter(filter_conditions)
    
    def add_forum_posts(self, posts: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Add forum posts to the vector store.
        
        Args:
            posts: List of post dictionaries with keys:
                - 'text': The content of the post
                - 'title': The post title
                - 'url': The URL to the post
                - 'author': The post author
                - 'timestamp': When the post was created
                - 'thread_id': The ID of the thread
                - 'post_id': The ID of the post
        
        Returns:
            Tuple of (success_count, error_count)
        """
        if not posts:
            logger.warning("No posts provided to add_forum_posts")
            return 0, 0
        
        try:
            # Prepare texts and metadata for embedding
            texts_to_embed = [f"Title: {post.get('title', '')}\n\n{post.get('text', '')}" for post in posts]
            
            # Embed the texts using semantic store type (for OpenAI embeddings)
            logger.info(f"Embedding {len(texts_to_embed)} forum posts")
            embeddings = embed_documents(texts_to_embed, "semantic")
            
            if not embeddings:
                logger.error("Failed to generate embeddings for forum posts")
                return 0, len(posts)
            
            # Create points for Qdrant
            points = []
            for i, post in enumerate(posts):
                try:
                    # Get the embedding for this post
                    embedding = embeddings[i]
                    
                    # Prepare metadata
                    metadata = {
                        "source": f"dnd_beyond_forum/{post.get('thread_id', 'unknown')}",
                        "page": post.get('post_id', 0),  # Use post_id as page
                        "title": post.get('title', 'Untitled Post'),
                        "url": post.get('url', ''),
                        "author": post.get('author', 'Unknown'),
                        "timestamp": post.get('timestamp', ''),
                        "thread_id": post.get('thread_id', ''),
                        "post_id": post.get('post_id', ''),
                        "thread_title": post.get('thread_title', ''),
                        "post_type": post.get('post_type', 'forum'),
                        "forum_section": post.get('forum_section', 'Unknown'),
                        "length": len(post.get('text', '')),
                        "indexed_at": datetime.now().isoformat()
                    }
                    
                    # Create the point
                    point_id = self.next_id + i
                    points.append(models.PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "text": post.get('text', ''),
                            "metadata": metadata
                        }
                    ))
                except Exception as e:
                    logger.error(f"Error preparing point for post {post.get('post_id', 'unknown')}: {e}")
            
            # Update Qdrant
            if points:
                logger.info(f"Adding {len(points)} points to {self.collection_name}")
                result = self.client.upsert(
                    collection_name=self.collection_name,
                    points=points
                )
                
                # Update next_id counter
                self.next_id += len(points)
                
                logger.info(f"Successfully added {len(points)} forum posts to {self.collection_name}")
                return len(points), 0
            else:
                logger.warning("No valid points to add after processing")
                return 0, len(posts)
                
        except Exception as e:
            logger.error(f"Error adding forum posts to vector store: {e}", exc_info=True)
            return 0, len(posts)
    
    def clear_store(self, client: QdrantClient = None):
        """Deletes the entire Qdrant collection associated with this store."""
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
            self._create_collection_if_not_exists(DND_BEYOND_FORUM_EMBEDDING_DIMENSION)
        except Exception as e:
            logger.warning(f"Could not delete Qdrant collection '{self.collection_name}': {e}") 