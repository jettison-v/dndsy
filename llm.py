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
default_store_type = os.getenv("DEFAULT_VECTOR_STORE", "standard")
default_vector_store = get_vector_store(default_store_type)

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

def get_relevant_context(query: str, model: str, limit: int = 5, store_type: str = None) -> list[dict]:
    """
    Search the vector store for relevant context.
    
    Args:
        query: The search query
        model: The LLM model name (for token handling)
        limit: Maximum number of results to return
        store_type: Vector store type to use ("standard" or "semantic")
    """
    # Get the appropriate vector store
    vector_store = get_vector_store(store_type)
    
    try:
        logger.info(f"Searching for context with query: {query} using store type: {store_type}")
        results = vector_store.search(query, limit=limit)
        logger.info(f"Found {len(results)} results from vector store")
        
        if not results:
            logger.warning("No results found in vector store")
            return []
        
        context_parts = []
        total_tokens = 0
        max_tokens_per_result = 1000
        
        for idx, result in enumerate(results):
            metadata = result['metadata']
            # Clean up source filename extraction
            source_key = metadata.get('source', 'unknown') # e.g., source-pdfs/MyBook.pdf
            source_filename = source_key.split('/')[-1]
            source_display_name = source_filename.replace('.pdf', '')
            
            text = result['text'].strip()
            score = result.get('score', 0)
            page = metadata.get('page', 'unknown')
            image_url = metadata.get('image_url', None)
            total_pages = metadata.get('total_pages', None)
            source_dir = metadata.get('source_dir', None) # Cleaned path for image dir
            original_s3_key = metadata.get('source') # The original S3 key
            
            # Extract heading context for better display
            section = metadata.get('section', None)
            subsection = metadata.get('subsection', None)
            heading_path = metadata.get('heading_path', None)
            
            # Build a context description based on available heading information
            context_info = None
            
            if heading_path:
                # Use the complete heading path if available
                context_info = heading_path
            elif section:
                # Use section and subsection if available
                if subsection:
                    context_info = f"{section} > {subsection}"
                else:
                    context_info = section
            
            # Get the most specific heading level available
            for level in range(6, 0, -1):
                heading_key = f"h{level}"
                if heading_key in metadata and metadata[heading_key]:
                    if not context_info:
                        context_info = metadata[heading_key]
                    break
            
            # Add specific position information from chunk metadata
            chunk_index = metadata.get('chunk_index', None)
            position = metadata.get('position', None)
            
            logger.info(f"Result {idx + 1} from {source_filename} (page {page}) with score {score:.4f}")
            if context_info:
                logger.info(f"  Context: {context_info}")
            
            context_piece = {
                'text': text,
                'source': source_display_name, # Use cleaned name for display
                'page': page,
                'image_url': image_url,
                'total_pages': total_pages,
                'source_dir': source_dir, 
                'score': score,
                'original_s3_key': original_s3_key, # Add the S3 key here
                'chunk_info': context_info if context_info else (
                              f"Position: {position}" if position else (
                              f"#{chunk_index}" if chunk_index is not None else None))
            }
            
            # Use tiktoken for OpenAI-specific token counting
            # TODO: Make token counting model-agnostic if needed later
            tokens = num_tokens_from_string(text, model=model)
            if tokens > max_tokens_per_result:
                context_piece['text'] = truncate_text(text, max_tokens=max_tokens_per_result, model=model)
                tokens = num_tokens_from_string(context_piece['text'], model=model)
            
            # Increased total token limit for context
            if total_tokens + tokens <= 4000: 
                context_parts.append(context_piece)
                total_tokens += tokens
                logger.info(f"Added context from {source_display_name} (page {page}) ({tokens} tokens). Total context tokens: {total_tokens}")
            else:
                logger.info(f"Skipping remaining results due to token limit ({total_tokens} + {tokens} > 4000)")
                break
        
        return context_parts
    except Exception as e:
        logger.error(f"Error searching vector store: {e}", exc_info=True)
        return []

