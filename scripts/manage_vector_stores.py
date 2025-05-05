from qdrant_client import QdrantClient
import os
import logging
from dotenv import load_dotenv
from pathlib import Path
import sys
import argparse
import json
import boto3
from botocore.exceptions import ClientError
import time # For timing
from typing import List # Added for type hinting

# Add project root to path to make imports work properly from script
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Imports that need project root in path
from vector_store import get_vector_store, PdfPagesStore, SemanticStore # Removed BaseVectorStore
from vector_store.search_helper import SearchHelper # Import SearchHelper directly
# Now import DataProcessor after the path is set
from data_ingestion.processor import DataProcessor
# Import constants directly from the module
from data_ingestion.processor import PROCESS_HISTORY_FILE, PROCESS_HISTORY_S3_KEY, AWS_S3_BUCKET_NAME
from config import S3_BUCKET_NAME # Import bucket name

env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path, override=True) # Override system vars

# Also load the default S3 prefix here
AWS_S3_PDF_PREFIX = os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/")

# Ensure logs directory exists relative to project root
logs_dir = project_root / 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
# Use a more descriptive log file name and overwrite it on each run
log_file_path = logs_dir / 'data_processing.log'

# Create a root logger configuration to ensure logs from all modules are captured
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s', # Added logger name
    handlers=[
        # Overwrite log file each time (filemode='w')
        logging.FileHandler(log_file_path, mode='w'),
        logging.StreamHandler(sys.stdout) # Restore StreamHandler
    ],
    force=True  # Force reconfiguration to ensure our handlers are applied
)

logger = logging.getLogger(__name__) # Get logger for this module

# --- SQS Configuration ---
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

s3_client = None
sqs_client = None

try:
    # Initialize S3 client (needed for listing PDFs)
    s3_client = boto3.client('s3', region_name=AWS_REGION)
    logger.info(f"Initialized S3 client for region {AWS_REGION}")
    
    # Initialize SQS client (needed for sending messages)
    if SQS_QUEUE_URL:
        sqs_client = boto3.client('sqs', region_name=AWS_REGION)
        logger.info(f"Initialized SQS client for queue: {SQS_QUEUE_URL}")
    else:
        logger.warning("SQS_QUEUE_URL environment variable not set. Cannot trigger processing.")
except Exception as e:
    logger.exception(f"Failed to initialize AWS clients: {e}")
    s3_client = None
    sqs_client = None

# --- Structured Output Function --- 
def send_status(status_type, data):
    """Prints a JSON status message to stdout for the parent process."""
    try:
        # Combine status type and data into a single dictionary
        status_update = {"type": status_type, **data}
        message = json.dumps(status_update)
        print(message, flush=True) # Ensure it's flushed immediately
        # Local logging of status updates is handled in app.py now
    except Exception as e:
        # Log error but don't crash the script
        logger.error(f"Failed to send status update: {e}")

# Initialize S3 client
def get_s3_client():
    try:
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        aws_region = os.getenv("AWS_REGION", "us-east-1")

        if aws_access_key_id and aws_secret_access_key:
            return boto3.client(
                's3',
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=aws_region
            )
        return None
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        return None

