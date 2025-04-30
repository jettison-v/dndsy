from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_cors import CORS
from llm import ask_dndsy, reinitialize_llm_client
from vector_store import get_vector_store
import os
from datetime import timedelta, datetime
import logging
import json
from dotenv import load_dotenv
from flask_session import Session
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from werkzeug.utils import secure_filename
import subprocess
import threading
import io
from qdrant_client import QdrantClient
from qdrant_client.http.models import CollectionDescription
import requests
import uuid
import time
from pathlib import Path
from queue import Queue, Empty
import collections
from config import app_config, update_app_config, default_store_type, S3_BUCKET_NAME, IS_DEV_ENV
from functools import wraps
from utils.device_detection import get_device_type

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global Configuration Dictionary ---
# Moved to config.py

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Use env var for secret key, fallback for local dev
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) 
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to cookies
app.config['SESSION_TYPE'] = 'filesystem'  # Add filesystem session type
CORS(app)
Session(app)

# Helper function to validate and update configuration
# Moved to config.py

PASSWORD = os.environ.get('APP_PASSWORD', 'dndsy')
logger.info(f"Password loaded from environment variable {'APP_PASSWORD' if 'APP_PASSWORD' in os.environ else '(using default)'}. ")

VECTOR_STORE_TYPES = ["pages", "semantic", "haystack-qdrant", "haystack-memory"]
# Get default store type from environment
# DEFAULT_VECTOR_STORE = os.getenv("DEFAULT_VECTOR_STORE", "pages")

# Define available LLM models with their display names
AVAILABLE_LLM_MODELS = {
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
    "gpt-4": "GPT-4",
    "gpt-4-turbo": "GPT-4 Turbo"
}

# Path for the new run history file
RUN_HISTORY_FILE = Path(__file__).parent / "data" / "admin_processing_runs.json"
RUN_HISTORY_S3_KEY = "processing/admin_processing_runs.json"  # S3 path for run history
RUN_HISTORY_LOCK = threading.Lock() # Lock for thread-safe file access

# Dictionary to hold active run queues for SSE streaming
# Key: run_id, Value: Queue
active_runs = {}
RUN_LOCK = threading.Lock() # Lock for accessing active_runs dictionary

def read_run_history():
    """
    Reads the run history JSON file from S3 or local file.
    First tries to get from S3, falls back to local file.
    """
    with RUN_HISTORY_LOCK:
        history_data = []
        
        # First try to get from S3
        s3_client = get_s3_client()
        if s3_client:
            try:
                bucket_name = os.environ.get('AWS_S3_BUCKET_NAME')
                if bucket_name:
                    logger.info(f"Attempting to read run history from S3: {RUN_HISTORY_S3_KEY}")
                    response = s3_client.get_object(
                        Bucket=bucket_name,
                        Key=RUN_HISTORY_S3_KEY
                    )
                    history_data = json.loads(response['Body'].read().decode('utf-8'))
                    logger.info(f"Successfully loaded run history from S3")
                    
                    # Also save it locally as a backup
                    try:
                        RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
                        with open(RUN_HISTORY_FILE, 'w') as f:
                            json.dump(history_data, f, indent=2)
                        logger.info(f"Saved S3 run history locally to {RUN_HISTORY_FILE}")
                        return history_data
                    except IOError as e:
                        logger.error(f"Could not write local run history backup: {e}")
                        # Continue with S3 data even if local write fails
                        return history_data
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    logger.info(f"Run history file not found in S3, will try local file")
                else:
                    logger.warning(f"S3 error accessing run history: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error loading run history from S3: {e}")
        
        # If S3 fails or isn't configured, try local file
        if RUN_HISTORY_FILE.exists():
            try:
                with open(RUN_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error reading local run history file: {e}")
                return []
        
        # If all else fails, return empty list
        return []

def write_run_history(history_data):
    """
    Writes the run history JSON file to both S3 and local storage.
    """
    with RUN_HISTORY_LOCK:
        # First save locally as a backup
        try:
            RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RUN_HISTORY_FILE, 'w') as f:
                json.dump(history_data, f, indent=2)
            logger.info(f"Saved run history to local file")
        except IOError as e:
            logger.error(f"Error writing local run history file: {e}")
        
        # Then save to S3
        s3_client = get_s3_client()
        if s3_client:
            try:
                bucket_name = os.environ.get('AWS_S3_BUCKET_NAME')
                if bucket_name:
                    history_json = json.dumps(history_data)
                    s3_client.put_object(
                        Bucket=bucket_name,
                        Key=RUN_HISTORY_S3_KEY,
                        Body=history_json,
                        ContentType='application/json'
                    )
                    logger.info(f"Saved run history to S3: {RUN_HISTORY_S3_KEY}")
            except Exception as e:
                logger.error(f"Failed to save run history to S3: {e}")
                # Continue even if S3 save fails

def check_auth():
    """Checks if the current session is authenticated."""
    auth_status = session.get('authenticated', False)
    logger.debug(f"Auth status: {auth_status}")
    return auth_status

def requires_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_auth():
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

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
        
        # Get device type for appropriate template
        device_type = get_device_type(request)
        if device_type == 'mobile':
            return render_template('mobile/mobile-login.html', error="Incorrect password")
        else:
            return render_template('login.html', error="Incorrect password")
            
    # GET request - show login form
    device_type = get_device_type(request)
    if device_type == 'mobile':
        return render_template('mobile/mobile-login.html', error=None)
    else:
        return render_template('login.html', error=None)

