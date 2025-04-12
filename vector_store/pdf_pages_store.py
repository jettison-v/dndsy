import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
import json
import logging
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

STANDARD_EMBEDDING_DIMENSION = 384
DEFAULT_PDF_PAGES_COLLECTION = "dnd_pdf_pages"

class PdfPagesStore:
    """Store for full PDF pages."""
    
    DEFAULT_COLLECTION_NAME = DEFAULT_PDF_PAGES_COLLECTION
    
    def __init__(self, collection_name: str = DEFAULT_PDF_PAGES_COLLECTION):
        """Initialize Qdrant vector store for full PDF pages."""
        self.collection_name = collection_name
        # ... (rest of __init__ unchanged) ...
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
        try:
            collection_info = self.client.get_collection(self.collection_name)
            collection_count = self.client.count(self.collection_name).count
            self.next_id = collection_count
            logging.info(f"Starting from ID: {self.next_id} for new documents in {self.collection_name}")
        except Exception as e:
            logging.warning(f"Error getting collection info for {self.collection_name}: {e}")
            self.next_id = 0
        logging.info(f"Initialized PdfPagesStore with collection: {collection_name}")

    # ... (_create_collection_if_not_exists unchanged) ...
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

    # ... (add_points, search, get_details_by_source_page, get_all_documents unchanged) ...
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
                max_id_in_batch = max(p.id for p in batch)
                self.next_id = max(self.next_id, max_id_in_batch + 1)
            except Exception as e:
                logging.error(f"Error adding batch {batch_num}/{num_batches} to {self.collection_name}: {e}", exc_info=True)
                raise
        logging.info(f"Finished adding {len(points)} points to {self.collection_name}. Next ID: {self.next_id}")

    def search(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents using a pre-computed query vector."""
        if not query_vector:
             logging.error("Search called with an empty query vector.")
             return []
        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit
            )
            documents = []
            for result in results:
                documents.append({
                    "text": result.payload["text"],
                    "metadata": result.payload["metadata"],
                    "score": result.score
                })
            return documents
        except Exception as e:
            logging.error(f"Error searching Qdrant collection {self.collection_name}: {e}", exc_info=True)
            return []

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
                limit=1,
                with_payload=True,
                with_vectors=False
            )
            if scroll_response and scroll_response[0]:
                point = scroll_response[0][0]
                payload = point.payload
                metadata = payload.get("metadata", {})
                return {
                    "text": payload.get("text", ""),
                    "image_url": metadata.get("image_url", None),
                    "total_pages": metadata.get("total_pages", None),
                }
            else:
                logging.warning(f"Qdrant scroll found no match for source: '{source_name}', page: {page_number} in {self.collection_name}")
                return None
        except Exception as e:
            logging.error(f"Error fetching details from Qdrant for '{source_name}' page {page_number} in {self.collection_name}: {e}", exc_info=True)
            return None

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Get all documents from the vector store."""
        documents = []
        offset = None
        limit = 100
        while True:
            response_tuple = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_vectors=False,
                with_payload=True
            )
            points = response_tuple[0]
            next_page_offset = response_tuple[1]
            if not points:
                break
            for point in points:
                documents.append({
                    "text": point.payload.get("text", ""),
                    "metadata": point.payload.get("metadata", {})
                })
            if next_page_offset is None:
                 break
            offset = next_page_offset
        return documents 