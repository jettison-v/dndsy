# Vector Store Tests

This directory contains tests for the various vector store implementations:

- Standard (PDF Pages) Store
- Semantic Store 
- Haystack implementations:
  - Haystack with Qdrant
  - Haystack with Memory storage

## Running Tests

To run vector store tests:

```bash
# Run all tests
python -m tests.vector_store.test_vector_store

# Run specific tests
python -m tests.vector_store.test_qdrant
python -m tests.vector_store.test_haystack_memory
python -m tests.vector_store.test_haystack_qdrant
```

## Test Coverage

The tests verify the following functionality:

- Initialization of vector stores
- Document chunking
- Adding points/documents
- Vector search
- Filtering by metadata
- Source page lookups 