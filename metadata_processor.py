import boto3
import json
import hashlib
import datetime
import logging
import os # Import os module
import re # Make sure re is imported
# Consider adding imports for NLP libraries (spaCy, NLTK) or LLM clients later

# --- LLM Integration ---
import sys
from pathlib import Path
# Add project root to path to find llm_providers
project_root = Path(__file__).parent.parent 
sys.path.insert(0, str(project_root))
try:
    from llm_providers import get_llm_client
    # Initialize a client specifically for metadata tasks if needed
    # This reads the same env vars as the main app's client
    metadata_llm_client = get_llm_client()
    logging.info("Initialized LLM client for metadata tasks.")
except ImportError as e:
    logging.error(f"Could not import get_llm_client from llm_providers: {e}")
    metadata_llm_client = None
except Exception as e:
    logging.error(f"Failed to initialize LLM client for metadata: {e}")
    metadata_llm_client = None
# ----------------------

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# S3 Configuration (relies on environment variables)
DEFAULT_BUCKET_NAME = "your-metadata-bucket-name-fallback"
METADATA_BUCKET = os.getenv("AWS_S3_BUCKET_NAME", DEFAULT_BUCKET_NAME)
METADATA_PREFIX = "pdf-metadata/"
AWS_ACCESS_KEY_ID_META = os.getenv("AWS_ACCESS_KEY_ID") # Explicitly check if set
AWS_SECRET_ACCESS_KEY_META = os.getenv("AWS_SECRET_ACCESS_KEY") # Explicitly check if set
AWS_REGION_META = os.getenv("AWS_REGION", "us-east-1") # Explicitly get region

if METADATA_BUCKET == DEFAULT_BUCKET_NAME:
    logging.warning(f"AWS_S3_BUCKET_NAME environment variable not set. Using default: {DEFAULT_BUCKET_NAME}")
if not AWS_ACCESS_KEY_ID_META or not AWS_SECRET_ACCESS_KEY_META:
    logging.warning("AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY environment variables not set. S3 operations will likely fail.")
else:
    logging.info(f"AWS Credentials and Region loaded for S3 operations (Region: {AWS_REGION_META}).")

# --- Metadata Schema (REVISED) ---
# {
#   "document_id": "unique_identifier_for_the_document",
#   "original_filename": "source_pdf_filename.pdf",
#   "s3_pdf_path": "s3://your-raw-pdf-bucket/path/to/document.pdf",
#   "constrained_category": "Category chosen from predefined list", # LLM Task A
#   "automatic_category": "Category determined freely by LLM",   # LLM Task B
#   "source_book_title": "Extracted Title",
#   "summary": "LLM-generated summary of the document.",
#   "keywords": ["keyword1", "keyword2", "topic3"],
#   "processing_timestamp": "ISO_8601_timestamp"
# }

# --- S3 Interaction Functions ---

def upload_metadata_to_s3(metadata_json: dict, document_id: str):
    """Uploads the metadata JSON to the configured S3 bucket."""
    # Boto3 client automatically uses credentials from env vars or config files
    # but region might be needed explicitly if not default
    try:
        s3_client = boto3.client('s3', region_name=AWS_REGION_META) # Pass region explicitly
        object_key = f"{METADATA_PREFIX}{document_id}.json"
        s3_client.put_object(
            Bucket=METADATA_BUCKET,
            Key=object_key,
            Body=json.dumps(metadata_json, indent=2),
            ContentType='application/json'
        )
        logging.info(f"Successfully uploaded metadata for {document_id} to s3://{METADATA_BUCKET}/{object_key}")
    except Exception as e:
        logging.error(f"Error uploading metadata for {document_id} to S3: {e}")
        raise

def get_metadata_from_s3(document_id: str) -> dict | None:
    """Retrieves metadata JSON from the configured S3 bucket."""
    try:
        s3_client = boto3.client('s3', region_name=AWS_REGION_META) # Pass region explicitly
        object_key = f"{METADATA_PREFIX}{document_id}.json"
        response = s3_client.get_object(Bucket=METADATA_BUCKET, Key=object_key)
        metadata = json.loads(response['Body'].read().decode('utf-8'))
        logging.info(f"Successfully retrieved metadata for {document_id} from s3://{METADATA_BUCKET}/{object_key}")
        return metadata
    except s3_client.exceptions.NoSuchKey:
        logging.warning(f"Metadata not found for {document_id} at s3://{METADATA_BUCKET}/{object_key}")
        return None
    except Exception as e:
        logging.error(f"Error retrieving metadata for {document_id} from S3: {e}")
        raise

