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
from typing import List, Dict, Any, Callable, Optional # Added Optional, Dict, Any, Callable
import uuid # Import UUID for run ID

# Add project root to path to make imports work properly from script
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Imports that need project root in path
from vector_store import get_vector_store, PdfPagesStore, SemanticStore # Removed BaseVectorStore
# --- Import Qdrant client and models directly for alias operations ---
from qdrant_client import QdrantClient, models
# ---------------------------------------------------------------------
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

# --- Helper Function for Alias Operations ---
def _update_qdrant_aliases(client: QdrantClient, operations: List[models.AliasOperations]):
    """Performs atomic alias updates using the Qdrant client."""
    if not operations:
        logger.info("No alias operations to perform.")
        return True
    try:
        logger.info(f"Attempting to update collection aliases with {len(operations)} operations...")
        client.update_collection_aliases(
            change_aliases_operations=operations,
            timeout=60  # Increase timeout for alias operations
        )
        logger.info("Successfully updated collection aliases.")
        return True
    except Exception as e:
        logger.error(f"Failed to update collection aliases: {e}", exc_info=True)
        # Optionally send error status
        # send_status("error", {"message": f"Failed to update Qdrant aliases: {e}"})
        return False

def _get_live_alias_name(base_collection_name: str) -> str:
    """Returns the standard 'live' alias name for a base collection name."""
    return f"{base_collection_name}_live"

def _get_temp_collection_name(base_collection_name: str, run_id: str) -> str:
    """Returns the temporary collection name for a given run ID."""
    return f"{base_collection_name}_temp_{run_id}"
# -----------------------------------------

