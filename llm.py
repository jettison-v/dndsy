import os
# Remove direct OpenAI import if no longer needed directly
# from openai import OpenAI 
from vector_store import get_vector_store
import logging
import tiktoken # For token counting (OpenAI specific for now)
from dotenv import load_dotenv
import time
import json
from typing import Generator, List, Dict, Set
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

from llm_providers import get_llm_client # Import the factory function
from embeddings.model_provider import embed_query # Import query embedding function
from config import app_config, default_store_type # Import from config instead of app

load_dotenv(override=True) # Load .env, potentially overriding system vars

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- S3 Configuration for Link Data --- 
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1") # Default region if not set
EXTRACTED_LINKS_S3_PREFIX = "extracted_links/"

s3_client_links = None
def get_s3_client_for_links():
    """Initializes and returns the S3 client for fetching link data."""
    global s3_client_links
    if s3_client_links:
        return s3_client_links

    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET_NAME:
        try:
            s3_client_links = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION
            )
            logger.info(f"Initialized S3 client for link data in region: {AWS_REGION}")
            return s3_client_links
        except (NoCredentialsError, PartialCredentialsError) as e:
            logger.error(f"AWS Credentials for link data not found or incomplete: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client for link data: {e}")
    else:
        logger.warning("AWS S3 credentials/bucket name not fully configured for link data.")
    return None

# Initialize LLM client using the factory
# Reads LLM_PROVIDER and LLM_MODEL_NAME from env vars
try:
    llm_client = get_llm_client()
except Exception as e:
    logger.critical(f"Failed to initialize LLM client on startup: {e}")
    llm_client = None 

def reinitialize_llm_client():
    """
    Reinitializes the LLM client with updated configuration.
    This function should be called when model settings change.
    """
    global llm_client
    try:
        logger.info("Reinitializing LLM client with updated configuration")
        llm_client = get_llm_client()
        logger.info(f"LLM client reinitialized. Using model: {llm_client.get_model_name()}")
        return True
    except Exception as e:
        logger.error(f"Failed to reinitialize LLM client: {e}")
        return False

# Get default store type from environment
default_store_type = os.getenv("DEFAULT_VECTOR_STORE", "semantic")

