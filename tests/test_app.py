import os
import pytest
import json
from app import app as flask_app
from flask import session

@pytest.fixture
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
    
    return flask_app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

def test_health_endpoint(client):
    """Test that the health endpoint returns a 200 status code and healthy status."""
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'

def test_login_page(client):
    """Test that the login page loads correctly."""
    response = client.get('/login')
    assert response.status_code == 200
    assert b'<form method="post" action="/login">' in response.data

def test_login_success(client):
    """Test that login works with the correct password."""
    response = client.post('/login', data={
        'password': 'test_password'
    }, follow_redirects=True)
    assert response.status_code == 200
    # Should redirect to home page after successful login
    assert b'<div class="chat-container">' in response.data

def test_login_failure(client):
    """Test that login fails with the wrong password."""
    response = client.post('/login', data={
        'password': 'wrong_password'
    })
    assert response.status_code == 200
    assert b'Incorrect password' in response.data

def test_unauthorized_access(client):
    """Test that unauthorized access is redirected to login."""
    response = client.get('/', follow_redirects=True)
    assert response.status_code == 200
    assert b'<form method="post" action="/login">' in response.data

def test_api_unauthorized(client):
    """Test that API endpoints require authentication."""
    response = client.get('/api/get_context_details?source=test&page=1')
    assert response.status_code == 401
    data = json.loads(response.data)
    assert 'error' in data
    assert data['error'] == 'Unauthorized'

def test_api_vector_store_types(client):
    """Test the vector store types API endpoint with authentication."""
    # Login first
    client.post('/login', data={'password': 'test_password'})
    
    # Now test the API
    response = client.get('/api/vector_stores')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'types' in data
    assert 'default' in data
    assert isinstance(data['types'], list)
    assert len(data['types']) > 0 