@app.route('/')
def home():
    """Renders the main chat page if authenticated."""
    if not check_auth():
        return redirect(url_for('login'))
    
    # Get LLM model info for display
    current_llm_model = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    # Detect device type
    device_type = get_device_type(request)
    
    # Serve different templates based on device type
    if device_type == 'mobile':
        return render_template('mobile/mobile-index.html', 
                              vector_store_types=VECTOR_STORE_TYPES,
                              default_vector_store=default_store_type,
                              llm_model=current_llm_model,
                              available_llm_models=AVAILABLE_LLM_MODELS)
    else:
        # Desktop and tablet use the standard template
        return render_template('index.html', 
                              vector_store_types=VECTOR_STORE_TYPES,
                              default_vector_store=default_store_type,
                              llm_model=current_llm_model,
                              available_llm_models=AVAILABLE_LLM_MODELS)

@app.route('/toggle-view/<view_type>')
def toggle_view(view_type):
    """Toggle between mobile and desktop views."""
    if not check_auth():
        return redirect(url_for('login'))
    
    # Set cookie for view preference
    response = redirect(url_for('home'))
    if view_type in ['mobile', 'desktop']:
        response.set_cookie('preferred_view', view_type, max_age=30*24*60*60)  # 30 days
    
    return response

@app.route('/api/chat')
def chat():
    """Handles the chat message submission and streams the RAG response."""
    if not check_auth():
        return Response(f"event: error\ndata: {json.dumps({'error': 'Unauthorized'})}\n\n", status=401, mimetype='text/event-stream')
        
    user_message = request.args.get('message', '') 
    vector_store_type = request.args.get('vector_store_type', None)
    model = request.args.get('model', None)
    
    if vector_store_type and vector_store_type not in VECTOR_STORE_TYPES:
        return Response(f"event: error\ndata: {json.dumps({'error': f'Invalid vector store type: {vector_store_type}'})}\n\n", 
                       status=400, mimetype='text/event-stream')
    
    if not user_message:
         return Response(f"event: error\ndata: {json.dumps({'error': 'No message provided'})}\n\n", status=400, mimetype='text/event-stream')
    
    # If model is provided and valid, set it for this request
    if model and model in AVAILABLE_LLM_MODELS:
        current_model = os.environ.get('LLM_MODEL_NAME')
        if model != current_model:
            os.environ['LLM_MODEL_NAME'] = model
            reinitialize_llm_client()
            # Update app_config to match
            app_config["llm_model"] = model
    else:
        # Use the model from app_config
        model = app_config["llm_model"]
    
    # Get other parameters from app_config (use the vector_store_type from request if provided)
    effective_store_type = vector_store_type or app_config["vector_store_type"]
    
    # Return the Server-Sent Events stream from the RAG function, passing all config parameters
    return Response(
        ask_dndsy(
            prompt=user_message, 
            store_type=effective_store_type,
            temperature=app_config["llm_temperature"],
            max_tokens=app_config["llm_max_output_tokens"],
            retrieval_limit=app_config["retrieval_k"],
            max_tokens_per_result=app_config["context_max_tokens_per_result"],
            max_total_context_tokens=app_config["context_max_total_tokens"],
            rerank_alpha=app_config["rerank_alpha"],
            rerank_beta=app_config["rerank_beta"],
            rerank_gamma=app_config["rerank_gamma"],
            fetch_multiplier=app_config["retrieval_fetch_multiplier"]
        ), 
        mimetype='text/event-stream'
    )

@app.route('/api/get_context_details')
def get_context_details():
    """API endpoint to fetch specific context details (text, image) for the source viewer."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    source_name = request.args.get('source')
    page_number_str = request.args.get('page')
    vector_store_type = request.args.get('vector_store_type', default_store_type)

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
        # Special handling for haystack-memory when empty
        if vector_store_type == 'haystack-memory':
            # Check if the directory exists and if it contains any PKL files
            haystack_dir = os.path.join('data', 'haystack_store')
            if not os.path.exists(haystack_dir) or not any(f.endswith('.pkl') for f in os.listdir(haystack_dir)):
                # Return a helpful message instead of a 404
                return jsonify({
                    'text': "The Haystack Memory store is empty. Please process documents using:\npython scripts/manage_vector_stores.py --only-haystack --haystack-type haystack-memory",
                    'metadata': {},
                    'image_url': None,
                    'total_pages': None,
                    'needs_processing': True
                })
        
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
        'default': default_store_type
    })

@app.route('/api/store_stats')
def get_store_stats():
    """Returns statistics about the vector stores for debugging."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    store_type = request.args.get('store_type', None)
    if store_type and store_type not in VECTOR_STORE_TYPES:
        return jsonify({'error': f'Invalid vector store type: {store_type}'}), 400
    
    stats = {}
    sample_count = 3  # Number of sample documents to return per store
    
    if store_type:
        types_to_check = [store_type]
    else:
        types_to_check = VECTOR_STORE_TYPES
    
    for store_type in types_to_check:
        try:
            vector_store = get_vector_store(store_type)
            all_docs = vector_store.get_all_documents()
            doc_count = len(all_docs)
            
            # Get sample documents
            sample_docs = all_docs[:sample_count] if doc_count > 0 else []
            
            # Format sample docs for display
            formatted_samples = []
            for doc in sample_docs:
                formatted_samples.append({
                    'text': doc.get('text', '')[:200] + '...' if len(doc.get('text', '')) > 200 else doc.get('text', ''),
                    'metadata': doc.get('metadata', {})
                })
            
            stats[store_type] = {
                'count': doc_count,
                'sample_documents': formatted_samples
            }
            
        except Exception as e:
            logger.error(f"Error getting stats for {store_type}: {e}", exc_info=True)
            stats[store_type] = {'error': str(e)}
    
    return jsonify(stats)

