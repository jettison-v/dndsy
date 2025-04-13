#!/usr/bin/env python3
import logging
import sys
from pprint import pprint
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import vector store
from vector_store import get_vector_store
from embeddings.model_provider import embed_query

def main():
    """Test the haystack store functionality"""
    logger.info("Testing haystack store functionality")
    
    # Initialize the haystack store
    haystack_store = get_vector_store("haystack")
    
    # Print document store class info
    logger.info(f"Document store class: {haystack_store.document_store.__class__.__name__}")
    logger.info(f"Document store dir: {dir(haystack_store.document_store)}")
    
    # Check document count
    doc_count = haystack_store.document_store.count_documents()
    logger.info(f"Haystack store has {doc_count} documents")
    logger.info(f"Next ID: {haystack_store.next_id}")
    
    # Get all documents
    try:
        logger.info("Getting a sample of documents...")
        all_docs = haystack_store.get_all_documents()
        logger.info(f"Retrieved {len(all_docs)} documents")
        
        # Print details of a few documents
        if all_docs:
            logger.info("Sample documents:")
            for i, doc in enumerate(all_docs[:3]):  # Print first 3 docs
                logger.info(f"Document {i+1}:")
                logger.info(f"  Text: {doc['text'][:100]}...")  # First 100 chars
                logger.info(f"  Metadata: {doc['metadata']}")
                
                # Detailed embedding info
                embedding = doc['embedding']
                if embedding is None:
                    logger.error(f"  Embedding is None for document {i+1}")
                elif hasattr(embedding, 'shape'):
                    logger.info(f"  Embedding: numpy array with shape {embedding.shape}, type {type(embedding)}")
                    logger.info(f"  First 5 values: {embedding[:5]}")
                else:
                    logger.info(f"  Embedding: {type(embedding)} with length {len(embedding)}")
                    logger.info(f"  First 5 values: {embedding[:5]}")
                
                # Check if embedding has any non-zero values
                if embedding is not None:
                    if hasattr(embedding, 'shape'):
                        non_zero = np.count_nonzero(embedding)
                        logger.info(f"  Embedding non-zero values: {non_zero} out of {embedding.size}")
                    else:
                        non_zero = sum(1 for x in embedding if x != 0)
                        logger.info(f"  Embedding non-zero values: {non_zero} out of {len(embedding)}")
    except Exception as e:
        logger.error(f"Error retrieving documents: {e}", exc_info=True)

    # Check the embedder initialization
    logger.info(f"SentenceTransformer initialized: {haystack_store.sentence_transformer is not None}")
    if haystack_store.sentence_transformer is not None:
        logger.info(f"SentenceTransformer model: {haystack_store.embedding_model_name}")

    # Try a direct manual similarity calculation
    try:
        logger.info("Testing direct manual similarity calculation...")
        query = "dragon"
        
        # Embed the query using the store's transformer
        query_embedding = haystack_store.sentence_transformer.encode(query)
        logger.info(f"Query embedding shape: {query_embedding.shape}")
        
        # Test with a few documents
        if all_docs:
            for i, doc in enumerate(all_docs[:5]):
                doc_embedding = doc['embedding']
                
                # Convert to numpy if needed
                if not hasattr(doc_embedding, 'shape'):
                    doc_embedding = np.array(doc_embedding)
                
                # Calculate similarity
                similarity = np.dot(query_embedding, doc_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(doc_embedding)
                )
                logger.info(f"Manual similarity for doc {i+1}: {similarity:.4f}")
    except Exception as e:
        logger.error(f"Error in manual similarity calculation: {e}", exc_info=True)

    # Test regular search
    try:
        logger.info("Testing search functionality...")
        # Try specific dragon-related queries that should match documents
        dragon_queries = [
            "What abilities do dragons have?",
            "dragon",
            "red dragon",
            "monster"
        ]
        
        for query in dragon_queries:
            logger.info(f"Searching for: '{query}'")
            
            # Embed the query
            query_vector = embed_query(query, "haystack")
            
            # Search
            results = haystack_store.search(query_vector=query_vector, query=query, limit=5)
            
            logger.info(f"Search for '{query}' returned {len(results)} results")
            
            # Print search results
            if results:
                logger.info(f"Search results for '{query}':")
                for i, result in enumerate(results):
                    logger.info(f"Result {i+1} (score: {result['score']:.4f}):")
                    logger.info(f"  Text: {result['text'][:100]}...")  # First 100 chars
                    logger.info(f"  Metadata: {result['metadata']}")
            else:
                logger.info(f"No results for '{query}'")
    except Exception as e:
        logger.error(f"Error during search: {e}", exc_info=True)

    # Test specialized monster search
    try:
        logger.info("\nTesting specialized monster search...")
        monster_types = ["dragon", "red dragon", "gold dragon", "goblin"]
        
        for monster_type in monster_types:
            logger.info(f"Searching for monster info about: '{monster_type}'")
            
            # Use the specialized search method
            results = haystack_store.search_monster_info(monster_type, limit=5)
            
            logger.info(f"Monster search for '{monster_type}' returned {len(results)} results")
            
            # Print search results
            if results:
                logger.info(f"Monster search results for '{monster_type}':")
                for i, result in enumerate(results):
                    logger.info(f"Result {i+1} (score: {result['score']:.4f}):")
                    logger.info(f"  Text: {result['text'][:100]}...")  # First 100 chars
                    logger.info(f"  Metadata source: {result['metadata'].get('source', 'unknown')}")
                    logger.info(f"  Metadata page: {result['metadata'].get('page', 'unknown')}")
                    if "section" in result["metadata"]:
                        logger.info(f"  Section: {result['metadata']['section']}")
                    if "heading_path" in result["metadata"]:
                        logger.info(f"  Heading path: {result['metadata']['heading_path']}")
            else:
                logger.info(f"No monster results for '{monster_type}'")
    except Exception as e:
        logger.error(f"Error during monster search: {e}", exc_info=True)

if __name__ == "__main__":
    main() 