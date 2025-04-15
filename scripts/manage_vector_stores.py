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

# Add project root to path to make imports work properly from script
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Imports that need project root in path
from vector_store import get_vector_store, PdfPagesStore, SemanticStore
# Now import DataProcessor after the path is set
from data_ingestion.processor import DataProcessor
# Import constants directly from the module
from data_ingestion.processor import PROCESS_HISTORY_FILE, PROCESS_HISTORY_S3_KEY, AWS_S3_BUCKET_NAME

env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path, override=True) # Override system vars

# Ensure logs directory exists relative to project root
logs_dir = project_root / 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
# Use a more descriptive log file name and overwrite it on each run
log_file_path = logs_dir / 'data_processing.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s', # Added logger name
    handlers=[
        # Overwrite log file each time (filemode='w')
        logging.FileHandler(log_file_path, mode='w'),
        logging.StreamHandler(sys.stdout) # Keep logging to console
    ]
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
        # Also log milestones/errors locally for debugging
        # if status_type in ['milestone', 'error', 'summary', 'start', 'end']:
        #     log_level = logging.ERROR if status_type == 'error' else logging.INFO
        #     logger.log(log_level, f"Status Update ({status_type}): {data}") # REMOVED - app.py handles logging if needed
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

def manage_vector_stores(store='all', cache_behavior='use', haystack_type='haystack-qdrant', s3_pdf_prefix=None):
    """Processes source documents and manages vector stores based on selected store and cache behavior."""
    
    start_time = time.time()
    send_status("start", {"message": "Processing run started.", "params": {"store": store, "cache_behavior": cache_behavior, "s3_prefix": s3_pdf_prefix}})
    
    # Log the received prefix
    logger.info(f"Starting vector store management. Store(s): '{store}', Cache Behavior: '{cache_behavior}'")
    if s3_pdf_prefix:
        logger.info(f"Using S3 PDF Prefix Override: {s3_pdf_prefix}")
    else:
        logger.info(f"Using default S3 PDF Prefix from environment.")

    # --- Determine stores to process based on 'store' parameter ---
    # This logic will replace the old flag-based determination inside the function
    process_pages = store == 'all' or store == 'pages'
    process_semantic = store == 'all' or store == 'semantic'
    # If 'haystack' is specified, process both qdrant and memory unless a specific one is chosen
    process_haystack = store == 'all' or 'haystack' in store # Covers 'haystack', 'haystack-qdrant', 'haystack-memory'
    process_haystack_qdrant = store == 'all' or store == 'haystack' or store == 'haystack-qdrant'
    process_haystack_memory = store == 'all' or store == 'haystack' or store == 'haystack-memory'

    logger.info(f"Processing Configuration:")
    logger.info(f"  - Pages: {process_pages}")
    logger.info(f"  - Semantic: {process_semantic}")
    logger.info(f"  - Haystack Qdrant: {process_haystack_qdrant}")
    logger.info(f"  - Haystack Memory: {process_haystack_memory}")
    logger.info(f"  - Cache Behavior: {cache_behavior}")


    overall_success = True
    processed_pdf_keys = set() # Track unique processed PDFs
    processing_summary = {}

    # --- Handle Cache Behavior (Reset/Rebuild) ---
    if cache_behavior == 'rebuild':
        logger.info("Cache behavior set to 'rebuild'. Resetting history and clearing target stores.")
        send_status("milestone", {"message": "Resetting processing history..."})
        _reset_processing_history()
        processed_pdf_keys = set() # Ensure set is clear after reset
        send_status("milestone", {"message": "Processing history reset."})

        # Clear collections based on which stores are being processed
        client = None
        # Consolidate client getting
        if process_pages or process_semantic or (process_haystack_qdrant and haystack_type != 'haystack-memory'):
            send_status("milestone", {"message": "Connecting to Qdrant..."})
            client = _get_qdrant_client()
            if client:
                send_status("milestone", {"message": "Connected to Qdrant."})
            else:
                send_status("error", {"message": "Failed to connect to Qdrant."})
                overall_success = False # Mark failure if Qdrant connection fails

        if process_pages and client:
            send_status("milestone", {"message": "Clearing Pages collection..."})
            _clear_pages_collection(client)
        if process_semantic and client:
            send_status("milestone", {"message": "Clearing Semantic collection..."})
            _clear_semantic_collection(client)
        # Pass client to haystack clearing if it's qdrant
        if process_haystack_qdrant:
             send_status("milestone", {"message": "Clearing Haystack-Qdrant store..."})
             _clear_haystack_store('haystack-qdrant', client)
        if process_haystack_memory:
            send_status("milestone", {"message": "Clearing Haystack-Memory store..."})
            _clear_haystack_store('haystack-memory', None)
        
        send_status("milestone", {"message": "Store clearing finished."})

    # --- Combined Data Processing --- 
    logger.info("--- Initializing Unified Data Processor ---")
    try:
        # Set HAYSTACK_STORE_TYPE env var before initializing DataProcessor if haystack is involved
        # This determines which haystack store (qdrant/memory) DataProcessor initializes
        effective_haystack_type = None
        if process_haystack_qdrant and process_haystack_memory:
             logger.warning("Processing both Haystack types sequentially. Qdrant first, then Memory.")
             # Process Qdrant first in this case
             effective_haystack_type = 'haystack-qdrant'
             os.environ["HAYSTACK_STORE_TYPE"] = effective_haystack_type
        elif process_haystack_qdrant:
            effective_haystack_type = 'haystack-qdrant'
            os.environ["HAYSTACK_STORE_TYPE"] = effective_haystack_type
        elif process_haystack_memory:
            effective_haystack_type = 'haystack-memory'
            os.environ["HAYSTACK_STORE_TYPE"] = effective_haystack_type
        
        # Instantiate DataProcessor ONCE with all necessary flags
        send_status("milestone", {"message": "Initializing Data Processor..."})
        try:
            processor = DataProcessor(
                process_pages=process_pages,
                process_semantic=process_semantic,
                # Only tell processor to handle haystack if at least one type is selected
                process_haystack=(process_haystack_qdrant or process_haystack_memory),
                cache_behavior=cache_behavior,
                s3_pdf_prefix_override=s3_pdf_prefix,
                # Pass the status function to the processor if it supports it
                # status_callback=send_status 
            )
            send_status("milestone", {"message": "Data Processor initialized."})
        except Exception as e:
            logger.error(f"Failed to initialize Data Processor: {e}", exc_info=True)
            send_status("error", {"message": f"Failed to initialize Data Processor: {e}"})
            overall_success = False
            processor = None # Ensure processor is None if init fails

        if processor:
            logger.info("--- Starting Unified Data Processing Run --- ")
            send_status("milestone", {"message": "Starting main data processing...", "long_running": True, "id": "main_processing"})
            
            # Run processing. The processor handles logic based on its initialized flags and cache behavior.
            processed_count = processor.process_all_sources(processed_pdf_keys_tracker=processed_pdf_keys)
            send_status("milestone", {"message": "Main data processing finished.", "id": "main_processing"})
            
            # --- Populate Summary --- 
            if process_pages:
                 processing_summary["Pages"] = f"{getattr(processor, 'pages_points_total', 0)} points added"
            if process_semantic:
                processing_summary["Semantic"] = f"{getattr(processor, 'semantic_points_total', 0)} points added"
            # Report Haystack based on the type(s) actually processed
            if process_haystack_qdrant:
                 # If both ran, this reflects the first run (Qdrant)
                 processing_summary["Haystack-Qdrant"] = f"{getattr(processor, 'haystack_points_total', 0)} points added"

            # --- Handle Processing Second Haystack Type (if needed) ---
            # If user selected 'all' or 'haystack', we process both Qdrant and Memory sequentially.
            if process_haystack_qdrant and process_haystack_memory:
                logger.info("--- Initializing Second Haystack Processor (Memory) ---")
                # Update environment variable for DataProcessor initialization
                os.environ["HAYSTACK_STORE_TYPE"] = "haystack-memory"
                # Re-run with only haystack memory enabled
                send_status("milestone", {"message": "Initializing Haystack Memory Processor..."})
                try:
                    processor_mem = DataProcessor(
                        process_pages=False,
                        process_semantic=False,
                        process_haystack=True,
                        cache_behavior=cache_behavior, # Keep same cache behavior
                        s3_pdf_prefix_override=s3_pdf_prefix # Pass prefix here too
                    )
                except Exception as e:
                     logger.error(f"Failed to initialize Haystack Memory Processor: {e}", exc_info=True)
                     send_status("error", {"message": f"Failed to initialize Haystack Memory Processor: {e}"})
                     overall_success = False
                     processor_mem = None

                if processor_mem:
                    logger.info("--- Starting Haystack Memory Processing Run --- ")
                    send_status("milestone", {"message": "Starting Haystack Memory processing...", "long_running": True, "id": "haystack_memory_processing"})
                    processed_count_mem = processor_mem.process_all_sources(processed_pdf_keys_tracker=processed_pdf_keys) # Use same tracker
                    send_status("milestone", {"message": "Haystack Memory processing finished.", "id": "haystack_memory_processing"})
                    processing_summary["Haystack-Memory"] = f"{getattr(processor_mem, 'haystack_points_total', 0)} points added"
                    processed_count += processed_count_mem 
            elif process_haystack_memory and not process_haystack_qdrant:
                # Only memory was processed in the first run (assuming init succeeded)
                if processor:
                    processing_summary["Haystack-Memory"] = f"{getattr(processor, 'haystack_points_total', 0)} points added"

            if processed_count < 0: # Check if processor reported errors (e.g., returned -1)
                overall_success = False
                logger.error("Errors may have occurred during data processing (check logs).")
                send_status("error", {"message": "Errors occurred during data processing."}) # Generic error
            else:
                logger.info(f"Unified data processing finished. Total points added across targeted stores: {processed_count}")
                
    except Exception as e:
        # Catch errors during the main processing block (after processor init)
        logger.error(f"An unexpected error occurred during DataProcessor execution: {e}", exc_info=True)
        send_status("error", {"message": f"Unexpected error during processing: {e}"})
        overall_success = False

    # --- Final Summary --- 
    logger.info("=== Overall Processing Summary ===")
    send_status("summary", {"details": processing_summary, "unique_pdfs": len(processed_pdf_keys)})
    if not processing_summary and overall_success:
         logger.warning("No stores were targeted or processed.")
    else:
        for store_name, result in processing_summary.items():
            logger.info(f"  - {store_name}: {result}")

    logger.info(f"Processed {len(processed_pdf_keys)} unique PDF(s) across all runs.")

    if not overall_success:
         logger.error("Vector store management finished with errors.")
         # Error status already sent if specific errors occurred
         # Send a general end error if not already sent
         # send_status("error", {"message": "Run finished with errors."})

    duration = time.time() - start_time
    send_status("end", {"success": overall_success, "duration": round(duration, 2)})
    return overall_success

