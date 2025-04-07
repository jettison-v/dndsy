import os
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer
import json
import logging

class QdrantStore:
    def __init__(self, collection_name: str = "dnd_knowledge"):
        """Initialize Qdrant vector store."""
        self.collection_name = collection_name
        # Load model only once if possible or ensure it's handled efficiently
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        
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
        
        logging.info(f"Initialized Qdrant store with collection: {collection_name}")
    
    def _create_collection_if_not_exists(self):
        """Create the collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(col.name == self.collection_name for col in collections)
        
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.model.get_sentence_embedding_dimension(),
                    distance=models.Distance.COSINE
                )
            )
            logging.info(f"Created new collection: {self.collection_name}")
    
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add documents to the vector store."""
        if not documents:
            return
        
        # Prepare points for batch insertion
        points = []
        for i, doc in enumerate(documents):
            # Generate embedding
            embedding = self.model.encode(doc["text"]).tolist()
            
            # Create point with sequential ID for this run
            point = models.PointStruct(
                id=i,  # Use loop index as ID (starts from 0)
                vector=embedding,
                payload={
                    "text": doc["text"],
                    "metadata": doc["metadata"]
                }
            )
            points.append(point)
        
        # Insert points in batches
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch
            )
            logging.info(f"Added batch of {len(batch)} documents to vector store")
    
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents."""
        # Generate query embedding
        query_vector = self.model.encode(query).tolist()
        
        # Search in Qdrant
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