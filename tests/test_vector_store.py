from vector_store.qdrant_store import QdrantStore
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_vector_search(query: str, limit: int = 5):
    """Test searching the vector store directly."""
    try:
        # Initialize vector store
        vector_store = QdrantStore()
        
        # Search for documents
        print(f"\n{'='*80}")
        print(f"Searching for: {query}")
        print(f"{'='*80}")
        results = vector_store.search(query, limit=limit)
        
        # Display results
        if not results:
            print("\nNo results found in the D&D documentation.")
            return
        
        print(f"\nFound {len(results)} relevant sections:\n")
        for i, result in enumerate(results, 1):
            source = result['metadata']['source'].split('/')[-1].replace('.pdf', '')
            page = result['metadata'].get('page', 'unknown')
            score = result.get('score', 0)
            
            print(f"\nResult {i} (Similarity Score: {score:.3f}):")
            print(f"Source: {source} (page {page})")
            print("-" * 80)
            print(f"Content: {result['text']}")
            print("-" * 80)
            
    except Exception as e:
        logger.error(f"Error during search: {str(e)}")

def list_all_documents():
    """List all documents in the vector store."""
    try:
        vector_store = QdrantStore()
        documents = vector_store.get_all_documents()
        
        print(f"\n{'='*80}")
        print(f"Vector Store Contents Summary")
        print(f"{'='*80}")
        print(f"Total documents in vector store: {len(documents)}")
        
        # Group by source
        sources = {}
        for doc in documents:
            source = doc['metadata']['source'].split('/')[-1].replace('.pdf', '')
            if source not in sources:
                sources[source] = 0
            sources[source] += 1
        
        print("\nDocuments by source:")
        for source, count in sorted(sources.items()):
            print(f"- {source}: {count} chunks")
            
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")

if __name__ == "__main__":
    # First, list all documents to verify the vector store has content
    list_all_documents()
    
    # Test some queries
    while True:
        print("\nEnter your search query (or 'quit' to exit):")
        query = input("> ")
        if query.lower() == 'quit':
            break
        test_vector_search(query) 