@app.route('/api/change_model', methods=['POST'])
def change_model():
    """Changes the LLM model to use for subsequent requests."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    model_name = data.get('model')
    
    if not model_name or model_name not in AVAILABLE_LLM_MODELS:
        return jsonify({'error': 'Invalid model name'}), 400
    
    # Update the environment variable
    os.environ['LLM_MODEL_NAME'] = model_name
    
    # Reinitialize the LLM client to use the new model
    reinitialize_llm_client()
    
    logger.info(f"Model changed to {model_name} ({AVAILABLE_LLM_MODELS[model_name]})")
    
    return jsonify({
        'success': True,
        'model': model_name,
        'display_name': AVAILABLE_LLM_MODELS[model_name]
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

@app.route('/api/get_pdf_image')
def get_pdf_image():
    """API endpoint to fetch images from S3 and serve them to clients.
    Handles S3 URLs and serves the image directly to the client.
    """
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    key = request.args.get('key')
    if not key:
        return jsonify({'error': 'Missing key parameter'}), 400
    
    # Parse the s3 URL format (s3://bucket/path)
    if not key.startswith('s3://'):
        return jsonify({'error': 'Invalid S3 URL format, must start with s3://'}), 400
    
    try:
        s3_url = key
        s3_parts = s3_url.replace('s3://', '').split('/')
        bucket = s3_parts[0]
        key_path = '/'.join(s3_parts[1:])
        
        # Get S3 client
        s3_client = get_s3_client()
        if not s3_client:
            return jsonify({'error': 'S3 client not available'}), 500
        
        logger.info(f"Fetching PDF image from S3: bucket={bucket}, key={key_path}")
        
        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key_path)
        image_data = response['Body'].read()
        
        # Determine content type based on file extension
        content_type = 'image/jpeg'  # Default
        if key_path.lower().endswith('.png'):
            content_type = 'image/png'
        elif key_path.lower().endswith('.gif'):
            content_type = 'image/gif'
        elif key_path.lower().endswith('.webp'):
            content_type = 'image/webp'
        
        # Return the image data with appropriate content type
        return Response(image_data, content_type=content_type)
        
    except NoCredentialsError:
        logger.error("AWS credentials not found")
        return jsonify({'error': 'AWS credentials not found'}), 500
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"S3 client error retrieving image: {error_code}")
        if error_code == 'NoSuchKey':
            return jsonify({'error': 'Image not found in S3'}), 404
        else:
            return jsonify({'error': f'S3 client error: {error_code}'}), 500
    except Exception as e:
        logger.error(f"Error retrieving PDF image from S3: {e}", exc_info=True)
        return jsonify({'error': f'Error retrieving image: {str(e)}'}), 500

# =============================================================================
# Admin API Routes
# =============================================================================

@app.route('/api/admin/process', methods=['POST'])
def admin_process():
    """API endpoint to trigger processing and provide a run_id for streaming."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get request data
    data = request.json
    if not data:
        return jsonify({'error': 'Missing request data'}), 400
    
    store_types = data.get('store_types', [])
    cache_behavior = data.get('cache_behavior', 'use')
    s3_prefix = data.get('s3_prefix', None)
    
    if not store_types:
        return jsonify({'error': 'No store types specified'}), 400
    
    if cache_behavior not in ['use', 'rebuild']:
        return jsonify({'error': 'Invalid cache behavior'}), 400
    
    # Create command arguments
    cmd_args = ['python', '-m', 'scripts.manage_vector_stores']
    
    # Simplified logic for adding store types
    valid_store_types = [st for st in store_types if st in VECTOR_STORE_TYPES]
    if not valid_store_types:
         return jsonify({'error': 'No valid store types specified'}), 400
         
    if set(valid_store_types) == set(VECTOR_STORE_TYPES):
         cmd_args.extend(['--store', 'all'])
    else:
         for st in valid_store_types:
             cmd_args.extend(['--store', st])

    cmd_args.extend(['--cache-behavior', cache_behavior])
    
    if s3_prefix:
        cmd_args.extend(['--s3-pdf-prefix', s3_prefix])
        
    run_id = str(uuid.uuid4())
    start_time = datetime.now().isoformat()
    
    # Create a queue for this run's messages
    message_queue = Queue()

    run_info = {
        "run_id": run_id,
        "start_time": start_time,
        "parameters": {
            "store_types": valid_store_types,
            "cache_behavior": cache_behavior,
            "s3_prefix": s3_prefix
        },
        "command": ' '.join(cmd_args),
        "status": "Running",
        "end_time": None,
        "duration_seconds": None,
        "log": "Processing started...",
        "return_code": None
    }

    # Add run to history (initial state)
    history = read_run_history()
    history.insert(0, run_info)
    write_run_history(history)

    # Store the queue and initialize process entry for SSE streaming
    with RUN_LOCK:
        active_runs[run_id] = {
            'queue': message_queue,      # Queue for this run's status messages
            'process': None            # Placeholder for the subprocess.Popen object
        }

    # Run the command in a separate thread
    def run_process(current_run_id, command_args, msg_queue):
        """Runs the management script in a subprocess and streams output.

        Captures stdout, parses JSON status updates, and puts them on the msg_queue.
        Handles process termination and updates the persistent run history file.
        """
        log_capture = io.StringIO() # Captures the raw log output for history
        process_start_time = time.time()
        final_status = "Unknown" # Track the final status reported by the script
        final_success = False
        final_duration = None
        return_code = -1
        process = None # Define process variable here
        
        try:
            process = subprocess.Popen(
                command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1 
            )
            
            # Store the process object in active_runs dictionary for potential cancellation
            with RUN_LOCK:
                if current_run_id in active_runs:
                    active_runs[current_run_id]['process'] = process
                else:
                    # Should not happen if started correctly, but handle defensively
                    logger.warning(f"Run ID {current_run_id} not found in active_runs when storing process object.")
                    # Attempt to terminate the process if we can't track it
                    try:
                         process.terminate()
                    except Exception as term_err:
                         logger.error(f"Failed to terminate untracked process: {term_err}")
                    raise Exception("Run ID missing from active runs, cannot track process.")

            initial_log = f"Starting process with command: {' '.join(command_args)}\n" + "-" * 30 + "\n"
            log_capture.write(initial_log)
            # Send initial log lines via queue as well
            msg_queue.put({"type": "log", "message": initial_log.strip()})

            # Read and process output line by line
            for line in iter(process.stdout.readline, ''):
                clean_line = line.strip()
                if not clean_line:
                    continue # Skip empty lines
                
                log_capture.write(clean_line + "\n") # Capture all output for final log
                
                # Attempt to parse as JSON status update
                parsed_as_status = False
                try:
                    status_update = json.loads(clean_line)
                    if isinstance(status_update, dict) and 'type' in status_update:
                        # Put the structured update onto the queue
                        msg_queue.put(status_update)
                        parsed_as_status = True # Flag that we handled this line as a status update
                        
                        # Check for final status message from script
                        if status_update.get('type') == 'end':
                            final_success = status_update.get('success', False)
                            final_duration = status_update.get('duration')
                            final_status = "Success" if final_success else "Failed (Script Error)"
                    # else: it was valid JSON but not a status update - treat as log below
                except json.JSONDecodeError:
                    # Line is not JSON - treat as log below
                    pass 
                
                # If the line wasn't handled as a structured status update, send it as a log message
                if not parsed_as_status:
                    logger.info(f"Processing Log [{current_run_id}]: {clean_line}") # Log non-status lines locally
                    msg_queue.put({"type": "log", "message": clean_line})
            
            process.wait()
            return_code = process.returncode
            logger.info(f"Subprocess [{current_run_id}] finished with exit code {return_code}")

            # Determine final status based on script output and exit code
            if final_status == "Unknown": # If script didn't send 'end' status
                final_success = (return_code == 0)
                final_status = "Success" if final_success else f"Failed (Exit Code {return_code})"
            elif return_code != 0 and final_success: # Script said success but exited non-zero
                 final_status = f"Warning (Finished with exit code {return_code} despite success status)"
                 final_success = False # Treat as failure overall
            
            end_log = "-" * 30 + f"\nProcess finished with exit code: {return_code} ({final_status})\n"
            log_capture.write(end_log)
            msg_queue.put({"type": "log", "message": end_log.strip()})
            
        except Exception as e:
            error_message = f"Error running document processing [{current_run_id}]: {e}"
            logger.error(error_message, exc_info=True)
            log_capture.write("\n!!! ERROR DURING FLASK EXECUTION !!!\n")
            log_capture.write(error_message + "\n")
            final_status = "Failed (Flask Exception)"
            final_success = False
            return_code = -1
            try:
                # Try to put the error on the queue for the frontend
                msg_queue.put({"type": "error", "message": error_message})
            except Exception as q_err:
                logger.error(f"Failed to put Flask exception onto queue: {q_err}")
                
        finally:
            # Signal end of messages for this run to the SSE stream
            msg_queue.put({"type": "end", "success": final_success, "status": final_status, "duration": final_duration})
            
            end_time = datetime.now().isoformat()
            # Calculate duration if script didn't provide it
            if final_duration is None:
                final_duration = time.time() - process_start_time
            
            # Update history entry with final details
            updated_history = read_run_history()
            for run in updated_history:
                if run["run_id"] == current_run_id:
                    run["status"] = final_status
                    run["end_time"] = end_time
                    run["duration_seconds"] = round(final_duration, 2)
                    run["log"] = log_capture.getvalue()
                    run["return_code"] = return_code
                    break # Found the run, no need to continue
            write_run_history(updated_history)
            log_capture.close()
            
            # Remove run from active dictionary
            with RUN_LOCK:
                if current_run_id in active_runs:
                    del active_runs[current_run_id]
                    logger.info(f"Removed run {current_run_id} from active runs.")

    # Start the background thread
    thread = threading.Thread(target=run_process, args=(run_id, cmd_args, message_queue))
    thread.daemon = True # Allow Flask to exit even if thread is running
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f"Processing run '{run_id}' started.",
        'run_id': run_id
    })