# --- Main Function: Refactored --- 
def manage_vector_stores(store_arg='all', cache_behavior='use', s3_pdf_prefix=None):
    """Orchestrates the two-phase data processing using the refactored DataProcessor."""

    start_time = time.time()
    send_status("start", {"message": "Processing run started.", "params": {"store": store_arg, "cache_behavior": cache_behavior, "s3_prefix": s3_pdf_prefix}})

    logger.info(f"Starting vector store management. Store(s) arg: '{store_arg}', Cache Behavior: '{cache_behavior}'")
    if s3_pdf_prefix:
        logger.info(f"Using S3 PDF Prefix Override: {s3_pdf_prefix}")
    else:
        logger.info(f"Using default S3 PDF Prefix from environment.")

    # --- Determine Target Stores --- 
    target_stores: List[str] = []
    # Flatten the list in case 'store_arg' is a list of lists (though argparse append shouldn't do that)
    requested_stores = []
    if isinstance(store_arg, list):
         # Handle special keywords 'all' and 'haystack'
         if 'all' in store_arg:
              requested_stores = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']
         else:
              temp_stores = set()
              for store in store_arg:
                   if store == 'haystack':
                        temp_stores.add('haystack-qdrant')
                        temp_stores.add('haystack-memory')
                   else:
                        temp_stores.add(store)
              requested_stores = list(temp_stores)
    elif isinstance(store_arg, str): # Handle case where only one --store is passed or default is used
          if store_arg == 'all':
               requested_stores = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']
          elif store_arg == 'haystack':
               requested_stores = ['haystack-qdrant', 'haystack-memory']
          else:
               requested_stores = [store_arg]
    else:
         # Default case if no store is specified - treat as 'all'
         if not store_arg:
              logger.info("No store specified, defaulting to 'all'.")
              requested_stores = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']
         else:
             logger.warning(f"Unrecognized store argument format: {store_arg}. Defaulting to all.")
             requested_stores = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']

    # Validate final list against known types
    all_known_stores = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']
    target_stores = [s for s in requested_stores if s in all_known_stores]

    if not target_stores:
         logger.warning(f"No valid stores resolved from input: {store_arg}. Processing will be skipped.")

    logger.info(f"Target stores determined: {target_stores}")
    logger.info(f"Cache Behavior: {cache_behavior}")

    overall_success = True
    total_points_added = 0

    # --- Handle Cache Behavior (Reset/Rebuild) --- 
    if cache_behavior == 'rebuild':
        logger.info("Cache behavior set to 'rebuild'. Resetting history and clearing target stores.")
        send_status("milestone", {"message": "Resetting processing history..."})
        _reset_processing_history()
        send_status("milestone", {"message": "Processing history reset."})

        # Clear collections/stores based on the *target_stores* list
        qdrant_client = None
        needs_qdrant_client = any(s in target_stores for s in ['pages', 'semantic', 'haystack-qdrant'])

        if needs_qdrant_client:
            send_status("milestone", {"message": "Connecting to Qdrant..."})
            qdrant_client = _get_qdrant_client()
            if qdrant_client:
                send_status("milestone", {"message": "Connected to Qdrant."})
            else:
                send_status("error", {"message": "Failed to connect to Qdrant. Cannot clear Qdrant-based stores."}) 
                # Decide if this is fatal or just skip clearing?
                # Let's mark as failure but allow memory store clearing if targeted
                overall_success = False

        # Clear individual stores
        if 'pages' in target_stores:
            send_status("milestone", {"message": "Clearing Pages store..."})
            _clear_store("pages", qdrant_client)
        if 'semantic' in target_stores:
            send_status("milestone", {"message": "Clearing Semantic store..."})
            _clear_store("semantic", qdrant_client)
        if 'haystack-qdrant' in target_stores:
             send_status("milestone", {"message": "Clearing Haystack-Qdrant store..."})
             _clear_store('haystack-qdrant', qdrant_client)
        if 'haystack-memory' in target_stores:
            send_status("milestone", {"message": "Clearing Haystack-Memory store..."})
            _clear_store('haystack-memory', None) # Memory store doesn't need qdrant client

        send_status("milestone", {"message": "Store clearing finished."})

    # --- Execute Two-Phase Processing --- 
    if not target_stores:
         logger.warning("No valid stores selected. Skipping processing.")
    else:
        logger.info("--- Initializing Data Processor for Two-Phase Execution ---")
        try:
            send_status("milestone", {"message": "Initializing Data Processor..."})
            processor = DataProcessor(
                cache_behavior=cache_behavior,
                s3_pdf_prefix_override=s3_pdf_prefix,
                status_callback=send_status
            )
            send_status("milestone", {"message": "Data Processor initialized."})

            logger.info(f"--- Starting Data Processing for stores: {target_stores} --- ")
            # Call the main refactored method
            total_points_added = processor.process_all_sources(target_stores=target_stores)
            # Status updates now come directly from the processor via the callback

            if total_points_added < 0: # Check if processor indicated errors
                 overall_success = False
                 logger.error("Errors occurred during data processing (check logs).")
                 # Status updates should come from processor now, but send generic if needed
                 # send_status("error", {"message": "Errors occurred during data processing."})
            else:
                logger.info(f"Data processing finished.")
                # The processor now logs its own summary

        except Exception as e:
            logger.error(f"An unexpected error occurred during DataProcessor execution: {e}", exc_info=True)
            send_status("error", {"message": f"Unexpected error during processing: {e}"})
            overall_success = False

    # --- Final Summary --- 
    logger.info("=== Overall Run Summary ===")
    logger.info(f"Target Stores: {store_arg}")
    logger.info(f"Cache Behavior: {cache_behavior}")
    logger.info(f"S3 Prefix Used: {s3_pdf_prefix or AWS_S3_PDF_PREFIX}")
    logger.info(f"Total Points Added Across All Stores: {total_points_added}") # Get final count from processor run

    duration = time.time() - start_time
    logger.info(f"Total Script Duration: {duration:.2f} seconds")
    
    if not overall_success:
         logger.error("Vector store management finished with errors.")

    # Send final status including total points added
    send_status("end", {"success": overall_success, "duration": round(duration, 2), "total_points_added": total_points_added})
    return overall_success

