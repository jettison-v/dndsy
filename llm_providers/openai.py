import os
from typing import Dict, Any, Union, Generator, Optional
from openai import OpenAI, OpenAIError
import logging

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

class OpenAILLM(BaseLLMProvider):
    """LLM Provider implementation for OpenAI models."""

    MODEL_PARAMETER_CONFIG = {
        "o4-mini-2025-04-16": {
            "param_name_map": {"max_tokens": "max_completion_tokens"},
            "fixed_parameters": {"temperature": 1.0},
            "unsupported_params": [], 
            # Add other o4-mini specific rules here if discovered
        },
        "gpt-4.1-nano-2025-04-14": { # Assuming standard behavior for GPT-4.1 family for now
            "param_name_map": {}, 
            "unsupported_params": []
        },
        "gpt-4.1-mini-2025-04-14": {
            "param_name_map": {},
            "unsupported_params": []
        },
        "gpt-4.1-2025-04-14": {
            "param_name_map": {},
            "unsupported_params": []
        },
        # Default for other models not explicitly listed (e.g., older GPT models if any were kept)
        "default": {
             "param_name_map": {},
             "unsupported_params": []
        }
    }

    # Standard OpenAI parameters we generally expect to pass through if not overridden or unsupported
    DEFAULT_SUPPORTED_KWARGS = [
        "top_p", "frequency_penalty", "presence_penalty", 
        "logit_bias", "seed", "stop", "user", "n", 
        "response_format", # For features like JSON mode
        # "tools", "tool_choice" are more complex and typically handled by dedicated logic
    ]

    def __init__(self, api_key: str = None, model_name: str = "gpt-3.5-turbo"):
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable or api_key parameter must be set")
        
        self.client = OpenAI(api_key=api_key)
        # Store separate model names for chat and embeddings if they differ
        self._chat_model_name = model_name
        # Default to the semantic embedding model name, but allow override if needed
        self._embedding_model_name = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small") 
        logger.info(f"Initialized OpenAI client.")
        logger.info(f"  Chat model: {self._chat_model_name}")
        logger.info(f"  Embedding model: {self._embedding_model_name}")

    def generate_response(
        self,
        prompt: str,
        system_message: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        stream: bool = False,
        **kwargs
    ) -> Union[Dict[str, Any], Generator[str, None, None]]:
        """Generates a response using the OpenAI ChatCompletion API, optionally streaming."""
        try:
            api_params = {
                "model": self._chat_model_name,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
            }

            # Get model specific config, falling back to a default empty config if model not listed
            model_config = self.MODEL_PARAMETER_CONFIG.get(self._chat_model_name, 
                                                           self.MODEL_PARAMETER_CONFIG.get("default", {}))
            param_name_map = model_config.get("param_name_map", {})
            fixed_params = model_config.get("fixed_parameters", {})
            unsupported_params_for_model = set(model_config.get("unsupported_params", []))

            # 1. Handle max_tokens (from method signature, originally from app_config)
            max_tokens_val = max_tokens 
            max_tokens_key_actual = param_name_map.get("max_tokens", "max_tokens") # Get mapped name if any

            if max_tokens_key_actual not in unsupported_params_for_model:
                if max_tokens_key_actual in fixed_params:
                    fixed_val = fixed_params[max_tokens_key_actual]
                    if fixed_val != max_tokens_val:
                        logger.warning(
                            f"Model {self._chat_model_name} has fixed {max_tokens_key_actual}={fixed_val}. "
                            f"Overriding passed value {max_tokens_val}."
                        )
                    api_params[max_tokens_key_actual] = fixed_val
                elif max_tokens_val is not None:
                    api_params[max_tokens_key_actual] = max_tokens_val
            else:
                logger.warning(f"Parameter 'max_tokens' (mapped to {max_tokens_key_actual}) is unsupported for {self._chat_model_name} and will be omitted.")

            # 2. Handle temperature (from method signature, originally from app_config)
            temperature_val = temperature
            temperature_key_actual = param_name_map.get("temperature", "temperature") # Usually just "temperature"

            if temperature_key_actual not in unsupported_params_for_model:
                if temperature_key_actual in fixed_params:
                    fixed_val = fixed_params[temperature_key_actual]
                    if fixed_val != temperature_val: # Log only if different
                        logger.warning(
                            f"Model {self._chat_model_name} has fixed {temperature_key_actual}={fixed_val}. "
                            f"Overriding passed value {temperature_val}."
                        )
                    api_params[temperature_key_actual] = fixed_val
                elif temperature_val is not None: # Allow API default if None
                    api_params[temperature_key_actual] = temperature_val
            else:
                logger.warning(f"Parameter 'temperature' (mapped to {temperature_key_actual}) is unsupported for {self._chat_model_name} and will be omitted.")
            
            # 3. Handle other kwargs passed into generate_response (originally from app_config)
            for k_orig, v_orig in kwargs.items():
                k_actual = param_name_map.get(k_orig, k_orig)

                if k_actual not in unsupported_params_for_model:
                    if k_actual in fixed_params:
                        fixed_val = fixed_params[k_actual]
                        if fixed_val != v_orig: # Log only if different
                             logger.warning(
                                f"Model {self._chat_model_name} has fixed {k_actual}={fixed_val}. "
                                f"Overriding passed kwarg {k_orig}={v_orig}."
                            )
                        api_params[k_actual] = fixed_val
                    elif k_actual in self.DEFAULT_SUPPORTED_KWARGS:
                        api_params[k_actual] = v_orig
                    else:
                        # This case means the kwarg is not in DEFAULT_SUPPORTED_KWARGS 
                        # and not explicitly handled by model_config.
                        # It might be a new/uncommon param or a typo from app_config.
                        logger.warning(
                            f"Parameter '{k_orig}' (mapped to '{k_actual}') from kwargs is not in "
                            f"DEFAULT_SUPPORTED_KWARGS for {self._chat_model_name} and will be omitted."
                        )
                else:
                    logger.warning(
                        f"Parameter '{k_orig}' (mapped to '{k_actual}') is explicitly unsupported "
                        f"for {self._chat_model_name} and will be omitted."
                    )

            if stream:
                return self._stream_response_with_params(api_params)
            else:
                api_params["stream"] = False
                response = self.client.chat.completions.create(**api_params)
                response_text = response.choices[0].message.content
                return {"response_text": response_text}
                
        except OpenAIError as e:
            logger.error(f"OpenAI API error (ChatCompletion): {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during OpenAI ChatCompletion API call: {e}")
            raise

    def _stream_response(
        self,
        prompt: str,
        system_message: str,
        temperature: float,
        max_tokens: int,
        **kwargs
    ) -> Generator[str, None, None]:
        """DEPRECATED: Streaming logic is now handled by generate_response calling _stream_response_with_params.
        This method remains for potential direct calls but bypasses centralized param building."""
        logger.warning("_stream_response called directly, bypassing centralized parameter building. Consider refactoring.")
        # Original _stream_response logic, which does its own param building (now redundant/divergent)
        # For consistency, this should ideally also use the MODEL_PARAMETER_CONFIG if it were to be maintained.
        # However, the current flow through generate_response -> _stream_response_with_params is preferred.
        _api_params_direct = {
            "model": self._chat_model_name,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature, # This would be subject to model specific rules not applied here
            "max_tokens": max_tokens,   # Same here
            "stream": True,
            **kwargs
        }
        # Quick fix for o4-mini if called directly (less robust than centralized):
        if self._chat_model_name == "o4-mini-2025-04-16":
            if "max_tokens" in _api_params_direct:
                _api_params_direct["max_completion_tokens"] = _api_params_direct.pop("max_tokens")
            _api_params_direct["temperature"] = 1.0


        stream_response = self.client.chat.completions.create(**_api_params_direct)
        try:
            for chunk in stream_response:
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
            logger.info("OpenAI stream finished.")
        except Exception as e:
            logger.error(f"Error during OpenAI stream: {e}", exc_info=True)
            raise
            
    def _stream_response_with_params(self, api_params: Dict[str, Any]) -> Generator[str, None, None]:
        """Internal streaming handler that expects fully prepared API parameters."""
        logger.info(f"Initiating stream response with prepped params for model {api_params.get('model')}")
        api_params["stream"] = True # Ensure stream is True
        
        stream_response = self.client.chat.completions.create(**api_params)
        try:
            for chunk in stream_response:
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
            logger.info("OpenAI stream finished.")
        except Exception as e:
            logger.error(f"Error during OpenAI stream: {e}", exc_info=True)
            raise

    def get_embedding(self, text: str) -> list[float]:
        """Generates an embedding for the given text using the configured embedding model."""
        try:
            response = self.client.embeddings.create(
                input=[text], # API expects a list of strings
                # Use the embedding model name here
                model=self._embedding_model_name 
            )
            # Extract the embedding vector from the response
            embedding = response.data[0].embedding
            return embedding
        except OpenAIError as e:
            logger.error(f"OpenAI API error (Embeddings): {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during OpenAI Embeddings API call: {e}")
            raise

    def get_model_name(self) -> str:
        """Returns the configured OpenAI chat model name."""
        # Return the chat model specifically
        return self._chat_model_name 

    def get_provider_name(self) -> str:
        """Returns the provider name."""
        return "OpenAI" 