@app.route('/api/admin/history')
def admin_history():
    """API endpoint to get PDF processing RUN history."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Read the new run history file
    history = read_run_history()
    
    # Optionally limit the history size returned
    max_history = 50 
    return jsonify(history[:max_history])

@app.route('/api/admin/process_stream/<run_id>')
def admin_process_stream(run_id):
    """SSE endpoint to stream processing status for a given run_id."""
    if not check_auth():
        return Response("event: error\ndata: {\"error\": \"Unauthorized\"}\n\n", status=401, mimetype='text/event-stream')

    logger.info(f"SSE connection requested for run_id: {run_id}")

    # Define the generator function for SSE
    def generate_updates():
        """Generator function to yield SSE messages from the run's queue."""
        msg_queue = None
        with RUN_LOCK:
            if run_id in active_runs:
                msg_queue = active_runs[run_id]['queue']
            else:
                # Check if run recently finished and might still be in history
                history = read_run_history()
                recent_run = next((r for r in history if r["run_id"] == run_id), None)
                if recent_run and recent_run["status"] != "Running":
                    # Run already finished, send final status from history
                    logger.warning(f"SSE requested for completed run {run_id}. Sending final status.")
                    final_data = {
                        "type": "end",
                        "success": recent_run["status"] == "Success",
                        "status": recent_run["status"],
                        "duration": recent_run.get("duration_seconds")
                    }
                    yield f"event: end\ndata: {json.dumps(final_data)}\n\n"
                    return # End the stream
                else:
                     logger.error(f"Run ID {run_id} not found in active runs or recent history.")
                     yield f"event: error\ndata: {json.dumps({'error': 'Run ID not found or invalid'})}\n\n"
                     return # End the stream

        if msg_queue is None:
            # Should not happen if logic above is correct, but handle defensively
             logger.error(f"Queue not found for run ID {run_id} despite being in active_runs.")
             yield f"event: error\ndata: {json.dumps({'error': 'Internal server error: Queue not found'})}\n\n"
             return

        logger.info(f"SSE stream started for run_id: {run_id}")
        
        keep_streaming = True
        while keep_streaming:
            try:
                # Wait for a message from the queue (with timeout)
                message = msg_queue.get(timeout=1)
                
                # Determine event type based on message content
                event_type = message.get('type', 'update') # Default to 'update'
                if event_type == 'end':
                    keep_streaming = False # Stop after sending the end event
                    event_type = 'end' # Ensure correct event name for final message
                elif event_type == 'error':
                     event_type = 'error' # Ensure correct event name for errors
                else:
                    event_type = 'update' # Use 'update' for log, milestone, progress etc.
                
                # Format and yield the message
                yield f"event: {event_type}\ndata: {json.dumps(message)}\n\n"
                
                # If it was the end message, break the loop
                if not keep_streaming:
                     logger.info(f"End message received for {run_id}. Closing SSE stream.")
                     break
                     
            except Empty:
                # Timeout - check if the run is still active
                with RUN_LOCK:
                    if run_id not in active_runs:
                        logger.warning(f"Run {run_id} disappeared from active runs. Closing SSE stream.")
                        # Send a final generic end event if the run vanished unexpectedly
                        yield f"event: end\ndata: {json.dumps({'type': 'end', 'success': False, 'status': 'Unknown (Stream Interrupted)', 'duration': None})}\n\n"
                        keep_streaming = False
                        break
                # If still active, just continue waiting for messages
                pass 
            except Exception as e:
                logger.error(f"Error in SSE generator for run {run_id}: {e}", exc_info=True)
                # Try to send an error to the client
                try:
                    yield f"event: error\ndata: {json.dumps({'error': f'Stream error: {e}'})}\n\n"
                except Exception:
                    pass # Ignore if yield fails
                keep_streaming = False # Stop streaming on error
                break
        
        logger.info(f"SSE stream finished for run_id: {run_id}")

    # Return the SSE response
    return Response(generate_updates(), mimetype='text/event-stream')

