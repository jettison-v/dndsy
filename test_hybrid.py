from llm import ask_dndsy
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

def test_hybrid_search():
    """Test the hybrid search functionality with various queries."""
    test_queries = [
        "What is a dragon's breath weapon?",
        "How does character creation work in D&D 2024?",
        "What are the rules for multiclassing in 5.5e?",
        "Can you explain how spell slots work in the new rules?"
    ]
    
    print("\nTesting Hybrid Search (Vector Store + OpenAI):")
    print("-" * 60)
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * len(f"Query: {query}"))
        
        response = ask_dndsy(query)
        print(f"\nResponse:\n{response}\n")
        print("-" * 60)

if __name__ == "__main__":
    test_hybrid_search() 