import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
# Remove SentenceTransformer import as embedding is now external
# from sentence_transformers import SentenceTransformer
import json
import logging
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent.parent / '.env' # Define path to .env file relative to this script
load_dotenv(dotenv_path=env_path) # Load environment variables from specified path

# Define embedding size here - must match the model used externally
# For 'all-MiniLM-L6-v2' it's 384
STANDARD_EMBEDDING_DIMENSION = 384

class QdrantStore:
    def __init__(self, collection_name: str = "dnd_knowledge"):
        """Initialize Qdrant vector store."""
        self.collection_name = collection_name
        # Remove model loading from here
        # self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Initialize Qdrant client for local or cloud
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        
        # Determine if it's a cloud URL
        is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")

        if is_cloud:
            logging.info(f"Connecting to Qdrant Cloud at: {qdrant_host}")
            # For cloud, use url and api_key. Port is usually inferred (443 for https).
            self.client = QdrantClient(
                url=qdrant_host, 
                api_key=qdrant_api_key, 
                timeout=60
            )
        else:
            logging.info(f"Connecting to local Qdrant at: {qdrant_host}")
            # For local, use host and explicit port.
            port = int(os.getenv("QDRANT_PORT", "6333"))
            self.client = QdrantClient(host=qdrant_host, port=port, timeout=60)
        
        # Create collection if it doesn't exist
        self._create_collection_if_not_exists()
        
        # Track the highest ID used so far to avoid overwriting points
        try:
            collection_info = self.client.get_collection(self.collection_name)
            collection_count = self.client.count(self.collection_name).count
            self.next_id = collection_count  # Start from the next available ID
            logging.info(f"Starting from ID: {self.next_id} for new documents in standard collection")
        except Exception as e:
            logging.warning(f"Error getting collection info: {e}")
            self.next_id = 0
        
        logging.info(f"Initialized Qdrant store with collection: {collection_name}")
    
    def _create_collection_if_not_exists(self):
        """Create the collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(col.name == self.collection_name for col in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    # Use the defined dimension
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
                    wait=True # Wait for operation to complete for potentially better stability
                )
                logging.info(f"Added batch {batch_num}/{num_batches} ({len(batch)} points) to {self.collection_name}")
                # Update next_id based on the highest ID in the current batch
                max_id_in_batch = max(p.id for p in batch)
                self.next_id = max(self.next_id, max_id_in_batch + 1)
            except Exception as e:
                logging.error(f"Error adding batch {batch_num}/{num_batches} to {self.collection_name}: {e}", exc_info=True)
                # Optionally, re-raise or implement retry logic
                raise
        
        logging.info(f"Finished adding {len(points)} points to {self.collection_name}. Next ID: {self.next_id}")

    def search(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents using a pre-computed query vector."""
        # No query embedding generation here - uses the provided vector
        # query_vector = self.model.encode(query).tolist()
        
        if not query_vector:
             logging.error("Search called with an empty query vector.")
             return []
             
        try:
            # Search in Qdrant using the provided vector
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
        except Exception as e:
            logging.error(f"Error searching Qdrant collection {self.collection_name}: {e}", exc_info=True)
            return []

    def get_details_by_source_page(self, source_name: str, page_number: int) -> Optional[Dict[str, Any]]:
        """Fetch details (text, image_url) for a specific source document and page."""
        try:
            # Define the filter for the specific source filename and page
            
            # Try matching with extension (e.g., "MyBook.pdf") or without (e.g., "MyBook")
            # Assumes source_name might or might not contain .pdf
            filename_filter_options = [
                models.FieldCondition(
                    key="metadata.filename",
                    match=models.MatchValue(value=source_name)
                )
            ]
            # If the name doesn't look like it has an extension, also try matching without .pdf
            if '.' not in source_name: 
                 # Basic check, might need refinement if filenames can contain dots
                 pass # Qdrant doesn't easily support regex/contains on metadata values directly in filters
                      # We rely on the frontend sending the name as stored in metadata.filename

            search_filter = models.Filter(
                must=[
                     # Use OR condition if we had multiple filename checks
                     # models.Condition(should=filename_filter_options), 
                     models.FieldCondition( 
                        key="metadata.source", # Changed back from metadata.filename
                        match=models.MatchValue(value=source_name) # Value is now the S3 Key
                    ),
                    models.FieldCondition(
                        key="metadata.page", 
                        match=models.MatchValue(value=page_number)
                    )
                ]
            )
            
            # Use scroll API to get the first matching document
            # We don't need vector similarity here, just filtering
            scroll_response = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=search_filter,
                limit=1, # We only need one result
                with_payload=True, # Ensure we get the payload
                with_vectors=False # No need for the vector
            )
            
            if scroll_response and scroll_response[0]:
                point = scroll_response[0][0] # Get the first point from the response tuple
                payload = point.payload
                metadata = payload.get("metadata", {})
                return {
                    "text": payload.get("text", ""),
                    "image_url": metadata.get("image_url", None), # Extract image_url from metadata
                    "total_pages": metadata.get("total_pages", None), # Add total_pages
                    # Add any other details needed by the frontend here
                }
            else:
                logging.warning(f"Qdrant scroll found no match for source: '{source_name}', page: {page_number}")
                return None
        except Exception as e:
            logging.error(f"Error fetching details from Qdrant for '{source_name}' page {page_number}: {e}", exc_info=True)
            return None

    def get_all_documents(self) -> List[Dict[str, Any]]:
        """Get all documents from the vector store."""
        documents = []
        offset = None # Start scrolling from the beginning
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
                 break # Reached the end
            offset = next_page_offset
        
        return documents 