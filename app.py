from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from flask_cors import CORS
from llm import ask_dndsy, default_store_type, reinitialize_llm_client
from vector_store import get_vector_store
import os
from datetime import timedelta
import logging
import json
from dotenv import load_dotenv
from flask_session import Session
import boto3
from werkzeug.utils import secure_filename
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import subprocess
import threading
import io
from qdrant_client import QdrantClient
from qdrant_client.http.models import CollectionDescription
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))  # Use env var for secret key, fallback for local dev
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30) 
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') != 'development'
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to cookies
app.config['SESSION_TYPE'] = 'filesystem'  # Add filesystem session type
CORS(app)
Session(app)

PASSWORD = os.environ.get('APP_PASSWORD', 'dndsy')
logger.info(f"Password loaded from environment variable {'APP_PASSWORD' if 'APP_PASSWORD' in os.environ else '(using default)'}. ")

VECTOR_STORE_TYPES = ["pages", "semantic", "haystack-qdrant", "haystack-memory"]
# Get default store type from environment
DEFAULT_VECTOR_STORE = os.getenv("DEFAULT_VECTOR_STORE", "pages")

# Define available LLM models with their display names
AVAILABLE_LLM_MODELS = {
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
    "gpt-4": "GPT-4",
    "gpt-4-turbo": "GPT-4 Turbo",
    "claude-3-opus-20240229": "Claude 3 Opus",
    "claude-3-sonnet-20240229": "Claude 3 Sonnet",
    "claude-3-haiku-20240307": "Claude 3 Haiku"
}

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
    current_llm_model = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    
    return render_template('index.html', 
                          vector_store_types=VECTOR_STORE_TYPES,
                          default_vector_store=DEFAULT_VECTOR_STORE,
                          llm_model=current_llm_model,
                          available_llm_models=AVAILABLE_LLM_MODELS)

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
        'default': DEFAULT_VECTOR_STORE
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

# =============================================================================
# Admin API Routes
# =============================================================================

@app.route('/api/admin/process', methods=['POST'])
def admin_process():
    """API endpoint to process documents and update vector stores."""
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
    
    if 'pages' in store_types and 'semantic' in store_types and 'haystack-qdrant' in store_types and 'haystack-memory' in store_types:
        cmd_args.extend(['--store', 'all'])
    else:
        if 'pages' in store_types:
            cmd_args.extend(['--store', 'pages'])
        if 'semantic' in store_types:
            cmd_args.extend(['--store', 'semantic'])
        if 'haystack-qdrant' in store_types:
            cmd_args.extend(['--store', 'haystack-qdrant'])
        if 'haystack-memory' in store_types:
            cmd_args.extend(['--store', 'haystack-memory'])
    
    cmd_args.extend(['--cache-behavior', cache_behavior])
    
    if s3_prefix:
        cmd_args.extend(['--s3-pdf-prefix', s3_prefix])
    
    # Run the command in a separate thread
    def run_process():
        try:
            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # Read and log output
            for line in process.stdout:
                logger.info(f"Processing: {line.strip()}")
            
            process.wait()
            logger.info(f"Document processing completed with exit code {process.returncode}")
        except Exception as e:
            logger.error(f"Error running document processing: {e}", exc_info=True)
    
    # Start thread
    thread = threading.Thread(target=run_process)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f"Processing started with: {', '.join(store_types)} (cache: {cache_behavior})",
        'command': ' '.join(cmd_args)
    })

@app.route('/api/admin/history')
def admin_history():
    """API endpoint to get PDF processing history."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Try to get history from S3 first
    try:
        s3_client = get_s3_client()
        if s3_client:
            s3_pdf_process_history_key = "processing/pdf_process_history.json"
            try:
                response = s3_client.get_object(
                    Bucket=os.environ.get('AWS_S3_BUCKET_NAME'),
                    Key=s3_pdf_process_history_key
                )
                history_content = response['Body'].read().decode('utf-8')
                history = json.loads(history_content)
                return jsonify(history)
            except Exception as e:
                logger.warning(f"Error getting history from S3: {e}")
    except Exception as e:
        logger.warning(f"Error getting S3 client: {e}")
    
    # Fall back to local file
    try:
        history_file = os.path.join(os.path.dirname(__file__), "pdf_process_history.json")
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                history = json.load(f)
                return jsonify(history)
        else:
            return jsonify({}), 200
    except Exception as e:
        logger.error(f"Error reading history file: {e}", exc_info=True)
        return jsonify({'error': f'Error reading history file: {str(e)}'}), 500

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
    
    # For now, we'll return mock data since OpenAI doesn't provide
    # a simple usage API without OAuth. In a real implementation,
    # you would integrate with the OpenAI API or use a tracking system.
    
    # Sample data structure to demonstrate UI
    mock_data = {
        'period': 'May 1 - May 31, 2023',
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
        ]
    }
    
    return jsonify(mock_data)

@app.route('/api/admin/config', methods=['GET', 'POST'])
def admin_config():
    """API endpoint to get and update configuration values."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    
    if request.method == 'GET':
        # Get configuration value
        key = request.args.get('key')
        if not key:
            return jsonify({'error': 'Missing key parameter'}), 400
        
        # For now, we'll only support system_prompt
        if key == 'system_prompt':
            # Sample prompt, in a production system you would store and retrieve this from a database or config file
            system_prompt = """You are DnDSy, an AI assistant specialized in the 2024 Dungeons & Dragons ruleset (5.5e). Answer questions accurately based on the D&D rulebooks. Follow these guidelines:

1. Provide clear, concise answers about D&D 5.5e rules
2. Use examples to illustrate complex rules
3. Include page references from source materials when available 
4. If information isn't in the context provided, say so rather than making up rules
5. Format your responses with markdown for readability
6. Be friendly and enthusiastic about helping with D&D questions"""
            
            return jsonify({
                'success': True,
                'key': key,
                'value': system_prompt
            })
        else:
            return jsonify({'error': 'Unsupported configuration key'}), 400
    
    else:  # POST request
        # Update configuration value
        data = request.json
        if not data or 'key' not in data or 'value' not in data:
            return jsonify({'error': 'Missing key or value parameters'}), 400
        
        key = data['key']
        value = data['value']
        
        # For now, we'll only support system_prompt
        if key == 'system_prompt':
            # In a production system, you would store this in a database or config file
            # For demo purposes, we'll just acknowledge the request
            logger.info(f"System prompt updated: {value[:50]}...")
            
            return jsonify({
                'success': True,
                'message': 'Configuration updated successfully'
            })
        else:
            return jsonify({'error': 'Unsupported configuration key'}), 400

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

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    load_dotenv(override=True) # Ensure .env overrides system vars if running directly
    debug_mode = os.environ.get('FLASK_DEBUG') == '1'
    port = int(os.environ.get('PORT', 5001))
    logger.info(f"Running in {'debug' if debug_mode else 'production'} mode on port {port}")
    # Use host='0.0.0.0' to be accessible on the network
    app.run(debug=debug_mode, host='0.0.0.0', port=port) 