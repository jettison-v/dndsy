# config.py
import os
import json
from dotenv import load_dotenv
import logging
import boto3
from botocore.exceptions import ClientError
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(override=True)

# Environment detection
IS_DEV_ENV = os.environ.get("ENV", "production").lower() in ("dev", "development", "beta")
ENV_PREFIX = "dev__" if IS_DEV_ENV else ""

# --- S3 Bucket Name (Read Only) ---
# We no longer modify the bucket name based on environment here.
# The correct bucket (e.g., 'dev-askdnd-ai' or 'askdnd-ai') 
# should be set directly via the AWS_S3_BUCKET_NAME env var.
S3_BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME")
if not S3_BUCKET_NAME:
    logger.error("AWS_S3_BUCKET_NAME environment variable not set!")
    # Potentially raise an error or set a dummy value depending on desired behavior
    # raise ValueError("AWS_S3_BUCKET_NAME must be set")
    S3_BUCKET_NAME = "default-bucket-name-error" # Placeholder

if IS_DEV_ENV:
    logger.info(f"Development environment detected. Using ENV_PREFIX='{ENV_PREFIX}'. S3 Bucket: {S3_BUCKET_NAME}")
else:
    logger.info(f"Production environment detected. ENV_PREFIX is empty. S3 Bucket: {S3_BUCKET_NAME}")

# Google Analytics
GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", None)

# --- S3 Base Keys/Prefixes (without environment prefix) ---
BASE_S3_CONFIG_KEY = "config/app_config.json"
BASE_S3_HISTORY_KEY = "processing/pdf_process_history.json"
BASE_S3_PDF_PREFIX = "source-pdfs/"
BASE_S3_IMAGE_PREFIX = "pdf_page_images/"
BASE_S3_LINKS_PREFIX = "extracted_links/"
BASE_S3_METADATA_PREFIX = "pdf-metadata/"
# --------------------------------------------------------

# --- Helper to Get Environment-Specific S3 Keys/Prefixes ---
def get_s3_key(base_key: str) -> str:
    """Prepends the environment prefix to a base S3 key."""
    return f"{ENV_PREFIX}{base_key}"

def get_s3_prefix(base_prefix: str) -> str:
    """Prepends the environment prefix to a base S3 prefix, ensuring trailing slash."""
    prefixed = f"{ENV_PREFIX}{base_prefix}"
    # Ensure trailing slash for prefixes
    if not prefixed.endswith('/'):
        prefixed += '/'
    return prefixed

# --- Environment-Specific S3 Keys/Prefixes (used by other modules) ---
S3_CONFIG_KEY = get_s3_key(BASE_S3_CONFIG_KEY)
S3_HISTORY_KEY = get_s3_key(BASE_S3_HISTORY_KEY)
S3_PDF_PREFIX = get_s3_prefix(BASE_S3_PDF_PREFIX)
S3_IMAGE_PREFIX = get_s3_prefix(BASE_S3_IMAGE_PREFIX)
S3_LINKS_PREFIX = get_s3_prefix(BASE_S3_LINKS_PREFIX)
S3_METADATA_PREFIX = get_s3_prefix(BASE_S3_METADATA_PREFIX)
# --------------------------------------------------------------------

# --- Predefined Document Categories ---
# List of categories (with descriptions) the LLM should choose from 
# for the 'constrained_category' metadata field.
PREDEFINED_CATEGORIES = [
    {
        "name": "Core Rules", 
        "description": "Foundational gameplay mechanics, character creation, combat rules, equipment."
    },
    {
        "name": "Monsters", 
        "description": "Stat blocks, descriptions, and lore for creatures."
    },
    {
        "name": "Adventure Module", 
        "description": "Content related to specific adventures, locations, NPCs, and plot points."
    },
    {
        "name": "Legacy Rules (5e)", 
        "description": "Rules content specifically from the 2014 5th Edition rulebooks."
    },
    {
        "name": "Spells", 
        "description": "Descriptions, levels, effects, and rules for spells."
    },
    {
        "name": "Items", 
        "description": "Descriptions and rules for non-magical equipment and gear."
    },
    {
        "name": "Magic Items", 
        "description": "Descriptions, rules, and properties of magical items."
    }
    # Add more category dictionaries as needed
]

# Default configuration dictionary with sensible defaults
DEFAULT_CONFIG = {
    # LLM Configuration
    "llm_model": os.environ.get("LLM_MODEL_NAME", "gpt-4-turbo"),
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

# The actual app_config that will be used (initialized below)
app_config = {}

def get_s3_client():
    """Get an S3 client with credentials from environment variables."""
    try:
        aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
        aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')
        
        if not aws_access_key or not aws_secret_key:
            logger.warning("AWS credentials not fully configured")
            return None
        
        return boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region
        )
    except Exception as e:
        logger.error(f"Error creating S3 client: {e}", exc_info=True)
        return None

