# AskDND Testing Suite

This directory contains tests for the AskDND application. The tests are designed to ensure that the application works as expected and to prevent regressions.

## Test Structure

The tests are organized into the following categories:

- **Unit Tests**: Test individual functions and methods in isolation
- **Integration Tests**: Test the interaction between different components
- **API Tests**: Test the web API endpoints
- **Vector Store Tests**: Test the vector store implementations

## Running Tests

### Prerequisites

Before running the tests, make sure you have:

1. Installed all dependencies: `pip install -r requirements.txt`
2. Installed pytest: `pip install pytest pytest-cov`
3. Set up environment variables (create a `.env` file or export them):
   - `APP_PASSWORD`: Password for authentication
   - `OPENAI_API_KEY`: API key for OpenAI (for LLM-related tests)
   - `QDRANT_API_KEY`: API key for Qdrant (for vector store tests)

### Running All Tests

To run all tests:

```bash
python -m pytest
```

### Running Specific Test Categories

To run specific categories of tests:

```bash
# Run API tests
python -m pytest tests/test_app.py

# Run vector store tests
python -m pytest tests/test_vector_store.py

# Run Qdrant-specific tests
python -m pytest tests/test_qdrant.py
```

### Test Coverage

To generate a test coverage report:

```bash
python -m pytest --cov=. --cov-report=html
```

This will generate a coverage report in the `htmlcov` directory.

## Continuous Integration

The tests are automatically run in the GitHub Actions CI pipeline on every push and pull request. See `.github/workflows/deploy.yml` for details.

## Mock Dependencies

When running tests, we use mock data and dependencies to avoid making actual API calls or accessing external services unless explicitly needed. This makes the tests faster and more reliable.

## Adding New Tests

When adding new features, make sure to add appropriate tests. Follow these guidelines:

1. Create a new test file if testing a new component
2. Follow the naming convention: `test_*.py` for test files
3. Use descriptive test names that explain what is being tested
4. Use fixtures for setup and teardown
5. Mock external dependencies when possible
6. Test both success and failure cases 