from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_cors import CORS
from llm import ask_dndsy, default_vector_store
from vector_store import get_vector_store
import os
from datetime import timedelta
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Use env var for secret key, fallback for local dev
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # Session lasts for 30 days
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to cookies
CORS(app)

PASSWORD = os.environ.get('APP_PASSWORD', 'dndsy')  # Get password from env var or use default
logger.info(f"Password loaded from environment variable {'APP_PASSWORD' if 'APP_PASSWORD' in os.environ else '(using default)'}. ")

# Vector store types
VECTOR_STORE_TYPES = ["standard", "semantic"]
DEFAULT_VECTOR_STORE = os.environ.get('DEFAULT_VECTOR_STORE', 'semantic')

def check_auth():
    auth_status = session.get('authenticated', False)
    logger.debug(f"Auth status: {auth_status}")
    return auth_status

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'}), 200

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        submitted_password = request.form.get('password')
        logger.debug(f"Submitted password: {submitted_password}")
        logger.debug(f"Expected password: {PASSWORD}")
        logger.debug(f"Password match: {submitted_password == PASSWORD}")
        
        if submitted_password == PASSWORD:
            session['authenticated'] = True
            logger.info("Login successful")
            if request.form.get('remember'):
                session.permanent = True
                logger.debug("Remember me enabled")
            return redirect(url_for('home'))
        logger.warning("Login failed - incorrect password")
        return render_template('login.html', error="Incorrect password")
    return render_template('login.html', error=None)

@app.route('/')
def home():
    if not check_auth():
        return redirect(url_for('login'))
    
    # Get LLM model info
    llm_model = os.environ.get('LLM_MODEL_NAME', 'Default Model')
    
    return render_template('index.html', 
                          vector_store_types=VECTOR_STORE_TYPES,
                          default_vector_store=DEFAULT_VECTOR_STORE,
                          llm_model=llm_model)

@app.route('/api/chat')
def chat():
    if not check_auth():
        return Response(f"event: error\ndata: {json.dumps({'error': 'Unauthorized'})}\n\n", status=401, mimetype='text/event-stream')
        
    # Read message from query parameters for SSE
    user_message = request.args.get('message', '') 
    
    # Get vector store type from request
    vector_store_type = request.args.get('vector_store_type', None)
    
    # Validate vector store type
    if vector_store_type and vector_store_type not in VECTOR_STORE_TYPES:
        return Response(f"event: error\ndata: {json.dumps({'error': f'Invalid vector store type: {vector_store_type}'})}\n\n", 
                       status=400, mimetype='text/event-stream')
    
    if not user_message:
         return Response(f"event: error\ndata: {json.dumps({'error': 'No message provided'})}\n\n", status=400, mimetype='text/event-stream')

    # Return a streaming response
    # Pass vector_store_type to ask_dndsy
    return Response(ask_dndsy(user_message, store_type=vector_store_type), mimetype='text/event-stream')

@app.route('/api/get_context_details')
def get_context_details():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    source_name = request.args.get('source')
    page_number_str = request.args.get('page')
    vector_store_type = request.args.get('vector_store_type', DEFAULT_VECTOR_STORE)

    if not source_name or not page_number_str:
        return jsonify({'error': 'Missing source or page parameter'}), 400

    try:
        page_number = int(page_number_str)
    except ValueError:
        return jsonify({'error': 'Invalid page number'}), 400

    # Validate vector store type
    if vector_store_type not in VECTOR_STORE_TYPES:
        return jsonify({'error': f'Invalid vector store type: {vector_store_type}'}), 400
    
    logger.info(f"Fetching details for source: '{source_name}', page: {page_number}, store type: {vector_store_type}")
    
    try:
        # Get the appropriate vector store
        vector_store = get_vector_store(vector_store_type)
        
        # Attempt to get details from the vector store
        details = vector_store.get_details_by_source_page(source_name, page_number)
        
        if details:
            logger.info(f"Found details: image_url exists = {details.get('image_url') is not None}")
            return jsonify(details)
        else:
            logger.warning(f"No details found for source: '{source_name}', page: {page_number}")
            return jsonify({'error': 'Context details not found'}), 404
            
    except Exception as e:
        logger.error(f"Error fetching context details for '{source_name}' page {page_number}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error fetching context details'}), 500

@app.route('/api/vector_stores')
def get_vector_store_types():
    """Return available vector store types"""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify({
        'types': VECTOR_STORE_TYPES,
        'default': DEFAULT_VECTOR_STORE
    })

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Running in {'debug' if debug_mode else 'production'} mode on port {port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port) 