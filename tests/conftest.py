"""
Global pytest fixtures and configuration.
"""

import os
import pytest
from app import app as flask_app
from flask import session

@pytest.fixture(scope="session")
def app():
    """Create and configure a Flask app for testing."""
    # Set the testing flag to true
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test_secret_key",
        "SESSION_TYPE": "filesystem"
    })
    
    # Set test password
    os.environ['APP_PASSWORD'] = 'test_password'
    os.environ['TESTING'] = 'true'
    
    # Yield the app for tests
    yield flask_app

@pytest.fixture
def client(app):
    """A test client for the app."""
    with app.test_client() as test_client:
        # Create an application context
        with app.app_context():
            yield test_client

@pytest.fixture
def authenticated_client(client):
    """A test client that is already authenticated."""
    # Perform login
    client.post('/login', data={
        'password': 'test_password'
    })
    return client

@pytest.fixture
def mock_vector_store(monkeypatch):
    """A fixture that returns a mock vector store for testing."""
    class MockVectorStore:
        def __init__(self, *args, **kwargs):
            self.type = "mock"
            self.store_name = "mock_store"
        
        def search(self, query, limit=5):
            return [
                {"text": "Mock result 1", "metadata": {"source": "mock_source", "page": 1}, "score": 0.95},
                {"text": "Mock result 2", "metadata": {"source": "mock_source", "page": 2}, "score": 0.85}
            ]
        
        def get_details_by_source_page(self, source, page):
            return {
                "text": "Mock page content",
                "metadata": {"source": source, "page": page},
                "image_url": "mock_image_url",
                "total_pages": 10
            }
    
    # Patch the get_vector_store function
    from vector_store import get_vector_store as original_get_vector_store
    
    def mock_get_vector_store(store_type=None):
        return MockVectorStore(store_type)
    
    monkeypatch.setattr("vector_store.get_vector_store", mock_get_vector_store)
    
    return MockVectorStore() 