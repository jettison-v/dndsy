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
                s3_pdf_prefix_override=s3_pdf_prefix
            )
            send_status("milestone", {"message": "Data Processor initialized."})

            logger.info(f"--- Starting Data Processing for stores: {target_stores} --- ")
            # Call the main refactored method
            total_points_added = processor.process_all_sources(target_stores=target_stores)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage vector stores using the two-phase processing pipeline.")

    # --- Argument Definitions ---
    all_store_choices = ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory']
    
    parser.add_argument(
        '--store',
        action='append',  # Allow the argument to be specified multiple times
        choices=all_store_choices + ['all', 'haystack'], # Add 'all' and 'haystack' as valid choices
        dest='stores',  # Store the results in a list called 'stores'
        default=[],
        help=("Which store(s) to process. Specify multiple times (e.g., --store pages --store semantic) "
              "or use 'all' or 'haystack' (implies both qdrant/memory). Defaults to ['all'] if none specified.")
    )
    parser.add_argument(
        '--cache-behavior',
        choices=['use', 'rebuild'],
        default='use',
        help="Cache behavior: 'use' (default) processes only new/changed files, 'rebuild' clears history/stores and processes all files."
    )
    parser.add_argument(
        '--s3-pdf-prefix',
        type=str,
        default=None,
        help="Optional S3 prefix for source PDF files (e.g., 'test-pdfs/'). Overrides the prefix from .env."
    )

    args = parser.parse_args()

    logger.info("Starting vector store management script")
    logger.info(f"Selected Store(s): {args.stores}")
    logger.info(f"Cache Behavior: {args.cache_behavior}")
    if args.s3_pdf_prefix:
        logger.info(f"Using S3 PDF Prefix Override: {args.s3_pdf_prefix}")
    else:
        logger.info(f"Using S3 PDF Prefix from environment variable.")

    # Call the main refactored function
    success = manage_vector_stores(
        store_arg=args.stores, # Pass the argument value
        cache_behavior=args.cache_behavior,
        s3_pdf_prefix=args.s3_pdf_prefix
    )

    if success:
        logger.info("Vector store management script finished successfully!")
    else:
        logger.error("Vector store management script finished with errors.")

    logger.info("Script finished") # Final script end message 