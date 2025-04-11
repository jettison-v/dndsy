import os
# Remove direct OpenAI import if no longer needed directly
# from openai import OpenAI 
from vector_store import get_vector_store
import logging
import tiktoken # Keep for token counting (OpenAI specific for now)
from dotenv import load_dotenv
import time # Import time module
import json # Import json for encoding metadata
from typing import Generator

from llm_providers import get_llm_client # Import the factory function
# Import the new embed_query function
from embeddings.model_provider import embed_query

load_dotenv() # Ensure environment variables are loaded

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize LLM client using the factory
# This reads LLM_PROVIDER and LLM_MODEL_NAME from env vars
try:
    llm_client = get_llm_client()
except Exception as e:
    logger.critical(f"Failed to initialize LLM client on startup: {e}")
    # Decide how to handle this - exit, use a fallback, etc.
    # For now, we might let subsequent calls fail.
    llm_client = None 

# Initialize default vector store
default_store_type = os.getenv("DEFAULT_VECTOR_STORE", "semantic")
# We no longer need to initialize the default store here, 
# as get_relevant_context will get the appropriate one.
# default_vector_store = get_vector_store(default_store_type)

def num_tokens_from_string(string: str, model: str) -> int:
    """Returns the number of tokens in a text string."""
    # WARNING: This uses tiktoken and is specific to OpenAI models.
    # A truly agnostic solution would need a different approach.
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        logger.warning(f"Tiktoken model {model} not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens

def truncate_text(text: str, max_tokens: int, model: str) -> str:
    """Truncate text to fit within token limit."""
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
    Embed the query, search the vector store, and prepare formatted context.
    (Renamed from get_relevant_context)
    
    Args:
        query: The search query string.
        model: The LLM model name (for token handling).
        limit: Maximum number of results to return.
        store_type: Vector store type to use ("standard" or "semantic").
    """
    if store_type is None:
        store_type = default_store_type
        
    # 1. Get the appropriate vector store client
    vector_store = get_vector_store(store_type)
    if vector_store is None:
         logger.error(f"Could not get vector store for type: {store_type}")
         return []

    try:
        # 2. Embed the query using the external function
        logger.info(f"Embedding query for {store_type} store: '{query[:50]}...'")
        query_vector = embed_query(query, store_type)
        
        # 3. Search the vector store using the embedding vector
        logger.info(f"Searching {store_type} store with query: {query}")
        # Pass vector and potentially original query (for semantic store's hybrid search)
        if store_type == "semantic":
             results = vector_store.search(query_vector=query_vector, query=query, limit=limit)
        else: # Standard store only needs the vector
             results = vector_store.search(query_vector=query_vector, limit=limit)
             
        logger.info(f"Found {len(results)} results from vector store")
        
        if not results:
            logger.warning("No results found in vector store")
            return []
            
        # 4. Process and format results (logic mostly unchanged from original get_relevant_context)
        context_parts = []
        total_tokens = 0
        max_tokens_per_result = 1000
        
        for idx, result in enumerate(results):
            metadata = result['metadata']
            source_key = metadata.get('source', 'unknown')
            source_filename = source_key.split('/')[-1]
            source_display_name = source_filename.replace('.pdf', '')
            
            text = result['text'].strip()
            score = result.get('score', 0)
            page = metadata.get('page', 'unknown')
            image_url = metadata.get('image_url', None)
            total_pages = metadata.get('total_pages', None)
            source_dir = metadata.get('source_dir', None)
            original_s3_key = metadata.get('source')
            
            section = metadata.get('section', None)
            subsection = metadata.get('subsection', None)
            heading_path = metadata.get('heading_path', None)
            context_info = None
            if heading_path:
                context_info = heading_path
            elif section:
                context_info = f"{section}{f' > {subsection}' if subsection else ''}"
            
            for level in range(6, 0, -1):
                heading_key = f"h{level}"
                if heading_key in metadata and metadata[heading_key]:
                    if not context_info:
                        context_info = metadata[heading_key]
                    break
            
            chunk_index = metadata.get('chunk_index', None)
            position = metadata.get('position', None) # Position might be relevant for semantic chunks?
            
            logger.info(f"Result {idx + 1} from {source_filename} (page {page}) with score {score:.4f}")
            if context_info:
                logger.info(f"  Context: {context_info}")
            
            context_piece = {
                'text': text,
                'source': source_display_name,
                'page': page,
                'image_url': image_url,
                'total_pages': total_pages,
                'source_dir': source_dir, 
                'score': score,
                'original_s3_key': original_s3_key,
                'chunk_info': context_info if context_info else (
                              f"Position: {position}" if position else (
                              f"#{chunk_index}" if chunk_index is not None else None))
            }
            
            # Token limiting (unchanged)
            tokens = num_tokens_from_string(text, model=model)
            if tokens > max_tokens_per_result:
                context_piece['text'] = truncate_text(text, max_tokens=max_tokens_per_result, model=model)
                tokens = num_tokens_from_string(context_piece['text'], model=model)
            
            if total_tokens + tokens <= 4000:
                context_parts.append(context_piece)
                total_tokens += tokens
                logger.info(f"Added context from {source_display_name} (page {page}) ({tokens} tokens). Total context tokens: {total_tokens}")
            else:
                logger.info(f"Skipping remaining results due to token limit ({total_tokens} + {tokens} > 4000)")
                break
        
        return context_parts
    except Exception as e:
        logger.error(f"Error retrieving context: {e}", exc_info=True)
        return []

def ask_dndsy(prompt: str, store_type: str = None) -> Generator[str, None, None]:
    """
    Processes a query using RAG and streams the response using the configured LLM provider.
    Yields JSON-encoded metadata first, then text chunks.
    
    Args:
        prompt: The user query
        store_type: Vector store type to use ("standard" or "semantic"). Uses default if None.
    """
    if not llm_client:
         error_msg = "LLM client failed to initialize. Cannot process query."
         logger.error(error_msg)
         yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
         return

    start_time_total = time.perf_counter()
    current_model_name = llm_client.get_model_name()
    logger.info(f"Using LLM model: {current_model_name}")
    context_parts = []
    sources_for_metadata = []
    error_occurred = False
    
    # Determine store type to use
    effective_store_type = store_type or default_store_type

    try:
        # --- Retrieve and Prepare Context ---
        logger.info("Starting context retrieval and preparation...")
        start_time_rag = time.perf_counter()
        # Call the renamed and refactored context retrieval function
        context_parts = _retrieve_and_prepare_context(
            query=prompt, 
            model=current_model_name, 
            store_type=effective_store_type
        )
        end_time_rag = time.perf_counter()
        logger.info(f"Context retrieval completed in {end_time_rag - start_time_rag:.4f} seconds. Found {len(context_parts)} parts.")

        # --- Yield Status Update (unchanged) ---
        start_time_yield_status = time.perf_counter()
        yield f"event: status\ndata: {json.dumps({'status': 'Consulting LLM'})}\n\n"
        end_time_yield_status = time.perf_counter()
        logger.info(f"Yielded status update to client in {end_time_yield_status - start_time_yield_status:.4f} seconds.")

        # --- Prepare Prompt & Initial Metadata (unchanged logic) ---
        logger.info("Starting prompt preparation...")
        start_time_prompt = time.perf_counter()
        context_text_for_prompt = ""
        if context_parts:
            for part in context_parts:
                display_text = f"{part['source']} (page {part['page']})"
                if part.get('chunk_info'):
                    display_text += f" - {part['chunk_info']}"
                
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
                    logger.warning(f"Missing 'original_s3_key' for context part: {part['source']} page {part['page']}")
                    
                context_text_for_prompt += f"Source: {part['source']} - Page {part['page']}"
                if part.get('chunk_info'):
                    context_text_for_prompt += f" - {part['chunk_info']}"
                context_text_for_prompt += f"\nContent:\n{part['text']}\n\n"
                
            logger.info(f"Prepared sources for metadata: {len(sources_for_metadata)} items")
        
        system_message = (
            "You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. "
            "Follow these guidelines:\n"
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
        logger.info(f"Prompt preparation completed in {end_time_prompt - start_time_prompt:.4f} seconds.")

        # --- Yield Initial Metadata (unchanged) ---
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
        logger.info(f"Yielded initial metadata to client in {end_time_yield_meta - start_time_yield_meta:.4f} seconds.")

        # --- LLM API Stream (unchanged) ---
        logger.info("Starting LLM stream initiation...")
        start_time_llm_init = time.perf_counter()
        stream_generator = llm_client.generate_response(
            prompt=prompt,
            system_message=system_message,
            temperature=0.3, 
            max_tokens=1500,
            stream=True
        )
        end_time_llm_init = time.perf_counter()
        logger.info(f"LLM stream initiated in {end_time_llm_init - start_time_llm_init:.4f} seconds.")

        logger.info("Iterating through LLM stream...")
        start_time_llm_stream = time.perf_counter()
        text_chunk_count = 0
        for text_chunk in stream_generator:
            start_time_yield_chunk = time.perf_counter()
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\n\n"
            end_time_yield_chunk = time.perf_counter()
            logger.debug(f"Yielded chunk {text_chunk_count + 1} in {end_time_yield_chunk - start_time_yield_chunk:.4f} seconds.")
            text_chunk_count += 1

        end_time_llm_stream = time.perf_counter()
        logger.info(f"LLM stream iteration finished after {end_time_llm_stream - start_time_llm_stream:.4f} seconds. Yielded {text_chunk_count} chunks.")

        # --- Yield Done Event (unchanged) ---
        start_time_yield_done = time.perf_counter()
        yield f"event: done\ndata: {json.dumps({'success': True})}\n\n"
        end_time_yield_done = time.perf_counter()
        logger.info(f"Yielded done event in {end_time_yield_done - start_time_yield_done:.4f} seconds.")

    except Exception as e:
        error_occurred = True
        error_msg = f"Error during query processing: {e}"
        logger.error(error_msg, exc_info=True)
        try:
            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
        except Exception as yield_err:
            logger.error(f"Failed to yield error: {yield_err}")
    
    finally:
        end_time_total = time.perf_counter()
        total_time = end_time_total - start_time_total
        logger.info(f"Total processing time: {total_time:.4f} seconds")