@app.route('/api/admin/run_log/<run_id>')
def admin_run_log(run_id):
    """API endpoint to get the log for a specific processing run."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
        
    history = read_run_history()
    run_log = None
    for run in history:
        if run.get("run_id") == run_id:
            run_log = run.get("log", "Log not found for this run.")
            break
            
    if run_log is None:
        return jsonify({'error': f'Run ID {run_id} not found'}), 404
        
    # Return log content as plain text
    return Response(run_log, mimetype='text/plain')

@app.route('/api/admin/upload', methods=['POST'])
def admin_upload():
    """API endpoint to upload a PDF file to S3."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Only PDF files are allowed'}), 400
    
    try:
        # Get S3 client
        s3_client = get_s3_client()
        if not s3_client:
            return jsonify({'error': 'S3 client not configured'}), 500
        
        # Prepare file for upload
        filename = secure_filename(file.filename)
        prefix = request.form.get('prefix', os.environ.get('AWS_S3_PDF_PREFIX', 'source-pdfs/'))
        
        # Ensure prefix ends with a slash
        if prefix and not prefix.endswith('/'):
            prefix += '/'
        
        # Set the S3 key
        s3_key = f"{prefix}{filename}"
        
        # Upload to S3
        file_content = file.read()  # Read file into memory
        s3_client.put_object(
            Bucket=os.environ.get('AWS_S3_BUCKET_NAME'),
            Key=s3_key,
            Body=file_content,
            ContentType='application/pdf'
        )
        
        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'key': s3_key
        })
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        return jsonify({'error': f'Error uploading file: {str(e)}'}), 500

