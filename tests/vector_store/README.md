# Vector Store Tests

This directory contains tests for the various vector store implementations:

- Standard (PDF Pages) Store
- Semantic Store 
- Haystack implementations:
  - Haystack with Qdrant
  - Haystack with Memory storage

## Running Tests

To run vector store tests located in this directory:

```bash
# Run all tests in this directory
pytest tests/vector_store/

# Run specific test files within this directory
pytest tests/vector_store/test_haystack.py
pytest tests/vector_store/test_force_auth.py
```

## Test Files

*   `test_haystack.py`: Contains tests for both Haystack Qdrant and Haystack Memory implementations.
*   `test_force_auth.py`: Contains tests related to authentication forcing mechanisms within vector store interactions (details may vary).

## Diagnostic Script

*   `check_qdrant.py`: This is not a pytest test file, but a standalone diagnostic script. Run it with `python tests/vector_store/check_qdrant.py` to connect to your configured Qdrant instance, list collections, check point counts, and view sample points. Useful for debugging Qdrant connection and data status.

## Test Coverage

The tests verify the following functionality:

- Initialization of vector stores
- Document chunking
- Adding points/documents
- Vector search
- Filtering by metadata
- Source page lookups 