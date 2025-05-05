import os
import json
from pathlib import Path
import fitz  # PyMuPDF
import sys
import hashlib  # For PDF content hashing
from typing import List, Dict, Any, Optional, Tuple, Set, Callable
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
import time

# Add parent directory to path to make imports work properly
# sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Imports need to be adjusted for the new package structure
# Assume vector_store and utils are accessible from the top level or adjust sys.path accordingly
from vector_store import get_vector_store # Removed BaseVectorStore
from vector_store.search_helper import SearchHelper # Import SearchHelper directly
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

# --- Add imports needed for metadata functions --- 
from config import PREDEFINED_CATEGORIES # Import category definitions
from llm_providers import get_llm_client # Import the LLM client factory
# -------------------------------------------------

# Ensure logs directory exists relative to project root
# Assumes this script is run from the project root or sys.path is set correctly
project_root = Path(__file__).parent.parent
logs_dir = project_root / 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Load environment variables from project root, overriding existing ones
env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path, override=True)

# Import environment-specific S3 bucket name
sys.path.append(str(project_root))
try:
    from config import S3_BUCKET_NAME
    print(f"Using environment-specific S3 bucket: {S3_BUCKET_NAME}")
except ImportError:
    S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
    print(f"Using default S3 bucket from environment: {S3_BUCKET_NAME}")

# Define base directory for images relative to static folder
PDF_IMAGE_DIR = "pdf_page_images"
STATIC_DIR = "static" # Define static directory name
# File to store processing history (both locally and on S3)
# Use absolute path for local history file
PROCESS_HISTORY_FILE = project_root / "pdf_process_history.json"
PROCESS_HISTORY_S3_KEY = "processing/pdf_process_history.json"  # S3 path
# S3 prefix for storing extracted link data
EXTRACTED_LINKS_S3_PREFIX = "extracted_links/"

# Color to category mapping for link extraction
COLOR_CATEGORY_MAP = {
    # Monster colors
    "#a70000": "monster",
    "#bc0f0f": "monster",
    
    # Spell colors
    "#704cd9": "spell",
    
    # Skill colors
    "#036634": "skill",
    "#11884c": "skill",
    
    # Item colors
    "#623a1e": "item", 
    "#774521": "item",
    
    # Magic Item colors
    "#0f5cbc": "magic-item",  # Light blue color for magic items/potions
    
    # Rule colors
    "#6a5009": "rule",
    "#9b740b": "rule",
    "#efb311": "rule",  # Yellow color for rules
    
    # Sense colors
    "#a41b96": "sense",
    
    # Condition colors
    "#364d00": "condition",
    "#5a8100": "condition",
    
    # Lore colors
    "#a83e3e": "lore",
    
    # Default - fallback
    "#0053a3": "reference",
    "#006abe": "reference",
    "#141414": "navigation",
    "#9a9a9a": "footer",
    "#e8f6ff": "footer"
}

# --- AWS S3 Configuration ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1") # Default region if not set
# Use environment-specific bucket
AWS_S3_BUCKET_NAME = S3_BUCKET_NAME

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

# Type alias for preprocessed data cache
PreprocessedData = Dict[str, Any] # Contains keys like 'text', 'page', 'metadata'
PreprocessedCache = Dict[str, List[PreprocessedData]] # Keyed by s3_pdf_key

# --- Configuration for Metadata --- 
METADATA_S3_PREFIX = "pdf-metadata/" # Store metadata under this prefix

# --- LLM Client Initialization for Metadata Tasks ---
# Initialize once when the module loads
metadata_llm_client = None
try:
    # This reads the same env vars as the main app's client
    metadata_llm_client = get_llm_client()
    logger.info("Initialized LLM client for metadata tasks within processor.")
except ImportError as e:
    logger.error(f"Could not import/initialize get_llm_client for metadata: {e}")
except Exception as e:
    logger.error(f"Failed to initialize LLM client for metadata: {e}")
# -------------------------------------------------

# ==============================================================================
# == METADATA GENERATION FUNCTIONS (Moved from metadata_processor.py) ==
# ==============================================================================

# --- S3 Interaction for Metadata --- 
def upload_metadata_to_s3(metadata_json: dict, document_id: str):
    # (Function body copied from metadata_processor.py)
    # Uses AWS_S3_BUCKET_NAME, AWS_REGION_META from this file's scope now
    """Uploads the metadata JSON to the configured S3 bucket.
    Args:
        metadata_json: The metadata dictionary to upload.
        document_id: The unique ID for the document (used as filename).
    Raises:
        Exception: Propagates S3 client errors.
    """
    global s3_client # Use the main s3_client initialized in this module
    if not s3_client:
        logger.error("S3 client not initialized. Cannot upload metadata.")
        raise ConnectionError("S3 client not available for metadata upload")

    object_key = f"{METADATA_S3_PREFIX}{document_id}.json"
    try:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET_NAME, # Use bucket from this module's config
            Key=object_key,
            Body=json.dumps(metadata_json, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Successfully uploaded metadata for {document_id} to s3://{AWS_S3_BUCKET_NAME}/{object_key}")
    except Exception as e:
        logger.error(f"Error uploading metadata for {document_id} to S3: {e}")
        raise

def get_metadata_from_s3(document_id: str) -> dict | None:
    # (Function body copied from metadata_processor.py)
    """Retrieves metadata JSON from the configured S3 bucket.
    Args:
        document_id: The unique ID for the document metadata file.
    Returns:
        The metadata dictionary if found, otherwise None.
    Raises:
        Exception: Propagates S3 client errors (except NoSuchKey).
    """
    global s3_client
    if not s3_client:
        logger.error("S3 client not initialized. Cannot get metadata.")
        raise ConnectionError("S3 client not available for metadata retrieval")

    object_key = f"{METADATA_S3_PREFIX}{document_id}.json"
    try:
        response = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=object_key)
        metadata = json.loads(response['Body'].read().decode('utf-8'))
        logger.info(f"Successfully retrieved metadata for {document_id} from s3://{AWS_S3_BUCKET_NAME}/{object_key}")
        return metadata
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
             logger.warning(f"Metadata not found for {document_id} at s3://{AWS_S3_BUCKET_NAME}/{object_key}")
             return None
        else:
             logger.error(f"S3 ClientError retrieving metadata for {document_id}: {e}")
             raise # Reraise other S3 errors
    except Exception as e:
        logger.error(f"Error retrieving metadata for {document_id} from S3: {e}")
        raise

# --- Metadata Extraction Functions --- 
def _generate_metadata_document_id(pdf_content: bytes | None = None, s3_path: str | None = None) -> str:
    # (Function body copied from metadata_processor.py)
    """Generates a unique ID for the document metadata.
    Preferentially uses S3 path hash if available, otherwise content hash.
    """
    if s3_path:
        return hashlib.sha256(s3_path.encode('utf-8')).hexdigest()
    elif pdf_content:
        logger.warning("Generating metadata document ID from PDF content hash as S3 path was not provided.")
        return hashlib.sha256(pdf_content).hexdigest()
    else:
        raise ValueError("Either pdf_content or s3_path must be provided to generate metadata document ID")

