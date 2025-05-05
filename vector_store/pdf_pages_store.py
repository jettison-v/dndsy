import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
import json
import logging
from dotenv import load_dotenv
from pathlib import Path
from .search_helper import SearchHelper

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logger = logging.getLogger(__name__)

STANDARD_EMBEDDING_DIMENSION = 384
DEFAULT_PDF_PAGES_COLLECTION = "dnd_pdf_pages"

# Define collection name using environment variable with fallback
COLLECTION_NAME = os.getenv("QDRANT_PAGES_COLLECTION", "dnd_pdf_pages")

class PdfPagesStore(SearchHelper):
    """Store for full PDF pages with standardized search methods."""
    
    DEFAULT_COLLECTION_NAME = DEFAULT_PDF_PAGES_COLLECTION
    
    def __init__(self, collection_name: str = DEFAULT_PDF_PAGES_COLLECTION):
        """Initialize Qdrant vector store for full PDF pages."""
        super().__init__(collection_name)
        # Use instance variable for collection name, allows overriding if needed
        self.collection_name = collection_name
        # Qdrant client initialization logic (should be consistent with other stores)
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        qdrant_port = int(os.getenv("QDRANT_PORT", 6333))
        prefer_grpc = os.getenv("QDRANT_PREFER_GRPC", "false").lower() == "true"
        
        logger.info(f"Connecting to Qdrant host: {qdrant_host} for {self.collection_name}")
        try:
            self.client = QdrantClient(
                host=qdrant_host,
                port=qdrant_port, 
                api_key=qdrant_api_key,
                prefer_grpc=prefer_grpc,
                 timeout=60 # Increase timeout
            )
            # Ensure collection exists
            self._ensure_collection()
            logger.info(f"Initialized PdfPagesStore with collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client for PdfPagesStore: {e}", exc_info=True)
            raise

    def _ensure_collection(self):
        """Ensure the Qdrant collection exists, creating it if necessary."""
        try:
            collections_response = self.client.get_collections()
            collection_names = [c.name for c in collections_response.collections]
            if self.collection_name not in collection_names:
                logger.info(f"Collection '{self.collection_name}' not found. Creating...")
                # Assuming embedding dimension is known (e.g., 384 for all-MiniLM-L6-v2)
                # This should ideally be configured or determined dynamically
                embedding_dim = 384 # Example dimension
                self.client.recreate_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=embedding_dim, distance=models.Distance.COSINE)
                )
                logger.info(f"Created collection: {self.collection_name}")
            else:
                logger.debug(f"Collection '{self.collection_name}' already exists.")
        except Exception as e:
            logger.error(f"Error checking/creating collection {self.collection_name}: {e}", exc_info=True)
            raise

    def add_points(self, points: List[models.PointStruct]) -> None:
        """Adds pre-constructed points (with vectors) to the Qdrant collection."""
        if not points:
            logger.warning("No points provided to add.")
            return 0
            
        logger.info(f"Adding {len(points)} points to collection '{self.collection_name}'")
        try:
            operation_info = self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True # Wait for operation to complete
            )
            if operation_info.status == models.UpdateStatus.COMPLETED:
                logger.info(f"Successfully added {len(points)} points.")
                return len(points) # Return number added
            else:
                logger.error(f"Failed to add points to {self.collection_name}. Status: {operation_info.status}")
                return 0
        except Exception as e:
            logger.error(f"Error adding points to {self.collection_name}: {e}", exc_info=True)
            return 0

    # Implement abstract methods from SearchHelper
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
        """Get a single document by filter."""
        results = self._execute_filter_search(filter_conditions, limit=1)
        if results:
            doc = results[0]
            # Get the metadata
            metadata = doc["metadata"]
            # Ensure total_pages is included
            total_pages = metadata.get("total_pages")
            
            # If total_pages isn't available in the document metadata,
            # try to extract it from the source file name or use a default
            if not total_pages and "source" in metadata:
                try:
                    # Try to get total pages by looking for other pages from same source
                    source = metadata["source"]
                    # Create a filter to find all pages from this source
                    source_filter = {"source": source}
                    all_pages = self._execute_filter_search(source_filter, limit=1000)
                    if all_pages:
                        # Get the maximum page number
                        page_numbers = [page["metadata"].get("page", 0) for page in all_pages if "metadata" in page]
                        if page_numbers:
                            total_pages = max(page_numbers)
                except Exception as e:
                    logging.error(f"Error finding total pages: {e}")
            
            return {
                "text": doc["text"],
                "metadata": metadata,
                "image_url": metadata.get("image_url"),
                "total_pages": total_pages
            }
        return None
    
    def _get_all_documents_raw(self, limit: int = 1000) -> List[Dict[str, Any]]:
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
    
    def clear_store(self):
        """Deletes and recreates the Qdrant collection."""
        try:
            logger.info(f"Attempting to delete Qdrant collection: {self.collection_name}")
            self.client.delete_collection(collection_name=self.collection_name)
            logger.info(f"Successfully deleted Qdrant collection: {self.collection_name}")
            # Recreate it immediately
            logger.info(f"Recreating collection {self.collection_name}...")
            self._ensure_collection() 
        except Exception as e:
            # Handle case where collection might not exist - log as warning
            if "not found" in str(e).lower() or "doesn't exist" in str(e).lower():
                 logger.warning(f"Collection {self.collection_name} not found during clear_store (already deleted?)")
            else:
                 logger.error(f"Error clearing/recreating collection {self.collection_name}: {e}", exc_info=True)
                 raise # Reraise other errors

    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Create source/page filter for Qdrant."""
        return {
            "source": source,
            "page": page
        } 