# --- Helper Functions --- 

def _reset_processing_history():
    """Reset processing history by deleting local and S3 files."""
    logger.info("Resetting processing history as requested")
    try:
        # Delete local file if it exists
        if os.path.exists(PROCESS_HISTORY_FILE):
            os.remove(PROCESS_HISTORY_FILE)
            logger.info(f"Deleted local {PROCESS_HISTORY_FILE}")
        else:
            logger.info(f"No existing local {PROCESS_HISTORY_FILE} to delete")

        # Also delete from S3
        s3_client = get_s3_client()
        if s3_client and AWS_S3_BUCKET_NAME:
            try:
                # Check if file exists in S3
                try:
                    s3_client.head_object(Bucket=AWS_S3_BUCKET_NAME, Key=PROCESS_HISTORY_S3_KEY)
                    # File exists, delete it
                    s3_client.delete_object(Bucket=AWS_S3_BUCKET_NAME, Key=PROCESS_HISTORY_S3_KEY)
                    logger.info(f"Deleted S3 process history: {PROCESS_HISTORY_S3_KEY}")
                except ClientError as e:
                    if e.response['Error']['Code'] == '404':
                        logger.info(f"No existing S3 process history file to delete")
                    else:
                        logger.error(f"Error checking S3 process history: {e}")
            except Exception as e:
                logger.error(f"Error deleting S3 process history: {e}")
    except Exception as e:
        logger.error(f"Error deleting process history: {e}")

# Consolidated store clearing function
def _clear_store(store_type: str, qdrant_client: QdrantClient = None):
    """Clears the specified vector store."""
    logger.info(f"Attempting to clear store: {store_type}")
    store_instance = None
    try:
        # Get the store instance to call its clear method
        store_instance = get_vector_store(store_type)
        if not store_instance:
            raise RuntimeError(f"Failed to get instance for store type '{store_type}' to clear.")

        # Special handling based on type might still be needed if clear_store isn't uniform
        if store_type == 'haystack-memory':
            # Memory store clearing might involve deleting a file + reinit
            try:
                persistence_file = getattr(store_instance, 'persistence_file', None)
                if persistence_file and os.path.exists(persistence_file):
                    os.remove(persistence_file)
                    logger.info(f"Deleted haystack persistence file: {persistence_file}")
                # Attempt reinitialization via get_vector_store if needed
                store_instance = get_vector_store(store_type, force_new=True)
                logger.info(f"Reinitialized {store_type} store")
            except Exception as mem_e:
                logger.warning(f"Could not fully clear/reset {store_type}: {mem_e}")
        elif store_type in ['pages', 'semantic', 'haystack-qdrant']:
            # Assume Qdrant-based stores need the client and have a clear_store method
            if not qdrant_client:
                logger.warning(f"Qdrant client not available, cannot clear Qdrant-based store: {store_type}")
                return # Skip clearing this store
            
            # Use the clear_store method (which should handle collection deletion)
            store_instance.clear_store(client=qdrant_client)
            logger.info(f"Successfully cleared store: {store_type}")
        else:
            # Fallback/General case: Assume a clear_store method exists
             logger.info(f"Using generic clear_store method for {store_type}")
             store_instance.clear_store()
             logger.info(f"Successfully cleared store: {store_type}")

    except Exception as e:
        logger.error(f"Failed to clear store '{store_type}': {e}", exc_info=True)
        # Optionally send error status
        # send_status("error", {"message": f"Failed to clear store '{store_type}': {e}"})

