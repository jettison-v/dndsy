# config.py
import os
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)

# --- Global Configuration Dictionary ---
# This dictionary stores all configurable parameters with sensible defaults
# It will be used by the admin panel and the various components
# Values here can be overridden via the admin panel
app_config = {
    # LLM Configuration
    "llm_model": os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"),
    "llm_temperature": 0.3,
    "llm_max_output_tokens": 1500,
    
    # Vector Store Configuration
    "vector_store_type": os.environ.get("DEFAULT_VECTOR_STORE", "semantic"),
    
    # Semantic Store Reranking Weights
    "rerank_alpha": 0.5,  # Dense vector weight (was 0.7 previously)
    "rerank_beta": 0.3,   # Sparse BM25 weight
    "rerank_gamma": 0.2,  # Keyword boost weight
    
    # Retrieval Parameters
    "retrieval_k": 5,     # Final results count before token limiting
    "retrieval_fetch_multiplier": 3,  # Multiplier for initial candidate fetching (e.g., 3 * k)
    
    # Context Token Limits
    "context_max_tokens_per_result": 1000,
    "context_max_total_tokens": 4000,
    
    # System Prompt
    "system_prompt": """You are a Dungeons & Dragons assistant focused on the 2024 (5.5e) rules. Follow these guidelines:

1. ALWAYS prioritize using the provided 2024 rules context when available.
2. If context is provided, base your answer ONLY on that context.
3. If NO relevant context is found, clearly state that you couldn't find specific rules and answer based on general knowledge of D&D 2024.
4. If comparing with 5e (2014) rules, clearly state this.
5. Be specific and cite rules when possible (using the Source and Page info from the context).
6. Format your response clearly using Markdown (headings, lists, bold text, etc.) for readability."""
}

# Get default store type from environment
default_store_type = os.getenv("DEFAULT_VECTOR_STORE", "semantic")

# Helper function to validate and update configuration
def update_app_config(new_config):
    """
    Updates the app_config dictionary with new values, applying validation rules.
    
    Args:
        new_config: Dictionary containing new configuration values
        
    Returns:
        (success, message) tuple
    """
    global app_config, default_store_type
    
    try:
        # Validate and update numeric values with bounds checking
        if "llm_temperature" in new_config:
            app_config["llm_temperature"] = max(0.0, min(2.0, float(new_config["llm_temperature"])))
            
        if "llm_max_output_tokens" in new_config:
            app_config["llm_max_output_tokens"] = max(100, min(4000, int(new_config["llm_max_output_tokens"])))
            
        if "rerank_alpha" in new_config:
            app_config["rerank_alpha"] = max(0.0, min(1.0, float(new_config["rerank_alpha"])))
            
        if "rerank_beta" in new_config:
            app_config["rerank_beta"] = max(0.0, min(1.0, float(new_config["rerank_beta"])))
            
        if "rerank_gamma" in new_config:
            app_config["rerank_gamma"] = max(0.0, min(1.0, float(new_config["rerank_gamma"])))
            
        if "retrieval_k" in new_config:
            app_config["retrieval_k"] = max(1, min(20, int(new_config["retrieval_k"])))
            
        if "retrieval_fetch_multiplier" in new_config:
            app_config["retrieval_fetch_multiplier"] = max(1, min(10, int(new_config["retrieval_fetch_multiplier"])))
            
        if "context_max_tokens_per_result" in new_config:
            app_config["context_max_tokens_per_result"] = max(100, min(4000, int(new_config["context_max_tokens_per_result"])))
            
        if "context_max_total_tokens" in new_config:
            app_config["context_max_total_tokens"] = max(1000, min(16000, int(new_config["context_max_total_tokens"])))
            
        # Update string values directly
        for key in ["llm_model", "vector_store_type", "system_prompt"]:
            if key in new_config:
                app_config[key] = str(new_config[key])
        
        # If LLM model changed, reinitialize the client
        if "llm_model" in new_config and new_config["llm_model"] != os.environ.get("LLM_MODEL_NAME"):
            os.environ["LLM_MODEL_NAME"] = new_config["llm_model"]
            # Import here to avoid circular imports
            from llm import reinitialize_llm_client
            reinitialize_llm_client()
            logger.info(f"LLM model changed to: {new_config['llm_model']}, client reinitialized")
            
        # Optional: If vector store type changed, update the default
        if "vector_store_type" in new_config:
            default_store_type = new_config["vector_store_type"]
            
        logger.info(f"Configuration updated successfully: {app_config}")
        return True, "Configuration updated successfully"
        
    except ValueError as e:
        logger.error(f"Invalid value type during config update: {e}")
        return False, f"Invalid value type provided: {e}"
        
    except Exception as e:
        logger.error(f"Error updating config: {e}", exc_info=True)
        return False, f"An unexpected error occurred while updating configuration: {str(e)}" 