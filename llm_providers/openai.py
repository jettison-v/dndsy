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
        self._model_name = model_name
        logger.info(f"Initialized OpenAI client for model: {self._model_name}")

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
            if stream:
                # Return a generator for streaming responses
                return self._stream_response(
                    prompt=prompt, 
                    system_message=system_message, 
                    temperature=temperature, 
                    max_tokens=max_tokens, 
                    **kwargs
                )
            else:
                # Original non-streaming logic
                response = self.client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                    **kwargs 
                )
                response_text = response.choices[0].message.content
                return {"response_text": response_text}
                
        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during OpenAI API call: {e}")
            raise

    def _stream_response(
        self,
        prompt: str,
        system_message: str,
        temperature: float,
        max_tokens: int,
        **kwargs
    ) -> Generator[str, None, None]:
        """Handles the streaming logic."""
        logger.info("Initiating stream response from OpenAI...")
        stream = self.client.chat.completions.create(
            model=self._model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )
        try:
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
            logger.info("OpenAI stream finished.")
        except Exception as e:
            logger.error(f"Error during OpenAI stream: {e}", exc_info=True)
            # You might want to yield a specific error message here
            # Or just let the exception propagate up if handled elsewhere
            raise # Re-raise for now

    def get_model_name(self) -> str:
        """Returns the configured OpenAI model name."""
        return self._model_name

    def get_provider_name(self) -> str:
        """Returns the provider name."""
        return "OpenAI" 