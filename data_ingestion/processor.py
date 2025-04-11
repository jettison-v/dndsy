import os
import json
from pathlib import Path
import fitz  # PyMuPDF
import sys
import hashlib  # For PDF content hashing

# Add parent directory to path to make imports work properly
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Imports need to be adjusted for the new package structure
# Assume vector_store and utils are accessible from the top level or adjust sys.path accordingly
from vector_store import get_vector_store
# Updated import for DocumentStructureAnalyzer
from .structure_analyzer import DocumentStructureAnalyzer
# Import embedding function
from embeddings.model_provider import embed_documents
# Import Qdrant PointStruct
from qdrant_client.http.models import PointStruct

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

# Ensure logs directory exists relative to project root
# Assumes this script is run from the project root or sys.path is set correctly
project_root = Path(__file__).parent.parent
logs_dir = project_root / 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(logs_dir / 'data_processing.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load environment variables from project root, overriding existing ones
env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# Define base directory for images relative to static folder
PDF_IMAGE_DIR = "pdf_page_images"
STATIC_DIR = "static" # Define static directory name
# File to store processing history (both locally and on S3)
# Use absolute path for local history file
PROCESS_HISTORY_FILE = project_root / "pdf_process_history.json"
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
    """Handles the end-to-end processing of PDF documents from S3 into vector stores."""

    def __init__(self, process_standard: bool = True, process_semantic: bool = True):
        """Initialize the data processor, optionally skipping stores."""
        self.process_standard_flag = process_standard
        self.process_semantic_flag = process_semantic
        
        # Initialize stores conditionally
        self.standard_store = None
        if self.process_standard_flag:
            self.standard_store = get_vector_store("standard")
            if not self.standard_store:
                raise RuntimeError("Failed to initialize standard vector store.")
            logger.info("Standard store initialized for processing.")
        else:
             logger.info("Skipping standard store initialization.")
             
        self.semantic_store = None
        if self.process_semantic_flag:
            self.semantic_store = get_vector_store("semantic")
            if not self.semantic_store:
                raise RuntimeError("Failed to initialize semantic vector store.")
            logger.info("Semantic store initialized for processing.")
        else:
            logger.info("Skipping semantic store initialization.")
            
        self.processed_sources = set()
        self.doc_analyzer = DocumentStructureAnalyzer()
        self.process_history = self._load_process_history()
        self.reprocessed_pdfs = [] 
        self.unchanged_pdfs = []   
        logging.info(f"DataProcessor initialized. Standard: {self.process_standard_flag}, Semantic: {self.process_semantic_flag}")
    
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

    def process_pdfs_from_s3(self) -> int:
        """Process PDF files from S3, generate page images, chunk, embed, and add to selected stores."""
        if not s3_client:
            logging.error("S3 client not configured. Cannot process PDFs from S3.")
            return 0
        documents_processed = 0
        s3_base_key_prefix = PDF_IMAGE_DIR
        pdf_files_s3_keys = []
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=AWS_S3_PDF_PREFIX)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if key.lower().endswith('.pdf') and key != AWS_S3_PDF_PREFIX:
                            pdf_files_s3_keys.append(key)
        except Exception as e:
            logging.error(f"Error listing PDFs: {e}")
            return 0

        start_time = datetime.now()
        total_pdfs = len(pdf_files_s3_keys)
        logging.info(f"Processing {total_pdfs} PDFs...")
        standard_points_total = 0
        semantic_points_total = 0
        
        for pdf_index, s3_pdf_key in enumerate(tqdm(pdf_files_s3_keys, desc="Processing PDFs from S3")):
            try:
                current_time = datetime.now()
                elapsed = (current_time - start_time).total_seconds()
                progress_pct = (pdf_index / total_pdfs) * 100 if total_pdfs > 0 else 0
                logging.info(f"===== Processing PDF {pdf_index+1}/{total_pdfs} ({progress_pct:.1f}%) - {s3_pdf_key} =====")
                if pdf_index > 0:
                    avg_time_per_pdf = elapsed / pdf_index
                    remaining_pdfs = total_pdfs - pdf_index
                    est_remaining_time = avg_time_per_pdf * remaining_pdfs
                    est_completion_time = current_time + timedelta(seconds=est_remaining_time)
                    logging.info(f"Elapsed time: {elapsed:.1f} seconds. Estimated completion time: {est_completion_time.strftime('%Y-%m-%d %H:%M:%S')}")
                rel_path = s3_pdf_key[len(AWS_S3_PDF_PREFIX):] if s3_pdf_key.startswith(AWS_S3_PDF_PREFIX) else s3_pdf_key
                pdf_filename = rel_path.split('/')[-1]
                pdf_image_sub_dir_name = self._clean_filename(rel_path.replace('.pdf', ''))
                try:
                    pdf_object = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                    pdf_bytes = pdf_object['Body'].read()
                    last_modified = pdf_object.get('LastModified', datetime.now()).isoformat()
                except ClientError as e:
                    logging.error(f"Failed to download PDF '{s3_pdf_key}' from S3: {e}")
                    continue
                except Exception as e:
                    logging.error(f"Unexpected error downloading PDF '{s3_pdf_key}' from S3: {e}")
                    continue
                pdf_hash = self._compute_pdf_hash(pdf_bytes)
                pdf_info = self.process_history.get(s3_pdf_key, {})
                old_hash = pdf_info.get('hash')
                process_this_pdf = True
                generate_images = True
                if old_hash == pdf_hash and pdf_info.get('processed'):
                    logging.info(f"PDF {s3_pdf_key} unchanged since last processing, skipping image generation")
                    self.unchanged_pdfs.append(s3_pdf_key)
                    generate_images = False
                elif old_hash and old_hash != pdf_hash:
                    logging.info(f"PDF {s3_pdf_key} has changed. Deleting old images and regenerating.")
                    self._delete_specific_s3_images(pdf_image_sub_dir_name)
                elif not old_hash:
                    logging.info(f"New PDF {s3_pdf_key}. Deleting any potentially stale images and generating new ones.")
                    self._delete_specific_s3_images(pdf_image_sub_dir_name)
                if generate_images:
                     self.reprocessed_pdfs.append(s3_pdf_key)
                     if s3_pdf_key not in self.process_history: self.process_history[s3_pdf_key] = {}
                     self.process_history[s3_pdf_key]['hash'] = pdf_hash
                     self.process_history[s3_pdf_key]['last_modified'] = last_modified
                     self.process_history[s3_pdf_key]['processed'] = datetime.now().isoformat()
                     self.process_history[s3_pdf_key]['pages'] = {}

                # --- Process PDF Content --- 
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_pages = len(doc)
                logging.info(f"Processing {total_pages} pages for text embeddings (Image Gen: {generate_images})")
                self.doc_analyzer.reset_for_document(s3_pdf_key)
                logging.info("Analyzing document structure...")
                sample_size = min(40, total_pages)
                if total_pages <= sample_size:
                    sample_pages = list(range(total_pages))
                else:
                    first_pages = list(range(min(5, total_pages // 4)))
                    step = max(1, (total_pages - 10) // (sample_size - 10))
                    middle_pages = list(range(5, total_pages - 5, step))[:sample_size-10]
                    last_pages = list(range(max(0, total_pages - 5), total_pages))
                    sample_pages = sorted(set(first_pages + middle_pages + last_pages))
                for page_num in sample_pages:
                    page = doc[page_num]
                    page_dict = page.get_text('dict')
                    self.doc_analyzer.analyze_page(page_dict, page_num)
                self.doc_analyzer.determine_heading_levels()
                logging.info("Document structure analysis complete.")

                standard_page_data = [] if self.process_standard_flag else None
                semantic_page_data = [] if self.process_semantic_flag else None

                # --- Second pass: Extract text, generate images (if needed), collect data --- 
                for page_num, page in enumerate(doc):
                    if page_num % 10 == 0 and page_num > 0:
                        logging.info(f"Extracted text from {page_num}/{total_pages} pages")
                    page_dict = page.get_text('dict')
                    self.doc_analyzer.process_page_headings(page_dict, page_num)
                    context = self.doc_analyzer.get_current_context()
                    page_text = ""
                    for block in page_dict['blocks']:
                        if block.get("type") == 0:
                            for line in block.get("lines", []):
                                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                                page_text += line_text + "\n"
                    page_text = page_text.strip()
                    if not page_text: continue
                    page_label = page_num + 1
                    page_source_id = f"{rel_path}_page_{page_label}"
                    s3_image_url = None
                    if generate_images:
                        pix = None
                        try:
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                            page_preview_path = f"{pdf_image_sub_dir_name}/{page_label}.png"
                            s3_image_url = f"s3://{AWS_S3_BUCKET_NAME}/{PDF_IMAGE_DIR}/{page_preview_path}"
                            img_bytes = pix.tobytes("png")
                            s3_client.put_object(
                                Bucket=AWS_S3_BUCKET_NAME,
                                Key=f"{PDF_IMAGE_DIR}/{page_preview_path}",
                                Body=img_bytes,
                                ContentType="image/png"
                            )
                            self.process_history[s3_pdf_key]['pages'][str(page_label)] = {
                                'image_url': s3_image_url,
                                'processed': datetime.now().isoformat()
                            }
                        except Exception as e:
                            logging.error(f"Error creating page image for page {page_label}: {e}")
                        finally:
                            if pix: pix = None
                    else:
                         page_info = pdf_info.get('pages', {}).get(str(page_label), {})
                         s3_image_url = page_info.get('image_url')
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
                    if context.get("section"): metadata["section"] = context["section"]
                    if context.get("subsection"): metadata["subsection"] = context["subsection"]
                    if context.get("heading_path"): metadata["heading_path"] = " > ".join(context["heading_path"])
                    for i in range(1, 7): 
                        key = f"h{i}"
                        if key in context: metadata[key] = context[key]
                    
                    # Conditionally collect data based on flags
                    if self.process_standard_flag:
                        standard_page_data.append({"text": page_text, "metadata": metadata.copy()})
                    if self.process_semantic_flag:
                        semantic_page_data.append({"text": page_text, "page": page_label, "metadata": metadata.copy()})
                    
                    self.processed_sources.add(page_source_id)

                # --- Embed and Add to Stores (Conditional Processing) --- 
                
                # 1. Standard Store 
                if self.process_standard_flag and standard_page_data:
                    logging.info(f"Embedding {len(standard_page_data)} pages for standard store...")
                    standard_texts = [item["text"] for item in standard_page_data]
                    standard_embeddings = embed_documents(standard_texts, store_type="standard")
                    standard_points = []
                    doc_id_counter = self.standard_store.next_id 
                    for i, data in enumerate(standard_page_data):
                        standard_points.append(PointStruct(
                            id=doc_id_counter + i,
                            vector=standard_embeddings[i],
                            payload={"text": data["text"], "metadata": data["metadata"]}
                        ))
                    if standard_points:
                        logging.info(f"Adding {len(standard_points)} points to standard store for {pdf_filename}")
                        self.standard_store.add_points(standard_points)
                        standard_points_total += len(standard_points)
                        documents_processed += len(standard_points)

                # 2. Semantic Store
                if self.process_semantic_flag and semantic_page_data:
                    logging.info(f"Chunking {len(semantic_page_data)} pages for semantic store...")
                    semantic_chunks = self.semantic_store.chunk_document_with_cross_page_context(semantic_page_data)
                    if semantic_chunks:
                        logging.info(f"Embedding {len(semantic_chunks)} semantic chunks...")
                        chunk_texts = [chunk["text"] for chunk in semantic_chunks]
                        try:
                            semantic_embeddings = embed_documents(chunk_texts, store_type="semantic")
                            semantic_points = []
                            doc_id_counter = self.semantic_store.next_id
                            if len(semantic_embeddings) == len(semantic_chunks):
                                for i, chunk_data in enumerate(semantic_chunks):
                                    semantic_points.append(PointStruct(
                                        id=doc_id_counter + i,
                                        vector=semantic_embeddings[i],
                                        payload={"text": chunk_data["text"], "metadata": chunk_data["metadata"]}
                                    ))
                            else: logging.error(f"Mismatch chunk/embedding count for {s3_pdf_key}")
                            if semantic_points:
                                logging.info(f"Adding {len(semantic_points)} points to semantic store for {pdf_filename}")
                                num_added = self.semantic_store.add_points(semantic_points)
                                semantic_points_total += num_added
                                documents_processed += num_added
                        except Exception as e: logging.error(f"Failed to embed/add semantic chunks for {s3_pdf_key}: {e}", exc_info=True)
                    else: logging.warning(f"No semantic chunks generated for {s3_pdf_key}")
                
                # Close the document
                doc.close()
                
            except Exception as e:
                logging.error(f"Error processing PDF {s3_pdf_key}: {e}", exc_info=True)
                if 'doc' in locals() and doc is not None:
                    try: doc.close()
                    except: pass 
                continue
        
        self._save_process_history()
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        hours, remainder = divmod(total_duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        logging.info(f"===== Processing Complete =====")
        logging.info(f"Total run time: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        logging.info(f"Processed {documents_processed} total points/documents across all stores")
        logging.info(f"Added {standard_points_total} points to standard store")
        logging.info(f"Added {semantic_points_total} points to semantic store")
        logging.info(f"Reprocessed {len(self.reprocessed_pdfs)} PDFs with new/changed content or images")
        logging.info(f"Skipped image generation for {len(self.unchanged_pdfs)} unchanged PDFs")
        return documents_processed

    def process_all_sources(self):
        """Process all data sources based on initialization flags."""
        processed_count = self.process_pdfs_from_s3()
        logging.info(f"Processed a total of {processed_count} points/documents")
        return processed_count

# Removed main() and if __name__ == "__main__" block as this is now a module 