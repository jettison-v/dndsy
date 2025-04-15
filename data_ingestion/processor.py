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
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re # Import re for path cleaning
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
import io # For handling image data in memory
from dotenv import load_dotenv
import uuid  # For generating unique UUIDs

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
# S3 prefix for storing extracted link data
EXTRACTED_LINKS_S3_PREFIX = "extracted_links/"

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

logger = logging.getLogger(__name__)

class DataProcessor:
    """Handles the end-to-end processing of PDF documents from S3 into vector stores."""

    def __init__(self, process_pages: bool = True, process_semantic: bool = True, process_haystack: bool = False, cache_behavior: str = 'use', s3_pdf_prefix_override: Optional[str] = None):
        """Initialize the data processor with target stores, cache behavior, and optional S3 prefix override."""
        self.process_pages = process_pages
        self.process_semantic = process_semantic
        self.process_haystack = process_haystack
        self.cache_behavior = cache_behavior # 'use' or 'rebuild'
        
        # Determine the S3 prefix to use
        self.s3_pdf_prefix = AWS_S3_PDF_PREFIX # Default from .env
        if s3_pdf_prefix_override:
            self.s3_pdf_prefix = s3_pdf_prefix_override
            # Ensure override prefix ends with a slash if not empty
            if self.s3_pdf_prefix and not self.s3_pdf_prefix.endswith('/'):
                self.s3_pdf_prefix += '/'
            logger.info(f"Using S3 PDF prefix override: {self.s3_pdf_prefix}")
        else:
            logger.info(f"Using S3 PDF prefix from environment: {self.s3_pdf_prefix}")

        # Log the configuration
        logger.info(f"DataProcessor initialized with config:")
        logger.info(f"  - Process Pages: {self.process_pages}")
        logger.info(f"  - Process Semantic: {self.process_semantic}")
        logger.info(f"  - Process Haystack: {self.process_haystack}")
        logger.info(f"  - Cache Behavior: {self.cache_behavior}")

        # force_processing is effectively True if cache_behavior is 'rebuild'
        self.force_processing = (self.cache_behavior == 'rebuild')
            
        # Initialize stores conditionally
        self.pages_store = None
        if self.process_pages:
            self.pages_store = get_vector_store("pages")
            if not self.pages_store:
                raise RuntimeError("Failed to initialize pages vector store.")
            logger.info("Pages store initialized.")
        else:
            logger.info("Skipping pages store initialization.")
             
        self.semantic_store = None
        if self.process_semantic:
            self.semantic_store = get_vector_store("semantic")
            if not self.semantic_store:
                raise RuntimeError("Failed to initialize semantic vector store.")
            logger.info("Semantic store initialized.")
        else:
            logger.info("Skipping semantic store initialization.")
            
        self.haystack_store = None
        if self.process_haystack:
            # Use the environment variable to determine which Haystack implementation to use
            haystack_type = os.environ.get("HAYSTACK_STORE_TYPE", "haystack-qdrant")
            self.haystack_type = haystack_type # Store the type being used
            self.haystack_store = get_vector_store(haystack_type)
            if not self.haystack_store:
                raise RuntimeError(f"Failed to initialize {haystack_type} vector store.")
            logger.info(f"{haystack_type} store initialized.")
        else:
            self.haystack_type = None
            logger.info("Skipping haystack store initialization.")
            
        self.processed_sources = set()
        self.doc_analyzer = DocumentStructureAnalyzer()
        self.process_history = self._load_process_history()
        self.new_or_changed_pdfs = [] # Track PDFs needing full processing
        self.unchanged_pdfs_skipped_images = [] # Track PDFs where image gen was skipped
        logger.info(f"DataProcessor initialization complete.")
    
    def _compute_pdf_hash(self, pdf_bytes):
        """Compute a hash of PDF content to detect changes."""
        return hashlib.sha256(pdf_bytes).hexdigest()
    
    def _load_process_history(self):
        """Load the PDF processing history from S3 or fall back to local file."""
        try:
            # First try to get from S3
            if s3_client:
                try:
                    logger.info(f"Trying to load process history from S3: {PROCESS_HISTORY_S3_KEY}")
                    response = s3_client.get_object(
                        Bucket=AWS_S3_BUCKET_NAME, 
                        Key=PROCESS_HISTORY_S3_KEY
                    )
                    history_content = response['Body'].read().decode('utf-8')
                    history = json.loads(history_content)
                    logger.info(f"Successfully loaded process history from S3")
                    
                    # Also save it locally as a backup
                    with open(PROCESS_HISTORY_FILE, 'w') as f:
                        json.dump(history, f, indent=2)
                    
                    return history
                except ClientError as e:
                    if e.response['Error']['Code'] == 'NoSuchKey':
                        logger.info(f"Process history file not found in S3, will create new one")
                    else:
                        logger.warning(f"Error accessing S3 process history: {e}")
                except Exception as e:
                    logger.warning(f"Unexpected error loading process history from S3: {e}")
            
            # Fall back to local file
            if os.path.exists(PROCESS_HISTORY_FILE):
                logger.info("Loading process history from local file")
                with open(PROCESS_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            
            # If neither works, start fresh
            logger.info("Starting with empty process history")
            return {}
            
        except Exception as e:
            logger.warning(f"Could not load process history: {e}")
            return {}
    
    def _save_process_history(self):
        """Save the PDF processing history to S3 and local file."""
        try:
            # First save locally as a backup
            with open(PROCESS_HISTORY_FILE, 'w') as f:
                json.dump(self.process_history, f, indent=2)
            logger.info(f"Saved process history to local file {PROCESS_HISTORY_FILE}")
            
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
                    logger.info(f"Saved process history to S3: {PROCESS_HISTORY_S3_KEY}")
                except Exception as e:
                    logger.error(f"Failed to save process history to S3: {e}")
        except Exception as e:
            logger.error(f"Failed to save process history: {e}")
    
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
        logger.info(f"Deleting images with prefix: {image_prefix}")
        
        objects_to_delete = []
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=image_prefix)
            
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        objects_to_delete.append({'Key': obj['Key']})
            
            if objects_to_delete:
                logger.info(f"Found {len(objects_to_delete)} image objects to delete for {pdf_prefix}")
                # Delete objects in batches
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i:i + 1000]
                    delete_payload = {'Objects': batch, 'Quiet': True}
                    s3_client.delete_objects(
                        Bucket=AWS_S3_BUCKET_NAME,
                        Delete=delete_payload
                    )
                logger.info(f"Deleted {len(objects_to_delete)} images for {pdf_prefix}")
            else:
                logger.info(f"No existing images found for {pdf_prefix}")
                
        except Exception as e:
            logger.error(f"Error deleting images for {pdf_prefix}: {e}")

    def process_pdfs_from_s3(self, processed_pdf_keys_tracker: Optional[set] = None) -> int:
        """Process PDF files from S3, generate page images, chunk, embed, and add to selected stores."""
        if not s3_client:
            logger.error("S3 client not configured. Cannot process PDFs from S3.")
            return 0
        documents_processed_total = 0 # Use a more descriptive name for the grand total
        pdf_files_s3_keys = []
        try:
            logger.info(f"Listing PDFs from bucket '{AWS_S3_BUCKET_NAME}' with prefix '{self.s3_pdf_prefix}'")
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=self.s3_pdf_prefix)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        # Ensure we only process actual PDFs and not the prefix "folder" itself
                        if key.lower().endswith('.pdf') and key != self.s3_pdf_prefix:
                            pdf_files_s3_keys.append(key)
            if not pdf_files_s3_keys:
                 logger.warning(f"No PDF files found in S3 bucket '{AWS_S3_BUCKET_NAME}' with prefix '{self.s3_pdf_prefix}'.")
                 return 0
        except Exception as e:
            logger.error(f"Error listing PDFs from S3: {e}")
            return 0 # Return 0 instead of -1 for consistency

        start_time = datetime.now()
        total_pdfs = len(pdf_files_s3_keys)
        logger.info(f"Found {total_pdfs} PDFs in S3 to process.")
        
        # Reset totals for this run
        self.pages_points_total = 0
        self.semantic_points_total = 0
        self.haystack_points_total = 0
        self.new_or_changed_pdfs = [] 
        self.unchanged_pdfs_skipped_images = []
        
        for pdf_index, s3_pdf_key in enumerate(tqdm(pdf_files_s3_keys, desc="Processing PDFs from S3")):
            current_pdf_points = 0 # Track points added for the current PDF
            try:
                current_time = datetime.now()
                elapsed = (current_time - start_time).total_seconds()
                progress_pct = ((pdf_index + 1) / total_pdfs) * 100 if total_pdfs > 0 else 0
                logger.info(f"===== Processing PDF {pdf_index+1}/{total_pdfs} ({progress_pct:.1f}%) - {s3_pdf_key} =====")
                if pdf_index > 0:
                    # Time estimation logic remains the same
                    avg_time_per_pdf = elapsed / pdf_index
                    remaining_pdfs = total_pdfs - (pdf_index + 1) # Correct remaining count
                    est_remaining_time = avg_time_per_pdf * remaining_pdfs
                    est_completion_time = current_time + timedelta(seconds=est_remaining_time)
                    logger.info(f"Elapsed: {elapsed:.1f}s. Est. completion: {est_completion_time.strftime('%Y-%m-%d %H:%M:%S')} ({timedelta(seconds=est_remaining_time)})")
                
                # Extract relative path and clean filename using the correct prefix
                rel_path = s3_pdf_key[len(self.s3_pdf_prefix):] if s3_pdf_key.startswith(self.s3_pdf_prefix) else s3_pdf_key
                pdf_filename = Path(rel_path).name # Use pathlib for safer filename extraction
                pdf_image_sub_dir_name = self._clean_filename(Path(rel_path).stem) # Cleaned name based on stem
                
                # Download PDF
                try:
                    pdf_object = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                    pdf_bytes = pdf_object['Body'].read()
                    last_modified = pdf_object.get('LastModified', datetime.now()).isoformat()
                except ClientError as e:
                    logger.error(f"Failed to download PDF '{s3_pdf_key}' from S3: {e}")
                    continue # Skip this PDF
                except Exception as e:
                    logger.error(f"Unexpected error downloading PDF '{s3_pdf_key}': {e}")
                    continue # Skip this PDF

                pdf_hash = self._compute_pdf_hash(pdf_bytes)
                pdf_info = self.process_history.get(s3_pdf_key, {})
                old_hash = pdf_info.get('hash')
                processed_stores = pdf_info.get('processed_stores', []) # Stores that processed this version

                # Determine if the PDF is new or changed
                is_new = not old_hash
                has_changed = old_hash and old_hash != pdf_hash
                
                # Determine if image generation is needed based on cache behavior and changes
                # Regenerate images if: rebuilding cache OR PDF is new OR PDF has changed
                generate_images = self.cache_behavior == 'rebuild' or is_new or has_changed
                
                if generate_images:
                    logger.info(f"Image generation required for {s3_pdf_key} (Reason: {'rebuild' if self.cache_behavior == 'rebuild' else 'new' if is_new else 'changed'})")
                    self.new_or_changed_pdfs.append(s3_pdf_key)
                    # Delete old images before generating new ones
                    self._delete_specific_s3_images(pdf_image_sub_dir_name) 
                    # Reset processed stores if content changed
                    if has_changed:
                         processed_stores = [] 
                         logger.info(f"Resetting processed stores history for changed PDF: {s3_pdf_key}")
                    
                    # Update history for new/changed PDF
                    if s3_pdf_key not in self.process_history: self.process_history[s3_pdf_key] = {}
                    self.process_history[s3_pdf_key]['hash'] = pdf_hash
                    self.process_history[s3_pdf_key]['last_modified'] = last_modified
                    self.process_history[s3_pdf_key]['processed'] = datetime.now().isoformat() # Timestamp of this processing run
                    self.process_history[s3_pdf_key]['processed_stores'] = processed_stores # Use potentially reset list
                    self.process_history[s3_pdf_key]['pages'] = {} # Reset page image info
                else:
                    # PDF is unchanged and we are using cache
                    logger.info(f"PDF {s3_pdf_key} is unchanged. Image generation skipped.")
                    self.unchanged_pdfs_skipped_images.append(s3_pdf_key)

                # --- Process PDF Content --- 
                doc = None # Initialize doc to None
                try:
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    total_pages = len(doc)
                    logger.info(f"Opened PDF: {total_pages} pages. Analyzing structure...")
                    
                    # Document structure analysis (remains the same)
                    self.doc_analyzer.reset_for_document(s3_pdf_key)
                    # --- Initialize link data list for this PDF ---
                    pdf_links_data = []
                    sample_size = min(40, total_pages) # Sample size calculation seems reasonable
                    if total_pages <= sample_size:
                        sample_pages = list(range(total_pages))
                    else:
                        first_pages = list(range(min(5, total_pages // 4)))
                        step = max(1, (total_pages - 10) // (sample_size - 10))
                        middle_pages = list(range(5, total_pages - 5, step))[:sample_size-10]
                        last_pages = list(range(max(0, total_pages - 5), total_pages))
                        sample_pages = sorted(set(first_pages + middle_pages + last_pages))
                    for page_num in sample_pages:
                        if page_num < len(doc): # Add boundary check
                             page = doc[page_num]
                             page_dict = page.get_text('dict')
                             self.doc_analyzer.analyze_page(page_dict, page_num)
                    self.doc_analyzer.determine_heading_levels()
                    logger.info("Document structure analysis complete.")

                    pages_data_for_pages_store = [] if self.process_pages else None
                    page_data_for_semantic_and_haystack = [] if (self.process_semantic or self.process_haystack) else None

                    # --- Second pass: Extract text, generate images (if needed), collect data --- 
                    logger.info(f"Extracting text and metadata from {total_pages} pages... (Image Gen: {generate_images})")
                    for page_num, page in enumerate(tqdm(doc, desc=f"Pages [{pdf_filename}]", leave=False)):
                        # Simplified logging for page extraction progress
                        # if page_num % 50 == 0 and page_num > 0: logger.debug(f" Extracted {page_num}/{total_pages}")
                        
                        page_dict = page.get_text('dict')
                        self.doc_analyzer.process_page_headings(page_dict, page_num)
                        context = self.doc_analyzer.get_current_context()
                        
                        page_text = ""
                        # Text extraction logic remains the same
                        for block in page_dict.get('blocks', []):
                            if block.get("type") == 0: # Text block
                                for line in block.get("lines", []):
                                    line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                                    page_text += line_text + "\n" # Use literal newline
                        page_text = page_text.strip()
                        
                        if not page_text: continue # Skip empty pages

                        # --- Extract Links from Page ---
                        try:
                            links = page.get_links() # PyMuPDF function to get links
                            for link in links:
                                link_text = ""
                                link_rect = fitz.Rect(link['from']) # Bounding box of the link

                                # --- Attempt Text Extraction ---
                                # Attempt 1: Extract text using words within the link's bounding box
                                words = page.get_text("words", clip=link_rect)
                                words.sort(key=lambda w: (w[1], w[0])) # Sort by y then x coordinate
                                if words:
                                    link_text = " ".join(w[4] for w in words).strip()

                                # Attempt 2 (Fallback): Try get_textbox if get_text("words") failed
                                if not link_text:
                                    try:
                                        expanded_rect = link_rect + (-1, -1, 1, 1) # Expand by 1 point
                                        link_text = page.get_textbox(expanded_rect).strip()
                                    except Exception:
                                        pass

                                # Clean up common issues like multiple spaces
                                if link_text:
                                    link_text = re.sub(r'\s+', ' ', link_text).strip()

                                # --- Process Link ONLY if Text was Found ---
                                if link_text:
                                    link_info = {
                                        "link_text": link_text,
                                        "source_page": page_num + 1,
                                        "source_rect": [link_rect.x0, link_rect.y0, link_rect.x1, link_rect.y1]
                                    }

                                    if link['kind'] == fitz.LINK_GOTO: # Internal page link
                                        target_page_num = link['page']
                                        target_page_label = target_page_num + 1
                                        link_info['link_type'] = "internal"
                                        link_info['target_page'] = target_page_label

                                        # Extract Target Snippet (logic remains the same)
                                        target_snippet = None
                                        if 0 <= target_page_num < total_pages:
                                            target_page = doc[target_page_num]
                                            target_page_text = target_page.get_text("text")
                                            match_start = -1
                                            try:
                                                pattern = r"\b" + re.escape(link_info['link_text']) + r"\b"
                                                match = re.search(pattern, target_page_text, re.IGNORECASE | re.DOTALL)
                                                if match:
                                                    match_start = match.start()
                                                else:
                                                    match_start = target_page_text.lower().find(link_info['link_text'].lower())
                                            except re.error:
                                                match_start = target_page_text.lower().find(link_info['link_text'].lower())

                                            if match_start != -1:
                                                start_para = target_page_text.rfind('\n\n', 0, match_start)
                                                start_para = 0 if start_para == -1 else start_para + 2
                                                end_para = target_page_text.find('\n\n', match_start)
                                                end_para = len(target_page_text) if end_para == -1 else end_para
                                                target_snippet = target_page_text[start_para:end_para].strip().replace('\n', ' ')
                                                snippet_max_len = 750
                                                if len(target_snippet) > snippet_max_len:
                                                    trunc_point = target_snippet.rfind('.', 0, snippet_max_len)
                                                    if trunc_point > snippet_max_len * 0.7:
                                                        target_snippet = target_snippet[:trunc_point+1] + "..."
                                                    else:
                                                        target_snippet = target_snippet[:snippet_max_len] + "..."
                                            else:
                                                logger.warning(f"Link text '{link_info['link_text']}' not found on target page {target_page_label} for {s3_pdf_key}. Using fallback snippet.")
                                                first_para_end = target_page_text.find('\n\n')
                                                if first_para_end != -1 and first_para_end > 50:
                                                    target_snippet = target_page_text[:first_para_end].strip().replace('\n', ' ')
                                                else:
                                                    fallback_len = 350
                                                    target_snippet = target_page_text[:fallback_len].strip().replace('\n', ' ') + ("..." if len(target_page_text) > fallback_len else "")
                                            if not target_snippet:
                                                target_snippet = f"Content from page {target_page_label}"
                                        else:
                                            logger.warning(f"Internal link target page {target_page_label} out of bounds for {s3_pdf_key}")
                                            target_snippet = f"Error: Target page {target_page_label} invalid."

                                        link_info['target_snippet'] = target_snippet
                                        link_info['target_url'] = None
                                        pdf_links_data.append(link_info) # Add internal link to list

                                    elif link['kind'] == fitz.LINK_URI: # External URL link
                                        link_info['link_type'] = "external"
                                        link_info['target_url'] = link['uri']
                                        link_info['target_page'] = None
                                        link_info['target_snippet'] = None
                                        pdf_links_data.append(link_info) # Add external link to list

                                    # else: # Other kinds (Launch, GoToR) are implicitly skipped
                                    #    pass

                                else: # Text extraction failed for this link
                                    # Log the failure and skip adding this link to our data
                                    logger.warning(f"Could not extract text for link on {s3_pdf_key} page {page_num+1} (likely image link). Skipping. Link details: {link}")

                        except Exception as link_e:
                            logger.error(f"Error processing links on {s3_pdf_key} page {page_num+1}: {link_e}", exc_info=False)

                        page_label = page_num + 1 # 1-based index for user display
                        page_source_id = f"{rel_path}_page_{page_label}" # Unique ID for the page source

                        s3_image_url = None
                        if generate_images:
                            pix = None
                            try:
                                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Increase resolution slightly if needed
                                page_preview_s3_key = f"{PDF_IMAGE_DIR}/{pdf_image_sub_dir_name}/{page_label}.png"
                                s3_image_url = f"s3://{AWS_S3_BUCKET_NAME}/{page_preview_s3_key}"
                                
                                img_bytes = pix.tobytes("png")
                                s3_client.put_object(
                                    Bucket=AWS_S3_BUCKET_NAME,
                                    Key=page_preview_s3_key,
                                    Body=img_bytes,
                                    ContentType="image/png"
                                )
                                # Update history with the generated image URL
                                self.process_history[s3_pdf_key]['pages'][str(page_label)] = {
                                    'image_url': s3_image_url,
                                    'processed': datetime.now().isoformat()
                                }
                            except Exception as img_e:
                                logger.error(f"Error generating/uploading image for {s3_pdf_key} page {page_label}: {img_e}")
                                s3_image_url = None # Ensure URL is None if error occurs
                            finally:
                                if pix: pix = None # Release pixmap resources
                        else:
                             # Retrieve existing image URL from history
                             page_info = self.process_history.get(s3_pdf_key, {}).get('pages', {}).get(str(page_label), {})
                             s3_image_url = page_info.get('image_url')
                             if not s3_image_url:
                                 logger.warning(f"Missing image URL in history for {s3_pdf_key} page {page_label} when skipping generation.")

                        # --- Metadata assembly --- (remains largely the same)
                        metadata = {
                            "source": s3_pdf_key, # S3 key acts as the canonical source identifier
                            "filename": pdf_filename,
                            "page": page_label,
                            "total_pages": total_pages,
                            "image_url": s3_image_url, 
                            "source_dir": pdf_image_sub_dir_name, # Base name for image folder
                            "type": "pdf",
                            "folder": str(Path(rel_path).parent), # Original folder path relative to prefix
                            "processed_at": datetime.now().isoformat(),
                            # Add heading info directly
                            **{f"h{i}": context.get(f"h{i}") for i in range(1, 7) if context.get(f"h{i}")},
                            "heading_path": " > ".join(context["heading_path"]) if context.get("heading_path") else None
                        }
                        # Remove None values from metadata for cleaner storage
                        metadata = {k: v for k, v in metadata.items() if v is not None}

                        # Conditionally collect data for different stores
                        if self.process_pages:
                            pages_data_for_pages_store.append({"text": page_text, "metadata": metadata.copy()})
                        if self.process_semantic or self.process_haystack:
                            # We need page_text, page_label, and metadata for chunking
                            page_data_for_semantic_and_haystack.append({"text": page_text, "page": page_label, "metadata": metadata.copy()})
                        
                        self.processed_sources.add(page_source_id) # Track processed page sources (seems unused)

                    # --- Save Extracted Link Data to S3 (after page loop for the PDF) ---
                    if pdf_links_data and s3_client:
                        try:
                            # Construct S3 key using the defined prefix and relative path
                            links_s3_key_suffix = f"{rel_path}.links.json"
                            # Ensure prefix ends with / if not empty
                            s3_prefix = EXTRACTED_LINKS_S3_PREFIX
                            if s3_prefix and not s3_prefix.endswith('/'):
                                s3_prefix += '/'
                            links_json_s3_key = f"{s3_prefix}{links_s3_key_suffix}"

                            links_json_content = json.dumps(pdf_links_data, indent=2)

                            # For review: Optionally print or save locally first during testing
                            # print(f"--- Links for {s3_pdf_key} ({len(pdf_links_data)} found) ---")
                            # print(f"Saving to S3 key: {links_json_s3_key}")
                            # try:
                            #     local_links_path = project_root / "temp_links" / f"{pdf_filename}.links.json"
                            #     os.makedirs(local_links_path.parent, exist_ok=True)
                            #     with open(local_links_path, "w") as f_local:
                            #        f_local.write(links_json_content)
                            #     logger.info(f"Also saved links locally to: {local_links_path}")
                            # except Exception as local_save_e:
                            #     logger.warning(f"Could not save links locally: {local_save_e}")

                            s3_client.put_object(
                                Bucket=AWS_S3_BUCKET_NAME,
                                Key=links_json_s3_key,
                                Body=links_json_content,
                                ContentType='application/json'
                            )
                            logger.info(f"Saved {len(pdf_links_data)} extracted links to S3: {links_json_s3_key}")

                            # Optional: Update process history with link count
                            if s3_pdf_key in self.process_history:
                                self.process_history[s3_pdf_key]['extracted_links_count'] = len(pdf_links_data)

                        except Exception as save_e:
                            logger.error(f"Failed to save extracted links to S3 for {s3_pdf_key}: {save_e}", exc_info=True)


                    # --- Embed and Add to Stores (Conditional Processing for this PDF) --- 
                    
                    pdf_processed_successfully_for_all_targets = True # Track success for this PDF

                    # 1. Pages Store
                    # Skip if cache='use', store already processed this version
                    skip_pages = (self.cache_behavior == 'use' and 
                                  "pages" in processed_stores and 
                                  not has_changed and not is_new)
                                  
                    if self.process_pages and pages_data_for_pages_store and not skip_pages:
                        logger.info(f"Processing PDF for Pages store ({len(pages_data_for_pages_store)} pages)...")
                        try:
                            pages_texts = [item["text"] for item in pages_data_for_pages_store]
                            pages_embeddings = embed_documents(pages_texts, store_type="pages")
                            pages_points = []
                            if len(pages_embeddings) == len(pages_data_for_pages_store):
                                for i, data in enumerate(pages_data_for_pages_store):
                                    pages_points.append(PointStruct(
                                        id=str(uuid.uuid4()), # Use UUIDs for pages store
                                        vector=pages_embeddings[i],
                                        payload={"text": data["text"], "metadata": data["metadata"]}
                                    ))
                            else:
                                logger.error(f"Mismatch embedding/data count for pages store: {s3_pdf_key} ({len(pages_embeddings)} vs {len(pages_data_for_pages_store)})")
                            
                            if pages_points:
                                logger.info(f"Adding {len(pages_points)} points to Pages store for {pdf_filename}")
                                self.pages_store.add_points(pages_points)
                                points_added_pages = len(pages_points)
                                self.pages_points_total += points_added_pages
                                current_pdf_points += points_added_pages
                                # Mark this store as having processed this PDF version
                                if "pages" not in self.process_history[s3_pdf_key]['processed_stores']:
                                    self.process_history[s3_pdf_key]['processed_stores'].append("pages")
                                logger.info(f"Successfully added {points_added_pages} points to Pages store.")
                        except Exception as e:
                            logger.error(f"Error processing Pages store for {s3_pdf_key}: {e}", exc_info=True)
                            pdf_processed_successfully_for_all_targets = False
                    elif self.process_pages and skip_pages:
                         logger.info(f"Skipping Pages store processing for {s3_pdf_key} (cached)")


                    # 2. Semantic Store
                    # Skip if cache='use', store already processed this version
                    skip_semantic = (self.cache_behavior == 'use' and 
                                     "semantic" in processed_stores and 
                                     not has_changed and not is_new)

                    if self.process_semantic and page_data_for_semantic_and_haystack and not skip_semantic:
                        logger.info(f"Processing PDF for Semantic store ({len(page_data_for_semantic_and_haystack)} pages)...")
                        try:
                            semantic_chunks = self.semantic_store.chunk_document_with_cross_page_context(page_data_for_semantic_and_haystack)
                            if semantic_chunks:
                                logger.info(f"Generated {len(semantic_chunks)} semantic chunks. Embedding...")
                                chunk_texts = [chunk["text"] for chunk in semantic_chunks]
                                semantic_embeddings = embed_documents(chunk_texts, store_type="semantic")
                                semantic_points = []
                                doc_id_counter = self.semantic_store.next_id # Get next ID from store
                                if len(semantic_embeddings) == len(semantic_chunks):
                                    for i, chunk_data in enumerate(semantic_chunks):
                                        semantic_points.append(PointStruct(
                                            id=doc_id_counter + i, # Use sequential IDs for semantic store
                                            vector=semantic_embeddings[i],
                                            payload={"text": chunk_data["text"], "metadata": chunk_data["metadata"]}
                                        ))
                                else: 
                                    logger.error(f"Mismatch chunk/embedding count for semantic store: {s3_pdf_key} ({len(semantic_embeddings)} vs {len(semantic_chunks)})")
                                
                                if semantic_points:
                                    logger.info(f"Adding {len(semantic_points)} points to Semantic store for {pdf_filename}")
                                    num_added = self.semantic_store.add_points(semantic_points) # Add points returns count added
                                    self.semantic_points_total += num_added
                                    current_pdf_points += num_added
                                    # Mark this store as having processed this PDF version
                                    if "semantic" not in self.process_history[s3_pdf_key]['processed_stores']:
                                        self.process_history[s3_pdf_key]['processed_stores'].append("semantic")
                                    logger.info(f"Successfully added {num_added} points to Semantic store.")
                            else: 
                                logger.warning(f"No semantic chunks generated for {s3_pdf_key}")
                        except Exception as e: 
                            logger.error(f"Error processing Semantic store for {s3_pdf_key}: {e}", exc_info=True)
                            pdf_processed_successfully_for_all_targets = False
                    elif self.process_semantic and skip_semantic:
                         logger.info(f"Skipping Semantic store processing for {s3_pdf_key} (cached)")

                    
                    # 3. Haystack Store
                    # Skip if cache='use', store already processed this version
                    # Note: haystack_type might be None if process_haystack is False
                    haystack_store_key = self.haystack_type if self.haystack_type else "haystack" # Key for history
                    skip_haystack = (self.cache_behavior == 'use' and 
                                     haystack_store_key in processed_stores and 
                                     not has_changed and not is_new)

                    if self.process_haystack and page_data_for_semantic_and_haystack and not skip_haystack:
                        logger.info(f"Processing PDF for {self.haystack_type} store ({len(page_data_for_semantic_and_haystack)} pages)...")
                        try:
                            # Haystack store likely has its own chunking logic, pass the page data
                            # Assuming haystack_store.add_points or similar handles chunking internally
                            # Or we need a specific chunking call similar to semantic
                            # Let's assume add_points takes the page data and handles it
                            # THIS MIGHT NEED ADJUSTMENT based on haystack store implementation
                            
                            # If Haystack needs pre-chunked data like Semantic:
                            haystack_chunks = self.haystack_store.chunk_document_with_cross_page_context(page_data_for_semantic_and_haystack)
                            
                            if haystack_chunks:
                                logger.info(f"Generated {len(haystack_chunks)} chunks for {self.haystack_type}. Adding to store...")
                                num_added = self.haystack_store.add_points(haystack_chunks) # add_points handles embedding
                                if num_added > 0:
                                    self.haystack_points_total += num_added
                                    current_pdf_points += num_added
                                    # Mark this store as having processed this PDF version
                                    if haystack_store_key not in self.process_history[s3_pdf_key]['processed_stores']:
                                        self.process_history[s3_pdf_key]['processed_stores'].append(haystack_store_key)
                                    logger.info(f"Successfully added {num_added} points to {self.haystack_type} store.")
                                else:
                                    # This could be normal if all chunks already exist, log carefully
                                    logger.warning(f"add_points reported 0 new points added to {self.haystack_type} for {s3_pdf_key}. Might be duplicates or an issue.")
                            else:
                                logger.warning(f"No chunks generated for {self.haystack_type} store for {s3_pdf_key}")
                        except AttributeError as ae:
                             logger.error(f"Haystack store '{self.haystack_type}' might be missing expected methods (e.g., chunk_document_with_cross_page_context or add_points): {ae}", exc_info=True)
                             pdf_processed_successfully_for_all_targets = False
                        except Exception as e:
                            logger.error(f"Error processing {self.haystack_type} store for {s3_pdf_key}: {e}", exc_info=True)
                            pdf_processed_successfully_for_all_targets = False
                    elif self.process_haystack and skip_haystack:
                         logger.info(f"Skipping {self.haystack_type} store processing for {s3_pdf_key} (cached)")

                finally:
                    # Ensure PDF document is closed
                    if doc:
                        doc.close()
                        logger.debug(f"Closed PDF document: {s3_pdf_key}")
                
                # Add the key to the tracker set if provided and if any points were added or attempted
                if processed_pdf_keys_tracker is not None and current_pdf_points > 0 : # Only track if work was done
                    processed_pdf_keys_tracker.add(s3_pdf_key)
                
                # Update total points processed
                documents_processed_total += current_pdf_points
                logger.info(f"Finished processing {s3_pdf_key}. Added {current_pdf_points} points in this run.")

            except Exception as e:
                logger.error(f"--- Critical Error processing PDF {s3_pdf_key}: {e} ---", exc_info=True)
                # Ensure doc is closed even if error occurs mid-processing
                if 'doc' in locals() and doc is not None:
                    try: doc.close() 
                    except: pass 
                continue # Move to the next PDF
        
        # Save history after processing all PDFs
        self._save_process_history()
        
        # --- Final Summary Logging ---
        end_time = datetime.now()
        total_duration = (end_time - start_time).total_seconds()
        hours, remainder = divmod(total_duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        logger.info(f"===== Processing Complete =====")
        logger.info(f"Total time: {int(hours)}h {int(minutes)}m {int(seconds)}s")
        logger.info(f"Processed {len(pdf_files_s3_keys)} PDFs from S3.")
        logger.info(f"Total points/documents added across all stores in this run: {documents_processed_total}")
        if self.process_pages: logger.info(f"  - Pages Store: {self.pages_points_total} points")
        if self.process_semantic: logger.info(f"  - Semantic Store: {self.semantic_points_total} points")
        if self.process_haystack: logger.info(f"  - {self.haystack_type} Store: {self.haystack_points_total} points")
        logger.info(f"Processed {len(self.new_or_changed_pdfs)} new or changed PDFs (images generated/regenerated).")
        logger.info(f"Skipped image generation for {len(self.unchanged_pdfs_skipped_images)} unchanged PDFs.")
        
        # Return the grand total number of documents/points processed in this run
        return documents_processed_total

    def process_all_sources(self, processed_pdf_keys_tracker: Optional[set] = None):
        """Process all data sources based on initialization flags.
        
        Args:
            processed_pdf_keys_tracker (Optional[set]): A set to track the keys of PDFs
                that were processed during this run. Used to get a unique count across
                multiple processing steps in manage_vector_stores.py.
        """
        processed_count = self.process_pdfs_from_s3(processed_pdf_keys_tracker)
        logger.info(f"DataProcessor finished run. Total points/documents processed: {processed_count}")
        # Return the total count for the summary in the calling script
        return processed_count

# Removed main() and if __name__ == "__main__" block as this is now a module 