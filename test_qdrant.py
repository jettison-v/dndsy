from vector_store.qdrant_store import QdrantStore
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def test_qdrant_connection():
    try:
        # Initialize Qdrant store
        store = QdrantStore()
        
        # Get collection info
        collections = store.client.get_collections()
        print("\nAvailable collections:")
        for collection in collections.collections:
            print(f"- {collection.name}")
            
            # Get collection details
            collection_info = store.client.get_collection(collection.name)
            print(f"  Points: {collection_info.points_count}")
            print(f"  Vectors: {collection_info.vectors_count}")
            
        return True
    except Exception as e:
        print(f"Error connecting to Qdrant: {str(e)}")
        return False

if __name__ == "__main__":
    test_qdrant_connection() 