def ask_dndsy(prompt: str, store_type: str = None) -> Generator[str, None, None]:
    """
    Processes a query using RAG and streams the response using the configured LLM provider.
    Yields JSON-encoded metadata first, then text chunks.
    
    Args:
        prompt: The user query
        store_type: Vector store type to use ("standard" or "semantic")
    """
    if not llm_client:
         error_msg = "LLM client failed to initialize. Cannot process query."
         logger.error(error_msg)
         # Yield an error event for SSE
         yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
         return # Stop generation

    start_time_total = time.perf_counter()
    current_model_name = llm_client.get_model_name()
    logger.info(f"Using LLM model: {current_model_name}")
    context_parts = []
    sources_for_metadata = [] # Changed from sources_for_display
    error_occurred = False

    try:
        # --- Vector Store Search ---
        logger.info("Starting RAG context search...") # Log start
        start_time_rag = time.perf_counter()
        context_parts = get_relevant_context(prompt, model=current_model_name, store_type=store_type)
        end_time_rag = time.perf_counter()
        logger.info(f"Context search completed in {end_time_rag - start_time_rag:.4f} seconds. Found {len(context_parts)} parts.") # Log end + result

        # --- Yield Status Update ---
        start_time_yield_status = time.perf_counter() # Log start
        yield f"event: status\\ndata: {json.dumps({'status': 'Consulting LLM'})}\\n\\n"
        end_time_yield_status = time.perf_counter() # Log end
        logger.info(f"Yielded status update to client in {end_time_yield_status - start_time_yield_status:.4f} seconds.")

        # --- Prepare Prompt & Initial Metadata ---
        logger.info("Starting prompt preparation...") # Log start
        start_time_prompt = time.perf_counter()
        context_text_for_prompt = ""
        if context_parts:
            for part in context_parts:
                # Use the cleaned source name and page for display
                display_text = f"{part['source']} (page {part['page']})"
                if part.get('chunk_info'):
                    display_text += f" - {part['chunk_info']}"
                
                # Get the original S3 key stored in the context part's metadata
                # We need to ensure get_relevant_context populates this correctly
                original_s3_key = part.get('original_s3_key') 
                if original_s3_key:
                    sources_for_metadata.append({
                        'display': display_text,
                        's3_key': original_s3_key,
                        'page': part['page'], # Include page for easier access on frontend
                        'score': part.get('score'), # Add the score here
                        'chunk_info': part.get('chunk_info')
                    })
                else:
                    logger.warning(f"Missing 'original_s3_key' for context part: {part['source']} page {part['page']}")
                    
                # Add source info to the context text for the LLM    
                context_text_for_prompt += f"Source: {part['source']} - Page {part['page']}"
                if part.get('chunk_info'):
                    context_text_for_prompt += f" - {part['chunk_info']}"
                context_text_for_prompt += f"\nContent:\n{part['text']}\n\n"
                
            logger.info(f"Prepared sources for metadata: {len(sources_for_metadata)} items")
        
        # Prepare the system message (could be customized based on provider later)
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
        logger.info(f"Prompt preparation completed in {end_time_prompt - start_time_prompt:.4f} seconds.") # Log end

        # --- Yield Initial Metadata ---
        start_time_yield_meta = time.perf_counter() # Log start
        initial_metadata = {
            "type": "metadata",
            "sources": sources_for_metadata, # Use the list of objects
            "using_context": bool(context_parts),
            "llm_provider": llm_client.get_provider_name(),
            "llm_model": current_model_name,
            "store_type": store_type or default_store_type
        }
        yield f"event: metadata\\ndata: {json.dumps(initial_metadata)}\\n\\n"
        end_time_yield_meta = time.perf_counter() # Log end
        logger.info(f"Yielded initial metadata to client in {end_time_yield_meta - start_time_yield_meta:.4f} seconds.")

        # --- LLM API Stream ---
        logger.info("Starting LLM stream initiation...") # Log start
        start_time_llm_init = time.perf_counter()
        stream_generator = llm_client.generate_response(
            prompt=prompt,
            system_message=system_message,
            temperature=0.3, 
            max_tokens=1500, # Increased max_tokens
            stream=True
        )
        end_time_llm_init = time.perf_counter() # Log end
        logger.info(f"LLM stream initiated in {end_time_llm_init - start_time_llm_init:.4f} seconds.")

        # Yield text chunks as they arrive
        logger.info("Iterating through LLM stream...") # Log start
        start_time_llm_stream = time.perf_counter()
        text_chunk_count = 0
        for text_chunk in stream_generator:
            start_time_yield_chunk = time.perf_counter() # Log start
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\\n\\n"
            end_time_yield_chunk = time.perf_counter() # Log end
            logger.debug(f"Yielded chunk {text_chunk_count + 1} in {end_time_yield_chunk - start_time_yield_chunk:.4f} seconds.") # Use debug for potentially noisy logs
            text_chunk_count += 1

        end_time_llm_stream = time.perf_counter() # Log end
        logger.info(f"LLM stream iteration finished after {end_time_llm_stream - start_time_llm_stream:.4f} seconds. Yielded {text_chunk_count} chunks.")

        # Send a proper close event
        start_time_yield_done = time.perf_counter() # Log start
        yield f"event: done\\ndata: {json.dumps({'success': True})}\\n\\n"
        end_time_yield_done = time.perf_counter() # Log end
        logger.info(f"Yielded done event in {end_time_yield_done - start_time_yield_done:.4f} seconds.")

    except Exception as e:
        error_occurred = True
        error_msg = f"Error during query processing: {e}"
        logger.error(error_msg, exc_info=True)
        # Yield an error event for SSE
        try:
            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
        except Exception as yield_err:
            logger.error(f"Failed to yield error: {yield_err}")
    
    finally:
        # Final timing info
        end_time_total = time.perf_counter()
        total_time = end_time_total - start_time_total
        logger.info(f"Total processing time: {total_time:.4f} seconds")