def _determine_metadata_constrained_category(document_text: str, available_categories: list[dict]) -> str:
    # (Function body copied from metadata_processor.py)
    # Uses metadata_llm_client initialized in this module
    """Analyzes text and selects the best category name from the provided list (with descriptions) using an LLM."""
    global metadata_llm_client
    if not metadata_llm_client:
        # ... (fallback logic as before)
        logging.warning("LLM client not available for constrained categorization. Returning placeholder.")
        if not available_categories: return "Unknown"
        cat_names = [cat['name'] for cat in available_categories]
        if "monster" in document_text.lower() and "Monsters" in cat_names: return "Monsters"
        return available_categories[0]['name']
    
    if not available_categories:
        logging.warning("No available categories provided for constrained categorization. Returning 'Unknown'.")
        return "Unknown"

    # ... (rest of function body: logging, prompt creation, LLM call, validation, fallback)
    logging.info(f"Determining constrained category from {len(available_categories)} options for doc ({len(document_text)} chars)...")
    category_list_str = "\n".join([f"{i+1}. {cat['name']}: {cat['description']}" for i, cat in enumerate(available_categories)])
    valid_category_names = [cat['name'] for cat in available_categories]
    prompt = (
        f"Analyze the following document text and determine which single category from the list below best describes its primary content. "
        f"Consider the category descriptions provided. "
        f"Respond with ONLY the category NAME exactly as it appears in the list (e.g., 'Core Rules', 'Monsters').\n\n"
        f"Available Categories:\n{category_list_str}\n\n"
        f"Document Text:\n---\n{document_text}\n---"        
    )
    system_prompt = "You are an expert assistant skilled at classifying documents based on a predefined list of categories with descriptions. You only respond with the single best category name from the provided list."
    try:
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt, 
            system_message=system_prompt, 
            temperature=0.0, 
            max_tokens=50, 
            stream=False
        )
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            chosen_category_name = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            chosen_category_name = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            chosen_category_name = str(response_obj)
            
        chosen_category_name = chosen_category_name.strip().strip('"\'')
        if chosen_category_name in valid_category_names:
            logging.info(f"Determined constrained category: '{chosen_category_name}'")
            return chosen_category_name
        else:
            logging.warning(f"LLM returned a category name ('{chosen_category_name}') not in the valid list: {valid_category_names}. Attempting fallback match or using default.")
            for name in valid_category_names:
                if chosen_category_name.lower() == name.lower():
                    logging.info(f"Found case-insensitive fallback match: '{name}'")
                    return name
            default_name = available_categories[0]['name']
            logging.warning(f"Using first available category name '{default_name}' as fallback.")
            return default_name
    except Exception as e:
        logging.error(f"Error determining constrained category with LLM: {e}", exc_info=True)
        default_name = available_categories[0]['name'] if available_categories else "Unknown"
        logging.warning(f"Using fallback category '{default_name}' due to LLM error.")
        return default_name

def _determine_metadata_automatic_category(document_text: str) -> str:
    # (Function body copied from metadata_processor.py)
    # Uses metadata_llm_client initialized in this module
    """Analyzes text to determine a descriptive category freely using an LLM."""
    global metadata_llm_client
    if not metadata_llm_client:
        # ... (fallback logic as before)
        logging.warning("LLM client not available for automatic categorization. Returning placeholder.")
        if "stat block" in document_text.lower(): return "Monsters (Placeholder)"
        if "spell level" in document_text.lower(): return "Spells (Placeholder)"
        return "General (Placeholder)"
    
    # ... (rest of function body: logging, prompt creation, LLM call, validation, fallback)
    logging.info(f"Determining automatic category freely for document ({len(document_text)} chars)...")
    prompt = (
        f"Analyze the following document text and provide a concise, descriptive category name "
        f"(e.g., 'Spell Descriptions', 'Monster Stat Blocks', 'Character Class Options', 'Magic Items List'). "
        f"Focus on the primary content type. Respond with ONLY the category name.\n\n"
        f"---\n{document_text}\n---"
    )
    system_prompt = "You are an expert assistant skilled at analyzing documents and assigning concise category labels."
    try:
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt, 
            system_message=system_prompt, 
            temperature=0.1, 
            max_tokens=50, 
            stream=False
        )
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            category = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            category = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            category = str(response_obj)
            
        category = category.strip().strip('"\'') 
        if not category:
            raise ValueError("LLM returned an empty category string.")
        logging.info(f"Determined automatic category: '{category}'")
        return category
    except Exception as e:
        logging.error(f"Error determining automatic category with LLM: {e}", exc_info=True)
        if "stat block" in document_text.lower(): return "Monsters (Error Fallback)"
        if "spell level" in document_text.lower(): return "Spells (Error Fallback)"
        return "General (Error Fallback)"

def _extract_metadata_source_book_title(document_text: str) -> str | None:
    # (Function body copied from metadata_processor.py)
    """Attempts to extract the source book title from text."""
    # ... (function body as before: logging, regex, fallback)
    logging.info("Extracting source book title...")
    search_text = '\n'.join(document_text.split('\n', 50)[:50])
    if len(search_text) > 4000:
        search_text = search_text[:4000]
    title_match = re.search(r"^\s*title\s*:\s*(.+)$", search_text, re.IGNORECASE | re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        if '/' not in title and '\\' not in title and len(title) < 150:
             logging.info(f"Found title via 'Title:' pattern: '{title}'")
             return title
        else:
             logging.debug(f"Rejected potential title from 'Title:' pattern (path-like or too long): '{title}'")
    lines = document_text.split('\n')
    checked_lines = 0
    max_lines_to_check = 5
    for line in lines:
        stripped_line = line.strip()
        if stripped_line:
            checked_lines += 1
            if 3 < len(stripped_line) < 100 and not stripped_line.endswith(('.', '?', '!')):
                if not (stripped_line.isupper() and len(stripped_line) < 15):
                    logging.info(f"Using first non-empty line as potential title: '{stripped_line}'")
                    return stripped_line
            if checked_lines >= max_lines_to_check:
                break
    logging.info("Could not confidently extract source book title.")
    return None

def _generate_metadata_summary(document_text: str, max_input_chars: int = 20000) -> str:
    # (Function body copied from metadata_processor.py)
    # Uses metadata_llm_client initialized in this module
    """Generates a summary of the document using an LLM, truncating input if necessary."""
    global metadata_llm_client
    if not metadata_llm_client:
        # ... (fallback logic as before)
        logging.warning("LLM client not available for summarization. Returning placeholder.")
        preview = (document_text[:200] + '...') if len(document_text) > 200 else document_text
        return f"[Placeholder] Summary of document starting with: '{preview}'"
    
    # ... (rest of function body: truncation, logging, prompt, LLM call, validation, fallback)
    if len(document_text) > max_input_chars:
        logging.warning(f"Input text ({len(document_text)} chars) exceeds limit ({max_input_chars}). Truncating for summary generation.")
        truncated_text = document_text[:max_input_chars]
    else:
        truncated_text = document_text
    logging.info(f"Generating summary from text ({len(truncated_text)} chars)...")
    prompt = f"Please provide a concise summary (around 2-4 sentences) of the following document text:\n\n---\n{truncated_text}\n---"
    system_prompt = "You are an expert assistant tasked with summarizing technical documents concisely."
    try:
        if not hasattr(metadata_llm_client, 'generate_response') or not callable(metadata_llm_client.generate_response):
             raise NotImplementedError("LLM client does not have a 'generate_response' method.")
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt, 
            system_message=system_prompt, 
            temperature=0.2, 
            max_tokens=250, 
            stream=False
        )
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            summary = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            summary = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            summary = str(response_obj)
            
        summary = summary.strip()
        if not summary:
            raise ValueError("LLM returned an empty summary string.")
        logging.info(f"Generated summary: '{summary[:100]}...'" )
        return summary
    except Exception as e:
        logging.error(f"Error generating summary with LLM: {e}", exc_info=True)
        preview = (truncated_text[:200] + '...') if len(truncated_text) > 200 else truncated_text
        return f"[Error] Failed to generate summary. Document starts: '{preview}'"

def _extract_metadata_keywords(document_text: str) -> list[str]:
    # (Function body copied from metadata_processor.py)
    # Uses metadata_llm_client initialized in this module
    """Extracts relevant keywords from the document text using an LLM."""
    global metadata_llm_client
    if not metadata_llm_client:
        # ... (fallback logic as before)
        logging.warning("LLM client not available for keyword extraction. Returning placeholder.")
        from collections import Counter
        words = [w.lower() for w in document_text.split() if len(w) > 4 and w.isalnum()]
        common_words = [word for word, count in Counter(words).most_common(10)]
        return [f"{kw} (Placeholder)" for kw in common_words]
    
    # ... (rest of function body: logging, prompt, LLM call, parsing, validation, fallback)
    logging.info(f"Extracting keywords for document ({len(document_text)} chars)...")
    prompt = (
        f"Analyze the following document text and extract the most relevant keywords or key phrases that represent the main topics. "
        f"Return a comma-separated list of these keywords/phrases.\n\n"
        f"Document Text:\n---\n{document_text}\n---"
    )
    system_prompt = "You are an expert assistant skilled at identifying the core topics of a document and extracting relevant keywords."
    try:
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt,
            system_message=system_prompt,
            temperature=0.2,
            max_tokens=150,
            stream=False
        )
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            keywords_text = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            keywords_text = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            keywords_text = str(response_obj)

        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
        if not keywords:
             raise ValueError("LLM returned no valid keywords.")
        logging.info(f"Extracted keywords: {keywords}")
        return keywords
    except Exception as e:
        logging.error(f"Error extracting keywords with LLM: {e}", exc_info=True)
        from collections import Counter
        words = [w.lower() for w in document_text.split() if len(w) > 4 and w.isalnum()]
        common_words = [word for word, count in Counter(words).most_common(10)]
        return [f"{kw} (Error Fallback)" for kw in common_words]

