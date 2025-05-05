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

To run all tests discovered by pytest in the `tests/` directory and its subdirectories:

```bash
pytest
# Or with explicit verbosity
# pytest -v
```

### Running Specific Test Files or Categories

You can run specific test files directly or use markers defined in `pytest.ini`.

```bash
# Run all tests in a specific file
pytest tests/test_api.py
pytest tests/test_app.py
pytest tests/test_search.py
pytest tests/test_vector_store.py
pytest tests/test_qdrant.py
pytest tests/test_qdrant_cloud.py
pytest tests/test_hybrid.py
pytest tests/test_tiktoken.py

# Run all tests in a subdirectory
pytest tests/vector_store/

# Run tests marked with 'api' (if markers are used in test functions)
# pytest -m api
```

### Test Configuration (`pytest.ini` and `conftest.py`)

*   `pytest.ini`: Configures test discovery patterns, logging, default options (`addopts`), and marker definitions.
*   `conftest.py`: This file contains shared fixtures (setup/teardown code) used by multiple tests, helping to avoid code duplication.

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