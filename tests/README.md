# DnDSy Tests

This directory contains test scripts and utilities for verifying the functionality of the DnDSy application.

## Test Structure

- **tests/vector_store/** - Tests for the vector store implementations
- **test_api.py** - Tests for the API endpoints and authentication

## API Tests

The `test_api.py` file contains tests for:
- Login functionality
- Session management
- API endpoint authorization
- API responses

To run the API test:

```bash
python -m tests.test_api
```

## Component Tests

Each subdirectory focuses on testing a specific component of the application:

- **vector_store/** - Tests for vector store implementations (standard, semantic, haystack)

See the README in each subdirectory for specific testing information. 