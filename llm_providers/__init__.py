import os
import logging

from .base import BaseLLMProvider
from .openai import OpenAILLM
# Import other providers here when added, e.g.:
# from .anthropic import AnthropicLLM 

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {
    "openai": OpenAILLM,
    # "anthropic": AnthropicLLM, 
}

def get_llm_client() -> BaseLLMProvider:
    """Factory function to get the configured LLM provider client."""
    provider_name = os.getenv("LLM_PROVIDER", "openai").lower()
    model_name = os.getenv("LLM_MODEL_NAME") # Specific model name is passed during instantiation

    ProviderClass = SUPPORTED_PROVIDERS.get(provider_name)

    if not ProviderClass:
        logger.error(f"Unsupported LLM_PROVIDER: {provider_name}. Supported: {list(SUPPORTED_PROVIDERS.keys())}")
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider_name}")

    try:
        # Pass model_name only if it's set, otherwise let the provider use its default
        if model_name:
            logger.info(f"Instantiating LLM provider '{provider_name}' with model '{model_name}'")
            client = ProviderClass(model_name=model_name)
        else:
            logger.info(f"Instantiating LLM provider '{provider_name}' with default model")
            client = ProviderClass()
            
        # Log the actual model name being used after instantiation
        logger.info(f"LLM client ready. Using model: {client.get_model_name()}")
        return client
        
    except Exception as e:
        logger.error(f"Failed to initialize LLM provider {provider_name}: {e}")
        raise
