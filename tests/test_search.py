from vector_store.qdrant_store import QdrantStore
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def test_search():
    store = QdrantStore()
    
    # Try a few test queries
    test_queries = [
        "What is a dragon's breath weapon?",
        "How does character creation work?",
        "What are the basic rules for combat?"
    ]
    
    print("\nTesting search functionality:")
    print("-" * 50)
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        results = store.search(query, limit=2)
        
        for i, result in enumerate(results, 1):
            print(f"\nResult {i} (Score: {result['score']:.3f})")
            print(f"Source: {result['metadata']['source']}")
            print(f"Text excerpt: {result['text'][:200]}...")

if __name__ == "__main__":
    test_search() 