# Helper functions to extract functionality
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

def _clear_pages_collection(client=None):
    """Clear the Pages (PDF pages) collection."""
    if client is None:
        client = _get_qdrant_client()
    
    try:
        # Get collection name from PdfPagesStore
        from vector_store.pdf_pages_store import PdfPagesStore 
        collection_name = PdfPagesStore.DEFAULT_COLLECTION_NAME
            
        logger.info(f"Deleting PDF Pages collection ({collection_name})")
        client.delete_collection(collection_name)
        logger.info("PDF Pages collection deleted successfully")
    except Exception as e:
        logger.warning(f"Could not delete PDF Pages collection ({collection_name}): {e}")

def _clear_semantic_collection(client=None):
    """Clear the semantic collection."""
    if client is None:
        client = _get_qdrant_client()
    
    try:
        # Try to get the collection name from the class
        try:
            collection_name = SemanticStore.DEFAULT_COLLECTION_NAME
        except AttributeError:
            # Fallback to a hardcoded value if not available as a class attribute
            collection_name = "dnd_semantic"
            
        logger.info(f"Deleting semantic collection ({collection_name})")
        client.delete_collection(collection_name)
        logger.info("Semantic collection deleted successfully")
    except Exception as e:
        logger.warning(f"Could not delete semantic collection ({collection_name}): {e}")

