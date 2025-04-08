import os
# Remove direct OpenAI import if no longer needed directly
# from openai import OpenAI 
from vector_store.qdrant_store import QdrantStore
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

# Initialize vector store
vector_store = QdrantStore()

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

def get_relevant_context(query: str, model: str, limit: int = 5) -> list[dict]:
    """Search the vector store for relevant context."""
    # NOTE: Passing 'model' here is currently only used for tiktoken calculations.
    # The search itself is model-agnostic (uses embeddings from SentenceTransformer).
    try:
        logger.info(f"Searching for context with query: {query}")
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
            
            logger.info(f"Result {idx + 1} from {source_filename} (page {page}) with score {score:.4f}")
            
            context_piece = {
                'text': text,
                'source': source_display_name, # Use cleaned name for display
                'page': page,
                'image_url': image_url,
                'total_pages': total_pages,
                'source_dir': source_dir, 
                'score': score
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

def ask_dndsy(prompt: str) -> Generator[str, None, None]:
    """
    Processes a query using RAG and streams the response using the configured LLM provider.
    Yields JSON-encoded metadata first, then text chunks.
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
    sources_for_display = []
    error_occurred = False

    try:
        # --- Vector Store Search --- 
        start_time_rag = time.perf_counter()
        context_parts = get_relevant_context(prompt, model=current_model_name)
        end_time_rag = time.perf_counter()
        logger.info(f"Context search took {end_time_rag - start_time_rag:.4f} seconds.")
        logger.info(f"Context found: {bool(context_parts)}")
        
        # --- Yield Status Update --- 
        yield f"event: status\ndata: {json.dumps({'status': 'Consulting LLM'})}\n\n"
        logger.info("Yielded status update to client.")

        # --- Prepare Prompt & Initial Metadata --- 
        start_time_prompt = time.perf_counter()
        context_text_for_prompt = ""
        if context_parts:
            for part in context_parts:
                # Use the cleaned source name and page for display
                source_id = f"{part['source']} (page {part['page']})"
                if source_id not in sources_for_display:
                    sources_for_display.append(source_id)
                # Add source info to the context text for the LLM    
                context_text_for_prompt += f"Source: {part['source']} - Page {part['page']}\n"
                context_text_for_prompt += f"Content:\n{part['text']}\n\n"
                
            logger.info(f"Formatted context with sources: {sources_for_display}")
        
        # Prepare the system message (could be customized based on provider later)
        system_message = (
            "You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. "
            "Follow these guidelines:\n"
            "1. ALWAYS prioritize using the provided 2024 rules context when available.\n"
            "2. If context is provided, base your answer ONLY on that context.\n"
            "3. If NO relevant context is found, clearly state that you couldn't find specific rules and answer based on general knowledge of D&D 2024.\n"
            "4. If comparing with 5e (2014) rules, clearly state this.\n"
            "5. Be specific and cite rules when possible (using the Source and Page info from the context).\n"
            "6. Keep responses clear, concise, and well-formatted, using markdown where appropriate.\n\n"
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
        logger.info(f"Prompt preparation took {end_time_prompt - start_time_prompt:.4f} seconds.")

        # --- Yield Initial Metadata --- 
        initial_metadata = {
            "type": "metadata",
            "sources": sources_for_display,
            "using_context": bool(context_parts),
            "context_parts": context_parts,
            "llm_provider": llm_client.get_provider_name(),
            "llm_model": current_model_name
        }
        yield f"event: metadata\ndata: {json.dumps(initial_metadata)}\n\n"
        logger.info("Yielded initial metadata to client.")

        # --- LLM API Stream --- 
        start_time_llm = time.perf_counter()
        logger.info("Starting LLM stream...")
        
        stream_generator = llm_client.generate_response(
            prompt=prompt,
            system_message=system_message,
            temperature=0.3, 
            max_tokens=500, # Still applies as a suggestion to the model
            stream=True
        )
        
        # Yield text chunks as they arrive
        text_chunk_count = 0
        for text_chunk in stream_generator:
            yield f"data: {json.dumps({'type': 'text', 'content': text_chunk})}\n\n"
            text_chunk_count += 1
        
        end_time_llm = time.perf_counter()
        logger.info(f"LLM stream finished after {end_time_llm - start_time_llm:.4f} seconds. Yielded {text_chunk_count} chunks.")

    except Exception as e:
        error_occurred = True
        error_msg = f"Error during query processing: {e}"
        logger.error(error_msg, exc_info=True)
        # Yield an error event for SSE
        try:
            yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
        except Exception as yield_err:
             logger.error(f"Error yielding error message: {yield_err}")
    finally:
        # --- Signal Stream End --- 
        yield f"event: end\ndata: End of stream\n\n"
        end_time_total = time.perf_counter()
        logger.info(f"Total ask_dndsy execution ({'error' if error_occurred else 'success'}) took {end_time_total - start_time_total:.4f} seconds.")