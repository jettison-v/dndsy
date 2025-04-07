from qdrant_client import QdrantClient
import os
from process_data_sources import DataProcessor
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def reset_and_process():
    # Initialize Qdrant client
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", "6333"))
    client = QdrantClient(host=host, port=port)
    
    # Delete existing collection if it exists
    try:
        client.delete_collection("dnd_knowledge")
        print("Deleted existing collection")
    except Exception as e:
        print(f"No existing collection to delete: {str(e)}")
    
    # Process PDFs (this will create a new collection)
    processor = DataProcessor()
    documents = processor.process_pdfs("data/pdfs")
    
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