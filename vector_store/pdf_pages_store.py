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

STANDARD_EMBEDDING_DIMENSION = 384
DEFAULT_PDF_PAGES_COLLECTION = "dnd_pdf_pages"

class PdfPagesStore(SearchHelper):
    """Store for full PDF pages with standardized search methods."""
    
    DEFAULT_COLLECTION_NAME = DEFAULT_PDF_PAGES_COLLECTION
    
    def __init__(self, collection_name: str = DEFAULT_PDF_PAGES_COLLECTION):
        """Initialize Qdrant vector store for full PDF pages."""
        super().__init__(collection_name)
        # Initialize Qdrant client
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")
        if is_cloud:
            logging.info(f"Connecting to Qdrant Cloud at: {qdrant_host}")
            self.client = QdrantClient(url=qdrant_host, api_key=qdrant_api_key, timeout=60)
        else:
            logging.info(f"Connecting to local Qdrant at: {qdrant_host}")
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = QdrantClient(host=qdrant_host, port=port, timeout=60)
        self._create_collection_if_not_exists()
        logging.info(f"Initialized PdfPagesStore with collection: {collection_name}")

    def _create_collection_if_not_exists(self):
        """Create the collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(col.name == self.collection_name for col in collections)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=STANDARD_EMBEDDING_DIMENSION, 
                    distance=models.Distance.COSINE
                )
            )
            logging.info(f"Created new collection: {self.collection_name}")

    def add_points(self, points: List[models.PointStruct]) -> None:
        """Adds pre-constructed points (with vectors) to the Qdrant collection."""
        if not points:
            return
        batch_size = 100
        num_batches = (len(points) + batch_size - 1) // batch_size
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
            except Exception as e:
                logging.error(f"Error adding batch {batch_num}/{num_batches} to {self.collection_name}: {e}", exc_info=True)
                raise
        logging.info(f"Finished adding {len(points)} points to {self.collection_name}.")

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
    
    def _create_source_page_filter(self, source: str, page: int) -> Dict[str, Any]:
        """Create source/page filter for Qdrant."""
        return {
            "source": source,
            "page": page
        } 