def _clear_haystack_store(haystack_type, client=None):
    """Clear the haystack store of the specified type. Pass client if it's Qdrant."""
    try:
        # Temporarily set env var to get the correct store instance for clearing
        original_haystack_type = os.environ.get("HAYSTACK_STORE_TYPE")
        os.environ["HAYSTACK_STORE_TYPE"] = haystack_type
        
        haystack_store = get_vector_store(haystack_type)
        logger.info(f"Clearing {haystack_type} store")
        
        # Restore original env var
        if original_haystack_type is not None:
            os.environ["HAYSTACK_STORE_TYPE"] = original_haystack_type
        else:
            del os.environ["HAYSTACK_STORE_TYPE"]
            
        # For QdrantDocumentStore, delete the entire collection
        try:
            if haystack_type == 'haystack-qdrant':
                collection_name = None
                try:
                    # Attempt to get collection name (logic remains the same)
                    if hasattr(haystack_store.document_store, 'collection_name'):
                        collection_name = haystack_store.document_store.collection_name
                    elif hasattr(haystack_store.document_store, '_collection_name'):
                        collection_name = haystack_store.document_store._collection_name
                    else:
                        collection_name = haystack_store.DEFAULT_COLLECTION_NAME # Assumes store has this defined
                except Exception as e:
                    collection_name = "dnd_haystack_qdrant" # Hardcoded fallback
                    logger.warning(f"Could not determine collection name, using default: {collection_name}. Error: {e}")
                
                if collection_name:
                    # Use the passed client if available, otherwise get a new one
                    qdrant_client = client if client else _get_qdrant_client()
                    if not qdrant_client:
                         logger.error("Could not get Qdrant client to delete collection.")
                         return # Cannot proceed with deletion
                         
                    logger.info(f"Deleting entire Haystack Qdrant collection: {collection_name}")
                    try:
                        qdrant_client.delete_collection(collection_name)
                        logger.info(f"Successfully deleted Haystack Qdrant collection: {collection_name}")
                    except Exception as del_e:
                        logger.warning(f"Error deleting collection {collection_name}: {del_e}. Falling back to document deletion.")
                        # Fallback logic remains the same (using haystack_store.document_store)
                        all_docs = haystack_store.document_store.filter_documents(filters={})
                        if all_docs:
                            doc_ids = [doc.id for doc in all_docs]
                            if doc_ids:
                                haystack_store.document_store.delete_documents(document_ids=doc_ids)
                                logger.info(f"Cleared {len(doc_ids)} documents from {haystack_type} store")
                            else:
                                logger.info(f"No documents to clear from {haystack_type} store")
                        else:
                            logger.info(f"No documents found in {haystack_type} store")
                else:
                    logger.warning("Could not determine collection name, attempting document deletion fallback")
                    # Fallback logic remains the same
                    all_docs = haystack_store.document_store.filter_documents(filters={})
                    if all_docs:
                        doc_ids = [doc.id for doc in all_docs]
                        if doc_ids:
                            haystack_store.document_store.delete_documents(document_ids=doc_ids)
                            logger.info(f"Cleared {len(doc_ids)} documents from {haystack_type} store")
                        else:
                            logger.info(f"No documents to clear from {haystack_type} store")
                    else:
                        logger.info(f"No documents found in {haystack_type} store")
            
            elif haystack_type == 'haystack-memory':
                # Memory store clearing logic remains the same
                try:
                    persistence_file = getattr(haystack_store, 'persistence_file', None)
                    if persistence_file and os.path.exists(persistence_file):
                        os.remove(persistence_file)
                        logger.info(f"Deleted haystack persistence file: {persistence_file}")
                except Exception as file_e:
                    logger.warning(f"Could not delete persistence file: {file_e}")
                # Try to recreate the store
                try:
                    # Reinitialize the memory store (if possible)
                    haystack_store = get_vector_store(haystack_type, force_new=True)
                    logger.info(f"Reinitialized {haystack_type} store")
                except Exception as reinit_e:
                    logger.warning(f"Could not reinitialize {haystack_type} store: {reinit_e}")
        except Exception as e:
            logger.warning(f"Error clearing {haystack_type} store: {e}")
            logger.info(f"Will try to continue with possibly non-empty {haystack_type} store")
    except Exception as e:
        logger.warning(f"Could not get vector store instance to clear {haystack_type}: {e}")
        # Restore env var in case of early exit
        if 'original_haystack_type' in locals():
            if original_haystack_type is not None:
                os.environ["HAYSTACK_STORE_TYPE"] = original_haystack_type
            elif "HAYSTACK_STORE_TYPE" in os.environ:
                 del os.environ["HAYSTACK_STORE_TYPE"]