def num_tokens_from_string(string: str, model: str) -> int:
    """(OpenAI specific) Returns the number of tokens in a text string."""
    # WARNING: This uses tiktoken and is specific to OpenAI models.
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        logger.warning(f"Tiktoken model {model} not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens

def truncate_text(text: str, max_tokens: int, model: str) -> str:
    """(OpenAI specific) Truncate text to fit within token limit."""
    # WARNING: This uses tiktoken and is specific to OpenAI models.
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        logger.warning(f"Tiktoken model {model} not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return encoding.decode(tokens[:max_tokens]) + "..."

def _get_link_data_for_sources(source_keys: List[str]) -> Dict[str, Dict]:
    """
    Fetches and consolidates link data from JSON files in S3 for given source keys.
    
    Args:
        source_keys: A list of unique S3 keys for the source PDFs.
        
    Returns:
        A dictionary where keys are lowercase link_text and values are link info 
        (type, url, page, snippet).
    """
    consolidated_links = {}
    if not source_keys:
        return consolidated_links
        
    s3 = get_s3_client_for_links()
    logger.info(f"S3 Client object for links check: {'VALID' if s3 else 'NONE'}")
    if not s3:
        logger.warning("S3 client not available, cannot fetch link data.")
        return consolidated_links
        
    # Ensure prefix ends with a slash
    s3_prefix = EXTRACTED_LINKS_S3_PREFIX
    if s3_prefix and not s3_prefix.endswith('/'):
        s3_prefix += '/'
        
    logger.info(f"Fetching link data from S3 prefix: {s3_prefix} for {len(source_keys)} sources")
    
    for s3_key in source_keys:
        # Construct the key for the .links.json file
        # Assumes s3_key includes the original prefix like 'source-pdfs/MyDoc.pdf'
        # We need to derive the relative path part for the links key
        original_pdf_prefix = os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/")
        if original_pdf_prefix and not original_pdf_prefix.endswith('/'):
            original_pdf_prefix += '/'
            
        rel_path = s3_key
        if s3_key.startswith(original_pdf_prefix):
            rel_path = s3_key[len(original_pdf_prefix):]
            
        links_s3_key = f"{s3_prefix}{rel_path}.links.json"
        
        logger.info(f"Attempting to fetch link key: {links_s3_key} (derived from source key: {s3_key})")
        
        try:
            response = s3.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=links_s3_key)
            links_content = response['Body'].read().decode('utf-8')
            links_list = json.loads(links_content)
            
            logger.debug(f"Successfully fetched and parsed {len(links_list)} links from {links_s3_key}")
            
            # Consolidate links, lowercasing the text for matching
            for link_info in links_list:
                link_text = link_info.get('link_text')
                if link_text:
                    key = link_text.lower()
                    consolidated_links[key] = {
                        'type': link_info.get('link_type'),
                        'url': link_info.get('target_url'),
                        'page': link_info.get('target_page'),
                        'snippet': link_info.get('target_snippet'),
                        'original_text': link_text # Keep original casing if needed later
                    }
                    
                    # Add the source document s3_key for internal links
                    if link_info.get('link_type') == 'internal':
                        consolidated_links[key]['s3_key'] = s3_key
                        
                    # Add color information if available
                    if link_info.get('color'):
                        consolidated_links[key]['color'] = link_info.get('color')
                    
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"Link data file not found in S3: {links_s3_key}")
            else:
                logger.error(f"S3 ClientError fetching link data {links_s3_key}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from link data file {links_s3_key}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching link data {links_s3_key}: {e}", exc_info=True)
            
    logger.info(f"Consolidated {len(consolidated_links)} unique link texts from sources.")
    return consolidated_links

