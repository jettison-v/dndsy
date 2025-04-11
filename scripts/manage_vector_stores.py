from qdrant_client import QdrantClient
import os
# Updated import for DataProcessor
from data_ingestion.processor import DataProcessor
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
from vector_store import get_vector_store
# Import constants directly from the module
from data_ingestion.processor import PROCESS_HISTORY_FILE, PROCESS_HISTORY_S3_KEY, AWS_S3_BUCKET_NAME

env_path = project_root / '.env' # Define path to .env file
load_dotenv(dotenv_path=env_path) # Load environment variables from specified path

# Ensure logs directory exists relative to project root
logs_dir = project_root / 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'reset_script.log'), # Use the new name consistent with logs folder
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

def manage_vector_stores(force_reprocess_images=False, reset_history=False):
    """Resets vector stores and processes source documents."""
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
    
    # Delete existing collections if they exist
    try:
        logger.info("Deleting standard collection (dnd_knowledge)")
        client.delete_collection("dnd_knowledge")
        logger.info("Standard collection deleted successfully")
    except Exception as e:
        logger.warning(f"Could not delete standard collection: {e}")
    
    try:
        logger.info("Deleting semantic collection (dnd_semantic)")
        client.delete_collection("dnd_semantic")
        logger.info("Semantic collection deleted successfully")
    except Exception as e:
        logger.warning(f"Could not delete semantic collection: {e}")
    
    # Process PDFs from S3 for both collections
    logger.info("Initializing data processor")
    processor = DataProcessor()
    
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
                    history[pdf_key]['processed'] = False
                
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
    
    # Run the processing (the DataProcessor.process_all_sources method handles both collections)
    logger.info("Starting data processing...")
    documents = processor.process_all_sources()
    
    if documents:
        logger.info(f"Processing completed with {len(documents)} documents")
        return True
    else:
        logger.error("No documents were processed")
        return False

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Manage vector stores: reset and process documents")
    parser.add_argument('--force-reprocess-images', action='store_true', 
                        help="Force reprocessing of all images even if PDFs are unchanged")
    parser.add_argument('--reset-history', action='store_true', 
                        help="Reset processing history (forces complete reprocessing)")
    args = parser.parse_args()
    
    logger.info("Starting vector store management script")
    logger.info(f"Force reprocess images: {args.force_reprocess_images}")
    logger.info(f"Reset history: {args.reset_history}")
    
    success = manage_vector_stores(
        force_reprocess_images=args.force_reprocess_images, 
        reset_history=args.reset_history
    )
    
    if success:
        logger.info("Vector store management completed successfully!")
    else:
        logger.error("Vector store management completed with errors.")
    
    logger.info("Script finished") 