def _get_qdrant_client():
    """Initialize and return Qdrant client."""
    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    # Determine if it's a cloud URL
    is_cloud = qdrant_host.startswith("http") or qdrant_host.startswith("https")

    if is_cloud:
        logger.info(f"Management script connecting to Qdrant Cloud at: {qdrant_host}")
        # For cloud, use url and api_key. Port is usually inferred (443 for https).
        client = QdrantClient(
            url=qdrant_host, 
            api_key=qdrant_api_key,
            timeout=60
        )
    else:
        logger.info(f"Management script connecting to local Qdrant at: {qdrant_host}")
        # For local, use host and explicit port.
        port = int(os.getenv("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=port, timeout=60)
    return client

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage vector stores: process documents based on store type and cache behavior.")

    # New simplified flags
    parser.add_argument(
        '--store',
        choices=['all', 'pages', 'semantic', 'haystack', 'haystack-qdrant', 'haystack-memory'],
        default='all',
        help="Which store(s) to process (default: all). 'haystack' processes both qdrant and memory."
    )
    parser.add_argument(
        '--cache-behavior',
        choices=['use', 'rebuild'],
        default='use',
        help="How to handle the processing cache: 'use' (default) processes only new/changed files, 'rebuild' clears history/stores and processes all files."
    )
    # Keep haystack-type for now, although its relevance might decrease if we refine '--store'
    parser.add_argument(
        '--haystack-type', # Maybe remove later if '--store haystack-qdrant/memory' is preferred
        choices=['haystack-qdrant', 'haystack-memory', 'both'],
        default='haystack-qdrant',
        help="The type of Haystack store to use when '--store' includes 'haystack'. (default: haystack-qdrant). 'both' implies processing both."
    )
    # Add new optional flag for S3 PDF prefix
    parser.add_argument(
        '--s3-pdf-prefix',
        type=str,
        default=None,
        help="Optional S3 prefix for source PDF files (e.g., 'test-pdfs/'). Overrides the prefix from .env."
    )

    # Remove old flags
    # parser.add_argument('--force-reprocess-images', action='store_true', ...)
    # parser.add_argument('--reset-history', action='store_true', ...)
    # parser.add_argument('--store-type', ...) # Replaced by --store

    args = parser.parse_args()

    logger.info("Starting vector store management script")
    logger.info(f"Selected Store(s): {args.store}")
    logger.info(f"Cache Behavior: {args.cache_behavior}")
    if args.s3_pdf_prefix:
        logger.info(f"Using S3 PDF Prefix Override: {args.s3_pdf_prefix}")
    else:
        logger.info(f"Using S3 PDF Prefix from environment variable.")
    # Determine the effective haystack type to log if needed
    if args.store == 'haystack' or args.store == 'all' or args.store == 'haystack-qdrant' or args.store == 'haystack-memory':
        # Decide which haystack type(s) will actually run based on --store and --haystack-type
        run_hq = args.store == 'all' or args.store == 'haystack' or args.store == 'haystack-qdrant'
        run_hm = args.store == 'all' or args.store == 'haystack' or args.store == 'haystack-memory'
        if run_hq and run_hm:
            log_ht = "haystack-qdrant and haystack-memory (sequentially)"
        elif run_hq:
            log_ht = "haystack-qdrant"
        elif run_hm:
            log_ht = "haystack-memory"
        else: 
            log_ht = "None specified/applicable"
        logger.info(f"Haystack Type(s) to Process: {log_ht}")

    # Call the main function with the arguments
    success = manage_vector_stores(
        store=args.store,
        cache_behavior=args.cache_behavior,
        haystack_type=args.haystack_type,
        s3_pdf_prefix=args.s3_pdf_prefix # Pass the new argument
    )

    if success:
        logger.info("Vector store management script finished successfully!")
    else:
        logger.error("Vector store management script finished with errors.")

    logger.info("Script finished") # Final script end message 