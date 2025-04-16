#!/usr/bin/env python
"""Common utility functions for data ingestion pipeline."""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Define constants previously in processor.py that these functions need
project_root = Path(__file__).resolve().parent.parent # Use resolve() for robustness
PROCESS_HISTORY_FILE = project_root / "data" / "pdf_process_history.json" # Correct path
PROCESS_HISTORY_S3_KEY = "processing/pdf_process_history.json"
PDF_IMAGE_DIR = "pdf_page_images"

def compute_pdf_hash(pdf_bytes: bytes) -> str:
    """Compute a SHA256 hash of PDF content."""
    return hashlib.sha256(pdf_bytes).hexdigest()

def load_process_history(s3_client: Optional[boto3.client], bucket_name: Optional[str]) -> Dict:
    """Load the PDF processing history from S3 or fall back to local file."""
    history = {}
    # First try to get from S3
    if s3_client and bucket_name:
        try:
            logger.info(f"Trying to load process history from S3: s3://{bucket_name}/{PROCESS_HISTORY_S3_KEY}")
            response = s3_client.get_object(
                Bucket=bucket_name, 
                Key=PROCESS_HISTORY_S3_KEY
            )
            history_content = response['Body'].read().decode('utf-8')
            history = json.loads(history_content)
            logger.info(f"Successfully loaded process history from S3")
            
            # Save locally as a backup (ensure parent directory exists)
            try:
                PROCESS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(PROCESS_HISTORY_FILE, 'w') as f:
                    json.dump(history, f, indent=2)
                logger.info(f"Saved S3 history locally to {PROCESS_HISTORY_FILE}")
            except IOError as e:
                 logger.error(f"Could not write local history backup {PROCESS_HISTORY_FILE}: {e}")
                 
            return history
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"Process history file not found in S3 ({bucket_name}/{PROCESS_HISTORY_S3_KEY}), will try local or create new.")
            else:
                logger.warning(f"S3 Error accessing process history {PROCESS_HISTORY_S3_KEY}: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error loading process history from S3: {e}")
    
    # Fall back to local file if S3 failed or wasn't configured
    if os.path.exists(PROCESS_HISTORY_FILE):
        try:
            logger.info(f"Loading process history from local file: {PROCESS_HISTORY_FILE}")
            with open(PROCESS_HISTORY_FILE, 'r') as f:
                history = json.load(f)
            return history
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error reading local history file {PROCESS_HISTORY_FILE}: {e}")
            # Continue to return empty dict if local read fails
    
    # If neither works, start fresh
    logger.info("Starting with empty process history")
    return {}

def save_process_history(process_history: Dict, s3_client: Optional[boto3.client], bucket_name: Optional[str]):
    """Save the PDF processing history to S3 and local file."""
    # First save locally as a backup
    try:
        PROCESS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROCESS_HISTORY_FILE, 'w') as f:
            json.dump(process_history, f, indent=2)
        logger.info(f"Saved process history to local file {PROCESS_HISTORY_FILE}")
    except IOError as e:
        logger.error(f"Failed to save process history locally to {PROCESS_HISTORY_FILE}: {e}")

    # Then save to S3
    if s3_client and bucket_name:
        try:
            history_json = json.dumps(process_history)
            s3_client.put_object(
                Bucket=bucket_name,
                Key=PROCESS_HISTORY_S3_KEY,
                Body=history_json,
                ContentType='application/json'
            )
            logger.info(f"Saved process history to S3: s3://{bucket_name}/{PROCESS_HISTORY_S3_KEY}")
        except Exception as e:
            logger.error(f"Failed to save process history to S3: {e}")
    elif not s3_client or not bucket_name:
         logger.warning("S3 client/bucket not configured, skipping S3 history save.")

def clean_filename(filename: str) -> str:
    """Remove potentially problematic characters for filenames/paths."""
    # Remove directory separators and replace other non-alphanumeric with underscore
    cleaned = re.sub(r'[/\\]+', '_', filename) # Replace slashes with underscore
    cleaned = re.sub(r'[^a-zA-Z0-9_\-\.]+', '_', cleaned) # Replace others
    return cleaned

def delete_specific_s3_images(s3_client: Optional[boto3.client], bucket_name: Optional[str], pdf_image_sub_dir_name: str):
    """Delete only images related to a specific PDF subdirectory name."""
    if not s3_client or not bucket_name:
        logger.warning("S3 client/bucket not configured, skipping image deletion.")
        return
        
    image_prefix = f"{PDF_IMAGE_DIR}/{pdf_image_sub_dir_name}/" # Ensure trailing slash
    logger.info(f"Deleting S3 images with prefix: s3://{bucket_name}/{image_prefix}")
    
    objects_to_delete = []
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=image_prefix)
        
        object_keys = []
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    # Ensure we only delete files, not the prefix itself if it appears as an object
                    if obj['Key'] != image_prefix: 
                        object_keys.append(obj['Key'])
        
        if object_keys:
            objects_to_delete = [{'Key': k} for k in object_keys]
            logger.info(f"Found {len(objects_to_delete)} image objects to delete for {pdf_image_sub_dir_name}")
            # Delete objects in batches (max 1000 per request)
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i + 1000]
                delete_payload = {'Objects': batch, 'Quiet': True}
                logger.debug(f"Deleting batch {i//1000 + 1} of {len(objects_to_delete)//1000 + 1} ({len(batch)} objects)")
                response = s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete=delete_payload
                )
                # Log errors if any occurred during delete_objects
                if 'Errors' in response and response['Errors']:
                     logger.error(f"Errors encountered deleting image batch: {response['Errors']}")
            logger.info(f"Finished deleting {len(objects_to_delete)} images for {pdf_image_sub_dir_name}")
        else:
            logger.info(f"No existing images found for prefix {image_prefix}")
            
    except Exception as e:
        logger.error(f"Error listing/deleting images for prefix {image_prefix}: {e}") 