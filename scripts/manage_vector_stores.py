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

def manage_vector_stores(force_reprocess_images=False, reset_history=False, only_standard=False, 
                         only_semantic=False, only_haystack=False, haystack_type='haystack-qdrant'):
    """Resets vector stores and processes source documents, optionally targeting specific stores."""
    
    # Determine which stores to process
    process_standard = not (only_semantic or only_haystack)
    process_semantic = not (only_standard or only_haystack)
    process_haystack = not (only_standard or only_semantic)
    
    logger.info(f"Processing standard store: {process_standard}")
    logger.info(f"Processing semantic store: {process_semantic}")
    logger.info(f"Processing haystack store: {process_haystack}")
    
    # Special handling when processing haystack without specifying a specific type
    if process_haystack and not only_haystack and haystack_type == 'haystack-qdrant':
        logger.info("Processing both Haystack implementations because no specific type was provided")
        
        # First process with Qdrant
        logger.info("First processing with Haystack (Qdrant)")
        os.environ["HAYSTACK_STORE_TYPE"] = "haystack-qdrant"
        process_with_qdrant = manage_vector_stores(
            force_reprocess_images=force_reprocess_images,
            reset_history=reset_history,
            only_standard=False,
            only_semantic=False, 
            only_haystack=True,
            haystack_type='haystack-qdrant'
        )
        
        # Then process with Memory
        logger.info("Now processing with Haystack (Memory)")
        os.environ["HAYSTACK_STORE_TYPE"] = "haystack-memory"
        process_with_memory = manage_vector_stores(
            force_reprocess_images=force_reprocess_images,
            reset_history=reset_history,
            only_standard=False,
            only_semantic=False,
            only_haystack=True, 
            haystack_type='haystack-memory'
        )
        
        # Return the combined result
        return process_with_qdrant and process_with_memory
    
    if process_haystack:
        logger.info(f"Using haystack type: {haystack_type}")
        # Set environment variable for DataProcessor to use
        os.environ["HAYSTACK_STORE_TYPE"] = haystack_type

    # Reset processing history if requested
    if reset_history:
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

    # Initialize Qdrant client (handling cloud/local)
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
    
    # Conditionally delete existing collections
    if process_standard:
        try:
            # Try to get the collection name from the class
            try:
                collection_name = PdfPagesStore.DEFAULT_COLLECTION_NAME
            except AttributeError:
                # Fallback to a hardcoded value if not available as a class attribute
                collection_name = "dnd_pdf_pages"
                
            logger.info(f"Deleting PDF pages collection ({collection_name})")
            client.delete_collection(collection_name)
            logger.info("PDF pages collection deleted successfully")
        except Exception as e:
            logger.warning(f"Could not delete PDF pages collection ({collection_name}): {e}")
    
    if process_semantic:
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
            
    if process_haystack:
        try:
            haystack_store = get_vector_store(haystack_type)
            logger.info(f"Clearing {haystack_type} store")
            
            # For QdrantDocumentStore, we use delete_documents to clear it
            try:
                # Clean delete all documents in the store
                haystack_store.document_store.delete_documents()
                logger.info(f"Cleared all documents from {haystack_type} store")
            except Exception as e:
                logger.warning(f"Error clearing {haystack_type} store: {e}")
                
                # For Haystack Memory Store, we might need to delete the persistence file
                if haystack_type == 'haystack-memory':
                    try:
                        persistence_file = getattr(haystack_store, 'persistence_file', None)
                        if persistence_file and os.path.exists(persistence_file):
                            os.remove(persistence_file)
                            logger.info(f"Deleted haystack persistence file: {persistence_file}")
                    except Exception as file_e:
                        logger.warning(f"Could not delete persistence file: {file_e}")
                
                logger.info(f"Will attempt to reset the {haystack_type} store")
                
                # Try to completely delete and recreate the collection if available
                try:
                    haystack_store.document_store.delete_index(haystack_store.collection_name)
                    logger.info(f"Deleted haystack index: {haystack_store.collection_name}")
                    
                    # Recreate the index with the same parameters
                    haystack_store.document_store.create_index(
                        index=haystack_store.collection_name,
                        embedding_dim=384  # Match the EMBEDDING_DIMENSION in common.py
                    )
                    logger.info(f"Recreated haystack index: {haystack_store.collection_name}")
                except Exception as inner_e:
                    logger.warning(f"Could not reset haystack index: {inner_e}")
                    logger.info(f"Will initialize a fresh {haystack_type} store")
        except Exception as e:
            logger.warning(f"Could not clear {haystack_type} store: {e}")
    
    # Process PDFs from S3 for all applicable collections
    logger.info("Initializing data processor")
    
    # When processing only haystack, force it to process PDFs regardless of change status
    force_processing = only_haystack
    if force_processing:
        logger.info(f"Forcing processing for {haystack_type} regardless of PDF change status")
    
    processor = DataProcessor(
        process_standard=process_standard, 
        process_semantic=process_semantic,
        process_haystack=process_haystack,
        force_processing=force_processing
    )
    
    # If force reprocessing is requested, modify the process history
    if force_reprocess_images and not reset_history:
        logger.info("Force reprocessing of images requested")
        # Load the history if it exists
        try:
            if os.path.exists(PROCESS_HISTORY_FILE):
                with open(PROCESS_HISTORY_FILE, 'r') as f:
                    history = json.load(f)
                
                # Set all PDFs as not processed to force regeneration
                for pdf_key in history:
                    # Mark as not processed overall
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
                    elif only_standard:
                        logger.info(f"Clearing standard from processed stores for all PDFs")
                        if 'processed_stores' not in history[pdf_key]:
                            history[pdf_key]['processed_stores'] = []
                        if 'standard' in history[pdf_key].get('processed_stores', []):
                            history[pdf_key]['processed_stores'].remove('standard')
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
    
    # Run the processing
    logger.info("Starting data processing...")
    processed_count = processor.process_all_sources()
    
    # Prepare a detailed summary of what was processed
    summary = {}
    if process_standard:
        summary["standard"] = f"{processor.standard_points_total if hasattr(processor, 'standard_points_total') else 'Unknown'} points added"
    if process_semantic:
        summary["semantic"] = f"{processor.semantic_points_total if hasattr(processor, 'semantic_points_total') else 'Unknown'} points added"
    if process_haystack:
        # Try to get haystack-specific information if available
        if hasattr(processor, "haystack_points_total"):
            summary[haystack_type] = f"{processor.haystack_points_total} points added"
        else:
            # For backward compatibility
            summary[haystack_type] = "Processing completed"
    
    # Log the detailed processing summary
    logger.info("=== Processing Summary ===")
    for store_name, result in summary.items():
        logger.info(f"{store_name.capitalize()}: {result}")
    
    if processed_count > 0:
        logger.info(f"Processing completed. Processed {processed_count} total points/documents.")
        return True
    elif processed_count == 0:
        logger.warning("Processing completed, but no documents/points were processed or added.")
        return True # Still consider it a success if no errors, just nothing to process
    else:
        logger.error("Processing completed with unexpected result.")
        return False

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Manage vector stores: reset and process documents")
    parser.add_argument('--force-reprocess-images', action='store_true', 
                        help="Force reprocessing of all images even if PDFs are unchanged")
    parser.add_argument('--reset-history', action='store_true', 
                        help="Reset processing history (forces complete reprocessing)")
    # Add arguments to target specific stores
    parser.add_argument('--only-standard', action='store_true', help="Only reset and process the standard (PDF pages) store.")
    parser.add_argument('--only-semantic', action='store_true', help="Only reset and process the semantic store.")
    parser.add_argument('--only-haystack', action='store_true', help="Only reset and process the haystack store.")
    # Add argument for haystack type
    parser.add_argument('--haystack-type', choices=['haystack-qdrant', 'haystack-memory'], 
                        default='haystack-qdrant', help="The type of Haystack store to use (default: haystack-qdrant)")
    args = parser.parse_args()
    
    # Count how many 'only' flags are set
    only_flags_count = sum([args.only_standard, args.only_semantic, args.only_haystack])
    
    if only_flags_count > 1:
        logger.error("Cannot specify more than one 'only' flag at the same time.")
        sys.exit(1)
        
    logger.info("Starting vector store management script")
    logger.info(f"Force reprocess images: {args.force_reprocess_images}")
    logger.info(f"Reset history: {args.reset_history}")
    logger.info(f"Only Standard: {args.only_standard}")
    logger.info(f"Only Semantic: {args.only_semantic}")
    logger.info(f"Only Haystack: {args.only_haystack}")
    if args.only_haystack or not only_flags_count:
        logger.info(f"Haystack type: {args.haystack_type}")
    
    success = manage_vector_stores(
        force_reprocess_images=args.force_reprocess_images, 
        reset_history=args.reset_history,
        only_standard=args.only_standard,
        only_semantic=args.only_semantic,
        only_haystack=args.only_haystack,
        haystack_type=args.haystack_type
    )
    
    if success:
        logger.info("Vector store management completed successfully!")
    else:
        logger.error("Vector store management completed with errors.")
    
    logger.info("Script finished") 