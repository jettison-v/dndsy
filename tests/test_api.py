import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()

# Get the password from environment variable
password = os.getenv('APP_PASSWORD')
if not password:
    password = 'default_password'  # Fallback for testing

# Create a session to maintain cookies
session = requests.Session()

# Login first
login_resp = session.post(
    'http://localhost:5001/login', 
    data={'password': password},
    allow_redirects=True
)
print(f'Login status code: {login_resp.status_code}')
print(f'Login URL after redirects: {login_resp.url}')
print(f'Cookies: {session.cookies.get_dict()}')

# Try to access the homepage to verify login
home_resp = session.get('http://localhost:5001/')
print(f'Home page status code: {home_resp.status_code}')
print(f'Home URL: {home_resp.url}')

# Now try the API endpoint
api_resp = session.get(
    'http://localhost:5001/api/get_context_details', 
    params={'source': 'source-pdfs/2024 Players Handbook.pdf', 'page': 172, 'vector_store_type': 'haystack'}
)
print(f'API status code: {api_resp.status_code}')

# Print the result
try:
    print(f'Response content: {api_resp.text[:200]}...')  # Print first 200 chars
    if api_resp.status_code == 200:
        data = api_resp.json()
        print(json.dumps(data, indent=2))
    else:
        print(api_resp.text)
except Exception as e:
    print(f'Error parsing response: {e}') 