# --- Main Metadata Generation Orchestrator --- 
def _generate_and_upload_metadata(
    pdf_bytes: bytes | None, 
    extracted_text: str,
    original_filename: str,
    s3_pdf_key: str, 
    available_categories: list[dict],
    status_callback: Optional[Callable[[str, dict], None]] = None # Add callback param
):
    """Orchestrates the generation and upload of metadata for a single document.
       Includes logging and error handling.
    Args:
        pdf_bytes: Raw bytes of the PDF content (optional).
        extracted_text: Full extracted text content.
        original_filename: The original name of the PDF file.
        s3_pdf_key: The S3 key (path within bucket) of the source PDF.
        available_categories: List of predefined category dictionaries from config.
        status_callback: Optional function to send status updates.
    """
    global AWS_S3_BUCKET_NAME # Access bucket name defined in module scope
    start_time = time.time()
    # Report start via callback if provided
    if status_callback:
        status_callback("milestone", {"message": f"Generating metadata: {original_filename}..."})
    else: # Log locally if no callback
        logger.info(f"Starting metadata generation process for: {original_filename}")

    # Construct full S3 path for metadata field
    s3_full_path = f"s3://{AWS_S3_BUCKET_NAME}/{s3_pdf_key}"

    try:
        document_id = _generate_metadata_document_id(pdf_content=pdf_bytes, s3_path=s3_full_path)

        # --- Generate Summary First --- 
        summary_text = _generate_metadata_summary(extracted_text)

        # --- Use Summary for Other LLM Tasks --- 
        constrained_category = _determine_metadata_constrained_category(summary_text, available_categories)
        automatic_category = _determine_metadata_automatic_category(summary_text)
        keywords = _extract_metadata_keywords(summary_text)

        # --- Extract Title (operates on original text) ---
        source_book_title = _extract_metadata_source_book_title(extracted_text)

        # --- Assemble Metadata --- 
        metadata = {
            "document_id": document_id,
            "original_filename": original_filename,
            "s3_pdf_path": s3_full_path, # Store the full S3 path
            "constrained_category": constrained_category,
            "automatic_category": automatic_category,
            "source_book_title": source_book_title,
            "summary": summary_text,
            "keywords": keywords,
            "processing_timestamp": datetime.now(datetime.timezone.utc).isoformat()
        }
        logger.debug(f"Generated metadata content for {original_filename}: {metadata}")

        # --- Upload Metadata --- 
        try:
            upload_metadata_to_s3(metadata, document_id)
            duration = time.time() - start_time
            success_msg = f"Finished metadata: {original_filename} ({duration:.2f}s)"
            logger.info(success_msg)
            if status_callback:
                status_callback("milestone", {"message": success_msg}) # Report success
        except Exception as upload_e:
             err_msg = f"Metadata upload failed: {original_filename} ({upload_e})"
             logger.error(err_msg)
             if status_callback:
                 status_callback("error", {"message": err_msg}) # Report error

    except Exception as e:
        # Catch errors during generation itself
        duration = time.time() - start_time
        err_msg = f"Metadata generation failed: {original_filename} after {duration:.2f}s ({e})"
        logger.error(err_msg, exc_info=True)
        if status_callback:
            status_callback("error", {"message": err_msg}) # Report error
        # Do not re-raise, allow main PDF processing to continue

# ==============================================================================
# == END OF METADATA GENERATION FUNCTIONS ==
# ==============================================================================

