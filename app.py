from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_cors import CORS
from llm import ask_dndsy, default_store_type
from vector_store import get_vector_store
import os
from datetime import timedelta
import logging
import json
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Use env var for secret key, fallback for local dev
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) 
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to cookies
CORS(app)

PASSWORD = os.environ.get('APP_PASSWORD', 'dndsy')
logger.info(f"Password loaded from environment variable {'APP_PASSWORD' if 'APP_PASSWORD' in os.environ else '(using default)'}. ")

VECTOR_STORE_TYPES = ["standard", "semantic"]
DEFAULT_VECTOR_STORE = default_store_type # Set from llm module

def check_auth():
    """Checks if the current session is authenticated."""
    auth_status = session.get('authenticated', False)
    logger.debug(f"Auth status: {auth_status}")
    return auth_status

@app.route('/health')
def health():
    """Basic health check endpoint."""
    return jsonify({'status': 'healthy'}), 200

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login."""
    if request.method == 'POST':
        submitted_password = request.form.get('password')
        logger.debug(f"Submitted password: {submitted_password}")
        # logger.debug(f"Expected password: {PASSWORD}") # Avoid logging expected password
        # logger.debug(f"Password match: {submitted_password == PASSWORD}")
        
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
    """Renders the main chat page if authenticated."""
    if not check_auth():
        return redirect(url_for('login'))
    
    # Get LLM model info for display
    llm_model = os.environ.get('LLM_MODEL_NAME', 'Default Model')
    
    return render_template('index.html', 
                          vector_store_types=VECTOR_STORE_TYPES,
                          default_vector_store=DEFAULT_VECTOR_STORE,
                          llm_model=llm_model)

@app.route('/api/chat')
def chat():
    """Handles the chat message submission and streams the RAG response."""
    if not check_auth():
        return Response(f"event: error\ndata: {json.dumps({'error': 'Unauthorized'})}\n\n", status=401, mimetype='text/event-stream')
        
    user_message = request.args.get('message', '') 
    vector_store_type = request.args.get('vector_store_type', None)
    
    if vector_store_type and vector_store_type not in VECTOR_STORE_TYPES:
        return Response(f"event: error\ndata: {json.dumps({'error': f'Invalid vector store type: {vector_store_type}'})}\n\n", 
                       status=400, mimetype='text/event-stream')
    
    if not user_message:
         return Response(f"event: error\ndata: {json.dumps({'error': 'No message provided'})}\n\n", status=400, mimetype='text/event-stream')

    # Return the Server-Sent Events stream from the RAG function
    return Response(ask_dndsy(user_message, store_type=vector_store_type), mimetype='text/event-stream')

@app.route('/api/get_context_details')
def get_context_details():
    """API endpoint to fetch specific context details (text, image) for the source viewer."""
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

    if vector_store_type not in VECTOR_STORE_TYPES:
        return jsonify({'error': f'Invalid vector store type: {vector_store_type}'}), 400
    
    logger.info(f"Fetching details for source: '{source_name}', page: {page_number}, store type: {vector_store_type}")
    
    try:
        vector_store = get_vector_store(vector_store_type)
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
    """Return available vector store types and the default."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify({
        'types': VECTOR_STORE_TYPES,
        'default': DEFAULT_VECTOR_STORE
    })

@app.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    session.clear()
    return redirect(url_for('login'))

@app.route('/api/gpu_status')
def gpu_status():
    """API endpoint to check GPU availability and status."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        device_count = torch.cuda.device_count() if gpu_available else 0
        device_names = [torch.cuda.get_device_name(i) for i in range(device_count)] if gpu_available else []
        
        return jsonify({
            'gpu_available': gpu_available,
            'device_count': device_count,
            'device_names': device_names,
            'torch_version': torch.__version__
        })
    except Exception as e:
        logger.error(f"Error checking GPU status: {e}", exc_info=True)
        return jsonify({'error': f'Error checking GPU status: {str(e)}'}), 500

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    load_dotenv(override=True) # Ensure .env overrides system vars if running directly
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Running in {'debug' if debug_mode else 'production'} mode on port {port}")
    # Use host='0.0.0.0' to be accessible on the network
    app.run(debug=debug_mode, host='0.0.0.0', port=port) 