@app.route('/api/admin/list-pdfs')
def admin_list_pdfs():
    """API endpoint to list PDF files in S3."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Get S3 client
        s3_client = get_s3_client()
        if not s3_client:
            return jsonify({'error': 'S3 client not configured'}), 500
        
        # List objects in bucket with PDF extension
        bucket_name = os.environ.get('AWS_S3_BUCKET_NAME')
        prefix = os.environ.get('AWS_S3_PDF_PREFIX', 'source-pdfs/')
        
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
        pdfs = []
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if key.lower().endswith('.pdf'):
                        pdfs.append({
                            'key': key,
                            'size': obj["Size"],
                            'last_modified': obj["LastModified"].isoformat()
                        })
        
        return jsonify({
            'success': True,
            'pdfs': pdfs
        })
    except Exception as e:
        logger.error(f"Error listing PDFs: {e}", exc_info=True)
        return jsonify({'error': f'Error listing PDFs: {str(e)}'}), 500

@app.route('/api/admin/delete-pdf', methods=['POST'])
def admin_delete_pdf():
    """API endpoint to delete a PDF file from S3."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    if not data or 'key' not in data:
        return jsonify({'error': 'Missing PDF key'}), 400
    
    key = data['key']
    
    try:
        # Get S3 client
        s3_client = get_s3_client()
        if not s3_client:
            return jsonify({'error': 'S3 client not configured'}), 500
        
        # Delete object from S3
        s3_client.delete_object(
            Bucket=os.environ.get('AWS_S3_BUCKET_NAME'),
            Key=key
        )
        
        return jsonify({
            'success': True,
            'message': f'PDF deleted: {key}'
        })
    except Exception as e:
        logger.error(f"Error deleting PDF: {e}", exc_info=True)
        return jsonify({'error': f'Error deleting PDF: {str(e)}'}), 500

@app.route('/api/admin/collections')
def admin_collections():
    """API endpoint to get Qdrant collection information."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # Get Qdrant client
        qdrant_client = get_qdrant_client()
        if not qdrant_client:
            return jsonify({'error': 'Qdrant client not configured'}), 500
        
        # Get collections list
        collections = qdrant_client.get_collections().collections
        
        # Get details for each collection
        collection_details = []
        for collection in collections:
            try:
                collection_info = qdrant_client.get_collection(collection.name)
                points_count = qdrant_client.count(collection.name).count
                
                collection_details.append({
                    'name': collection.name,
                    'vector_size': collection_info.config.params.vectors.size,
                    'points_count': points_count,
                    'status': 'green' if collection_info.status == 'green' else 'yellow'
                })
            except Exception as e:
                logger.warning(f"Error getting details for collection {collection.name}: {e}")
                collection_details.append({
                    'name': collection.name,
                    'vector_size': 'unknown',
                    'points_count': 0,
                    'status': 'error'
                })
        
        return jsonify({
            'success': True,
            'collections': collection_details
        })
    except Exception as e:
        logger.error(f"Error getting collections: {e}", exc_info=True)
        return jsonify({'error': f'Error getting collections: {str(e)}'}), 500

@app.route('/api/admin/points')
def admin_points():
    """API endpoint to get sample points from a Qdrant collection."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    collection = request.args.get('collection')
    if not collection:
        return jsonify({'error': 'Missing collection parameter'}), 400
    
    limit = int(request.args.get('limit', 5))
    
    try:
        # Get Qdrant client
        qdrant_client = get_qdrant_client()
        if not qdrant_client:
            return jsonify({'error': 'Qdrant client not configured'}), 500
        
        # Get sample points
        points = qdrant_client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )[0]
        
        # Format points for response
        formatted_points = []
        for point in points:
            formatted_points.append({
                'id': point.id,
                'payload': point.payload
            })
        
        return jsonify({
            'success': True,
            'points': formatted_points
        })
    except Exception as e:
        logger.error(f"Error getting points: {e}", exc_info=True)
        return jsonify({'error': f'Error getting points: {str(e)}'}), 500

@app.route('/api/admin/api-costs')
def admin_api_costs():
    """API endpoint to get OpenAI API usage and costs."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # This implementation returns mock data for demonstration purposes.
    # To implement actual usage tracking, you would need to either:
    #
    # 1. Use OpenAI API directly (requires OAuth setup):
    #    - Set up OAuth credentials in the OpenAI dashboard
    #    - Use the OpenAI API's usage endpoints:
    #      https://platform.openai.com/docs/api-reference/usage
    #
    # 2. Implement a local usage tracker:
    #    - Create a database table to log each API call with:
    #      * timestamp, model, prompt_tokens, completion_tokens, total_cost
    #    - Calculate cost based on current pricing for each model
    #    - Aggregate data when this endpoint is called
    #
    # 3. Use OpenAI's export data feature to download usage periodically
    #    and import into your local database
    
    # For now, displaying sample data to demonstrate the UI
    current_month = datetime.now().strftime('%B %Y')
    sample_period = f"Usage for {current_month}"
    
    mock_data = {
        'period': sample_period,
        'total_cost': 28.75,
        'usage': [
            {
                'name': 'gpt-4o-mini',
                'requests': 350,
                'input_tokens': 45000,
                'output_tokens': 15000,
                'cost': 12.75
            },
            {
                'name': 'text-embedding-3-small',
                'requests': 1200,
                'input_tokens': 80000,
                'output_tokens': 0,
                'cost': 8.00
            },
            {
                'name': 'gpt-4',
                'requests': 50,
                'input_tokens': 6000,
                'output_tokens': 2000,
                'cost': 8.00
            }
        ],
        'is_mock_data': True  # Flag to indicate this is sample data
    }
    
    return jsonify(mock_data)

@app.route('/api/admin/config', methods=['GET', 'POST'])
def admin_config():
    """API endpoint to get and update configuration values."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        # Get configuration value(s)
        key = request.args.get('key')
        
        if key:
            # Return a specific configuration value if key is provided
            if key in app_config:
                return jsonify({
                    'success': True,
                    'key': key,
                    'value': app_config[key]
                })
            else:
                return jsonify({'error': f'Unknown configuration key: {key}'}), 400
        else:
            # Return all configuration values if no key is specified
            return jsonify({
                'success': True,
                'config': app_config
            })
    
    else:  # POST request
        # Update configuration value(s)
        data = request.json
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
        
        # If a single key/value pair is provided
        if 'key' in data and 'value' in data:
            key = data['key']
            value = data['value']
            
            # Create a temp dict with just this one key/value pair
            temp_config = {key: value}
            success, message = update_app_config(temp_config)
        else:
            # If a full or partial config object is provided
            success, message = update_app_config(data)
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'config': app_config  # Return the updated config
            })
        else:
            return jsonify({'error': message}), 400

