# Vector Store Tests

This directory contains test scripts for verifying the functionality of different vector store implementations.

## Test Files

1. **test_haystack.py**
   - Tests the functionality of the Haystack vector store
   - Verifies document retrieval, search, and embedding initialization
   - Prints detailed logs about document count and embedding values

2. **test_force_auth.py**
   - Direct test for the `get_details_by_source_page` method
   - Bypasses authentication to test core functionality
   - Useful for debugging issues with document retrieval
   - Compares results between Haystack and Standard stores

## Running Tests

To run these tests, use:

```bash
# Run a specific test file
python -m tests.vector_store.test_haystack

# Run the force auth test
python -m tests.vector_store.test_force_auth
```

These tests can help verify that vector stores are properly initialized and functioning correctly after code changes. 