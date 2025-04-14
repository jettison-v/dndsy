"""
Tests for the main Flask application.
"""

import os
import pytest
import json
from flask import session

# No need to define fixtures here as they're in conftest.py

@pytest.mark.api
def test_health_endpoint(client):
    """Test that the health endpoint returns a 200 status code and healthy status."""
    response = client.get('/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy'

@pytest.mark.api
def test_login_page(client):
    """Test that the login page loads correctly."""
    response = client.get('/login')
    assert response.status_code == 200
    assert b'<form method="post" action="/login">' in response.data

@pytest.mark.api
def test_login_success(client):
    """Test that login works with the correct password."""
    response = client.post('/login', data={
        'password': 'test_password'
    }, follow_redirects=True)
    assert response.status_code == 200
    # Should redirect to home page after successful login
    assert b'<div class="chat-container">' in response.data

@pytest.mark.api
def test_login_failure(client):
    """Test that login fails with the wrong password."""
    response = client.post('/login', data={
        'password': 'wrong_password'
    })
    assert response.status_code == 200
    assert b'Incorrect password' in response.data

@pytest.mark.api
def test_unauthorized_access(client):
    """Test that unauthorized access is redirected to login."""
    response = client.get('/', follow_redirects=True)
    assert response.status_code == 200
    assert b'<form method="post" action="/login">' in response.data

@pytest.mark.api
def test_api_unauthorized(client):
    """Test that API endpoints require authentication."""
    response = client.get('/api/get_context_details?source=test&page=1')
    assert response.status_code == 401
    data = json.loads(response.data)
    assert 'error' in data
    assert data['error'] == 'Unauthorized'

@pytest.mark.api
def test_api_vector_store_types(authenticated_client):
    """Test the vector store types API endpoint with authentication."""
    # Use the authenticated client fixture instead of manually logging in
    response = authenticated_client.get('/api/vector_stores')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'types' in data
    assert 'default' in data
    assert isinstance(data['types'], list)
    assert len(data['types']) > 0

@pytest.mark.api
def test_source_details_api(authenticated_client, mock_vector_store):
    """Test the get_context_details API endpoint."""
    response = authenticated_client.get('/api/get_context_details', query_string={
        'source': 'source-pdfs/test.pdf',
        'page': 1,
        'vector_store_type': 'haystack-qdrant'
    })
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'text' in data
    assert 'image_url' in data
    assert 'metadata' in data 