@app.route('/api/admin/env')
def admin_env():
    """API endpoint to get environment variables (safe ones only)."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # List of environment variables to include
    safe_vars = [
        'DEFAULT_VECTOR_STORE',
        'AWS_REGION',
        'AWS_S3_BUCKET_NAME',
        'AWS_S3_PDF_PREFIX',
        'LLM_PROVIDER',
        'LLM_MODEL_NAME',
        'OPENAI_EMBEDDING_MODEL',
        'HAYSTACK_STORE_TYPE',
        'FLASK_DEBUG',
        'FLASK_ENV'
    ]
    
    # Sensitive vars to include with masked values
    sensitive_vars = [
        'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY',
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY',
        'QDRANT_API_KEY',
        'SECRET_KEY'
    ]
    
    env_vars = {}
    
    # Include safe vars with actual values
    for var in safe_vars:
        if var in os.environ:
            env_vars[var] = os.environ.get(var)
    
    # Include sensitive vars with masked values
    for var in sensitive_vars:
        if var in os.environ:
            env_vars[var] = "********"
    
    return jsonify({
        'success': True,
        'env': env_vars
    })

# Helper functions for admin routes

def get_s3_client():
    """Get an S3 client with credentials from environment variables."""
    try:
        aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
        aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')
        
        if not aws_access_key or not aws_secret_key:
            logger.warning("AWS credentials not fully configured")
            return None
        
        return boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
    except Exception as e:
        logger.error(f"Error creating S3 client: {e}", exc_info=True)
        return None

def get_qdrant_client():
    """Get a Qdrant client with credentials from environment variables."""
    try:
        qdrant_host = os.environ.get('QDRANT_HOST')
        qdrant_port = os.environ.get('QDRANT_PORT')
        qdrant_api_key = os.environ.get('QDRANT_API_KEY')
        
        if not qdrant_host:
            logger.warning("Qdrant host not configured")
            return None
        
        # Connect to Qdrant
        if qdrant_port and not qdrant_api_key:
            # Local Qdrant instance
            return QdrantClient(host=qdrant_host, port=int(qdrant_port))
        else:
            # Qdrant Cloud or custom setup with API key
            return QdrantClient(url=qdrant_host, api_key=qdrant_api_key)
    except Exception as e:
        logger.error(f"Error creating Qdrant client: {e}", exc_info=True)
        return None

@app.route('/api/admin/cancel_run/<run_id>', methods=['POST'])
def cancel_run(run_id):
    """Attempts to terminate a running processing script."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    logger.info(f"Cancellation requested for run ID: {run_id}")
    process_terminated = False
    message = ""

    with RUN_LOCK:
        run_details = active_runs.get(run_id)
        if run_details and run_details.get('process'):
            process = run_details['process']
            # Check if the process is still running
            if process.poll() is None: # poll() returns None if process is running
                try:
                    process.terminate() # Send SIGTERM
                    logger.info(f"Sent terminate signal to process for run ID: {run_id}")
                    # Give it a moment to terminate, then check
                    time.sleep(0.5)
                    if process.poll() is None:
                         logger.warning(f"Process {run_id} did not terminate gracefully, sending kill signal.")
                         process.kill() # Send SIGKILL if still running
                    process_terminated = True
                    message = f"Cancellation signal sent to run {run_id}. The process should stop shortly."
                except Exception as e:
                    logger.error(f"Error terminating process for run ID {run_id}: {e}", exc_info=True)
                    message = f"Error attempting to cancel run {run_id}: {e}"
            else:
                logger.warning(f"Attempted to cancel run {run_id}, but process has already finished.")
                message = f"Run {run_id} has already finished."
        else:
            logger.warning(f"Attempted to cancel run {run_id}, but it was not found or process object missing.")
            message = f"Run {run_id} not found or not active."

    return jsonify({'success': process_terminated, 'message': message})

