import os
from typing import Dict, Any, Union, Generator, Optional
from openai import OpenAI, OpenAIError
import logging

from .base import BaseLLMProvider

logger = logging.getLogger(__name__)

class OpenAILLM(BaseLLMProvider):
    """LLM Provider implementation for OpenAI models."""
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
            # Prepare common parameters for the API call
            api_params = {
                "model": self._chat_model_name,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                **kwargs
            }

            # Model-specific adjustments for max_tokens parameter
            if self._chat_model_name == "o4-mini-2025-04-16":
                api_params["max_completion_tokens"] = max_tokens
            else:
                api_params["max_tokens"] = max_tokens

            if stream:
                # For streaming, call _stream_response with the assembled parameters
                # Note: _stream_response will also need this logic if called directly elsewhere,
                # or it should expect the correct parameter name.
                # For now, assuming generate_response is the primary entry point.
                return self._stream_response_with_params(api_params)
            else:
                # For non-streaming, make the direct API call
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
        """Handles the streaming logic. Consider refactoring to use a single param prep point."""
        logger.info("Initiating stream response from OpenAI...")
        
        # Prepare common parameters for the API call (duplicated logic, ideally refactor)
        api_params = {
            "model": self._chat_model_name,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True, # Explicitly set stream to True
            **kwargs
        }

        # Model-specific adjustments for max_tokens parameter
        if self._chat_model_name == "o4-mini-2025-04-16":
            api_params["max_completion_tokens"] = max_tokens # Assumes max_tokens arg is the value intended for either name
        else:
            api_params["max_tokens"] = max_tokens

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