def _retrieve_and_prepare_context(query: str, model: str, limit: int = 5, store_type: str = None, 
                              max_tokens_per_result: int = 1000, max_total_context_tokens: int = 4000,
                              rerank_alpha: float = 0.5, rerank_beta: float = 0.3, rerank_gamma: float = 0.2,
                              fetch_multiplier: int = 3) -> list[dict]:
    """
    Orchestrates context retrieval: embeds query, searches store, formats results.
    
    Args:
        query: The user's search query string.
        model: The LLM model name (used for token counting/limits).
        limit: Max number of context results to return.
        store_type: Vector store type ("standard" or "semantic"). Uses default if None.
        max_tokens_per_result: Maximum tokens allowed per context result
        max_total_context_tokens: Maximum total tokens for all context combined
        rerank_alpha: Weight for dense vector scores (semantic store)
        rerank_beta: Weight for sparse BM25 scores (semantic store)
        rerank_gamma: Weight for keyword match scores (semantic store)
        fetch_multiplier: Multiplier for initial retrieval before reranking
    """
    effective_store_type = store_type or default_store_type
        
    vector_store = get_vector_store(effective_store_type)
    if vector_store is None:
         logger.error(f"Could not get vector store for type: {effective_store_type}")
         return []

    try:
        # Embed the query based on the selected store type
        logger.info(f"Embedding query for {effective_store_type} store: '{query[:50]}...'")
        query_vector = embed_query(query, effective_store_type)
        
        # Search the vector store
        logger.info(f"Searching {effective_store_type} store with query: '{query}'")
        if effective_store_type == "semantic":
             # Semantic store uses hybrid search (vector + original query for BM25/keywords)
             results = vector_store.search(
                 query_vector=query_vector, 
                 query=query, 
                 limit=limit,
                 rerank_alpha=rerank_alpha,
                 rerank_beta=rerank_beta,
                 rerank_gamma=rerank_gamma,
                 fetch_multiplier=fetch_multiplier
             )
        else: 
             # Standard store uses simple vector search
             results = vector_store.search(query_vector=query_vector, limit=limit)
             
        logger.info(f"Found {len(results)} results from vector store")
        if not results: return []
            
        # Process and format results, applying token limits
        context_parts = []
        total_tokens = 0
        # Use the token limits passed in as parameters
        # max_tokens_per_result and max_total_context_tokens are now parameters
        
        for idx, result in enumerate(results):
            # Extract necessary data from result payload/metadata
            metadata = result.get('metadata', {})
            text = result.get('text', '').strip()
            score = result.get('score', 0)
            source_key = metadata.get('source', 'unknown')
            page = metadata.get('page', 'unknown')
            
            if not text: continue # Skip empty results
            
            # --- Format result for display and internal use --- 
            source_filename = source_key.split('/')[-1]
            source_display_name = source_filename.replace('.pdf', '')
            
            # Build context info string (e.g., heading path)
            context_info = None
            heading_path = metadata.get('heading_path')
            section = metadata.get('section')
            subsection = metadata.get('subsection')
            if heading_path: context_info = heading_path
            elif section: context_info = f"{section}{f' > {subsection}' if subsection else ''}"
            # Fallback to most specific heading level if no path/section
            if not context_info:
                for level in range(6, 0, -1):
                    heading_key = f"h{level}"
                    if heading_key in metadata and metadata[heading_key]:
                        context_info = metadata[heading_key]
                        break
            
            # Add chunk index if available (primarily for semantic chunks)
            chunk_index = metadata.get('chunk_index')
            chunk_info_display = context_info
            if chunk_index is not None and not context_info:
                 chunk_info_display = f"Chunk #{chunk_index}" # Basic fallback if no context
            elif chunk_index is not None: # Append chunk index if context exists
                 chunk_info_display = f"{context_info} (#{chunk_index})"

            logger.info(f"Result {idx + 1} from {source_filename} (page {page}) score={score:.4f}")
            if context_info: logger.info(f"  Context: {context_info}")
            
            # Truncate individual result text if it exceeds per-result limit
            tokens = num_tokens_from_string(text, model=model)
            if tokens > max_tokens_per_result:
                text = truncate_text(text, max_tokens=max_tokens_per_result, model=model)
                tokens = num_tokens_from_string(text, model=model) # Recalculate after truncation
            
            # Check if adding this result exceeds total context token limit
            if total_tokens + tokens <= max_total_context_tokens:
                context_parts.append({
                    'text': text,
                    'source': source_display_name,
                    'page': page,
                    'image_url': metadata.get('image_url'),
                    'total_pages': metadata.get('total_pages'),
                    'source_dir': metadata.get('source_dir'), 
                    'score': score,
                    'original_s3_key': source_key, # Use the original S3 key
                    'chunk_info': chunk_info_display # Formatted context/chunk info
                })
                total_tokens += tokens
                logger.info(f"Added context {idx+1} ({tokens} tokens). Total context: {total_tokens}/{max_total_context_tokens}")
            else:
                logger.info(f"Skipping remaining results due to token limit ({total_tokens}+{tokens} > {max_total_context_tokens})")
                break
        
        return context_parts
    except Exception as e:
        logger.error(f"Error retrieving context for query '{query}': {e}", exc_info=True)
        return []

