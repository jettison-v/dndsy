"""
Session fix for mobile testing.

Run this file instead of app.py for local mobile testing:
python session_fix.py
"""

import os
import logging
import socket
from app import app
from flask_session import Session
from datetime import timedelta

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('flask_session')
logger.setLevel(logging.DEBUG)

# Debug middleware to log session activity
class SessionDebugMiddleware:
    def __init__(self, app):
        self.app = app
        
    def __call__(self, environ, start_response):
        def session_start_response(status, headers, exc_info=None):
            logger.debug(f"Response Status: {status}")
            logger.debug(f"Headers: {headers}")
            return start_response(status, headers, exc_info)
        
        logger.debug(f"Request to: {environ.get('PATH_INFO')}")
        # Force mobile view query param support
        if '?' in environ.get('PATH_INFO', '') and 'device=mobile' in environ.get('PATH_INFO', ''):
            logger.debug("Mobile view forced via URL parameter")
        
        return self.app(environ, session_start_response)

def get_local_ip():
    """Get the local IP address for displaying to the user."""
    try:
        # Create a socket to determine the local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't need to be reachable, just used to determine the IP
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"  # Fallback to localhost

if __name__ == "__main__":
    # Essential session fixes for mobile testing
    app.config['SESSION_COOKIE_SAMESITE'] = None   # Most permissive setting for testing
    app.config['SESSION_COOKIE_SECURE'] = False    # Allow non-HTTPS (for local testing)
    app.config['SESSION_COOKIE_HTTPONLY'] = True   # Security best practice
    app.config['SESSION_COOKIE_DOMAIN'] = None     # Allow any subdomain
    app.config['SESSION_COOKIE_PATH'] = '/'        # Allow access across all paths
    
    # Disable signature verification which can cause issues on some mobile browsers
    app.config['SESSION_USE_SIGNER'] = False
    
    # Set a long-lived session
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
    app.config['SESSION_PERMANENT'] = True
    
    # Force session type to filesystem for more reliable persistence
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_FILE_DIR'] = './flask_session'
    app.config['SESSION_FILE_THRESHOLD'] = 100     # Number of sessions stored before cleanup
    
    # Make sure directory exists
    os.makedirs('./flask_session', exist_ok=True)
    
    # Disable strict slashes which can cause redirect issues
    app.url_map.strict_slashes = False
    
    # Initialize session with new settings
    Session(app)
    
    # Add debugging middleware
    app.wsgi_app = SessionDebugMiddleware(app.wsgi_app)
    
    # Set environment variable for local testing
    os.environ['FLASK_ENV'] = 'development'
    
    # Get local IP for display
    local_ip = get_local_ip()
    port = 5001
    
    # Print useful information
    print("=" * 80)
    print(f"Mobile testing server running at: http://{local_ip}:{port}")
    print(f"Force mobile view: http://{local_ip}:{port}/?device=mobile")
    print(f"Force desktop view: http://{local_ip}:{port}/?device=desktop")
    print("=" * 80)
    
    # Run the app with increased request timeout
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True, 
            use_reloader=True, use_debugger=True) 