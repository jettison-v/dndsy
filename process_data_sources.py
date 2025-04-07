import os
import json
from pathlib import Path
import fitz  # PyMuPDF
from vector_store.qdrant_store import QdrantStore
from tqdm import tqdm
import logging
import sys
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re # Import re for path cleaning
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import io # For handling image data in memory

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_processing.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Define base directory for images relative to static folder
PDF_IMAGE_DIR = "pdf_page_images"
STATIC_DIR = "static" # Define static directory name

# --- AWS S3 Configuration ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1") # Default region if not set

s3_client = None
if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET_NAME:
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION
        )
        logging.info(f"Initialized S3 client for bucket: {AWS_S3_BUCKET_NAME} in region: {AWS_REGION}")
    except (NoCredentialsError, PartialCredentialsError) as e:
        logging.error(f"AWS Credentials not found or incomplete: {e}")
    except Exception as e:
        logging.error(f"Failed to initialize S3 client: {e}")
else:
    logging.warning("AWS S3 credentials/bucket name not fully configured. Image uploads will be skipped.")

class DataProcessor:
    def __init__(self):
        """Initialize the data processor."""
        self.vector_store = QdrantStore()
        self.processed_sources = set()
    
    def _clean_filename(self, filename: str) -> str:
        """Remove potentially problematic characters for filenames/paths."""
        # Remove directory separators and replace other non-alphanumeric with underscore
        cleaned = re.sub(r'[/\\]+', '_', filename) # Replace slashes with underscore
        cleaned = re.sub(r'[^a-zA-Z0-9_\-\.]+', '_', cleaned) # Replace others
        return cleaned

    def process_pdfs(self, pdf_dir: str) -> List[Dict[str, Any]]:
        """Process PDF files, generate page images, and return documents."""
        pdf_dir_path = Path(pdf_dir)
        documents = []
        
        # S3 base path
        s3_base_key_prefix = PDF_IMAGE_DIR

        # Find all PDF files
        pdf_files = list(pdf_dir_path.rglob('*.pdf'))
        logging.info(f"Found {len(pdf_files)} PDF files to process")
        
        for pdf_path in tqdm(pdf_files, desc="Processing PDFs"):
            try:
                rel_path = str(pdf_path.relative_to(pdf_dir_path))
                # Clean the relative path to use as a directory name
                pdf_image_sub_dir_name = self._clean_filename(rel_path.replace('.pdf', ''))

                # Extract text and generate images page by page
                doc = fitz.open(pdf_path)
                total_pages = len(doc) # Get total page count

                for page_num, page in enumerate(doc): 
                    page_text = page.get_text().strip()
                    if not page_text: 
                        continue

                    page_label = page_num + 1 
                    page_source_id = f"{rel_path}_page_{page_label}"

                    if page_source_id in self.processed_sources:
                        # logging.info(f"Skipping already processed page: {page_source_id}") # Can be verbose
                        continue
                    
                    # Generate image
                    image_filename = f"page_{page_label}.png"
                    s3_object_key = f"{s3_base_key_prefix}/{pdf_image_sub_dir_name}/{image_filename}"
                    s3_image_url = None # Default to None
                    
                    try:
                        pix = page.get_pixmap(dpi=150) # Render at 150 DPI
                        # Convert pixmap to PNG bytes in memory
                        img_bytes = pix.tobytes("png")
                        img_file_obj = io.BytesIO(img_bytes)

                        # Upload to S3 if client is configured
                        if s3_client:
                            try:
                                s3_client.upload_fileobj(
                                    img_file_obj, 
                                    AWS_S3_BUCKET_NAME, 
                                    s3_object_key,
                                    ExtraArgs={
                                        'ACL': 'public-read', 
                                        'ContentType': 'image/png'
                                    }
                                )
                                # Construct the public S3 URL
                                s3_image_url = f"https://{AWS_S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_object_key}"
                                logging.debug(f"Successfully uploaded {s3_object_key} to S3.")
                            except ClientError as s3_e:
                                logging.error(f"Error uploading {s3_object_key} to S3: {s3_e}")
                            except Exception as s3_e:
                                logging.error(f"Unexpected error during S3 upload for {s3_object_key}: {s3_e}")
                        else:
                            logging.warning(f"S3 client not configured. Skipping upload for {s3_object_key}")

                    except Exception as img_e:
                        logging.error(f"Error generating image for {rel_path} page {page_label}: {img_e}")
                        s3_image_url = None # Ensure URL is None if image gen fails

                    # Create document per page
                    document = {
                        "text": page_text, 
                        "metadata": {
                            "source": rel_path, 
                            "page": page_label, 
                            "image_url": s3_image_url, # Store the S3 URL (or None)
                            "total_pages": total_pages, # Add total pages
                            "source_dir": pdf_image_sub_dir_name, # Add cleaned source dir name
                            "type": "pdf",
                            "folder": str(pdf_path.parent.relative_to(pdf_dir_path)), # Store relative folder
                            "filename": pdf_path.name,
                            "processed_at": datetime.now().isoformat()
                        }
                    }
                    documents.append(document)
                    self.processed_sources.add(page_source_id) 

                doc.close()

            except Exception as e:
                logging.error(f"Error processing {pdf_path}: {str(e)}")
        
        return documents
    
    def process_all_sources(self):
        """Process all data sources and add to vector store."""
        # Process PDFs
        pdf_documents = self.process_pdfs("data/pdfs")
        if pdf_documents:
            logging.info(f"Adding {len(pdf_documents)} PDF documents to vector store")
            self.vector_store.add_documents(pdf_documents)
        
        logging.info("PDF Processing complete!") # Updated log message

def main():
    processor = DataProcessor()
    processor.process_all_sources()

if __name__ == "__main__":
    main() 