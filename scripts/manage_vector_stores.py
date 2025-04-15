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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'reset_script.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

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

def manage_vector_stores(force_reprocess_images=False, reset_history=False, only_pages=False,
                         only_semantic=False, only_haystack=False, haystack_type='haystack-qdrant'):
    """Resets vector stores and processes source documents, optionally targeting specific stores."""
    
    # Determine which stores to process based on the "only" flags
    # These flags are derived from the --store-type argument in __main__
    run_pages = only_pages or not (only_semantic or only_haystack)
    run_semantic = only_semantic or not (only_pages or only_haystack)
    run_haystack = only_haystack or not (only_pages or only_semantic)
    
    # Determine which Haystack types to run if Haystack processing is enabled
    # Default to 'haystack-qdrant' if 'both' is selected but only processing haystack
    effective_haystack_type = haystack_type
    if only_haystack and haystack_type == 'both':
         logger.warning("Cannot specify --haystack-type both when --store-type is haystack. Defaulting to haystack-qdrant.")
         effective_haystack_type = 'haystack-qdrant'
         
    run_haystack_qdrant = run_haystack and (effective_haystack_type == 'haystack-qdrant' or effective_haystack_type == 'both')
    run_haystack_memory = run_haystack and (effective_haystack_type == 'haystack-memory' or effective_haystack_type == 'both')

    logger.info(f"Processing Pages: {run_pages}")
    logger.info(f"Processing Semantic: {run_semantic}")
    logger.info(f"Processing Haystack Qdrant: {run_haystack_qdrant}")
    logger.info(f"Processing Haystack Memory: {run_haystack_memory}")

    overall_success = True
    # Using a set to track unique processed PDFs across runs
    processed_pdf_keys = set() 
    processing_summary = {}

    # --- Reset History (Run Once) ---
    if reset_history:
        _reset_processing_history()
        # Clear the set as history is reset
        processed_pdf_keys = set() 

    # --- Pages and Semantic Processing ---
    if run_pages or run_semantic:
        logger.info("--- Starting Pages/Semantic Processing ---")
        client = _get_qdrant_client()
        if run_pages:
            _clear_pages_collection(client)
        if run_semantic:
            _clear_semantic_collection(client)
            
        # Modify history for reprocessing pages/semantic if needed
        if force_reprocess_images and not reset_history:
            _modify_history_for_reprocessing(run_pages, run_semantic, False, None)

        logger.info("Initializing data processor for Pages/Semantic stores...")
        processor_pg_sem = DataProcessor(
            process_pages=run_pages,
            process_semantic=run_semantic,
            process_haystack=False,
            force_reprocess_images=force_reprocess_images
        )
        
        logger.info("Running data processing for Pages/Semantic stores...")
        processed_count_pg_sem = processor_pg_sem.process_all_sources(processed_pdf_keys_tracker=processed_pdf_keys)
        
        # Capture summary details
        if run_pages:
             processing_summary["Pages"] = f"{getattr(processor_pg_sem, 'pages_points_total', 'Unknown')} points added"
        if run_semantic:
            processing_summary["Semantic"] = f"{getattr(processor_pg_sem, 'semantic_points_total', 'Unknown')} points added"
            
        if processed_count_pg_sem < 0:
             overall_success = False
             logger.error("Errors occurred during Pages/Semantic processing.")
        logger.info("--- Finished Pages/Semantic Processing ---")


    # --- Haystack Qdrant Processing ---
    if run_haystack_qdrant:
        logger.info("--- Starting Haystack Qdrant Processing ---")
        _clear_haystack_store('haystack-qdrant')
        os.environ["HAYSTACK_STORE_TYPE"] = "haystack-qdrant"

        # Modify history for reprocessing haystack if needed
        # Check reset_history flag because _reset_processing_history already clears history
        if force_reprocess_images and not reset_history:
             if not (run_pages or run_semantic):
                 _modify_history_for_reprocessing(False, False, True, 'haystack-qdrant')

        logger.info("Initializing data processor for Haystack Qdrant store...")
        # Use force_processing=True because we always clear the store here
        processor_hq = DataProcessor(
            process_pages=False,
            process_semantic=False,
            process_haystack=True, # This processor instance only handles haystack
            force_processing=True, 
            force_reprocess_images=force_reprocess_images # Pass the flag
        )

        logger.info("Running data processing for Haystack Qdrant store...")
        # Pass the set to track processed files
        processed_count_hq = processor_hq.process_all_sources(processed_pdf_keys_tracker=processed_pdf_keys) 

        # Capture summary details
        processing_summary["Haystack-qdrant"] = f"{getattr(processor_hq, 'haystack_points_total', 'Unknown')} points added"
        
        if processed_count_hq < 0: # Check for errors
            overall_success = False
            logger.error("Errors occurred during Haystack Qdrant processing.")
        logger.info("--- Finished Haystack Qdrant Processing ---")


    # --- Haystack Memory Processing ---
    if run_haystack_memory:
        logger.info("--- Starting Haystack Memory Processing ---")
        _clear_haystack_store('haystack-memory')
        os.environ["HAYSTACK_STORE_TYPE"] = "haystack-memory"

        # Modify history for reprocessing haystack if needed
        # Check reset_history flag because _reset_processing_history already clears history
        if force_reprocess_images and not reset_history:
             if not (run_pages or run_semantic or run_haystack_qdrant):
                 _modify_history_for_reprocessing(False, False, True, 'haystack-memory')

        logger.info("Initializing data processor for Haystack Memory store...")
        # Use force_processing=True because we always clear the store here
        processor_hm = DataProcessor(
            process_pages=False,
            process_semantic=False,
            process_haystack=True, # This processor instance only handles haystack
            force_processing=True, 
            force_reprocess_images=force_reprocess_images # Pass the flag
        )

        logger.info("Running data processing for Haystack Memory store...")
        # Pass the set to track processed files
        processed_count_hm = processor_hm.process_all_sources(processed_pdf_keys_tracker=processed_pdf_keys)
        
        # Capture summary details
        processing_summary["Haystack-memory"] = f"{getattr(processor_hm, 'haystack_points_total', 'Unknown')} points added"

        if processed_count_hm < 0: # Check for errors
            overall_success = False
            logger.error("Errors occurred during Haystack Memory processing.")
        logger.info("--- Finished Haystack Memory Processing ---")


    # --- Final Summary ---
    logger.info("=== Overall Processing Summary ===")
    if not processing_summary:
         logger.warning("No stores were processed.")
    else:
        for store_name, result in processing_summary.items():
            logger.info(f"{store_name}: {result}")

    # Report total unique PDFs processed
    logger.info(f"Processed {len(processed_pdf_keys)} unique PDFs across all relevant stores.")

    if overall_success:
        logger.info(f"Vector store management completed successfully!")
    else:
         logger.error("Vector store management completed with errors in one or more steps.")

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

