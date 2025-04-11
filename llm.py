import os
# Remove direct OpenAI import if no longer needed directly
# from openai import OpenAI 
from vector_store import get_vector_store
import logging
import tiktoken # For token counting (OpenAI specific for now)
from dotenv import load_dotenv
import time
import json
from typing import Generator

from llm_providers import get_llm_client # Import the factory function
from embeddings.model_provider import embed_query # Import query embedding function

load_dotenv(override=True) # Load .env, potentially overriding system vars

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def _retrieve_and_prepare_context(query: str, model: str, limit: int = 5, store_type: str = None) -> list[dict]:
    """
    Orchestrates context retrieval: embeds query, searches store, formats results.
    
    Args:
        query: The user's search query string.
        model: The LLM model name (used for token counting/limits).
        limit: Max number of context results to return.
        store_type: Vector store type ("standard" or "semantic"). Uses default if None.
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
             results = vector_store.search(query_vector=query_vector, query=query, limit=limit)
        else: 
             # Standard store uses simple vector search
             results = vector_store.search(query_vector=query_vector, limit=limit)
             
        logger.info(f"Found {len(results)} results from vector store")
        if not results: return []
            
        # Process and format results, applying token limits
        context_parts = []
        total_tokens = 0
        # Limit tokens per individual context piece to avoid overly long items
        max_tokens_per_result = 1000 
        # Limit total tokens added to context (adjust as needed for LLM context window)
        max_total_context_tokens = 4000 
        
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

def ask_dndsy(prompt: str, store_type: str = None) -> Generator[str, None, None]:
    """
    Main RAG pipeline function.
    Processes a query using RAG and streams the response via SSE.
    
    Args:
        prompt: The user query.
        store_type: Vector store type ("standard" or "semantic"). Uses default if None.
        
    Yields:
        Server-Sent Events (SSE) strings containing metadata, status updates, 
        text chunks, or errors.
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

    try:
        # --- Step 1: Retrieve and Prepare Context --- 
        logger.info("Step 1: Retrieving context...")
        start_time_rag = time.perf_counter()
        context_parts = _retrieve_and_prepare_context(
            query=prompt, 
            model=current_model_name, # Pass model for token calculations
            store_type=effective_store_type
        )
        end_time_rag = time.perf_counter()
        logger.info(f"Context retrieval completed in {end_time_rag - start_time_rag:.4f}s. Found {len(context_parts)} parts.")

        # --- Step 2: Yield Status Update --- 
        yield f"event: status\ndata: {json.dumps({'status': 'Consulting LLM'})}\n\n"

        # --- Step 3: Prepare Prompt & Initial Metadata --- 
        logger.info("Step 3: Preparing LLM prompt...")
        start_time_prompt = time.perf_counter()
        context_text_for_prompt = ""
        sources_for_metadata = []
        if context_parts:
            for part in context_parts:
                # Format source display text
                display_text = f"{part['source']} (Pg {part['page']})"
                if part.get('chunk_info'): display_text += f" - {part['chunk_info']}"
                
                # Prepare metadata object for frontend
                original_s3_key = part.get('original_s3_key') 
                if original_s3_key:
                    sources_for_metadata.append({
                        'display': display_text,
                        's3_key': original_s3_key,
                        'page': part['page'],
                        'score': part.get('score'),
                        'chunk_info': part.get('chunk_info') # Keep raw context info
                    })
                else: logger.warning(f"Missing 'original_s3_key' for context part: {part}")
                    
                # Append context to the text block for the LLM prompt
                context_text_for_prompt += f"Source: {display_text}\nContent:\n{part['text']}\n\n" # Use display_text here too
                
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
            temperature=0.3, 
            max_tokens=1500,
            stream=True
        )
        
        text_chunk_count = 0
        for text_chunk in stream_generator:
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\n\n"
            text_chunk_count += 1
        
        end_time_llm_stream = time.perf_counter()
        logger.info(f"LLM stream finished in {end_time_llm_stream - start_time_llm_stream:.4f}s. Yielded {text_chunk_count} chunks.")

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