@app.route('/api/admin/inspect-context')
def inspect_context():
    """API endpoint to inspect what context would be retrieved for a query without sending to LLM."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    query = request.args.get('query', '')
    store_type = request.args.get('store_type', default_store_type)
    k = int(request.args.get('k', 5))
    include_detailed = request.args.get('include_detailed', 'false') == 'true'
    include_tokens = request.args.get('include_tokens', 'false') == 'true'
    
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    
    if store_type not in VECTOR_STORE_TYPES:
        return jsonify({'error': f'Invalid vector store type: {store_type}'}), 400
    
    try:
        # Import here to avoid circular dependency
        from llm import _retrieve_and_prepare_context, num_tokens_from_string
        
        # Get the current model name
        import llm
        current_model_name = llm.llm_client.get_model_name() if llm.llm_client else "gpt-4o-mini"
        
        # Get the configs from app_config
        rerank_alpha = app_config["rerank_alpha"]
        rerank_beta = app_config["rerank_beta"]
        rerank_gamma = app_config["rerank_gamma"]
        fetch_multiplier = app_config["retrieval_fetch_multiplier"]
        max_tokens_per_result = app_config["context_max_tokens_per_result"]
        max_total_context_tokens = app_config["context_max_total_tokens"]
        
        # Retrieve context
        start_time = time.time()
        context_parts = _retrieve_and_prepare_context(
            query=query,
            model=current_model_name,
            store_type=store_type,
            limit=k,
            max_tokens_per_result=max_tokens_per_result,
            max_total_context_tokens=max_total_context_tokens,
            rerank_alpha=rerank_alpha,
            rerank_beta=rerank_beta,
            rerank_gamma=rerank_gamma,
            fetch_multiplier=fetch_multiplier
        )
        retrieval_time = time.time() - start_time
        
        # Generate system prompt with context
        system_prompt = app_config["system_prompt"]
        
        context_text_for_prompt = ""
        if context_parts:
            for part in context_parts:
                # Format source display text
                display_text = f"{part['source']} (Pg {part['page']})"
                if part.get('chunk_info'): 
                    display_text += f" - {part['chunk_info']}"
                
                # Append context to the text block for the LLM prompt
                context_text_for_prompt += f"Source: {display_text}\nContent:\n{part['text']}\n\n"
                
        # Add context to system prompt if available
        complete_system_prompt = system_prompt
        if context_text_for_prompt:
            complete_system_prompt += (
                "\n\nUse the following official 2024 D&D rules context to answer the question. "
                "Prioritize this information:\n\n---\n"
                f"{context_text_for_prompt}"
                "---\n\nAnswer the user's question based *only* on the context above:"
            )
        else:
            complete_system_prompt += (
                "\n\nWARNING: No specific rule context was found for this query. "
                "Answer based on your general knowledge of D&D 2024 rules, "
                "but explicitly state that the information is not from the provided source materials.\n"
            )
        
        # Calculate token counts for analysis
        total_tokens = 0
        prompt_tokens = num_tokens_from_string(complete_system_prompt, model=current_model_name)
        user_tokens = num_tokens_from_string(query, model=current_model_name)
        
        # Prepare results
        results = {
            'context_parts': context_parts,
            'retrieval_time': round(retrieval_time, 3),
            'context_count': len(context_parts),
            'system_prompt': complete_system_prompt if include_detailed else None,
            'prompt_tokens': prompt_tokens,
            'user_tokens': user_tokens,
            'total_tokens': prompt_tokens + user_tokens,
            'model': current_model_name,
            'store_type': store_type
        }
        
        # Add per-context token information if requested
        if include_tokens and context_parts:
            token_data = []
            for part in context_parts:
                tokens = num_tokens_from_string(part['text'], model=current_model_name)
                token_data.append({
                    'source': part['source'],
                    'page': part['page'],
                    'tokens': tokens,
                    'percentage': round((tokens / prompt_tokens) * 100, 1)
                })
                total_tokens += tokens
            
            results['token_breakdown'] = token_data
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Error inspecting context: {e}", exc_info=True)
        return jsonify({'error': f'Error inspecting context: {str(e)}'}), 500

@app.route('/api/admin/system-info', methods=['GET'])
@requires_auth
def get_system_info():
    """Get information about the system status and configuration."""
    # Check if we have vector store access
    stores_available = {}
    
    # Check for various vector stores
    for store_type in VECTOR_STORE_TYPES:
        try:
            store = get_vector_store(store_type, force_new=False)
            stores_available[store_type] = {
                "available": True,
                "collection_name": getattr(store, "collection_name", "unknown")
            }
        except Exception as e:
            stores_available[store_type] = {
                "available": False,
                "error": str(e)
            }
    
    # Get info about S3 buckets
    s3_client = get_s3_client()
    s3_info = {
        "available": s3_client is not None,
        "bucket": S3_BUCKET_NAME,
        "environment": "development" if IS_DEV_ENV else "production"
    }
    
    if s3_client:
        try:
            # Check if we can list the bucket
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME, MaxKeys=1)
            s3_info["accessible"] = True
        except Exception as e:
            s3_info["accessible"] = False
            s3_info["error"] = str(e)
    
    # System information
    return jsonify({
        "vector_stores": stores_available,
        "s3": s3_info,
        "environment": "development" if IS_DEV_ENV else "production",
        "app_config": app_config,
        "default_store_type": default_store_type
    })

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    load_dotenv(override=True) # Ensure .env overrides system vars if running directly
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Running in {'debug' if debug_mode else 'production'} mode on port {port}")
    # Use host='0.0.0.0' to be accessible on the network
    app.run(debug=debug_mode, host='0.0.0.0', port=port) 