# --- Main Function: Refactored ---
def manage_vector_stores(store_arg='all', cache_behavior='use', s3_pdf_prefix=None):
    """Orchestrates the data processing, potentially using staging and atomic swaps for 'rebuild'."""

    start_time = time.time()
    # --- Generate Run ID ---
    run_id = str(uuid.uuid4())[:8] # Short unique ID for this run
    logger.info(f"Processing Run ID: {run_id}")
    # -----------------------

    send_status("start", {"message": f"Processing run {run_id} started.", "params": {"store": store_arg, "cache_behavior": cache_behavior, "s3_prefix": s3_pdf_prefix, "run_id": run_id}})

    logger.info(f"Starting vector store management. Run ID: {run_id}, Store(s) arg: '{store_arg}', Cache Behavior: '{cache_behavior}'")
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
    qdrant_client = None
    s3_client = get_s3_client() # Initialize S3 client earlier for cleanup checks

    # --- Get Qdrant client if needed for processing or swap ---
    needs_qdrant_client = any(s in target_stores for s in ['pages', 'semantic', 'haystack-qdrant'])
    if needs_qdrant_client:
        send_status("milestone", {"message": "Connecting to Qdrant..."})
        qdrant_client = _get_qdrant_client()
        if qdrant_client:
            send_status("milestone", {"message": "Connected to Qdrant."})
        else:
            send_status("error", {"message": "Failed to connect to Qdrant. Cannot process Qdrant-based stores."})
            # If Qdrant connection fails, we cannot proceed with Qdrant stores.
            # Filter out Qdrant stores if connection failed.
            target_stores = [s for s in target_stores if s not in ['pages', 'semantic', 'haystack-qdrant']]
            if not target_stores:
                logger.error("Qdrant connection failed and no non-Qdrant stores targeted. Aborting.")
                send_status("end", {"success": False, "duration": round(time.time() - start_time, 2), "total_points_added": 0, "message": "Aborted due to Qdrant connection failure."})
                return False
            else:
                logger.warning(f"Qdrant connection failed. Proceeding with non-Qdrant stores only: {target_stores}")


    # --- Handle Cache Behavior (Reset/Rebuild) ---
    # --- MODIFIED: Remove Store Clearing from Rebuild ---
    if cache_behavior == 'rebuild':
        logger.info(f"Cache behavior set to 'rebuild' for run {run_id}. Staging data in temporary locations.")
        send_status("milestone", {"message": f"Rebuild run {run_id}: Using temporary locations."})
        # DO NOT reset history or clear stores here anymore.
        # The processor will handle creating data in temporary locations.
        # Cleanup of old data happens *after* a successful swap.
    # --- END MODIFICATION ---

    # --- Execute Processing ---
    collections_to_swap = {} # Store mapping {live_alias: temp_collection_name} for Qdrant
    temp_haystack_memory_dir = None # Store path to temp haystack memory dir
    old_collections_to_delete = [] # Store names of old Qdrant collections to delete on success
    old_haystack_memory_dir_to_delete = None # Store path of old haystack dir to delete on success

    if not target_stores:
         logger.warning("No valid stores selected. Skipping processing.")
    else:
        logger.info(f"--- Initializing Data Processor for Run ID: {run_id} ---")
        try:
            send_status("milestone", {"message": "Initializing Data Processor..."})
            # --- MODIFIED: Pass run_id to DataProcessor ---
            processor = DataProcessor(
                cache_behavior=cache_behavior,
                s3_pdf_prefix_override=s3_pdf_prefix,
                status_callback=send_status,
                run_id=run_id if cache_behavior == 'rebuild' else None # Pass run_id only for rebuilds
            )
            # --- END MODIFICATION ---
            send_status("milestone", {"message": "Data Processor initialized."})

            logger.info(f"--- Starting Data Processing for stores: {target_stores} (Run ID: {run_id}) ---")
            send_status("milestone", {"message": f"Processing data into temporary locations (Run ID: {run_id})..."})

            # Call the main method - it now processes into temp locations if run_id is provided
            total_points_added = processor.process_all_sources(target_stores=target_stores)

            if total_points_added < 0: # Check if processor indicated errors
                 overall_success = False
                 logger.error(f"Errors occurred during data processing (Run ID: {run_id}). Check logs.")
                 send_status("error", {"message": f"Errors occurred during data processing (Run ID: {run_id})."})
            else:
                logger.info(f"Data processing phase finished successfully for Run ID: {run_id}.")
                send_status("milestone", {"message": "Data processing phase complete."})

                # --- Prepare for Swap (only on successful rebuild) ---
                if cache_behavior == 'rebuild' and overall_success:
                    logger.info(f"Preparing to swap data for successful rebuild run {run_id}.")
                    send_status("milestone", {"message": "Preparing for data swap..."})

                    # Identify Qdrant collections and Haystack dirs to swap
                    for store_type in target_stores:
                        store_instance = get_vector_store(store_type, run_id=run_id) # Get temp instance
                        if not store_instance:
                            logger.error(f"Failed to get temporary store instance for '{store_type}' (Run ID: {run_id}) during swap preparation. Aborting swap.")
                            overall_success = False
                            break

                        base_collection_name = getattr(store_instance, 'DEFAULT_COLLECTION_NAME', None)
                        if not base_collection_name:
                             # Handle Haystack memory store name derivation if needed
                             if store_type == 'haystack-memory':
                                 base_collection_name = 'haystack_memory' # Or derive from config
                             else:
                                logger.error(f"Could not determine base collection name for store type '{store_type}'. Cannot prepare swap.")
                                overall_success = False
                                break


                        temp_name = store_instance.collection_name # This should be the temp name (e.g., ..._temp_<run_id>)
                        live_alias = _get_live_alias_name(base_collection_name)

                        if store_type in ['pages', 'semantic', 'haystack-qdrant']:
                             # Ensure temp collection exists
                             if not qdrant_client.collection_exists(collection_name=temp_name):
                                 logger.error(f"Temporary Qdrant collection '{temp_name}' not found after processing. Aborting swap.")
                                 overall_success = False
                                 break
                             collections_to_swap[live_alias] = temp_name
                             logger.info(f"Prepared Qdrant swap: Alias '{live_alias}' -> Collection '{temp_name}'")
                        elif store_type == 'haystack-memory':
                             # TODO: Implement Haystack Memory swap prep
                             # temp_haystack_memory_dir = store_instance.persistence_path
                             # logger.info(f"Prepared Haystack Memory swap: Live dir -> '{temp_haystack_memory_dir}'")
                             logger.warning("Haystack Memory store swap logic not yet implemented.")
                             pass

                    if not overall_success:
                         logger.error(f"Failed during swap preparation for Run ID: {run_id}. Swap aborted.")
                         send_status("error", {"message": "Failed during swap preparation. Swap aborted."})


        except Exception as e:
            logger.error(f"An unexpected error occurred during DataProcessor execution (Run ID: {run_id}): {e}", exc_info=True)
            send_status("error", {"message": f"Unexpected error during processing (Run ID: {run_id}): {e}"})
            overall_success = False

    # --- Perform Atomic Swap and Cleanup (only on successful rebuild) ---
    if cache_behavior == 'rebuild' and overall_success:
        logger.info(f"--- Starting Atomic Swap for Run ID: {run_id} ---")
        send_status("milestone", {"message": "Performing atomic data swap..."})

        swap_successful = True

        # --- Qdrant Alias Swap ---
        if collections_to_swap and qdrant_client:
            alias_operations = []
            temp_collection_names = list(collections_to_swap.values()) # Names like 'dnd_semantic_temp_<run_id>'

            # 1. Get current collections pointed to by the live aliases
            try:
                aliases_response = qdrant_client.get_aliases()
                live_aliases_to_update = list(collections_to_swap.keys()) # Names like 'dnd_semantic_live'

                for alias_desc in aliases_response.aliases:
                    if alias_desc.alias_name in live_aliases_to_update:
                        old_collection_name = alias_desc.collection_name
                        # Don't delete if the old collection is one of the new temp ones (e.g., first run)
                        if old_collection_name not in temp_collection_names:
                            old_collections_to_delete.append(old_collection_name)
                            logger.info(f"Identified old Qdrant collection '{old_collection_name}' for deletion after swap.")
                        else:
                             logger.info(f"Alias '{alias_desc.alias_name}' already points to a temp collection '{old_collection_name}'. Skipping deletion planning for this one.")

                        # Add operation to delete the current alias
                        alias_operations.append(
                            models.DeleteAliasOperation(
                                delete_alias=models.DeleteAlias(alias_name=alias_desc.alias_name)
                            )
                        )
            except Exception as e:
                 logger.error(f"Failed to get current Qdrant aliases: {e}. Aborting swap.", exc_info=True)
                 swap_successful = False

            if swap_successful:
                # 2. Add operations to create new aliases pointing to temp collections
                for live_alias, temp_collection_name in collections_to_swap.items():
                    alias_operations.append(
                        models.CreateAliasOperation(
                            create_alias=models.CreateAlias(
                                collection_name=temp_collection_name,
                                alias_name=live_alias
                            )
                        )
                    )

                # 3. Perform atomic update
                if not _update_qdrant_aliases(qdrant_client, alias_operations):
                    swap_successful = False
                    logger.error(f"Qdrant alias swap failed for Run ID: {run_id}.")
                    send_status("error", {"message": "Qdrant alias swap failed."})
                else:
                     logger.info(f"Successfully swapped Qdrant aliases for Run ID: {run_id}.")
                     send_status("milestone", {"message": "Qdrant aliases swapped."})


        # --- Haystack Memory Swap ---
        if temp_haystack_memory_dir:
            # TODO: Implement atomic rename for Haystack Memory directory
            # Identify old dir, perform renames, update old_haystack_memory_dir_to_delete
            logger.warning("Haystack Memory store swap logic not yet implemented.")
            pass


        # --- S3 Data Swap ---
        # TODO: Implement S3 promotion logic (copy from temp prefix, then delete old)
        # Needs careful implementation, potentially using S3 Batch or list/copy/delete loops.
        logger.warning("S3 data swap logic (images, links, metadata, history) not yet implemented.")
        # For now, assume swap failure if S3 swap is needed but not implemented
        # if any(store in ['pages', 'semantic', 'haystack-qdrant', 'haystack-memory'] for store in target_stores): # Simplistic check
        #     swap_successful = False
        #     logger.error("S3 data swap is required but not implemented. Marking swap as failed.")
        #     send_status("error", {"message": "S3 data swap not implemented."})
        pass # Placeholder


        # --- Finalize Swap ---
        if swap_successful:
            logger.info(f"--- Atomic Swap Completed Successfully for Run ID: {run_id} ---")
            send_status("milestone", {"message": "Atomic swap successful. Cleaning up old data..."})

            # --- Cleanup Old Data ---
            # Delete old Qdrant collections
            if old_collections_to_delete and qdrant_client:
                logger.info(f"Cleaning up {len(old_collections_to_delete)} old Qdrant collections...")
                for coll_name in old_collections_to_delete:
                    try:
                        # Double-check it's not one of the *new* temp collections before deleting
                        if coll_name not in temp_collection_names:
                            logger.info(f"Deleting old Qdrant collection: {coll_name}")
                            qdrant_client.delete_collection(collection_name=coll_name, timeout=60)
                        else:
                             logger.warning(f"Skipping deletion of '{coll_name}' as it appears to be a new temporary collection.")
                    except Exception as e:
                        logger.error(f"Failed to delete old Qdrant collection '{coll_name}': {e}")
                        # Log error but continue cleanup

            # Delete old Haystack Memory dir
            if old_haystack_memory_dir_to_delete:
                # TODO: Implement deletion
                logger.warning("Old Haystack Memory dir cleanup logic not yet implemented.")
                pass

            # Delete old S3 objects/prefixes
            # TODO: Implement S3 cleanup
            logger.warning("Old S3 data cleanup logic not yet implemented.")
            pass

            logger.info(f"--- Old Data Cleanup Finished for Run ID: {run_id} ---")
            send_status("milestone", {"message": "Old data cleanup finished."})

        else:
            logger.error(f"--- Atomic Swap Failed for Run ID: {run_id}. Initiating Temp Data Cleanup ---")
            send_status("error", {"message": "Atomic swap failed. Rolling back temporary changes..."})
            # Set overall success to False if swap failed
            overall_success = False
            # Cleanup temporary data from the FAILED run
            _cleanup_temp_data(run_id, target_stores, qdrant_client, s3_client)
            send_status("milestone", {"message": "Temporary data cleanup finished."})


    # --- Handle Processing Errors (if swap wasn't attempted or failed earlier) ---
    elif not overall_success:
        logger.error(f"Processing run {run_id} failed before swap.")
        if cache_behavior == 'rebuild':
             logger.info(f"--- Initiating Temp Data Cleanup for Failed Rebuild Run ID: {run_id} ---")
             send_status("milestone", {"message": "Processing failed. Cleaning up temporary data..."})
             _cleanup_temp_data(run_id, target_stores, qdrant_client, s3_client)
             send_status("milestone", {"message": "Temporary data cleanup finished."})

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
    send_status("end", {"success": overall_success, "duration": round(duration, 2), "total_points_added": total_points_added, "run_id": run_id})
    return overall_success

