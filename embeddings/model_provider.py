import os
from sentence_transformers import SentenceTransformer
# Explicitly import the top-level package first, then the module
import llm_providers 
# Correct the import to match the filename openai.py and class name OpenAILLM
from llm_providers.openai import OpenAILLM 
import logging
from typing import List
import time

logger = logging.getLogger(__name__)

# --- Model Configuration ---
# Store models globally after loading once
_embedding_models = {}

# Define model names explicitly or get from env (as fallback)
# For consistency, using names from README/previous context
STANDARD_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
SEMANTIC_EMBEDDING_MODEL_NAME = "text-embedding-3-small" # Used by OpenAILLM
HAYSTACK_EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

def _load_standard_model():
    """Loads the Sentence Transformer model for standard embeddings."""
    global _embedding_models
    if "standard" not in _embedding_models:
        try:
            logger.info(f"Loading standard embedding model: {STANDARD_EMBEDDING_MODEL_NAME}")
            _embedding_models["standard"] = SentenceTransformer(STANDARD_EMBEDDING_MODEL_NAME)
            logger.info("Standard embedding model loaded.")
        except Exception as e:
            logger.error(f"Failed to load standard embedding model: {e}", exc_info=True)
            _embedding_models["standard"] = None
    return _embedding_models["standard"]

def _load_semantic_model():
    """Loads the client responsible for semantic embeddings (currently OpenAI)."""
    global _embedding_models
    if "semantic" not in _embedding_models:
        try:
            logger.info(f"Initializing semantic embedding client (OpenAI: {SEMANTIC_EMBEDDING_MODEL_NAME})")
            # Instantiate the correct class: OpenAILLM
            _embedding_models["semantic"] = OpenAILLM(model_name=SEMANTIC_EMBEDDING_MODEL_NAME)
            logger.info("Semantic embedding client initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize semantic embedding client: {e}", exc_info=True)
            _embedding_models["semantic"] = None
    return _embedding_models["semantic"]

def _load_haystack_model():
    """Loads the Sentence Transformer model for haystack embeddings."""
    global _embedding_models
    if "haystack" not in _embedding_models:
        try:
            logger.info(f"Loading haystack embedding model: {HAYSTACK_EMBEDDING_MODEL_NAME}")
            _embedding_models["haystack"] = SentenceTransformer(HAYSTACK_EMBEDDING_MODEL_NAME)
            logger.info("Haystack embedding model loaded.")
        except Exception as e:
            logger.error(f"Failed to load haystack embedding model: {e}", exc_info=True)
            _embedding_models["haystack"] = None
    return _embedding_models["haystack"]

def get_embedding_model(store_type: str):
    """Factory function to get the appropriate embedding model/client."""
    if store_type == "standard":
        return _load_standard_model()
    elif store_type == "semantic":
        return _load_semantic_model()
    elif store_type in ["haystack", "haystack-qdrant", "haystack-memory"]:
        return _load_haystack_model()
    else:
        logger.error(f"Unsupported store_type for embeddings: {store_type}")
        raise ValueError(f"Unsupported store_type for embeddings: {store_type}")

def embed_query(query: str, store_type: str) -> list[float]:
    """Embeds a single query using the model appropriate for the store type."""
    model_or_client = get_embedding_model(store_type)
    if model_or_client is None:
        raise RuntimeError(f"Embedding model/client for {store_type} could not be loaded.")

    logger.info(f"Embedding query for {store_type} store: '{query[:50]}...'")
    if store_type == "standard":
        embedding = model_or_client.encode(query).tolist()
    elif store_type == "semantic":
        try:
            embedding = model_or_client.get_embedding(query) 
        except AttributeError:
             logger.error(f"The configured OpenAILLM client does not have a 'get_embedding' method.")
             raise NotImplementedError("Semantic embedding requires the client to have a 'get_embedding' method.")
        except Exception as e:
            logger.error(f"Error getting semantic embedding for query: {e}", exc_info=True)
            raise
    elif store_type in ["haystack", "haystack-qdrant", "haystack-memory"]:
        embedding = model_or_client.encode(query).tolist()
    else:
        raise ValueError(f"Unsupported store_type: {store_type}")
        
    logger.info(f"Generated {store_type} embedding vector of dimension {len(embedding)}")
    return embedding

def embed_documents(texts: List[str], store_type: str) -> List[list[float]]:
    """Embeds a batch of documents using the model appropriate for the store type."""
    if not texts:
        return []
        
    model_or_client = get_embedding_model(store_type)
    if model_or_client is None:
        raise RuntimeError(f"Embedding model/client for {store_type} could not be loaded.")

    logger.info(f"Embedding batch of {len(texts)} documents for store_type '{store_type}'")
    embeddings = []
    start_time = time.time()

    if store_type in ["standard", "haystack", "haystack-qdrant", "haystack-memory"]:
        # SentenceTransformer encode can handle lists directly and efficiently
        embeddings = model_or_client.encode(texts, show_progress_bar=True).tolist()
    elif store_type == "semantic":
        # OpenAI API might need batching or sequential calls depending on client implementation
        # Assuming OpenAILLM's get_embedding handles single texts, we loop. 
        # TODO: Potentially optimize OpenAILLM to handle batches if the underlying API supports it well.
        batch_size = 50 # Arbitrary batch size for logging
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            try:
                # Assuming get_embedding can handle a list or we adapt OpenAILLM later
                # For now, let's assume it takes one string at a time for simplicity here
                # If OpenAILLM needs modification, that's a separate step.
                for text in batch_texts:
                    embeddings.append(model_or_client.get_embedding(text))
                    
                if i % (batch_size * 5) == 0: # Log progress periodically
                    logger.info(f"Processed {i+len(batch_texts)}/{len(texts)} semantic embeddings...")

            except AttributeError:
                 logger.error("The configured OpenAILLM client does not have a 'get_embedding' method.")
                 raise NotImplementedError("Semantic embedding requires the client to have a 'get_embedding' method.")
            except Exception as e:
                logger.error(f"Error getting semantic embeddings batch (starting index {i}): {e}", exc_info=True)
                # Decide on error handling: fail all, skip batch, return partial? For now, raise.
                raise
    else:
        raise ValueError(f"Unsupported store_type: {store_type}")
        
    end_time = time.time()
    logger.info(f"Generated {len(embeddings)} {store_type} embedding vectors in {end_time - start_time:.2f} seconds")
    return embeddings

# Optional: Pre-load models on startup if desired, though lazy loading might be better
# _load_standard_model()
# _load_semantic_model() 