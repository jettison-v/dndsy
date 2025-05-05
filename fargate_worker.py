import boto3
import json
import logging
import os
import sys
import time
from pathlib import Path
from botocore.exceptions import ClientError
from typing import List

# Ensure the main app directory is in the path for imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import the refactored DataProcessor
from data_ingestion.processor import DataProcessor
from vector_store import get_vector_store # Still needed if we do checks here
from config import S3_BUCKET_NAME # Get bucket name from config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration from Environment Variables ---
SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Determine target stores from environment variable
TARGET_STORES_ENV = os.getenv("TARGET_STORES", "all") # Example: "pages,semantic" or "all"
def parse_target_stores(env_var: str) -> List[str]:
    if not env_var or env_var.lower() == 'all':
        # TODO: Define what 'all' means - fetch from vector_store factory?
        # Hardcoding for now based on README
        return ["pages", "semantic", "haystack-qdrant", "haystack-memory"]
    else:
        return [store.strip() for store in env_var.split(',') if store.strip()]

TARGET_STORES = parse_target_stores(TARGET_STORES_ENV)
logger.info(f"Worker configured to target stores: {TARGET_STORES}")

# --- AWS Clients ---
sqs_client = None
try:
    sqs_client = boto3.client("sqs", region_name=AWS_REGION)
    logger.info(f"Initialized SQS client for region: {AWS_REGION}")
except Exception as e:
    logger.exception(f"Failed to initialize SQS client: {e}")
    sys.exit(1)

# --- Main Worker Loop ---
def process_message(message: dict):
    """Processes a single message from the SQS queue."""
    logger.info(f"Received message: {message.get('MessageId')}")
    receipt_handle = message.get('ReceiptHandle')
    if not receipt_handle:
        logger.error("Message missing ReceiptHandle.")
        return # Cannot process or delete

    success = False # Default to failure
    s3_pdf_key = None # Keep track for logging

    try:
        body = json.loads(message.get('Body', '{}'))
        # Expected message format (from S3 Event Notification via SNS/SQS):
        # Adjust parsing based on actual S3 event structure if needed
        if 'Records' in body and len(body['Records']) > 0 and 's3' in body['Records'][0]:
             s3_info = body['Records'][0]['s3']
             bucket_name = s3_info['bucket']['name']
             s3_pdf_key = s3_info['object']['key']
             # URL Decode the key
             s3_pdf_key = requests.utils.unquote(s3_pdf_key)

             # Basic validation
             if bucket_name != S3_BUCKET_NAME:
                 logger.warning(f"Received notification for wrong bucket: {bucket_name}. Expected: {S3_BUCKET_NAME}. Skipping.")
                 success = True # Consider it processed as it's not for us
             elif not s3_pdf_key.lower().endswith('.pdf'):
                 logger.warning(f"Received non-PDF file notification: {s3_pdf_key}. Skipping.")
                 success = True # Consider it processed as it's not actionable
             else:
                 logger.info(f"Processing PDF: s3://{bucket_name}/{s3_pdf_key}")

                 # --- Instantiate DataProcessor --- 
                 # Use cache_behavior='use' for single file processing triggered by events
                 # The status_callback could be implemented to push updates to another queue/db
                 processor = DataProcessor(cache_behavior='use', status_callback=None) 

                 # --- Call the processing method --- 
                 # Pass the specific S3 key and the configured target stores
                 processing_result = processor.process_single_source(s3_pdf_key, TARGET_STORES)
                 success = processing_result # Update success based on return value

                 if not success:
                      logger.error(f"DataProcessor reported failure for {s3_pdf_key}.")

        else:
            logger.warning(f"Message body does not match expected S3 event format: {message.get('MessageId')}")
            success = True # Delete unprocessable message format

    except json.JSONDecodeError:
        logger.exception(f"Failed to decode message body: {message.get('MessageId')}")
        success = True # Delete malformed message
    except ImportError as e:
         logger.exception(f"ImportError during processing setup: {e}. Check dependencies and paths.")
         # Don't delete, might be a transient config issue
    except Exception as e:
        logger.exception(f"Unhandled error processing message {message.get('MessageId')}: {e}")
        # Let message return to queue for retry

    # --- Message Deletion --- 
    # Delete message only if processing was successful OR if the message was unprocessable/invalid
    if success and receipt_handle:
        try:
            sqs_client.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
            logger.info(f"Deleted message {message.get('MessageId')}{f' for {s3_pdf_key}' if s3_pdf_key else ''}.")
        except ClientError as del_e:
            logger.exception(f"Failed to delete message {message.get('MessageId')}: {del_e}")
    elif not success:
        logger.warning(f"Processing failed for message {message.get('MessageId')}{f' for {s3_pdf_key}' if s3_pdf_key else ''}. Message will return to queue.")

def poll_sqs():
    """Polls the SQS queue for messages and processes them."""
    if not sqs_client or not SQS_QUEUE_URL:
        logger.error("SQS Client or Queue URL not configured. Worker cannot run.")
        return

    logger.info(f"Starting SQS polling loop for queue: {SQS_QUEUE_URL}")
    while True:
        try:
            # Long polling
            response = sqs_client.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1, # Process one message at a time
                WaitTimeSeconds=20,   # Enable long polling
                MessageAttributeNames=['All'],
                AttributeNames=['All']
            )

            messages = response.get('Messages', [])
            if messages:
                process_message(messages[0])
            else:
                # No messages received, loop continues
                logger.debug("No messages received. Continuing poll.")
                pass

        except ClientError as e:
            # Handle specific SQS client errors if needed
            if e.response['Error']['Code'] == 'AWS.SimpleQueueService.NonExistentQueue':
                logger.error(f"SQS queue not found: {SQS_QUEUE_URL}. Worker stopping.")
                break # Exit loop if queue doesn't exist
            else:
                logger.error(f"SQS ClientError during polling: {e}")
                time.sleep(60) # Wait before retrying on other client errors
        except Exception as e:
            logger.exception(f"Unexpected error in SQS polling loop: {e}")
            time.sleep(30) # Wait before retrying

if __name__ == "__main__":
    # Add requests import for URL decoding
    import requests
    poll_sqs() 