# --- MODIFIED HELPER FUNCTIONS ---
# Consolidated store clearing function (NO LONGER USED FOR REBUILD)
def _clear_store(store_type: str, qdrant_client: QdrantClient = None):
    logger.warning(f"_clear_store called for {store_type}. This is no longer part of the standard 'rebuild' flow.")
    # ... (Keep existing implementation for potential other uses) ...

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

# --- NEW HELPER FUNCTION ---
def _cleanup_temp_data(run_id: str, target_stores: List[str], qdrant_client: Optional[QdrantClient], s3_client: Optional[Any]):
    """Cleans up temporary data artifacts for a specific run ID upon failure or rollback."""
    logger.info(f"--- Starting Cleanup for Temporary Data (Run ID: {run_id}) ---")

    # --- Cleanup Temp Qdrant Collections ---
    if qdrant_client:
        qdrant_stores_to_clean = [s for s in target_stores if s in ['pages', 'semantic', 'haystack-qdrant']]
        if qdrant_stores_to_clean:
            logger.info(f"Cleaning up temporary Qdrant collections for run {run_id}...")
            for store_type in qdrant_stores_to_clean:
                store_instance = get_vector_store(store_type) # Get default instance to find base name
                if store_instance and hasattr(store_instance, 'DEFAULT_COLLECTION_NAME'):
                    base_name = store_instance.DEFAULT_COLLECTION_NAME
                    temp_collection_name = _get_temp_collection_name(base_name, run_id)
                    try:
                        if qdrant_client.collection_exists(collection_name=temp_collection_name):
                            logger.info(f"Deleting temporary Qdrant collection: {temp_collection_name}")
                            qdrant_client.delete_collection(collection_name=temp_collection_name, timeout=60)
                        else:
                            logger.info(f"Temporary Qdrant collection {temp_collection_name} not found, skipping deletion.")
                    except Exception as e:
                        logger.error(f"Failed to delete temporary Qdrant collection '{temp_collection_name}': {e}")
                else:
                     logger.warning(f"Could not determine base collection name for '{store_type}' during temp cleanup.")

    # --- Cleanup Temp Haystack Memory Dir ---
    if 'haystack-memory' in target_stores:
        # TODO: Implement temp Haystack Memory directory cleanup
        logger.warning(f"Temporary Haystack Memory directory cleanup logic for Run ID {run_id} not yet implemented.")
        # Example:
        # temp_dir = Path(f"data/haystack_store_temp_{run_id}")
        # if temp_dir.exists(): shutil.rmtree(temp_dir) ...

    # --- Cleanup Temp S3 Objects/Prefixes ---
    if s3_client:
        # TODO: Implement temp S3 data cleanup (images, links, metadata, history file)
        logger.warning(f"Temporary S3 data cleanup logic for Run ID {run_id} not yet implemented.")
        # Example: list objects under temp prefixes and delete

    logger.info(f"--- Finished Cleanup for Temporary Data (Run ID: {run_id}) ---")


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

    # --- MODIFICATION: Extract store_arg for clarity ---
    store_argument = args.stores if args.stores else ['all'] # Use 'all' if no --store provided
    logger.info(f"Selected Store(s) argument: {store_argument}")
    # --- END MODIFICATION ---

    # Call the main refactored function
    success = manage_vector_stores(
        store_arg=store_argument, # Pass the potentially modified argument list/string
        cache_behavior=args.cache_behavior,
        s3_pdf_prefix=args.s3_pdf_prefix
    )

    if success:
        logger.info("Vector store management script finished successfully!")
    else:
        logger.error("Vector store management script finished with errors.")

    logger.info("Script finished") # Final script end message 