def _clear_haystack_store(haystack_type):
    """Clear the haystack store of the specified type."""
    try:
        haystack_store = get_vector_store(haystack_type)
        logger.info(f"Clearing {haystack_type} store")
        
        # For QdrantDocumentStore, delete the entire collection
        try:
            if haystack_type == 'haystack-qdrant':
                # Get the collection name from the document store
                collection_name = None
                try:
                    # Try different ways to get the collection name
                    if hasattr(haystack_store.document_store, 'collection_name'):
                        collection_name = haystack_store.document_store.collection_name
                    elif hasattr(haystack_store.document_store, '_collection_name'):
                        collection_name = haystack_store.document_store._collection_name
                    else:
                        # Fallback to default collection name from the store
                        collection_name = haystack_store.DEFAULT_COLLECTION_NAME
                except Exception as e:
                    # Last resort - use a hardcoded default
                    collection_name = "dnd_haystack_qdrant"
                    logger.warning(f"Could not determine collection name, using default: {collection_name}")
                
                if collection_name:
                    # Get a Qdrant client directly
                    client = _get_qdrant_client()
                    logger.info(f"Deleting entire Haystack Qdrant collection: {collection_name}")
                    try:
                        client.delete_collection(collection_name)
                        logger.info(f"Successfully deleted Haystack Qdrant collection: {collection_name}")
                    except Exception as del_e:
                        logger.warning(f"Error deleting collection {collection_name}: {del_e}")
                        
                        # Fallback to just clearing documents if we can't delete the collection
                        logger.info("Falling back to document deletion...")
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
                    logger.warning("Could not determine collection name, falling back to document deletion")
                    # Fallback to just clearing documents
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
            
            # For Memory Store, handle differently
            elif haystack_type == 'haystack-memory':
                # For Haystack Memory Store, we might need to delete the persistence file
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
        logger.warning(f"Could not clear {haystack_type} store: {e}")

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