# --- Metadata Extraction Functions (Placeholders - REVISED) ---

def generate_document_id(pdf_content: bytes | None = None, s3_path: str | None = None) -> str:
    """Generates a unique ID for the document (e.g., hash of content or use S3 path)."""
    if pdf_content:
        return hashlib.sha256(pdf_content).hexdigest()
    elif s3_path:
        return hashlib.sha256(s3_path.encode('utf-8')).hexdigest()
    else:
        raise ValueError("Either pdf_content or s3_path must be provided to generate document ID")

def determine_constrained_category(document_text: str, available_categories: list[dict]) -> str:
    """Analyzes text and selects the best category name from the provided list (with descriptions) using an LLM."""
    if not metadata_llm_client:
        logging.warning("LLM client not available for constrained categorization. Returning placeholder.")
        # Fallback placeholder logic
        if not available_categories: return "Unknown"
        # Simple keyword check (less effective now, but keeps fallback simple)
        cat_names = [cat['name'] for cat in available_categories]
        if "monster" in document_text.lower() and "Monsters" in cat_names: return "Monsters"
        return available_categories[0]['name'] # Default to first name

    if not available_categories:
        logging.warning("No available categories provided for constrained categorization. Returning 'Unknown'.")
        return "Unknown"

    logging.info(f"Determining constrained category from {len(available_categories)} options for doc ({len(document_text)} chars)...")

    # Create a numbered list of categories with descriptions for the prompt
    category_list_str = "\n".join([f"{i+1}. {cat['name']}: {cat['description']}" for i, cat in enumerate(available_categories)])
    valid_category_names = [cat['name'] for cat in available_categories]

    # Prompt asking the LLM to choose ONLY from the list based on descriptions
    prompt = (
        f"Analyze the following document text and determine which single category from the list below best describes its primary content. "
        f"Consider the category descriptions provided. "
        f"Respond with ONLY the category NAME exactly as it appears in the list (e.g., 'Core Rules', 'Monsters').\n\n"
        f"Available Categories:\n{category_list_str}\n\n"
        f"Document Text:\n---\n{document_text}\n---"        
    )
    
    system_prompt = "You are an expert assistant skilled at classifying documents based on a predefined list of categories with descriptions. You only respond with the single best category name from the provided list."

    try:
        # Use the LLM client to generate the category
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt, 
            system_message=system_prompt, 
            temperature=0.0, # Zero temperature for precise selection
            max_tokens=50,  # Should be enough for any category name
            stream=False
        )
        
        # --- UPDATED HANDLING --- 
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            chosen_category_name = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            chosen_category_name = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            chosen_category_name = str(response_obj)
        # ------------------------
            
        chosen_category_name = chosen_category_name.strip().strip('"\'')

        # Validate the response against the available category names
        if chosen_category_name in valid_category_names:
            logging.info(f"Determined constrained category: '{chosen_category_name}'")
            return chosen_category_name
        else:
            logging.warning(f"LLM returned a category name ('{chosen_category_name}') not in the valid list: {valid_category_names}. Attempting fallback match or using default.")
            # Attempt a case-insensitive match as a fallback
            for name in valid_category_names:
                if chosen_category_name.lower() == name.lower():
                    logging.info(f"Found case-insensitive fallback match: '{name}'")
                    return name
            # If still no match, default to the first category name
            default_name = available_categories[0]['name']
            logging.warning(f"Using first available category name '{default_name}' as fallback.")
            return default_name

    except Exception as e:
        logging.error(f"Error determining constrained category with LLM: {e}", exc_info=True)
        # Fallback placeholder on error
        default_name = available_categories[0]['name'] if available_categories else "Unknown"
        logging.warning(f"Using fallback category '{default_name}' due to LLM error.")
        return default_name

