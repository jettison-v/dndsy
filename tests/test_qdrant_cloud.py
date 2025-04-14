import os
from vector_store.qdrant_store import QdrantStore
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_connection():
    logger.info("Attempting to connect to Qdrant...")
    qdrant_host = os.getenv("QDRANT_HOST")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    if not qdrant_host:
        logger.error("QDRANT_HOST environment variable is not set.")
        return

    logger.info(f"Using QDRANT_HOST: {qdrant_host}")
    if qdrant_api_key:
        logger.info("QDRANT_API_KEY is set.")
    else:
        logger.warning("QDRANT_API_KEY is NOT set. Connection might fail if required.")

    try:
        # Initialize the store - this will attempt connection and check/create collection
        store = QdrantStore() 
        
        # Attempt to get collection info as a basic check
        collection_info = store.client.get_collection(collection_name=store.collection_name)
        logger.info(f"Successfully connected and retrieved info for collection: {store.collection_name}")
        logger.info(f"Collection status: {collection_info.status}")
        logger.info(f"Points count: {collection_info.points_count}")
        logger.info("Qdrant Cloud connection test successful!")

    except Exception as e:
        logger.error(f"Failed to connect or interact with Qdrant: {e}")
        logger.error("Please check your QDRANT_HOST URL, QDRANT_API_KEY, and network connectivity.")

if __name__ == "__main__":
    test_connection() 