def load_config_from_s3():
    """
    Load configuration from S3, falling back to defaults if not found.
    
    Returns:
        dict: The loaded configuration dictionary
    """
    global default_store_type
    
    try:
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("S3 client not available, using default configuration")
            return DEFAULT_CONFIG.copy()
        
        # Use the environment-specific bucket name
        bucket_name = S3_BUCKET_NAME
        if not bucket_name:
            logger.warning("S3 bucket name not configured, using default configuration")
            return DEFAULT_CONFIG.copy()
        
        # Try to get the config file from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=S3_CONFIG_KEY)
        config_data = json.loads(response['Body'].read().decode('utf-8'))
        logger.info(f"Loaded configuration from S3: {bucket_name}/{S3_CONFIG_KEY}")
        
        # Set default_store_type from loaded config if available
        if "vector_store_type" in config_data:
            default_store_type = config_data["vector_store_type"]
            
        return config_data
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info(f"Config file {S3_CONFIG_KEY} not found in S3, using default configuration")
        else:
            logger.error(f"S3 error loading config: {e}")
        return DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error(f"Error loading configuration from S3: {e}", exc_info=True)
        return DEFAULT_CONFIG.copy()

def save_config_to_s3(config_data):
    """
    Save configuration to S3.
    
    Args:
        config_data (dict): The configuration to save
        
    Returns:
        bool: True if saved successfully, False otherwise
    """
    try:
        s3_client = get_s3_client()
        if not s3_client:
            logger.warning("S3 client not available, cannot save configuration")
            return False
        
        # Use the environment-specific bucket name
        bucket_name = S3_BUCKET_NAME
        if not bucket_name:
            logger.warning("S3 bucket name not configured, cannot save configuration")
            return False
        
        # Convert config to JSON string
        config_json = json.dumps(config_data, indent=2)
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=S3_CONFIG_KEY,
            Body=config_json,
            ContentType='application/json'
        )
        
        logger.info(f"Saved configuration to S3: {bucket_name}/{S3_CONFIG_KEY}")
        return True
    except Exception as e:
        logger.error(f"Error saving configuration to S3: {e}", exc_info=True)
        return False

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
        # Make a copy of the current config for validation
        updated_config = app_config.copy()
        
        # Validate and update numeric values with bounds checking
        if "llm_temperature" in new_config:
            updated_config["llm_temperature"] = max(0.0, min(2.0, float(new_config["llm_temperature"])))
            
        if "llm_max_output_tokens" in new_config:
            updated_config["llm_max_output_tokens"] = max(100, min(4000, int(new_config["llm_max_output_tokens"])))
            
        if "rerank_alpha" in new_config:
            updated_config["rerank_alpha"] = max(0.0, min(1.0, float(new_config["rerank_alpha"])))
            
        if "rerank_beta" in new_config:
            updated_config["rerank_beta"] = max(0.0, min(1.0, float(new_config["rerank_beta"])))
            
        if "rerank_gamma" in new_config:
            updated_config["rerank_gamma"] = max(0.0, min(1.0, float(new_config["rerank_gamma"])))
            
        if "retrieval_k" in new_config:
            updated_config["retrieval_k"] = max(1, min(20, int(new_config["retrieval_k"])))
            
        if "retrieval_fetch_multiplier" in new_config:
            updated_config["retrieval_fetch_multiplier"] = max(1, min(10, int(new_config["retrieval_fetch_multiplier"])))
            
        if "context_max_tokens_per_result" in new_config:
            updated_config["context_max_tokens_per_result"] = max(100, min(4000, int(new_config["context_max_tokens_per_result"])))
            
        if "context_max_total_tokens" in new_config:
            updated_config["context_max_total_tokens"] = max(1000, min(16000, int(new_config["context_max_total_tokens"])))
            
        # Update string values directly
        for key in ["llm_model", "vector_store_type", "system_prompt"]:
            if key in new_config:
                updated_config[key] = str(new_config[key])
        
        # If validation passes, apply to the actual app_config
        app_config.update(updated_config)
        
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
        
        # Save updated configuration to S3
        save_success = save_config_to_s3(app_config)
        if save_success:
            logger.info(f"Configuration updated and saved to S3: {app_config}")
        else:
            logger.warning(f"Configuration updated but not saved to S3: {app_config}")
            
        return True, "Configuration updated successfully"
        
    except ValueError as e:
        logger.error(f"Invalid value type during config update: {e}")
        return False, f"Invalid value type provided: {e}"
        
    except Exception as e:
        logger.error(f"Error updating config: {e}", exc_info=True)
        return False, f"An unexpected error occurred while updating configuration: {str(e)}"

# Initialize app_config by loading from S3 (falling back to defaults if needed)
app_config = load_config_from_s3() 

# --- Getters for Environment Specific Names ---
def get_qdrant_collection_name(base_name: str) -> str:
    """Prepends the environment prefix to a base Qdrant collection name."""
    return f"{ENV_PREFIX}{base_name}"

def get_haystack_memory_dir(base_dir_name: str = "haystack_store") -> str:
    """Returns the environment-specific path for the Haystack memory store directory."""
    # Assumes it lives under a 'data/' directory relative to project root
    # Modify path logic if needed
    project_root = Path(__file__).parent
    return str(project_root / "data" / f"{ENV_PREFIX}{base_dir_name}")
# ------------------------------------------- 