class DataProcessor:
    """Handles the end-to-end processing of PDF documents from S3 into vector stores."""

    def __init__(self, cache_behavior: str = 'use', s3_pdf_prefix_override: Optional[str] = None, 
                 status_callback: Optional[Callable[[str, dict], None]] = None): # Add callback param
        """Initialize the data processor."""
        self.cache_behavior = cache_behavior 
        self.s3_pdf_prefix = AWS_S3_PDF_PREFIX 
        if s3_pdf_prefix_override:
            # ... (prefix override logic) ...
            self.s3_pdf_prefix = s3_pdf_prefix_override
            if self.s3_pdf_prefix and not self.s3_pdf_prefix.endswith('/'):
                self.s3_pdf_prefix += '/'
            logger.info(f"Using S3 PDF prefix override: {self.s3_pdf_prefix}")
        else:
            logger.info(f"Using S3 PDF prefix from environment: {self.s3_pdf_prefix}")

        logger.info(f"DataProcessor initialized with config:")
        logger.info(f"  - Cache Behavior: {self.cache_behavior}")

        self.doc_analyzer = DocumentStructureAnalyzer()
        self.process_history = self._load_process_history()
        self.preprocessed_data_cache: PreprocessedCache = {}
        self.total_points_added_across_stores = 0
        self.status_callback = status_callback # Store the callback

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
        cleaned = re.sub(r'[/\\\\]+', '_', filename) # Replace slashes with underscore
        cleaned = re.sub(r'[^a-zA-Z0-9_\\-\\.]+', '_', cleaned) # Replace others
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

    def _delete_s3_object(self, s3_key: str):
        """Deletes a single object from S3 if it exists."""
        if not s3_client or not AWS_S3_BUCKET_NAME:
            logger.warning(f"S3 client not configured, cannot delete object: {s3_key}")
            return
        
        try:
            # Check if the object exists before attempting deletion
            s3_client.head_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_key)
            # Object exists, proceed with deletion
            s3_client.delete_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_key)
            logger.info(f"Successfully deleted S3 object: {s3_key}")
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                # Object does not exist, which is fine
                logger.info(f"S3 object not found (already deleted?): {s3_key}")
            else:
                # Other S3 related error
                logger.error(f"Error checking/deleting S3 object {s3_key}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error deleting S3 object {s3_key}: {e}")

    def _preprocess_single_pdf(self, s3_pdf_key: str) -> Optional[List[PreprocessedData]]:
        pdf_start_time = time.time() 
        """
        Phase 1 logic: Download, hash check, image gen (if needed),
        link extraction, text/metadata extraction for ONE PDF.
        Updates self.process_history and returns preprocessed page data.
        """
        try:
            # Extract relative path and clean filename
            rel_path = s3_pdf_key[len(self.s3_pdf_prefix):] if s3_pdf_key.startswith(self.s3_pdf_prefix) else s3_pdf_key
            pdf_filename = Path(rel_path).name
            pdf_image_sub_dir_name = self._clean_filename(Path(rel_path).stem)

            # Download PDF
            try:
                pdf_object = s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                pdf_bytes = pdf_object['Body'].read()
                last_modified = pdf_object.get('LastModified', datetime.now()).isoformat()
            except ClientError as e:
                logger.error(f"Failed to download PDF '{s3_pdf_key}' from S3: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error downloading PDF '{s3_pdf_key}': {e}")
                return None

            pdf_hash = self._compute_pdf_hash(pdf_bytes)
            pdf_info = self.process_history.get(s3_pdf_key, {})
            old_hash = pdf_info.get('hash')

            # Determine if the PDF is new or changed
            is_new = not old_hash
            has_changed = old_hash and old_hash != pdf_hash

            # --- Cache Behavior Actions (Rebuild) ---
            if self.cache_behavior == 'rebuild':
                logger.info(f"Rebuild triggered for {s3_pdf_key}. Clearing derived data...")
                # Delete images
                self._delete_specific_s3_images(pdf_image_sub_dir_name)
                # Delete existing links JSON file
                links_s3_key_suffix = f"{rel_path}.links.json"
                s3_prefix_links = EXTRACTED_LINKS_S3_PREFIX
                if s3_prefix_links and not s3_prefix_links.endswith('/'): s3_prefix_links += '/'
                links_json_s3_key = f"{s3_prefix_links}{links_s3_key_suffix}"

                self._delete_s3_object(links_json_s3_key)
                
                # Reset processed stores list if content changed (important for Phase 2)
                if has_changed or is_new: # Also reset for new PDFs during rebuild
                    pdf_info['processed_stores'] = []
                    logger.info(f"Resetting processed stores history for new/changed PDF during rebuild: {s3_pdf_key}")

            # Determine if image generation is needed specifically (can be true even if not rebuilding if PDF changed)
            generate_images = self.cache_behavior == 'rebuild' or is_new or has_changed
            if generate_images and self.cache_behavior != 'rebuild': # Only delete images here if *not* rebuilding (rebuild already deleted)
                logger.info(f"Image generation required for changed/new PDF {s3_pdf_key} (Cache=use)")
                self._delete_specific_s3_images(pdf_image_sub_dir_name)
                if has_changed:
                     pdf_info['processed_stores'] = [] # Reset history if changed
                     logger.info(f"Resetting processed stores history for changed PDF: {s3_pdf_key}")
            elif not generate_images:
                logger.info(f"PDF {s3_pdf_key} is unchanged. Image generation skipped.")

            # --- Update History (Hash, Timestamps) ---
            if s3_pdf_key not in self.process_history: self.process_history[s3_pdf_key] = {}
            self.process_history[s3_pdf_key]['hash'] = pdf_hash
            self.process_history[s3_pdf_key]['last_modified'] = last_modified
            self.process_history[s3_pdf_key]['last_preprocessed'] = datetime.now().isoformat() # New field
            # Ensure 'processed_stores' exists, keep existing if pdf hasn't changed
            if 'processed_stores' not in self.process_history[s3_pdf_key]:
                self.process_history[s3_pdf_key]['processed_stores'] = []
            if 'pages' not in self.process_history[s3_pdf_key]:
                 self.process_history[s3_pdf_key]['pages'] = {} # Ensure page image info dict exists


            # --- Process PDF Content (Structure, Text, Links, Images) ---
            doc = None
            preprocessed_page_data: List[PreprocessedData] = []
            pdf_links_data: List[Dict[str, Any]] = []
            # Store for links to future pages - we'll process these after going through all pages
            pending_future_links = []

            try:
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_pages = len(doc)
                logger.info(f"Opened PDF: {total_pages} pages. Analyzing structure...")

                # Document structure analysis
                self.doc_analyzer.reset_for_document(s3_pdf_key)
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
                    if page_num < len(doc):
                         page = doc[page_num]
                         page_dict = page.get_text('dict')
                         self.doc_analyzer.analyze_page(page_dict, page_num)
                self.doc_analyzer.determine_heading_levels()
                logger.info("Document structure analysis complete.")

                # First pass - process all pages and extract text
                page_texts = {}
                logger.info(f"First pass: Extracting text and metadata from {total_pages} pages...")
                for page_num, page in enumerate(tqdm(doc, desc=f"Pages - First Pass [{pdf_filename}]", leave=False)):
                    page_dict = page.get_text('dict')
                    self.doc_analyzer.process_page_headings(page_dict, page_num)
                    context = self.doc_analyzer.get_current_context()

                    page_text = ""
                    for block in page_dict.get('blocks', []):
                        if block.get("type") == 0: # Text block
                            for line in block.get("lines", []):
                                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                                page_text += line_text + "\\n"
                    page_text = page_text.strip()

                    if not page_text: continue
                    
                    page_label = page_num + 1
                    page_texts[page_label] = page_text
                
                # Second pass - process all pages for links and images, with complete text available
                logger.info(f"Second pass: Processing links and images for {total_pages} pages... (Image Gen: {generate_images})")
                for page_num, page in enumerate(tqdm(doc, desc=f"Pages - Second Pass [{pdf_filename}]", leave=False)):
                    page_dict = page.get_text('dict')
                    self.doc_analyzer.process_page_headings(page_dict, page_num)
                    context = self.doc_analyzer.get_current_context()
                    
                    page_label = page_num + 1
                    page_text = page_texts.get(page_label)
                    
                    if not page_text: continue

                    # --- Extract Links from Page ---
                    try:
                        links = page.get_links() # PyMuPDF function to get links
                        for link in links:
                            link_text = ""
                            link_rect = fitz.Rect(link['from']) # Bounding box of the link

                            words = page.get_text("words", clip=link_rect)
                            words.sort(key=lambda w: (w[1], w[0])) # Sort by y then x
                            if words:
                                link_text = " ".join(w[4] for w in words).strip()

                            if not link_text:
                                try:
                                    expanded_rect = link_rect + (-1, -1, 1, 1) # Expand by 1 point
                                    link_text = page.get_textbox(expanded_rect).strip()
                                except Exception:
                                    pass

                            if link_text:
                                link_text = re.sub(r'\\s+', ' ', link_text).strip()

                                link_info = {
                                    "link_text": link_text,
                                    "source_page": page_num + 1,
                                    "source_rect": [link_rect.x0, link_rect.y0, link_rect.x1, link_rect.y1]
                                }
                                
                                # Extract link color information
                                try:
                                    # Get the text with detailed information including color
                                    page_dict = page.get_text('dict')
                                    
                                    # Track if we found a color
                                    found_color = False
                                    
                                    # Look for text blocks that overlap with our link rectangle
                                    for block in page_dict.get("blocks", []):
                                        if block.get("type") == 0:  # Text block
                                            for line in block.get("lines", []):
                                                line_rect = fitz.Rect(line.get("bbox"))
                                                
                                                # Check if this line overlaps with our link
                                                if line_rect.intersects(link_rect):
                                                    # Check the spans in this line
                                                    for span in line.get("spans", []):
                                                        span_rect = fitz.Rect(span.get("bbox"))
                                                        span_text = span.get("text", "")
                                                        
                                                        # If the span's rectangle intersects with our link and contains part of the link text
                                                        if span_rect.intersects(link_rect) and span_text and (span_text in link_text or link_text in span_text):
                                                            # Get the color of this span
                                                            span_color = span.get("color")
                                                            
                                                            if span_color:
                                                                # Convert the color to our hex format
                                                                # In PyMuPDF, text colors are typically RGB integers
                                                                if isinstance(span_color, int):
                                                                    # Convert from integer RGB value (0xRRGGBB)
                                                                    r = (span_color >> 16) & 0xFF
                                                                    g = (span_color >> 8) & 0xFF
                                                                    b = span_color & 0xFF
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                else:
                                                                    # For other color formats
                                                                    if isinstance(span_color, (list, tuple)):
                                                                        if len(span_color) == 3:  # RGB color
                                                                            r, g, b = [max(0, min(255, int(c * 255))) for c in span_color]
                                                                            color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                        elif len(span_color) == 1:  # Gray
                                                                            gray = max(0, min(255, int(span_color[0] * 255)))
                                                                            color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                    else:
                                                                        continue
                                                                
                                                                link_info["color"] = color_hex
                                                                found_color = True
                                                                
                                                                # Once we find a color, we can stop looking
                                                                break
                                                    
                                                    if found_color:
                                                        break
                                        
                                        if found_color:
                                            break
                                    
                                    # If we didn't find a color through spans, as a fallback, try to extract 
                                    # a color from the annotation (original method)
                                    if not found_color and page.annots():
                                        # Direct approach - try to match URI in link with annotation URI
                                        for annot in page.annots():
                                            # First check if it's a link annotation
                                            if annot.type[1] == "Link":
                                                # More reliable matching based on rectangle overlap
                                                annot_rect = annot.rect
                                                
                                                # Check for significant overlap (rectangles are very close)
                                                if (abs(annot_rect.x0 - link_rect.x0) < 10 and 
                                                    abs(annot_rect.y0 - link_rect.y0) < 10 and
                                                    abs(annot_rect.x1 - link_rect.x1) < 10 and
                                                    abs(annot_rect.y1 - link_rect.y1) < 10):
                                                    
                                                    # For external links, also confirm URL matches
                                                    if link.get('kind') == fitz.LINK_URI:
                                                        uri = link.get('uri')
                                                        annot_uri = annot.uri if hasattr(annot, 'uri') else None
                                                        # If both URIs exist and don't match, skip
                                                        if uri and annot_uri and uri != annot_uri:
                                                            continue
                                                            
                                                    # Extract color information
                                                    if hasattr(annot, "colors") and annot.colors:
                                                        colors = annot.colors
                                                        color = None
                                                        if "stroke" in colors and colors["stroke"]:
                                                            color = colors["stroke"]
                                                        elif "fill" in colors and colors["fill"]:
                                                            color = colors["fill"]
                                                            
                                                        # If we found a color
                                                        if color:
                                                            # Process different color formats
                                                            if isinstance(color, (list, tuple)):
                                                                if len(color) == 3:  # RGB color
                                                                    r, g, b = [max(0, min(255, int(c * 255))) for c in color]
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                    link_info["color"] = color_hex
                                                                elif len(color) == 1:  # Gray color
                                                                    gray = max(0, min(255, int(color[0] * 255)))
                                                                    color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                    link_info["color"] = color_hex
                                                                elif len(color) == 4:  # CMYK color - approximate conversion to RGB
                                                                    c, m, y, k = color
                                                                    # Simple CMYK to RGB conversion
                                                                    r = max(0, min(255, int((1 - c) * (1 - k) * 255)))
                                                                    g = max(0, min(255, int((1 - m) * (1 - k) * 255)))
                                                                    b = max(0, min(255, int((1 - y) * (1 - k) * 255)))
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                    link_info["color"] = color_hex
                                                            elif isinstance(color, (int, float)):  # Single value for gray
                                                                gray = max(0, min(255, int(color * 255)))
                                                                color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                link_info["color"] = color_hex
                                    
                                    # Add category information based on color
                                    if "color" in link_info:
                                        color = link_info["color"].lower()
                                        if color in COLOR_CATEGORY_MAP:
                                            link_info["link_category"] = COLOR_CATEGORY_MAP[color]
                                
                                except Exception as color_e:
                                    logger.warning(f"Error extracting link color: {color_e}")

                                if link['kind'] == fitz.LINK_GOTO:
                                    target_page_num = link['page']
                                    target_page_label = target_page_num + 1
                                    link_info['link_type'] = "internal"
                                    link_info['target_page'] = target_page_label

                                    target_snippet = None
                                    if 0 <= target_page_num < total_pages:
                                        # Check if we have the target text in our page_texts dictionary
                                        target_page_text = page_texts.get(target_page_label)
                                        if target_page_text:
                                            match_start = -1
                                            try:
                                                pattern = r"\\b" + re.escape(link_info['link_text']) + r"\\b"
                                                match = re.search(pattern, target_page_text, re.IGNORECASE | re.DOTALL)
                                                if match: match_start = match.start()
                                                else: match_start = target_page_text.lower().find(link_info['link_text'].lower())
                                            except re.error:
                                                match_start = target_page_text.lower().find(link_info['link_text'].lower())

                                            if match_start != -1:
                                                start_para = target_page_text.rfind('\\n\\n', 0, match_start)
                                                start_para = 0 if start_para == -1 else start_para + 2
                                                end_para = target_page_text.find('\\n\\n', match_start)
                                                end_para = len(target_page_text) if end_para == -1 else end_para
                                                target_snippet = target_page_text[start_para:end_para].strip().replace('\\n', ' ')
                                                snippet_max_len = 750
                                                if len(target_snippet) > snippet_max_len:
                                                    trunc_point = target_snippet.rfind('.', 0, snippet_max_len)
                                                    if trunc_point > snippet_max_len * 0.7: target_snippet = target_snippet[:trunc_point+1] + "..."
                                                    else: target_snippet = target_snippet[:snippet_max_len] + "..."
                                            else:
                                                # Use a fallback snippet, but don't log a warning since we're handling future links better now
                                                first_para_end = target_page_text.find('\\n\\n')
                                                if first_para_end != -1 and first_para_end > 50: target_snippet = target_page_text[:first_para_end].strip().replace('\\n', ' ')
                                                else:
                                                    fallback_len = 350
                                                    target_snippet = target_page_text[:fallback_len].strip().replace('\\n', ' ') + ("..." if len(target_page_text) > fallback_len else "")
                                        else:
                                            # This is a link to a future page, add to pending list to process later
                                            pending_future_links.append({
                                                "link_info": link_info,
                                                "target_page_num": target_page_num
                                            })
                                            continue
                                    else:
                                        logger.warning(f"Internal link target page {target_page_label} out of bounds for {s3_pdf_key}")
                                        target_snippet = f"Error: Target page {target_page_label} invalid."

                                    link_info['target_snippet'] = target_snippet
                                    link_info['target_url'] = None
                                    pdf_links_data.append(link_info)

                                elif link['kind'] == fitz.LINK_URI:
                                    link_info['link_type'] = "external"
                                    link_info['target_url'] = link['uri']
                                    link_info['target_page'] = None
                                    link_info['target_snippet'] = None
                                    pdf_links_data.append(link_info)
                            else:
                                logger.warning(f"Could not extract text for link on {s3_pdf_key} page {page_num+1} (likely image link). Skipping. Link details: {link}")

                    except Exception as link_e:
                        logger.error(f"Error processing links on {s3_pdf_key} page {page_num+1}: {link_e}", exc_info=False)

                    s3_image_url = None
                    if generate_images:
                        pix = None
                        try:
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                            page_preview_s3_key = f"{PDF_IMAGE_DIR}/{pdf_image_sub_dir_name}/{page_label}.png"
                            s3_image_url = f"s3://{AWS_S3_BUCKET_NAME}/{page_preview_s3_key}"

                            img_bytes = pix.tobytes("png")
                            s3_client.put_object(
                                Bucket=AWS_S3_BUCKET_NAME, Key=page_preview_s3_key, Body=img_bytes, ContentType="image/png"
                            )
                            # Update history with the generated image URL
                            if 'pages' not in self.process_history[s3_pdf_key]: self.process_history[s3_pdf_key]['pages'] = {}
                            self.process_history[s3_pdf_key]['pages'][str(page_label)] = {
                                'image_url': s3_image_url, 'processed': datetime.now().isoformat()
                            }
                        except Exception as img_e:
                            logger.error(f"Error generating/uploading image for {s3_pdf_key} page {page_label}: {img_e}")
                            s3_image_url = None
                        finally:
                            if pix: pix = None
                    else:
                         # Retrieve existing image URL from history
                         page_info = self.process_history.get(s3_pdf_key, {}).get('pages', {}).get(str(page_label), {})
                         s3_image_url = page_info.get('image_url')
                         if not s3_image_url:
                             logger.warning(f"Missing image URL in history for {s3_pdf_key} page {page_label} when skipping generation.")

                    # --- Assemble Metadata ---
                    metadata = {
                        "source": s3_pdf_key,
                        "filename": pdf_filename,
                        "page": page_label,
                        "total_pages": total_pages,
                        "image_url": s3_image_url,
                        "source_dir": pdf_image_sub_dir_name,
                        "type": "pdf",
                        "folder": str(Path(rel_path).parent),
                        "processed_at": datetime.now().isoformat(),
                        **{f"h{i}": context.get(f"h{i}") for i in range(1, 7) if context.get(f"h{i}")},
                        "heading_path": " > ".join(context["heading_path"]) if context.get("heading_path") else None
                    }
                    metadata = {k: v for k, v in metadata.items() if v is not None}

                    # --- Collect data needed for Phase 2 ---
                    # We need page_text, page_label, and metadata for all store types now
                    preprocessed_page_data.append({"text": page_text, "page": page_label, "metadata": metadata.copy()})

                # Process any pending future links now that we have all pages
                if pending_future_links:
                    logger.info(f"Processing {len(pending_future_links)} links to future pages...")
                    for pending_link in pending_future_links:
                        link_info = pending_link["link_info"]
                        target_page_num = pending_link["target_page_num"]
                        target_page_label = target_page_num + 1
                        
                        target_page_text = page_texts.get(target_page_label)
                        if target_page_text:
                            match_start = -1
                            try:
                                pattern = r"\\b" + re.escape(link_info['link_text']) + r"\\b"
                                match = re.search(pattern, target_page_text, re.IGNORECASE | re.DOTALL)
                                if match: match_start = match.start()
                                else: match_start = target_page_text.lower().find(link_info['link_text'].lower())
                            except re.error:
                                match_start = target_page_text.lower().find(link_info['link_text'].lower())

                            if match_start != -1:
                                start_para = target_page_text.rfind('\\n\\n', 0, match_start)
                                start_para = 0 if start_para == -1 else start_para + 2
                                end_para = target_page_text.find('\\n\\n', match_start)
                                end_para = len(target_page_text) if end_para == -1 else end_para
                                target_snippet = target_page_text[start_para:end_para].strip().replace('\\n', ' ')
                                snippet_max_len = 750
                                if len(target_snippet) > snippet_max_len:
                                    trunc_point = target_snippet.rfind('.', 0, snippet_max_len)
                                    if trunc_point > snippet_max_len * 0.7: target_snippet = target_snippet[:trunc_point+1] + "..."
                                    else: target_snippet = target_snippet[:snippet_max_len] + "..."
                            else:
                                # Even after post-processing, we couldn't find the exact text. Use a fallback
                                logger.warning(f"Link text '{link_info['link_text']}' not found on target page {target_page_label} for {s3_pdf_key} even in second pass. Using fallback snippet.")
                                first_para_end = target_page_text.find('\\n\\n')
                                if first_para_end != -1 and first_para_end > 50: target_snippet = target_page_text[:first_para_end].strip().replace('\\n', ' ')
                                else:
                                    fallback_len = 350
                                    target_snippet = target_page_text[:fallback_len].strip().replace('\\n', ' ') + ("..." if len(target_page_text) > fallback_len else "")
                        else:
                            # Still can't find the target page
                            logger.warning(f"Target page {target_page_label} still not found for link after processing all pages in {s3_pdf_key}")
                            target_snippet = f"Content from page {target_page_label}"
                            
                        link_info['target_snippet'] = target_snippet
                        link_info['target_url'] = None
                        pdf_links_data.append(link_info)

                # --- Save Extracted Link Data to S3 ---
                if pdf_links_data and s3_client:
                    try:
                        links_s3_key_suffix = f"{rel_path}.links.json"
                        s3_prefix = EXTRACTED_LINKS_S3_PREFIX
                        if s3_prefix and not s3_prefix.endswith('/'): s3_prefix += '/'
                        links_json_s3_key = f"{s3_prefix}{links_s3_key_suffix}"
                        links_json_content = json.dumps(pdf_links_data, indent=2)

                        # Save extracted links to S3
                        try:
                            s3_client.put_object(
                                Bucket=AWS_S3_BUCKET_NAME, Key=links_json_s3_key, Body=links_json_content, ContentType='application/json'
                            )

                            logger.info(f"Saved {len(pdf_links_data)} extracted links to S3: {links_json_s3_key}")
                        except Exception as e:
                            logger.error(f"Failed to save links to S3: {links_json_s3_key} - Error: {str(e)}")

                    except Exception as save_e:
                        logger.error(f"Failed to save extracted links to S3 for {s3_pdf_key}: {save_e}", exc_info=True)

                # --- Generate and Upload Document Metadata ---
                # Use self.status_callback here
                if self.status_callback:
                    self.status_callback("milestone", {"message": f"Preprocessing complete, starting metadata generation for {pdf_filename}..."})
                else: 
                    logger.info(f"Initiating metadata generation for {s3_pdf_key}...")
                
                if preprocessed_page_data: 
                    try:
                        full_extracted_text = "\n\n".join(page_texts.values())
                        _generate_and_upload_metadata(
                            pdf_bytes=pdf_bytes,
                            extracted_text=full_extracted_text,
                            original_filename=pdf_filename,
                            s3_pdf_key=s3_pdf_key, 
                            available_categories=PREDEFINED_CATEGORIES,
                            status_callback=self.status_callback # Pass it down
                        )
                    except Exception as meta_outer_e:
                         logger.error(f"Outer error calling metadata generation for {s3_pdf_key}: {meta_outer_e}", exc_info=True)
                else:
                    logger.warning(f"Skipping metadata generation for {s3_pdf_key} as no text was extracted.")

            except Exception as pdf_proc_e:
                 logger.error(f"Error processing PDF content for {s3_pdf_key}: {pdf_proc_e}", exc_info=True)
                 if self.status_callback:
                    self.status_callback("error", {"message": f"Error processing PDF content for {pdf_filename}: {pdf_proc_e}"})
                 return None
            finally:
                if doc: doc.close()
            
            preprocess_duration = time.time() - pdf_start_time 
            logger.info(f"Finished pre-processing phase for {s3_pdf_key} in {preprocess_duration:.2f}s. Storing {len(preprocessed_page_data)} pages of data.")
            return preprocessed_page_data

        except Exception as outer_e:
             # ... (outer error handling) ...
             logger.error(f"Unhandled error during pre-processing of {s3_pdf_key}: {outer_e}", exc_info=True)
             if self.status_callback:
                 self.status_callback("error", {"message": f"Unhandled error during pre-processing of {pdf_filename}: {outer_e}"})
             return None

    def preprocess_all_pdfs(self) -> Tuple[PreprocessedCache, List[str]]:
        """
        Phase 1 Orchestration: Iterate through S3 PDFs, call _preprocess_single_pdf,
        build the preprocessed_data_cache, update history, and save intermediate history.
        Returns the cache and the list of successfully preprocessed PDF keys.
        """
        if not s3_client:
            logger.error("S3 client not configured. Cannot preprocess PDFs.")
            return {}, []

        pdf_files_info = []  # Will store tuples of (s3_key, size)
        try:
            logger.info(f"Listing PDFs from bucket '{AWS_S3_BUCKET_NAME}' with prefix '{self.s3_pdf_prefix}'")
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=self.s3_pdf_prefix)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if key.lower().endswith('.pdf') and key != self.s3_pdf_prefix:
                            # Store both the key and file size
                            pdf_files_info.append((key, obj.get("Size", 0)))
            if not pdf_files_info:
                 logger.warning(f"No PDF files found in S3 bucket '{AWS_S3_BUCKET_NAME}' with prefix '{self.s3_pdf_prefix}'.")
                 return {}, []
                 
            # Sort PDFs by size (smallest first)
            pdf_files_info.sort(key=lambda x: x[1])  # Sort by the size (second element in tuple)
            logger.info(f"Sorted {len(pdf_files_info)} PDFs by size (smallest first)")
            # Log size range
            if pdf_files_info:
                smallest = pdf_files_info[0]
                largest = pdf_files_info[-1]
                logger.info(f"Size range: Smallest {smallest[0]} ({smallest[1]} bytes) - Largest {largest[0]} ({largest[1]} bytes)")
                
            # Extract just the keys in size-sorted order
            pdf_files_s3_keys = [info[0] for info in pdf_files_info]
            
        except Exception as e:
            logger.error(f"Error listing PDFs from S3: {e}")
            return {}, []

        start_time = datetime.now()
        total_pdfs = len(pdf_files_s3_keys)
        logger.info(f"Found {total_pdfs} PDFs in S3 for pre-processing.")
        self.preprocessed_data_cache = {} # Reset cache for this run
        successfully_preprocessed_keys = []

        if self.status_callback: 
            self.status_callback("milestone", {"message": f"Found {total_pdfs} PDFs. Starting pre-processing phase..."})

        for pdf_index, s3_pdf_key in enumerate(tqdm(pdf_files_s3_keys, desc="Phase 1: Pre-processing PDFs")):
            current_time = datetime.now()
            elapsed = (current_time - start_time).total_seconds()
            progress_pct = ((pdf_index + 1) / total_pdfs) * 100 if total_pdfs > 0 else 0
            logger.info(f"===== Pre-processing PDF {pdf_index+1}/{total_pdfs} ({progress_pct:.1f}%) - {s3_pdf_key} =====")
            if pdf_index > 0:
                avg_time_per_pdf = elapsed / pdf_index
                remaining_pdfs = total_pdfs - (pdf_index + 1)
                est_remaining_time = avg_time_per_pdf * remaining_pdfs
                est_completion_time = current_time + timedelta(seconds=est_remaining_time)
                logger.info(f"Elapsed: {elapsed:.1f}s. Est. completion: {est_completion_time.strftime('%Y-%m-%d %H:%M:%S')} ({timedelta(seconds=est_remaining_time)})")

            if self.status_callback: 
                self.status_callback("progress", {"current": pdf_index + 1, "total": total_pdfs, "filename": Path(s3_pdf_key).name})

            # --- Call the single PDF preprocessor (already passes callback via self) ---
            pdf_preprocessed_data = self._preprocess_single_pdf(s3_pdf_key)

            if pdf_preprocessed_data is not None:
                # Store results in cache if successful
                self.preprocessed_data_cache[s3_pdf_key] = pdf_preprocessed_data
                successfully_preprocessed_keys.append(s3_pdf_key)
                logger.info(f"Successfully pre-processed {s3_pdf_key}. Cached {len(pdf_preprocessed_data)} pages.")
            else:
                logger.error(f"Failed to pre-process {s3_pdf_key}. Skipping for Phase 2.")

            # --- Save history periodically ---
            if (pdf_index + 1) % 10 == 0 or (pdf_index + 1) == total_pdfs:
                 logger.info(f"Saving intermediate process history after {pdf_index+1} PDFs...")
                 self._save_process_history()

        logger.info(f"===== Phase 1: Pre-processing complete. Processed {len(successfully_preprocessed_keys)}/{total_pdfs} PDFs. =====")
        logger.info(f"Total pre-processing time: {(datetime.now() - start_time).total_seconds():.1f}s")

        # Final history save after Phase 1
        self._save_process_history()

        if self.status_callback:
            self.status_callback("milestone", {"message": f"Pre-processing phase complete. Processed {len(successfully_preprocessed_keys)} PDFs."}) 
        return self.preprocessed_data_cache, successfully_preprocessed_keys

    def _populate_store_for_pdf(self, store: SearchHelper, store_type: str, s3_pdf_key: str, pdf_preprocessed_data: List[PreprocessedData]) -> int:
        """
        Phase 2 logic: Handles chunking, embedding, and adding points/documents
        for ONE PDF to ONE specific store, using pre-processed data.
        Returns the number of points/documents added.
        """
        points_added_to_store = 0
        pdf_filename = Path(pdf_preprocessed_data[0]['metadata']['filename']).name if pdf_preprocessed_data else "Unknown"
        logger.info(f"Processing pre-processed data for '{store_type}' store: {s3_pdf_key} ({len(pdf_preprocessed_data)} pages)")

        try:
            if store_type == "pages":
                pages_texts = [item["text"] for item in pdf_preprocessed_data]
                pages_embeddings = embed_documents(pages_texts, store_type="pages")
                pages_points = []
                if len(pages_embeddings) == len(pdf_preprocessed_data):
                    for i, data in enumerate(pdf_preprocessed_data):
                        pages_points.append(PointStruct(
                            id=str(uuid.uuid4()),
                            vector=pages_embeddings[i],
                            payload={"text": data["text"], "metadata": data["metadata"]}
                        ))
                else:
                    logger.error(f"Mismatch embedding/data count for pages store: {s3_pdf_key} ({len(pages_embeddings)} vs {len(pdf_preprocessed_data)})")

                if pages_points:
                    logger.info(f"Adding {len(pages_points)} points to Pages store for {pdf_filename}")
                    store.add_points(pages_points)
                    points_added_to_store = len(pages_points)

            elif store_type == "semantic":
                # Assume semantic store has chunking method
                semantic_chunks = store.chunk_document_with_cross_page_context(pdf_preprocessed_data)
                if semantic_chunks:
                    logger.info(f"Generated {len(semantic_chunks)} semantic chunks. Embedding...")
                    chunk_texts = [chunk["text"] for chunk in semantic_chunks]
                    semantic_embeddings = embed_documents(chunk_texts, store_type="semantic")
                    semantic_points = []
                    doc_id_counter = store.next_id # Get next ID from store
                    if len(semantic_embeddings) == len(semantic_chunks):
                        for i, chunk_data in enumerate(semantic_chunks):
                            semantic_points.append(PointStruct(
                                id=doc_id_counter + i,
                                vector=semantic_embeddings[i],
                                payload={"text": chunk_data["text"], "metadata": chunk_data["metadata"]}
                            ))
                    else:
                        logger.error(f"Mismatch chunk/embedding count for semantic store: {s3_pdf_key} ({len(semantic_embeddings)} vs {len(semantic_chunks)})")

                    if semantic_points:
                        logger.info(f"Adding {len(semantic_points)} points to Semantic store for {pdf_filename}")
                        points_added_to_store = store.add_points(semantic_points) # add_points returns count added
                else:
                    logger.warning(f"No semantic chunks generated for {s3_pdf_key}")

            elif store_type.startswith("haystack"): # Covers "haystack-qdrant" and "haystack-memory"
                 # Assume haystack store has chunking method similar to semantic
                haystack_chunks = store.chunk_document_with_cross_page_context(pdf_preprocessed_data)
                if haystack_chunks:
                    logger.info(f"Generated {len(haystack_chunks)} chunks for {store_type}. Adding to store...")
                    # Haystack add_points likely handles embedding internally
                    points_added_to_store = store.add_points(haystack_chunks)
                else:
                    logger.warning(f"No chunks generated for {store_type} store for {s3_pdf_key}")

            else:
                logger.error(f"Unknown store type '{store_type}' encountered during population.")
                return 0

            if points_added_to_store > 0:
                 logger.info(f"Successfully added {points_added_to_store} points/documents to {store_type} store for {s3_pdf_key}.")
            elif points_added_to_store == 0 and (store_type != "semantic" or semantic_chunks): # Avoid warning if no chunks generated
                 logger.info(f"No new points/documents added to {store_type} store for {s3_pdf_key}.")


        except Exception as e:
            logger.error(f"Error populating {store_type} store for {s3_pdf_key}: {e}", exc_info=True)
            return 0 # Return 0 points on error

        return points_added_to_store

    def populate_store(self, store_type: str, successfully_preprocessed_keys: List[str]):
        """
        Phase 2 Orchestration: Populate a *single specified store* using the
        pre-processed data from the cache. Checks store-specific history.
        Updates history and saves it finally.
        """
        store_instance = None
        try:
            store_instance = get_vector_store(store_type)
            if not store_instance:
                 raise RuntimeError(f"Failed to initialize {store_type} vector store.")
            logger.info(f"Initialized {store_type} store for population.")
        except Exception as e:
             logger.error(f"Cannot proceed with populating {store_type} store due to initialization error: {e}", exc_info=True)
             return # Stop processing for this store

        if self.cache_behavior == 'rebuild':
            logger.info(f"Cache behavior is 'rebuild', clearing store: {store_type}")
            try:
                # Assuming a clear method exists on the store base class/interface
                store_instance.clear_store()
                logger.info(f"Successfully cleared store: {store_type}")
                # Also reset this store's history for all PDFs since we are rebuilding it
                for key in self.process_history:
                    if 'processed_stores' in self.process_history[key] and store_type in self.process_history[key]['processed_stores']:
                        self.process_history[key]['processed_stores'].remove(store_type)
            except Exception as e:
                logger.error(f"Error clearing store {store_type}: {e}. Proceeding cautiously...", exc_info=True)


        start_time = datetime.now()
        total_pdfs_to_process = len(successfully_preprocessed_keys)
        store_points_total_this_run = 0
        logger.info(f"===== Phase 2: Populating '{store_type}' store for {total_pdfs_to_process} pre-processed PDFs =====")

        pdfs_processed_for_this_store = 0
        pdfs_skipped_for_this_store = 0

        for pdf_index, s3_pdf_key in enumerate(tqdm(successfully_preprocessed_keys, desc=f"Phase 2: Populating {store_type}")):
            # Retrieve pre-processed data (should exist if key is in the list)
            pdf_preprocessed_data = self.preprocessed_data_cache.get(s3_pdf_key)
            if not pdf_preprocessed_data:
                logger.warning(f"Pre-processed data for {s3_pdf_key} not found in cache. Skipping for {store_type} store.")
                continue

            # --- Check Store-Specific Cache History ---
            pdf_history_entry = self.process_history.get(s3_pdf_key, {})
            current_pdf_hash = pdf_history_entry.get('hash')
            processed_stores_for_this_hash = pdf_history_entry.get('processed_stores', [])

            # Determine if we should skip based on cache='use' and history
            skip_store = (self.cache_behavior == 'use' and
                          store_type in processed_stores_for_this_hash)

            if skip_store:
                logger.info(f"Skipping {store_type} store processing for {s3_pdf_key} (cached)")
                pdfs_skipped_for_this_store += 1
                continue # Skip to the next PDF for this store

            # --- Populate the store for this PDF ---
            logger.info(f"Populating {store_type} store with PDF {pdf_index+1}/{total_pdfs_to_process}: {s3_pdf_key}")
            points_added = self._populate_store_for_pdf(store_instance, store_type, s3_pdf_key, pdf_preprocessed_data)

            if points_added > 0:
                 store_points_total_this_run += points_added
                 pdfs_processed_for_this_store += 1
                 # Mark this store as having processed this PDF version in history
                 if store_type not in processed_stores_for_this_hash:
                     self.process_history[s3_pdf_key]['processed_stores'].append(store_type)
            elif points_added == 0: # Successfully processed but added no new points
                 pdfs_processed_for_this_store += 1 # Still count as processed
                 # Mark as processed if it wasn't already (e.g., empty PDF resulted in 0 chunks)
                 if store_type not in processed_stores_for_this_hash:
                      self.process_history[s3_pdf_key]['processed_stores'].append(store_type)
                      logger.info(f"Marked {s3_pdf_key} as processed for {store_type} even though 0 points were added.")
            else: # Error occurred in _populate_store_for_pdf (indicated by negative return, though current returns 0)
                 logger.error(f"Failed to populate {store_type} store for {s3_pdf_key}. History not updated for this PDF/store.")
                 # Do not mark as processed in history if population failed

            # --- Save history periodically within store population ---
            if (pdf_index + 1) % 20 == 0 or (pdf_index + 1) == total_pdfs_to_process:
                 logger.info(f"Saving intermediate process history during {store_type} population...")
                 self._save_process_history()

        # --- Final summary for this store ---
        elapsed_time = (datetime.now() - start_time).total_seconds()
        logger.info(f"===== Phase 2: Finished populating '{store_type}' store. =====")
        logger.info(f"  - PDFs processed: {pdfs_processed_for_this_store}")
        logger.info(f"  - PDFs skipped (cached): {pdfs_skipped_for_this_store}")
        logger.info(f"  - Points/Documents added to {store_type}: {store_points_total_this_run}")
        logger.info(f"  - Time taken for {store_type}: {elapsed_time:.1f}s")

        # Accumulate total points added across all stores processed in this run
        self.total_points_added_across_stores += store_points_total_this_run

        # --- Final history save after this store is done ---
        logger.info(f"Saving final process history after populating {store_type}.")
        self._save_process_history()


    def process_all_sources(self, target_stores: List[str]):
        """
        Main entry point using the refactored two-phase approach.
        Passes the status_callback down to preprocess_all_pdfs.
        """
        logger.info("Starting data processing using two-phase approach...")
        logger.info(f"Target stores: {target_stores}")
        logger.info(f"Cache behavior: {self.cache_behavior}")

        overall_start_time = datetime.now()
        self.total_points_added_across_stores = 0 # Reset grand total

        # --- Phase 1: Pre-processing (passes callback implicitly via self) ---
        preprocessed_cache, successfully_preprocessed_keys = self.preprocess_all_pdfs()

        if not successfully_preprocessed_keys:
            logger.warning("Phase 1 did not successfully preprocess any PDFs. Aborting Phase 2.")
            if self.status_callback:
                 self.status_callback("warning", {"message": "No PDFs were successfully pre-processed."}) 
            return 0
        
        # --- Phase 2: Store Population --- 
        if self.status_callback:
             self.status_callback("milestone", {"message": "Starting Phase 2: Populating vector stores..."})
        # ... (Loop through target stores and call self.populate_store)
        # Note: populate_store doesn't currently accept/use the callback, 
        # but milestones could be added there too if needed for store population progress.
        for store_type in target_stores:
            # ... (store selection logic) ...
            self.populate_store(actual_store_type, successfully_preprocessed_keys)

        # ... (Final Summary Logging) ...
        total_elapsed = (datetime.now() - overall_start_time).total_seconds()
        if self.status_callback:
            self.status_callback("milestone", {"message": f"Data processing complete ({total_elapsed:.1f}s). Total points added: {self.total_points_added_across_stores}"}) 
        # ... (return) ...
        return self.total_points_added_across_stores

    def rebuild_semantic_store(self, validate=True, test_search=True, sample_size=10):
        """
        Rebuilds the semantic vector store from scratch.
        
        This method:
        1. Clears the existing semantic collection
        2. Reprocesses all PDFs with cache_behavior="rebuild"
        3. Optionally validates that metadata matches content
        4. Optionally tests search functionality
        
        Args:
            validate (bool): Whether to validate metadata alignment
            test_search (bool): Whether to test search functionality
            sample_size (int): Number of chunks to sample for validation
            
        Returns:
            bool: True if rebuild was successful, False otherwise
        """
        import time
        from vector_store import get_vector_store
        
        start_time = time.time()
        logger.info("Starting semantic store rebuild process...")
        
        # 1. Initialize semantic store
        semantic_store = get_vector_store("semantic")
        if not semantic_store:
            logger.error("Failed to initialize semantic store")
            return False
        
        # Optional: validate current store to document issues
        if validate:
            logger.info("Validating current semantic store for issues...")
            semantic_store.validate_metadata_alignment(sample_size=sample_size)
        
        # 2. Delete the existing semantic collection
        try:
            logger.info("Deleting existing semantic collection...")
            semantic_store.clear_store()
            logger.info("Successfully cleared semantic collection")
        except Exception as e:
            logger.error(f"Error deleting semantic collection: {e}")
            return False
        
        # 3. Process all PDFs targeting only the semantic store
        logger.info("Beginning PDF processing with rebuilt semantic store...")
        result = self.process_all_sources(target_stores=["semantic"])
        
        # 4. Validate the rebuilt store if requested
        if result and validate:
            logger.info("Validating rebuilt semantic store...")
            validation_passed = semantic_store.validate_metadata_alignment(sample_size=sample_size)
            
            # 5. Test search functionality if requested
            if test_search:
                logger.info("Testing semantic search functionality...")
                search_passed = semantic_store.test_semantic_search()
                
                if validation_passed and search_passed:
                    logger.info("Validation and search tests successful!")
                else:
                    logger.warning("Some validation or search tests failed - review logs for details")
        
        duration = time.time() - start_time
        if result:
            logger.info(f"Semantic store rebuild completed successfully in {duration:.2f} seconds!")
            return True
        else:
            logger.error(f"Semantic store rebuild failed after {duration:.2f} seconds")
            return False

# Example usage (if run directly, though typically called from manage_vector_stores.py)
if __name__ == "__main__":
    logger.info("Running DataProcessor directly for testing...")
    # Example: Rebuild 'pages' and 'semantic' stores
    processor = DataProcessor(cache_behavior='rebuild')
    target_stores_to_process = ['pages', 'semantic']
    processor.process_all_sources(target_stores=target_stores_to_process)
    logger.info("Direct test run finished.") 