# Deprecated clearing functions (replaced by _clear_store)
# def _clear_pages_collection(client=None): ...
# def _clear_semantic_collection(client=None): ...
# def _clear_haystack_store(haystack_type, client=None): ...

def _get_qdrant_client() -> QdrantClient | None:
    """Initialize and return Qdrant client."""
    try:
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        qdrant_port = os.getenv("QDRANT_PORT", "6333")

        # Determine connection method based on host format
        if qdrant_host.startswith("http://") or qdrant_host.startswith("https://"):
            logger.info(f"Management script connecting to Qdrant Cloud/URL: {qdrant_host}")
            client = QdrantClient(
                url=qdrant_host,
                api_key=qdrant_api_key, # Will be None if not set, which is fine for unsecured
                timeout=60
            )
        else:
            logger.info(f"Management script connecting to Qdrant host: {qdrant_host}:{qdrant_port}")
            client = QdrantClient(
                host=qdrant_host,
                port=int(qdrant_port),
                api_key=qdrant_api_key,
                timeout=60
            )
        # Test connection
        client.get_collections()
        logger.info("Qdrant connection successful.")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Qdrant: {e}", exc_info=True)
        return None

def clear_stores(stores_to_clear: List[str]):
    """Clears the specified vector stores."""
    logger.info(f"Attempting to clear stores: {stores_to_clear}")
    cleared_count = 0
    for store_type in stores_to_clear:
        try:
            logger.info(f"Clearing store: {store_type}")
            store = get_vector_store(store_type)
            if store:
                store.clear_store()
                logger.info(f"Successfully cleared store: {store_type}")
                cleared_count += 1
            else:
                logger.warning(f"Could not get instance for store type '{store_type}' to clear.")
        except Exception as e:
            logger.error(f"Failed to clear store '{store_type}': {e}", exc_info=True)
    logger.info(f"Finished clearing stores. Cleared {cleared_count}/{len(stores_to_clear)}.")