def ask_dndsy(prompt: str, store_type: str = None, temperature: float = 0.3, max_tokens: int = 1500,
              retrieval_limit: int = 5, max_tokens_per_result: int = 1000, 
              max_total_context_tokens: int = 4000, rerank_alpha: float = 0.5, 
              rerank_beta: float = 0.3, rerank_gamma: float = 0.2,
              fetch_multiplier: int = 3) -> Generator[str, None, None]:
    """
    Main RAG pipeline function.
    Processes a query using RAG and streams the response via SSE.
    Includes fetching and streaming link data after the main response.
    
    Args:
        prompt: The user query.
        store_type: Vector store type ("standard" or "semantic"). Uses default if None.
        temperature: Temperature setting for LLM response generation.
        max_tokens: Maximum number of tokens the LLM should generate.
        retrieval_limit: Maximum number of context results to return.
        max_tokens_per_result: Maximum tokens allowed per context result.
        max_total_context_tokens: Maximum total tokens for all context combined.
        rerank_alpha: Weight for dense vector scores (semantic store).
        rerank_beta: Weight for sparse BM25 scores (semantic store).
        rerank_gamma: Weight for keyword match scores (semantic store).
        fetch_multiplier: Multiplier for initial retrieval before reranking.
        
    Yields:
        Server-Sent Events (SSE) strings containing metadata, status updates, 
        text chunks, link data, or errors.
    """
    if not llm_client:
         # ... (error handling for LLM client unchanged) ...
         error_msg = "LLM client failed to initialize. Cannot process query."
         logger.error(error_msg)
         yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
         return

    start_time_total = time.perf_counter()
    current_model_name = llm_client.get_model_name()
    logger.info(f"Processing query with LLM: {current_model_name}")
    effective_store_type = store_type or default_store_type
    logger.info(f"Using vector store type: {effective_store_type}")

    sources_for_metadata = [] # Keep track of sources used

    try:
        # --- Step 1: Retrieve and Prepare Context --- 
        logger.info("Step 1: Retrieving context...")
        start_time_rag = time.perf_counter()
        context_parts = _retrieve_and_prepare_context(
            query=prompt, 
            model=current_model_name, # Pass model for token calculations
            store_type=effective_store_type,
            limit=retrieval_limit,
            max_tokens_per_result=max_tokens_per_result,
            max_total_context_tokens=max_total_context_tokens,
            rerank_alpha=rerank_alpha,
            rerank_beta=rerank_beta,
            rerank_gamma=rerank_gamma,
            fetch_multiplier=fetch_multiplier
        )
        end_time_rag = time.perf_counter()
        logger.info(f"Context retrieval completed in {end_time_rag - start_time_rag:.4f}s. Found {len(context_parts)} parts.")

        # --- Step 2: Yield Status Update --- 
        yield f"event: status\ndata: {json.dumps({'status': 'Consulting LLM'})}\n\n"

        # --- Step 3: Prepare Prompt & Collect Source Keys --- 
        logger.info("Step 3: Preparing LLM prompt and collecting source keys...")
        start_time_prompt = time.perf_counter()
        context_text_for_prompt = ""
        if context_parts:
            for part in context_parts:
                # Format source display text
                display_text = f"{part['source']} (Pg {part['page']})"
                if part.get('chunk_info'): display_text += f" - {part['chunk_info']}"
                
                # Prepare metadata object for frontend & collect source keys
                original_s3_key = part.get('original_s3_key') 
                if original_s3_key:
                    sources_for_metadata.append({
                        'display': display_text,
                        's3_key': original_s3_key,
                        'page': part['page'],
                        'score': part.get('score'),
                        'chunk_info': part.get('chunk_info')
                    })
                else: 
                    logger.warning(f"Missing 'original_s3_key' for context part: {part}")
                    
                # Append context to the text block for the LLM prompt
                context_text_for_prompt += f"Source: {display_text}\nContent:\n{part['text']}\n\n"
                
            logger.info(f"Prepared {len(sources_for_metadata)} sources for metadata. Context length: {len(context_text_for_prompt)} chars.")
        
        # Define the system prompt for the LLM
        system_message = (
            "You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. "
            "Follow these guidelines:\n"
            # ... (guidelines unchanged) ...
            "1. ALWAYS prioritize using the provided 2024 rules context when available.\n"
            "2. If context is provided, base your answer ONLY on that context.\n"
            "3. If NO relevant context is found, clearly state that you couldn't find specific rules and answer based on general knowledge of D&D 2024.\n"
            "4. If comparing with 5e (2014) rules, clearly state this.\n"
            "5. Be specific and cite rules when possible (using the Source and Page info from the context).\n"
            "6. Format your response clearly using Markdown (headings, lists, bold text, etc.) for readability.\n\n"
        )
        if context_text_for_prompt:
            system_message += (
                "Use the following official 2024 D&D rules context to answer the question. "
                "Prioritize this information:\n\n---\n"
                f"{context_text_for_prompt}"
                "---\n\nAnswer the user's question based *only* on the context above:"
            )
        else:
            system_message += (
                "WARNING: No specific rule context was found for this query. "
                "Answer based on your general knowledge of D&D 2024 rules, "
                "but explicitly state that the information is not from the provided source materials.\n"
            )
        end_time_prompt = time.perf_counter()
        logger.info(f"Prompt preparation completed in {end_time_prompt - start_time_prompt:.4f}s.")

        # Log the context being sent for debugging, especially for semantic
        if effective_store_type == "semantic":
            logger.info(f"Context being sent to LLM for semantic query:\n---\n{context_text_for_prompt[:1000]}...\n---")
        elif not context_parts: 
             logger.info("No context parts found, sending prompt without specific context.")

        # --- Step 4: Yield Initial Metadata --- 
        start_time_yield_meta = time.perf_counter()
        initial_metadata = {
            "type": "metadata",
            "sources": sources_for_metadata,
            "using_context": bool(context_parts),
            "llm_provider": llm_client.get_provider_name(),
            "llm_model": current_model_name,
            "store_type": effective_store_type
        }
        yield f"event: metadata\ndata: {json.dumps(initial_metadata)}\n\n"
        end_time_yield_meta = time.perf_counter()
        logger.info(f"Yielded initial metadata in {end_time_yield_meta - start_time_yield_meta:.4f}s.")

        # --- Step 5: Stream LLM Response --- 
        logger.info("Step 5: Streaming response from LLM...")
        start_time_llm_stream = time.perf_counter()
        stream_generator = llm_client.generate_response(
            prompt=prompt,
            system_message=system_message,
            temperature=temperature, 
            max_tokens=max_tokens,
            stream=True
        )
        
        text_chunk_count = 0
        for text_chunk in stream_generator:
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\n\n"
            text_chunk_count += 1
        
        end_time_llm_stream = time.perf_counter()
        logger.info(f"LLM stream finished in {end_time_llm_stream - start_time_llm_stream:.4f}s. Yielded {text_chunk_count} chunks.")
        
        # --- Step 5.5: Fetch and Yield Link Data --- 
        link_data = {}
        if sources_for_metadata: # Only fetch if context was used
            unique_source_keys = list({s['s3_key'] for s in sources_for_metadata if s.get('s3_key')})
            logger.info(f"Unique source keys found in metadata: {unique_source_keys}")
            if unique_source_keys:
                logger.info(f"Fetching link data for {len(unique_source_keys)} source(s)...")
                start_time_links = time.perf_counter()
                link_data = _get_link_data_for_sources(unique_source_keys)
                end_time_links = time.perf_counter()
                if link_data:
                    logger.info(f"Found {len(link_data)} unique link texts. Yielding link data in {end_time_links - start_time_links:.4f}s.")
                    # Use event type 'links' to distinguish from text chunks
                    yield f"event: links\ndata: {json.dumps({'type': 'links', 'links': link_data})}\n\n"
                else:
                    logger.info(f"No link data found for sources in {end_time_links - start_time_links:.4f}s.")
            else:
                logger.info("No valid S3 keys found in sources, skipping link data fetch.")
        else:
             logger.info("No context used, skipping link data fetch.")

        # --- Step 6: Yield Done Event --- 
        yield f"event: done\ndata: {json.dumps({'success': True})}\n\n"
        logger.info("Yielded done event.")

    except Exception as e:
        error_msg = f"Error during query processing: {e}"
        logger.error(error_msg, exc_info=True)
        try:
            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
        except Exception as yield_err:
            logger.error(f"Failed to yield error: {yield_err}")
    
    finally:
        end_time_total = time.perf_counter()
        total_time = end_time_total - start_time_total
        logger.info(f"Total request processing time: {total_time:.4f} seconds")