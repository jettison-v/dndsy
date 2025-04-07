from qdrant_client import QdrantClient
import os
from process_data_sources import DataProcessor
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def reset_and_process():
    # Initialize Qdrant client (handling cloud/local)
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    # Determine if it's a cloud URL
    is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")

    if is_cloud:
        logging.info(f"Reset script connecting to Qdrant Cloud at: {qdrant_host}")
        # For cloud, use url and api_key. Port is usually inferred (443 for https).
        client = QdrantClient(
            url=qdrant_host, 
            api_key=qdrant_api_key,
            timeout=60
        )
    else:
        logging.info(f"Reset script connecting to local Qdrant at: {qdrant_host}")
        # For local, use host and explicit port.
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=port, timeout=60)
    
    # Delete existing collection if it exists
    try:
        client.delete_collection("dnd_knowledge")
        print("Deleted existing collection")
    except Exception as e:
        print(f"No existing collection to delete: {str(e)}")
    
    # Process PDFs from S3 (path is handled internally via env vars)
    processor = DataProcessor()
    documents = processor.process_pdfs_from_s3()
    
    if documents:
        print(f"\nProcessed {len(documents)} documents")
        # Add to vector store
        processor.vector_store.add_documents(documents)
        print("Documents added to vector store")
        return True
    else:
        print("No documents were processed")
        return False

if __name__ == "__main__":
    success = reset_and_process()
    
    if success:
        print("\nProcessing completed successfully!")
        print("You can now use the vector store to search through the content.")
    else:
        print("\nProcessing completed with errors.")
        print("Check the logs for details.") 