def determine_automatic_category(document_text: str) -> str:
    """Analyzes text to determine a descriptive category freely using an LLM."""
    if not metadata_llm_client:
        logging.warning("LLM client not available for automatic categorization. Returning placeholder.")
        # Fallback placeholder logic
        if "stat block" in document_text.lower(): return "Monsters (Placeholder)"
        if "spell level" in document_text.lower(): return "Spells (Placeholder)"
        return "General (Placeholder)"

    logging.info(f"Determining automatic category freely for document ({len(document_text)} chars)...")
    
    # Prompt asking for a concise, descriptive category name
    # TODO: Refine prompt, maybe ask for only 1-4 words?
    prompt = (
        f"Analyze the following document text and provide a concise, descriptive category name "
        f"(e.g., 'Spell Descriptions', 'Monster Stat Blocks', 'Character Class Options', 'Magic Items List'). "
        f"Focus on the primary content type. Respond with ONLY the category name.\n\n"
        f"---\n{document_text}\n---"
    )
    
    # Use a system prompt appropriate for categorization
    system_prompt = "You are an expert assistant skilled at analyzing documents and assigning concise category labels."

    try:
        # Use the LLM client to generate the category
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt, 
            system_message=system_prompt, 
            temperature=0.1, # Very low temperature for focused category name
            max_tokens=50,  # Limit category name length
            stream=False
        )
        
        # --- UPDATED HANDLING --- 
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            category = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            category = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            category = str(response_obj)
        # ------------------------
            
        category = category.strip().strip('"\'') 
        if not category:
            raise ValueError("LLM returned an empty category string.")

        logging.info(f"Determined automatic category: '{category}'")
        return category

    except Exception as e:
        logging.error(f"Error determining automatic category with LLM: {e}", exc_info=True)
        # Fallback placeholder on error
        if "stat block" in document_text.lower(): return "Monsters (Error Fallback)"
        if "spell level" in document_text.lower(): return "Spells (Error Fallback)"
        return "General (Error Fallback)"

