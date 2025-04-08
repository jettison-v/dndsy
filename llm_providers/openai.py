import os
from typing import Dict, Any
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
        self._model_name = model_name
        logger.info(f"Initialized OpenAI client for model: {self._model_name}")

    def generate_response(
        self,
        prompt: str,
        system_message: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        **kwargs # Allows passing extra args if needed later
    ) -> Dict[str, Any]:
        """Generates a response using the OpenAI ChatCompletion API."""
        try:
            response = self.client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs # Pass any additional OpenAI-specific args
            )
            
            response_text = response.choices[0].message.content
            # Optionally extract usage stats or other info
            # usage = response.usage
            
            return {
                "response_text": response_text,
                # "usage": usage # Example
            }
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            # Re-raise or return an error structure
            raise
        except Exception as e:
            logger.error(f"Unexpected error during OpenAI API call: {e}")
            raise

    def get_model_name(self) -> str:
        """Returns the configured OpenAI model name."""
        return self._model_name

    def get_provider_name(self) -> str:
        """Returns the provider name."""
        return "OpenAI" 