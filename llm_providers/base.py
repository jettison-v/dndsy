from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate_response(
        self,
        prompt: str,
        system_message: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generates a response from the LLM.

        Args:
            prompt: The user's prompt.
            system_message: The system message/instructions for the LLM.
            temperature: The sampling temperature.
            max_tokens: The maximum number of tokens to generate.
            **kwargs: Additional provider-specific arguments.

        Returns:
            A dictionary containing at least the generated 'response_text'.
            Specific providers might add more keys (e.g., usage stats, stop reason).
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Returns the name of the model being used by this provider instance."""
        pass

# Optional: Define a standard response structure if needed, e.g., using Pydantic
# class LLMResponse(TypedDict):
#     response_text: str
#     model_name: str
#     input_tokens: Optional[int]
#     output_tokens: Optional[int] 