def extract_source_book_title(document_text: str) -> str | None:
    """Attempts to extract the source book title from text."""
    logging.info("Extracting source book title...")
    
    # Limit search to the beginning of the document to avoid grabbing random matches
    # Look within the first ~50 lines or ~4000 characters, whichever is smaller
    search_text = '\n'.join(document_text.split('\n', 50)[:50])
    if len(search_text) > 4000:
        search_text = search_text[:4000]

    # 1. Look for lines starting with "Title:" (case-insensitive, allows space)
    #    Example: "Title: Player's Handbook", "TITLE : Monster Manual"
    title_match = re.search(r"^\s*title\s*:\s*(.+)$", search_text, re.IGNORECASE | re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()
        # Basic cleaning (remove if it looks like a path or is too long)
        if '/' not in title and '\\' not in title and len(title) < 150:
             logging.info(f"Found title via 'Title:' pattern: '{title}'")
             return title
        else:
             logging.debug(f"Rejected potential title from 'Title:' pattern (path-like or too long): '{title}'")

    # 2. Fallback: Check the first few non-empty lines for a likely title
    lines = document_text.split('\n')
    checked_lines = 0
    max_lines_to_check = 5
    for line in lines:
        stripped_line = line.strip()
        if stripped_line: # If it's not empty
            checked_lines += 1
            # Check if it looks like a title (reasonable length, not typical sentence punctuation)
            if 3 < len(stripped_line) < 100 and not stripped_line.endswith(('.', '?', '!')):
                # Avoid lines that are all caps and very short (likely headers)
                if not (stripped_line.isupper() and len(stripped_line) < 15):
                    logging.info(f"Using first non-empty line as potential title: '{stripped_line}'")
                    return stripped_line
            
            if checked_lines >= max_lines_to_check:
                break # Stop checking after a few non-empty lines

    logging.info("Could not confidently extract source book title.")
    return None

def generate_summary(document_text: str, max_input_chars: int = 20000) -> str:
    """Generates a summary of the document using an LLM, truncating input if necessary."""
    if not metadata_llm_client:
        logging.warning("LLM client not available for summarization. Returning placeholder.")
        preview = (document_text[:200] + '...') if len(document_text) > 200 else document_text
        return f"[Placeholder] Summary of document starting with: '{preview}'"

    # Truncate input text if it exceeds the limit
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
        
        # --- UPDATED HANDLING --- 
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            summary = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            summary = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            summary = str(response_obj)
        # ------------------------
            
        summary = summary.strip()
        if not summary:
            raise ValueError("LLM returned an empty summary string.")
        logging.info(f"Generated summary: '{summary[:100]}...'")
        return summary

    except Exception as e:
        logging.error(f"Error generating summary with LLM: {e}", exc_info=True)
        preview = (truncated_text[:200] + '...') if len(truncated_text) > 200 else truncated_text
        return f"[Error] Failed to generate summary. Document starts: '{preview}'"

def extract_keywords(document_text: str) -> list[str]:
    """Extracts relevant keywords from the document text using an LLM."""
    if not metadata_llm_client:
        logging.warning("LLM client not available for keyword extraction. Returning placeholder.")
        # Fallback placeholder logic (original simple version)
        from collections import Counter
        words = [w.lower() for w in document_text.split() if len(w) > 4 and w.isalnum()]
        common_words = [word for word, count in Counter(words).most_common(10)]
        return [f"{kw} (Placeholder)" for kw in common_words]

    logging.info(f"Extracting keywords for document ({len(document_text)} chars)...")

    # Prompt asking for keywords
    # TODO: Refine prompt, specify number of keywords (e.g., 10-15)?
    prompt = (
        f"Analyze the following document text and extract the most relevant keywords or key phrases that represent the main topics. "
        f"Return a comma-separated list of these keywords/phrases.\n\n"
        f"Document Text:\n---\n{document_text}\n---"
    )

    system_prompt = "You are an expert assistant skilled at identifying the core topics of a document and extracting relevant keywords."

    try:
        # Use the LLM client to generate keywords
        response_obj = metadata_llm_client.generate_response(
            prompt=prompt,
            system_message=system_prompt,
            temperature=0.2, # Relatively low temperature for focused keywords
            max_tokens=150, # Allow space for a decent number of keywords
            stream=False
        )

        # --- UPDATED HANDLING --- 
        if isinstance(response_obj, dict) and "response_text" in response_obj:
            keywords_text = response_obj["response_text"]
        elif hasattr(response_obj, '__iter__') and not isinstance(response_obj, str):
            logging.warning("LLM client returned a generator unexpectedly for stream=False. Consuming it.")
            keywords_text = "".join(chunk for chunk in response_obj)
        else:
            logging.warning(f"Unexpected response type from LLM client ({type(response_obj)}). Attempting str conversion.")
            keywords_text = str(response_obj)
        # ------------------------

        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
        if not keywords:
             raise ValueError("LLM returned no valid keywords.")

        logging.info(f"Extracted keywords: {keywords}")
        return keywords

    except Exception as e:
        logging.error(f"Error extracting keywords with LLM: {e}", exc_info=True)
        # Fallback placeholder on error
        from collections import Counter
        words = [w.lower() for w in document_text.split() if len(w) > 4 and w.isalnum()]
        common_words = [word for word, count in Counter(words).most_common(10)]
        return [f"{kw} (Error Fallback)" for kw in common_words]


# --- Main Processing Function (REVISED) ---

def process_document_for_metadata(
    pdf_content: bytes | None,
    extracted_text: str,
    original_filename: str,
    s3_pdf_path: str,
    available_categories: list[dict]
) -> dict:
    """
    Generates metadata for a single document, using a summary for categorization and keywords.
    """
    logging.info(f"Starting metadata processing for: {original_filename}")

    document_id = generate_document_id(pdf_content=pdf_content, s3_path=s3_pdf_path)

    # --- Generate Summary First --- 
    # Use the full text to generate summary, but the function itself will truncate if needed.
    # Consider a reasonable char limit for summary input if full text is extremely large.
    summary_text = generate_summary(extracted_text) 

    # --- Use Summary for Other LLM Tasks --- 
    # Pass the generated summary (or error/placeholder string) to the categorization
    # and keyword extraction functions to reduce token usage.
    constrained_category = determine_constrained_category(summary_text, available_categories)
    automatic_category = determine_automatic_category(summary_text)
    keywords = extract_keywords(summary_text)

    # --- Extract Title (operates on original text) ---
    source_book_title = extract_source_book_title(extracted_text)

    # --- Assemble Metadata --- 
    metadata = {
        "document_id": document_id,
        "original_filename": original_filename,
        "s3_pdf_path": s3_pdf_path,
        "constrained_category": constrained_category, # Based on summary
        "automatic_category": automatic_category,     # Based on summary
        "source_book_title": source_book_title,       # Based on original text
        "summary": summary_text,                      # Store the generated summary
        "keywords": keywords,                         # Based on summary
        "processing_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    logging.info(f"Finished metadata processing for: {original_filename}")
    return metadata

# --- Example Usage (for testing - REVISED) ---

if __name__ == "__main__":
    import argparse
    import time
    import fitz # PyMuPDF for text extraction
    from pathlib import Path # For filename extraction
    from botocore.exceptions import ClientError # Import ClientError
    
    # Import the categories directly from config
    try:
        from config import PREDEFINED_CATEGORIES
    except ImportError:
        logging.error("Could not import PREDEFINED_CATEGORIES from config.py. Ensure config.py is accessible.")
        PREDEFINED_CATEGORIES = [
             {"name": "Core Rules", "description": "Gameplay mechanics, character creation, combat, equipment."},
             {"name": "Monsters", "description": "Creature stat blocks and lore."},
        ]
        logging.warning(f"Using fallback mock categories: {PREDEFINED_CATEGORIES}")

    # --- Argument Parsing --- 
    parser = argparse.ArgumentParser(description="Test Metadata Processor by processing a PDF from S3")
    parser.add_argument(
        "-k", "--s3-key", 
        default=None, 
        help="Specific S3 key of the PDF to process (within source-pdfs/ prefix). If omitted, processes the first PDF found."
    )
    parser.add_argument(
        "--s3-test", 
        action="store_true", 
        help="Enable S3 upload/download tests for the generated metadata (requires AWS credentials and bucket config)"
    )
    parser.add_argument(
        "--source-prefix",
        default=os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/"), # Get prefix from env
        help="S3 prefix where source PDFs are located."
    )

    args = parser.parse_args()

    # Ensure prefix ends with /
    s3_source_prefix = args.source_prefix
    if s3_source_prefix and not s3_source_prefix.endswith('/'):
        s3_source_prefix += '/'

    logging.info("Running metadata_processor.py standalone test...")
    logging.info(f"Target S3 Key: {args.s3_key if args.s3_key else 'First PDF found'}")
    logging.info(f"Source Prefix: {s3_source_prefix}")
    logging.info(f"S3 Metadata Testing Enabled: {args.s3_test}")

    # --- S3 Client Initialization for Source PDF --- 
    s3_source_client = None
    if AWS_ACCESS_KEY_ID_META and AWS_SECRET_ACCESS_KEY_META and METADATA_BUCKET != DEFAULT_BUCKET_NAME:
        try:
            s3_source_client = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID_META,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY_META,
                region_name=AWS_REGION_META
            )
            logging.info(f"Initialized S3 client for source PDF operations.")
        except Exception as e:
            logging.error(f"Failed to initialize S3 client for source PDFs: {e}")
            sys.exit(1)
    else:
        logging.error("S3 credentials or bucket name not configured. Cannot access source PDFs.")
        sys.exit(1)

    # --- Find Target S3 Key --- 
    target_s3_key = args.s3_key
    if not target_s3_key:
        logging.info(f"No specific S3 key provided. Listing PDFs in s3://{METADATA_BUCKET}/{s3_source_prefix} ...")
        try:
            paginator = s3_source_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=METADATA_BUCKET, Prefix=s3_source_prefix)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if key.lower().endswith('.pdf') and key != s3_source_prefix: # Find first PDF
                            target_s3_key = key
                            logging.info(f"Found first PDF: {target_s3_key}")
                            break
                if target_s3_key: break # Stop after finding the first one
            if not target_s3_key:
                logging.error(f"No PDF files found in s3://{METADATA_BUCKET}/{s3_source_prefix}")
                sys.exit(1)
        except Exception as e:
            logging.error(f"Error listing PDFs from S3: {e}")
            sys.exit(1)
    else:
        # If key was provided, ensure it has the prefix (if not already present)
        if not target_s3_key.startswith(s3_source_prefix):
             target_s3_key = s3_source_prefix + target_s3_key
             logging.info(f"Prepended source prefix to key: {target_s3_key}")

    # --- Load Data from S3 --- 
    logging.info(f"Loading PDF: {target_s3_key}")
    try:
        pdf_object = s3_source_client.get_object(Bucket=METADATA_BUCKET, Key=target_s3_key)
        test_pdf_bytes = pdf_object['Body'].read()
        original_filename = Path(target_s3_key).name
        logging.info(f"Downloaded {len(test_pdf_bytes)} bytes for {original_filename}")
    except ClientError as e:
        logging.error(f"Failed to download PDF '{target_s3_key}' from S3: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error downloading PDF '{target_s3_key}': {e}")
        sys.exit(1)

    # --- Extract Text using PyMuPDF --- 
    test_extracted_text = ""
    try:
        logging.info("Extracting text from PDF...")
        doc = fitz.open(stream=test_pdf_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc[page_num]
            test_extracted_text += page.get_text("text") + "\n"
        doc.close()
        logging.info(f"Extracted {len(test_extracted_text)} characters of text.")
    except Exception as e:
        logging.error(f"Error extracting text from PDF {original_filename}: {e}")
        # Continue without extracted text? Or exit? Let's exit for now.
        sys.exit(1)

    # --- Processing Metadata --- 
    try:
        generated_metadata = process_document_for_metadata(
            pdf_content=test_pdf_bytes, # Pass the actual PDF bytes
            extracted_text=test_extracted_text,
            original_filename=original_filename,
            s3_pdf_path=f"s3://{METADATA_BUCKET}/{target_s3_key}", # Use actual S3 path
            available_categories=PREDEFINED_CATEGORIES
        )
        print("\n--- Generated Metadata ---")
        print(json.dumps(generated_metadata, indent=2))

        # --- S3 Metadata Upload/Download Test --- 
        if args.s3_test:
            doc_id = generated_metadata["document_id"]
            print(f"\n--- Attempting S3 Metadata Upload/Download Test for doc_id: {doc_id} ---")
            
            if METADATA_BUCKET == DEFAULT_BUCKET_NAME:
                 print(f"SKIPPING S3 Test: Set the AWS_S3_BUCKET_NAME environment variable. Current value: {METADATA_BUCKET}")
            elif not AWS_ACCESS_KEY_ID_META or not AWS_SECRET_ACCESS_KEY_META:
                 print(f"SKIPPING S3 Test: AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY not set in environment.")
            else:
                try:
                    # 1. Upload
                    print("Attempting metadata upload...")
                    upload_metadata_to_s3(generated_metadata, doc_id)
                    print("Metadata upload successful (according to function). Waiting 2s...")
                    time.sleep(2)

                    # 2. Download
                    print("Attempting metadata download...")
                    retrieved_metadata = get_metadata_from_s3(doc_id)
                    
                    # 3. Verify
                    if retrieved_metadata:
                        print("Download successful. Retrieved Metadata:")
                        print(json.dumps(retrieved_metadata, indent=2))
                        if retrieved_metadata == generated_metadata:
                            print("VERIFICATION: SUCCESS - Retrieved metadata matches generated metadata.")
                        else:
                            print("VERIFICATION: FAILED - Retrieved metadata does NOT match generated metadata.")
                    else:
                        print("Download failed.")
                except Exception as s3_err:
                     print(f"S3 Metadata Test Error: {s3_err}")
                     logging.error(f"Error during S3 metadata test: {s3_err}", exc_info=True)
        else:
            print("\n--- Skipping S3 Metadata Tests (--s3-test flag not set) ---")

    except Exception as e:
        logging.error(f"Error during metadata processing test: {e}", exc_info=True)

    logging.info("Standalone test finished.") 