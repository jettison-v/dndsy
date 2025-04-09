import os
import json
from pathlib import Path
import fitz  # PyMuPDF
import sys
import hashlib  # For PDF content hashing

# Add parent directory to path to make imports work properly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from vector_store import get_vector_store
from utils.document_structure import DocumentStructureAnalyzer

from tqdm import tqdm
import logging
import sys
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re # Import re for path cleaning
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import io # For handling image data in memory
from dotenv import load_dotenv

# Ensure logs directory exists
logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(logs_dir, 'data_processing.log')),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Define base directory for images relative to static folder
PDF_IMAGE_DIR = "pdf_page_images"
STATIC_DIR = "static" # Define static directory name
# File to store processing history (both locally and on S3)
PROCESS_HISTORY_FILE = "pdf_process_history.json"
PROCESS_HISTORY_S3_KEY = "processing/pdf_process_history.json"  # S3 path

# --- AWS S3 Configuration ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1") # Default region if not set

# New variable for PDF source location in S3
AWS_S3_PDF_PREFIX = os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/") 
# Ensure prefix ends with a slash if it's not empty
if AWS_S3_PDF_PREFIX and not AWS_S3_PDF_PREFIX.endswith('/'):
    AWS_S3_PDF_PREFIX += '/'

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
        # Get both vector stores
        self.standard_store = get_vector_store("standard")
        self.semantic_store = get_vector_store("semantic")
        self.processed_sources = set()
        
        # Create document structure analyzer
        self.doc_analyzer = DocumentStructureAnalyzer()
        
        # Load process history if exists
        self.process_history = self._load_process_history()
        self.reprocessed_pdfs = []  # Track which PDFs were reprocessed
        self.unchanged_pdfs = []    # Track which PDFs were unchanged
    
    def _compute_pdf_hash(self, pdf_bytes):
        """Compute a hash of PDF content to detect changes."""
        return hashlib.sha256(pdf_bytes).hexdigest()
    
    def _load_process_history(self):
        """Load the PDF processing history from S3 or fall back to local file."""
        try:
            # First try to get from S3
            if s3_client:
                try:
                    logging.info(f"Trying to load process history from S3: {PROCESS_HISTORY_S3_KEY}")
                    response = s3_client.get_object(
                        Bucket=AWS_S3_BUCKET_NAME, 
                        Key=PROCESS_HISTORY_S3_KEY
                    )
                    history_content = response['Body'].read().decode('utf-8')
                    history = json.loads(history_content)
                    logging.info(f"Successfully loaded process history from S3")
                    
                    # Also save it locally as a backup
                    with open(PROCESS_HISTORY_FILE, 'w') as f:
                        json.dump(history, f, indent=2)
                    
                    return history
                except ClientError as e:
                    if e.response['Error']['Code'] == 'NoSuchKey':
                        logging.info(f"Process history file not found in S3, will create new one")
                    else:
                        logging.warning(f"Error accessing S3 process history: {e}")
                except Exception as e:
                    logging.warning(f"Unexpected error loading process history from S3: {e}")
            
            # Fall back to local file
            if os.path.exists(PROCESS_HISTORY_FILE):
                logging.info("Loading process history from local file")
                with open(PROCESS_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            
            # If neither works, start fresh
            logging.info("Starting with empty process history")
            return {}
            
        except Exception as e:
            logging.warning(f"Could not load process history: {e}")
            return {}
    
    def _save_process_history(self):
        """Save the PDF processing history to S3 and local file."""
        try:
            # First save locally as a backup
            with open(PROCESS_HISTORY_FILE, 'w') as f:
                json.dump(self.process_history, f, indent=2)
            logging.info(f"Saved process history to local file {PROCESS_HISTORY_FILE}")
            
            # Then save to S3
            if s3_client:
                try:
                    history_json = json.dumps(self.process_history)
                    s3_client.put_object(
                        Bucket=AWS_S3_BUCKET_NAME,
                        Key=PROCESS_HISTORY_S3_KEY,
                        Body=history_json,
                        ContentType='application/json'
                    )
                    logging.info(f"Saved process history to S3: {PROCESS_HISTORY_S3_KEY}")
                except Exception as e:
                    logging.error(f"Failed to save process history to S3: {e}")
        except Exception as e:
            logging.error(f"Failed to save process history: {e}")
    
    def _clean_filename(self, filename: str) -> str:
        """Remove potentially problematic characters for filenames/paths."""
        # Remove directory separators and replace other non-alphanumeric with underscore
        cleaned = re.sub(r'[/\\]+', '_', filename) # Replace slashes with underscore
        cleaned = re.sub(r'[^a-zA-Z0-9_\-\.]+', '_', cleaned) # Replace others
        return cleaned
        
    def _delete_specific_s3_images(self, pdf_prefix):
        """Delete only images related to a specific PDF."""
        if not s3_client:
            return
            
        image_prefix = f"{PDF_IMAGE_DIR}/{pdf_prefix}"
        logging.info(f"Deleting images with prefix: {image_prefix}")
        
        objects_to_delete = []
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=image_prefix)
            
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        objects_to_delete.append({'Key': obj['Key']})
            
            if objects_to_delete:
                logging.info(f"Found {len(objects_to_delete)} image objects to delete for {pdf_prefix}")
                # Delete objects in batches
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i:i + 1000]
                    delete_payload = {'Objects': batch, 'Quiet': True}
                    s3_client.delete_objects(
                        Bucket=AWS_S3_BUCKET_NAME,
                        Delete=delete_payload
                    )
                logging.info(f"Deleted {len(objects_to_delete)} images for {pdf_prefix}")
            else:
                logging.info(f"No existing images found for {pdf_prefix}")
                
        except Exception as e:
            logging.error(f"Error deleting images for {pdf_prefix}: {e}")

    def process_pdfs_from_s3(self) -> List[Dict[str, Any]]:
        """Process PDF files from S3, generate page images, and return documents."""
        if not s3_client:
            logging.error("S3 client not configured. Cannot process PDFs from S3.")
            return []

        documents = []
        
        # S3 base path for generated images
        s3_base_key_prefix = PDF_IMAGE_DIR

        # List PDF files from S3
        pdf_files_s3_keys = []
        try:
            logging.info(f"Listing PDF files from S3 bucket {AWS_S3_BUCKET_NAME}, prefix {AWS_S3_PDF_PREFIX}")
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=AWS_S3_PDF_PREFIX)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        # Ensure it's a PDF and not just the prefix itself
                        if key.lower().endswith('.pdf') and key != AWS_S3_PDF_PREFIX:
                            pdf_files_s3_keys.append(key)
        except ClientError as e:
            logging.error(f"Failed to list PDFs from S3 prefix '{AWS_S3_PDF_PREFIX}': {e}")
            return []
        except Exception as e:
            logging.error(f"Unexpected error listing PDFs from S3: {e}")
            return []

        start_time = datetime.now()
        total_pdfs = len(pdf_files_s3_keys)
        logging.info(f"===== Found {total_pdfs} PDF files in S3 prefix '{AWS_S3_PDF_PREFIX}' =====")
        logging.info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        standard_docs_total = 0
        semantic_docs_total = 0
        
        for pdf_index, s3_pdf_key in enumerate(tqdm(pdf_files_s3_keys, desc="Processing PDFs from S3")):
            try:
                current_time = datetime.now()
                elapsed = (current_time - start_time).total_seconds()
                progress_pct = (pdf_index / total_pdfs) * 100 if total_pdfs > 0 else 0
                
                logging.info(f"===== Processing PDF {pdf_index+1}/{total_pdfs} ({progress_pct:.1f}%) - {s3_pdf_key} =====")
                if pdf_index > 0:  # Only show time estimates after first PDF
                    avg_time_per_pdf = elapsed / pdf_index
                    remaining_pdfs = total_pdfs - pdf_index
                    est_remaining_time = avg_time_per_pdf * remaining_pdfs
                    est_completion_time = current_time + timedelta(seconds=est_remaining_time)
                    logging.info(f"Elapsed time: {elapsed:.1f} seconds. Estimated completion time: {est_completion_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                # Extract relative path for use in naming etc.
                rel_path = s3_pdf_key[len(AWS_S3_PDF_PREFIX):] if s3_pdf_key.startswith(AWS_S3_PDF_PREFIX) else s3_pdf_key
                pdf_filename = rel_path.split('/')[-1]

                # Clean the relative path to use as a directory name
                pdf_image_sub_dir_name = self._clean_filename(rel_path.replace('.pdf', ''))
                
                # Download PDF content from S3
                try:
                    pdf_object = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                    pdf_bytes = pdf_object['Body'].read()
                    last_modified = pdf_object.get('LastModified', datetime.now()).isoformat()
                except ClientError as e:
                    logging.error(f"Failed to download PDF '{s3_pdf_key}' from S3: {e}")
                    continue # Skip this PDF
                except Exception as e:
                    logging.error(f"Unexpected error downloading PDF '{s3_pdf_key}' from S3: {e}")
                    continue

                # Compute hash of PDF content
                pdf_hash = self._compute_pdf_hash(pdf_bytes)
                
                # Check if PDF has changed since last processing
                pdf_info = self.process_history.get(s3_pdf_key, {})
                old_hash = pdf_info.get('hash')
                
                # If hash matches and images already exist, skip image generation
                if old_hash == pdf_hash and pdf_info.get('processed'):
                    logging.info(f"PDF {s3_pdf_key} unchanged since last processing, skipping image generation")
                    self.unchanged_pdfs.append(s3_pdf_key)
                    
                    # Still need to process text for embeddings
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    total_pages = len(doc)
                    logging.info(f"PDF has {total_pages} pages to process for text embeddings")
                    
                    # Process document for both standard and semantic approaches
                    standard_docs = []
                    semantic_docs = []

                    for page_num, page in enumerate(doc): 
                        if page_num % 10 == 0 and page_num > 0:
                            logging.info(f"Processed {page_num}/{total_pages} pages ({(page_num/total_pages*100):.1f}%)")
                            
                        page_text = page.get_text().strip()
                        if not page_text: 
                            continue

                        page_label = page_num + 1 
                        page_source_id = f"{rel_path}_page_{page_label}"

                        if page_source_id in self.processed_sources:
                            continue
                        
                        # Use existing image URL from history
                        page_key = f"{page_label}"
                        page_info = pdf_info.get('pages', {}).get(page_key, {})
                        s3_image_url = page_info.get('image_url')
                        
                        # Create document metadata
                        metadata = {
                            "source": s3_pdf_key,
                            "filename": pdf_filename,
                            "page": page_label,
                            "total_pages": total_pages,
                            "image_url": s3_image_url,
                            "source_dir": pdf_image_sub_dir_name,
                            "type": "pdf",
                            "folder": str(Path(rel_path).parent),
                            "processed_at": datetime.now().isoformat()
                        }
                        
                        # Standard approach
                        standard_docs.append({
                            "text": page_text,
                            "metadata": metadata.copy()
                        })
                        
                        # Semantic approach
                        semantic_docs.append({
                            "text": page_text,
                            "metadata": metadata.copy()
                        })
                        
                        # Mark as processed
                        self.processed_sources.add(page_source_id)
                    
                    # Add documents to both vector stores
                    if standard_docs:
                        logging.info(f"Adding {len(standard_docs)} documents to standard store from {pdf_filename}")
                        standard_docs_total += len(standard_docs)
                        self.standard_store.add_documents(standard_docs)
                        documents.extend(standard_docs)
                    
                    if semantic_docs:
                        logging.info(f"Adding {len(semantic_docs)} documents to semantic store from {pdf_filename}")
                        semantic_docs_total += len(semantic_docs)
                        self.semantic_store.add_documents(semantic_docs)
                    
                    # Close the document
                    doc.close()
                    continue
                
                # If we got here, PDF is new or changed - delete any existing images
                if old_hash and old_hash != pdf_hash:
                    logging.info(f"PDF {s3_pdf_key} has changed, regenerating images")
                    # Delete existing images for this PDF
                    self._delete_specific_s3_images(pdf_image_sub_dir_name)
                elif not old_hash:
                    logging.info(f"New PDF {s3_pdf_key}, generating images")
                
                self.reprocessed_pdfs.append(s3_pdf_key)
                
                # Track processing in history
                if s3_pdf_key not in self.process_history:
                    self.process_history[s3_pdf_key] = {}
                
                self.process_history[s3_pdf_key]['hash'] = pdf_hash
                self.process_history[s3_pdf_key]['last_modified'] = last_modified
                self.process_history[s3_pdf_key]['processed'] = datetime.now().isoformat()
                self.process_history[s3_pdf_key]['pages'] = {}

                # Extract text and generate images page by page using content from memory
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_pages = len(doc) # Get total page count
                logging.info(f"PDF has {total_pages} pages to process with image generation")
                
                # Reset the document analyzer for this PDF
                self.doc_analyzer.reset_for_document(s3_pdf_key)

                # First pass: Analyze document structure by sampling pages
                # This helps identify heading levels and font styles used in the document
                logging.info("Analyzing document structure...")
                
                # Sample pages throughout the document (first few, middle, last few)
                sample_size = min(40, total_pages)
                if total_pages <= sample_size:
                    # If document is short, analyze all pages
                    sample_pages = list(range(total_pages))
                else:
                    # Take first few, spaced middle pages, and last few
                    first_pages = list(range(min(5, total_pages // 4)))
                    step = max(1, (total_pages - 10) // (sample_size - 10))
                    middle_pages = list(range(5, total_pages - 5, step))[:sample_size-10]
                    last_pages = list(range(max(0, total_pages - 5), total_pages))
                    sample_pages = sorted(set(first_pages + middle_pages + last_pages))
                
                for page_num in sample_pages:
                    page = doc[page_num]
                    # Extract text with formatting information
                    page_dict = page.get_text('dict')
                    # Analyze the page for font styles and heading levels
                    self.doc_analyzer.analyze_page(page_dict, page_num)
                
                # Determine heading levels based on collected font statistics
                self.doc_analyzer.determine_heading_levels()
                
                # Process document for standard approach page by page
                # For semantic approach, we'll collect all text first
                standard_docs = []
                
                # For semantic approach, collect all page texts with their page numbers
                semantic_page_texts = [] 
                
                # Second pass: Process actual content with structure context
                for page_num, page in enumerate(doc):
                    if page_num % 10 == 0 and page_num > 0:
                        logging.info(f"Processed {page_num}/{total_pages} pages ({(page_num/total_pages*100):.1f}%)")
                    
                    # Extract text with formatting information
                    page_dict = page.get_text('dict')
                    
                    # Process headings on this page to update document structure
                    self.doc_analyzer.process_page_headings(page_dict, page_num)
                    
                    # Get the current document context (heading path)
                    context = self.doc_analyzer.get_current_context()
                     
                    # Extract the plain text for processing
                    page_text = ""
                    for block in page_dict['blocks']:
                        if block.get("type") == 0:  # Text blocks only
                            for line in block.get("lines", []):
                                line_text = ""
                                for span in line.get("spans", []):
                                    line_text += span.get("text", "")
                                page_text += line_text + "\n"
                    
                    page_text = page_text.strip()
                    if not page_text: 
                        continue

                    page_label = page_num + 1 
                    page_source_id = f"{rel_path}_page_{page_label}"

                    if page_source_id in self.processed_sources:
                        continue
                    
                    # Generate image for the page
                    s3_image_url = None
                    page_preview_path = None
                    pix = None
                    try:
                        # Higher resolution for better readability
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        page_preview_path = f"{pdf_image_sub_dir_name}/{page_label}.png"
                        s3_image_url = f"s3://{AWS_S3_BUCKET_NAME}/{PDF_IMAGE_DIR}/{page_preview_path}"
                        
                        # Save image directly to bytes
                        img_bytes = pix.tobytes("png")
                        
                        # Upload to S3
                        s3_client.put_object(
                            Bucket=AWS_S3_BUCKET_NAME,
                            Key=f"{PDF_IMAGE_DIR}/{page_preview_path}",
                            Body=img_bytes,
                            ContentType="image/png"
                        )
                        
                        # Store image URL in history
                        if s3_pdf_key not in self.process_history:
                            self.process_history[s3_pdf_key] = {}
                        if 'pages' not in self.process_history[s3_pdf_key]:
                            self.process_history[s3_pdf_key]['pages'] = {}
                        
                        self.process_history[s3_pdf_key]['pages'][str(page_label)] = {
                            'image_url': s3_image_url,
                            'processed': datetime.now().isoformat()
                        }
                    except Exception as e:
                        logging.error(f"Error creating page image for page {page_label}: {e}")
                    finally:
                        if pix:
                            pix = None  # Release pixmap resource
                    
                    # Create document metadata with heading context
                    metadata = {
                        "source": s3_pdf_key,
                        "filename": pdf_filename,
                        "page": page_label,
                        "total_pages": total_pages,
                        "image_url": s3_image_url,
                        "source_dir": pdf_image_sub_dir_name,
                        "type": "pdf",
                        "folder": str(Path(rel_path).parent),
                        "processed_at": datetime.now().isoformat()
                    }
                    
                    # Add heading context information
                    if context.get("section"):
                        metadata["section"] = context["section"]
                    if context.get("subsection"):
                        metadata["subsection"] = context["subsection"]
                    
                    # Add full heading path
                    if context.get("heading_path"):
                        metadata["heading_path"] = " > ".join(context["heading_path"])
                    
                    # Add individual heading level information
                    for i in range(1, 7):  # H1 through H6
                        key = f"h{i}"
                        if key in context:
                            metadata[key] = context[key]
                    
                    # Standard approach - add each page as a document
                    standard_docs.append({
                        "text": page_text,
                        "metadata": metadata.copy()
                    })
                    
                    # For semantic approach - collect text with metadata
                    semantic_page_texts.append({
                        "text": page_text,
                        "page": page_label,
                        "metadata": metadata.copy()
                    })
                    
                    # Mark as processed
                    self.processed_sources.add(page_source_id)
                
                # Process standard approach directly
                if standard_docs:
                    logging.info(f"Adding {len(standard_docs)} documents to standard store from {pdf_filename}")
                    standard_docs_total += len(standard_docs)
                    self.standard_store.add_documents(standard_docs)
                    documents.extend(standard_docs)
                
                # Process semantic approach with cross-page chunking
                if semantic_page_texts:
                    logging.info(f"Processing semantic chunking across {len(semantic_page_texts)} pages from {pdf_filename}")
                    semantic_docs_total += len(semantic_page_texts)
                    
                    # Process the document as a whole for semantic chunking
                    self.semantic_store.add_document_with_cross_page_chunking(semantic_page_texts)
                
                # Close the document
                doc.close()
                
            except Exception as e:
                logging.error(f"Error processing PDF {s3_pdf_key}: {e}")
                continue
        
        # Save updated process history
        self._save_process_history()
        
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        hours, remainder = divmod(total_duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        logging.info(f"===== Processing Complete =====")
        logging.info(f"Total run time: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        logging.info(f"Processed {len(documents)} total documents")
        logging.info(f"Added {standard_docs_total} documents to standard store")
        logging.info(f"Added {semantic_docs_total} documents to semantic store")
        logging.info(f"Reprocessed {len(self.reprocessed_pdfs)} PDFs with new/changed content")
        logging.info(f"Skipped image generation for {len(self.unchanged_pdfs)} unchanged PDFs")
        
        return documents

    def process_all_sources(self):
        """Process all data sources and add them to vector store."""
        documents = []
        # Process PDFs from S3
        pdf_documents = self.process_pdfs_from_s3()
        if pdf_documents:
            documents.extend(pdf_documents)
        
        logging.info(f"Processed a total of {len(documents)} documents")
        return documents

def main():
    """Main function."""
    processor = DataProcessor()
    processor.process_all_sources()

if __name__ == "__main__":
    main() 