def trigger_processing_for_pdf(s3_pdf_key: str, bucket_name: str):
    """Sends an SQS message to trigger processing for a single PDF."""
    if not sqs_client or not SQS_QUEUE_URL:
        logger.error(f"SQS client or URL not available. Cannot trigger processing for {s3_pdf_key}")
        return False

    # Construct message body mimicking S3 event notification structure
    # Note: S3 keys in event notifications are often URL-encoded.
    # The worker should handle decoding. We send it raw here.
    message_body = json.dumps({
        "Records": [{
            "s3": {
                "bucket": {"name": bucket_name},
                "object": {"key": s3_pdf_key}
            }
        }]
    })

    try:
        response = sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=message_body
        )
        logger.info(f"Sent SQS message for {s3_pdf_key}. Message ID: {response.get('MessageId')}")
        return True
    except ClientError as e:
        logger.error(f"Failed to send SQS message for {s3_pdf_key}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error sending SQS message for {s3_pdf_key}: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage vector stores: clear and trigger processing.")
    
    # Get available store choices dynamically
    available_stores = list_available_stores()
    store_choices = available_stores + ['all', 'haystack'] # Add aggregate options

    parser.add_argument(
        "--store", 
        nargs='+', 
        default=["all"], 
        choices=store_choices,
        help=f"Vector store(s) to manage. Choose from: {store_choices}"
    )
    parser.add_argument(
        "--cache-behavior", 
        default='use', 
        choices=['use', 'rebuild'], 
        help="'rebuild' clears the stores before triggering processing. 'use' triggers processing without clearing."
    )
    parser.add_argument(
        "--s3-pdf-prefix",
        default=os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/"),
        help="S3 prefix where source PDFs are located. Overrides environment variable."
    )

    args = parser.parse_args()

    # Determine target stores
    target_stores_arg = args.store
    stores_to_manage = set()
    if "all" in target_stores_arg:
        stores_to_manage.update(available_stores)
    elif "haystack" in target_stores_arg:
        # Add both haystack types if 'haystack' is specified
        if 'haystack-qdrant' in available_stores: stores_to_manage.add('haystack-qdrant')
        if 'haystack-memory' in available_stores: stores_to_manage.add('haystack-memory')
        # Add any other specified stores too
        stores_to_manage.update(s for s in target_stores_arg if s != 'haystack' and s in available_stores)
    else:
        stores_to_manage.update(s for s in target_stores_arg if s in available_stores)
    
    stores_to_manage = sorted(list(stores_to_manage))
    if not stores_to_manage:
        logger.error("No valid stores selected to manage.")
        sys.exit(1)
        
    logger.info(f"Selected Store(s): {stores_to_manage}")
    logger.info(f"Cache Behavior: {args.cache_behavior}")
    logger.info(f"Using S3 PDF Prefix: {args.s3_pdf_prefix}")

    # --- Clear Stores if Rebuilding --- 
    if args.cache_behavior == 'rebuild':
        # We still need DataProcessor or equivalent logic to reset history file
        # For simplicity now, just clear the vector stores themselves.
        # Resetting history should ideally happen within the worker based on messages.
        logger.info("Resetting processing history is now handled by workers receiving messages.")
        # processor = DataProcessor(cache_behavior='rebuild', status_callback=log_status)
        # processor.reset_history()
        clear_stores(stores_to_manage)
    else:
        logger.info("Cache behavior is 'use'. Stores will not be cleared.")

    # --- Trigger Processing via SQS --- 
    if not sqs_client or not SQS_QUEUE_URL:
        logger.error("SQS client not configured. Cannot trigger processing.")
        sys.exit(1)
    if not s3_client:
        logger.error("S3 client not configured. Cannot list PDFs to trigger processing.")
        sys.exit(1)

    pdf_prefix = args.s3_pdf_prefix
    if pdf_prefix and not pdf_prefix.endswith('/'):
        pdf_prefix += '/'
        
    logger.info(f"Listing PDFs from bucket '{S3_BUCKET_NAME}' with prefix '{pdf_prefix}' to trigger processing...")
    triggered_count = 0
    skipped_count = 0
    error_count = 0
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=pdf_prefix)
        pdf_keys_to_trigger = []
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    # Ensure it's a PDF and not just the prefix itself
                    if key.lower().endswith('.pdf') and key != pdf_prefix:
                        pdf_keys_to_trigger.append(key)
        
        if not pdf_keys_to_trigger:
            logger.warning(f"No PDF files found in s3://{S3_BUCKET_NAME}/{pdf_prefix} to trigger.")
        else:
            logger.info(f"Found {len(pdf_keys_to_trigger)} PDFs. Sending SQS triggers...")
            for s3_key in pdf_keys_to_trigger:
                if trigger_processing_for_pdf(s3_key, S3_BUCKET_NAME):
                    triggered_count += 1
                    time.sleep(0.1) # Small delay to avoid overwhelming SQS API
                else:
                    error_count += 1
            logger.info(f"Finished sending SQS triggers. Sent: {triggered_count}, Errors: {error_count}")
            
    except ClientError as e:
        logger.error(f"Error listing PDFs from S3: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error during PDF listing or SQS triggering: {e}")

    logger.info("Vector store management script finished.")

    logger.info("Script finished") # Final script end message 