def _modify_history_for_reprocessing(only_pages, only_semantic, only_haystack, haystack_type):
    """Modify processing history to force reprocessing."""
    logger.info("Force reprocessing of images requested")
    # Load the history if it exists
    try:
        if os.path.exists(PROCESS_HISTORY_FILE):
            with open(PROCESS_HISTORY_FILE, 'r') as f:
                history = json.load(f)
            
            # Set all PDFs as not processed to force regeneration
            for pdf_key in history:
                history[pdf_key]['processed'] = False
                
                # If processing only a specific store, clear only that store's processed flag
                if only_haystack:
                    logger.info(f"Clearing {haystack_type} from processed stores for all PDFs")
                    # Make sure processed_stores exists for each PDF
                    if 'processed_stores' not in history[pdf_key]:
                        history[pdf_key]['processed_stores'] = []
                    # Remove haystack from processed stores if it's there
                    for store_type in ['haystack', 'haystack-qdrant', 'haystack-memory']:
                        if store_type in history[pdf_key].get('processed_stores', []):
                            history[pdf_key]['processed_stores'].remove(store_type)
                elif only_semantic:
                    logger.info(f"Clearing semantic from processed stores for all PDFs")
                    if 'processed_stores' not in history[pdf_key]:
                        history[pdf_key]['processed_stores'] = []
                    if 'semantic' in history[pdf_key].get('processed_stores', []):
                        history[pdf_key]['processed_stores'].remove('semantic')
                elif only_pages:
                    logger.info(f"Clearing pages from processed stores for all PDFs")
                    if 'processed_stores' not in history[pdf_key]:
                        history[pdf_key]['processed_stores'] = []
                    if 'pages' in history[pdf_key].get('processed_stores', []):
                        history[pdf_key]['processed_stores'].remove('pages')
                else:
                    # If processing all stores, clear all processed_stores
                    logger.info(f"Clearing all processed stores for all PDFs")
                    history[pdf_key]['processed_stores'] = []
            
            # Save modified history
            with open(PROCESS_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            
            # Also update in S3
            s3_client = get_s3_client()
            if s3_client and AWS_S3_BUCKET_NAME:
                try:
                    history_json = json.dumps(history)
                    s3_client.put_object(
                        Bucket=AWS_S3_BUCKET_NAME,
                        Key=PROCESS_HISTORY_S3_KEY,
                        Body=history_json,
                        ContentType='application/json'
                    )
                    logger.info(f"Updated process history in S3 to force reprocessing")
                except Exception as e:
                    logger.error(f"Error updating S3 process history: {e}")
            
            logger.info("Modified history to force reprocessing of all images")
    except Exception as e:
        logger.error(f"Error modifying process history: {e}")

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Manage vector stores: reset and process documents")
    parser.add_argument('--force-reprocess-images', action='store_true', 
                        help="Force reprocessing of all images even if PDFs are unchanged")
    parser.add_argument('--reset-history', action='store_true', 
                        help="Reset processing history (forces complete reprocessing)")
    
    # Replace multiple flags with a single store type parameter
    parser.add_argument('--store-type', choices=['all', 'pages', 'semantic', 'haystack'], 
                        default='all', help="Which store type to process (default: all)")
    
    # Haystack type is now only relevant when store-type is haystack
    parser.add_argument('--haystack-type', choices=['haystack-qdrant', 'haystack-memory', 'both'], 
                        default='haystack-qdrant', help="The type of Haystack store to use (default: haystack-qdrant)")
    args = parser.parse_args()
    
    logger.info("Starting vector store management script")
    logger.info(f"Force reprocess images: {args.force_reprocess_images}")
    logger.info(f"Reset history: {args.reset_history}")
    logger.info(f"Store type: {args.store_type}")
    
    if args.store_type == 'haystack' or args.store_type == 'all':
        logger.info(f"Haystack type: {args.haystack_type}")
    
    # Convert new parameters to old format
    only_pages = args.store_type == 'pages'
    only_semantic = args.store_type == 'semantic'
    only_haystack = args.store_type == 'haystack'
    
    # For 'both' haystack type, use the original haystack-qdrant value
    # It will handle both types in its logic
    haystack_type = args.haystack_type
    if haystack_type == 'both':
        haystack_type = 'haystack-qdrant'  # The function will handle both types
    
    success = manage_vector_stores(
        force_reprocess_images=args.force_reprocess_images, 
        reset_history=args.reset_history,
        only_pages=only_pages,
        only_semantic=only_semantic,
        only_haystack=only_haystack,
        haystack_type=haystack_type
    )
    
    if success:
        logger.info("Vector store management completed successfully!")
    else:
        logger.error("Vector store management completed with errors.")
    
    logger.info("Script finished") 