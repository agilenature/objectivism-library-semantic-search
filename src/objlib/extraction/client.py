"""Mistral API client wrapper for metadata extraction.

Wraps the magistral-medium-latest model with:
- Async API calls with JSON mode
- Configurable temperature (defaults to 1.0 for production)
- Thinking block filtering via two-phase parser
- Credit exhaustion (402) and rate limit (429) exception handling
"""

from __future__ import annotations

from mistralai import Mistral
from mistralai.models.sdkerror import SDKError

from objlib.extraction.parser import parse_magistral_response


class CreditExhaustedException(Exception):
    """Raised when Mistral API returns 402 (Payment Required)."""

    pass


class RateLimitException(Exception):
    """Raised when Mistral API returns 429 (Too Many Requests)."""

    pass


class MistralClient:
    """Async wrapper around Mistral's chat completion API for metadata extraction.

    Uses magistral-medium-latest by default with JSON mode enabled.
    Temperature defaults to 1.0 (required for magistral production use).
    Wave 1 strategies may override temperature for experimental lanes.

    Usage:
        client = MistralClient(api_key="...")
        metadata, tokens = await client.extract_metadata(
            transcript_text="...",
            system_prompt="...",
        )
    """

    def __init__(self, api_key: str, model: str = "magistral-medium-latest") -> None:
        """Initialize the Mistral client.

        Args:
            api_key: Mistral API key.
            model: Model identifier (default: magistral-medium-latest).
        """
        self._client = Mistral(api_key=api_key)
        self._model = model

    async def extract_metadata(
        self,
        transcript_text: str,
        system_prompt: str,
        max_tokens: int = 8000,
        temperature: float = 1.0,
    ) -> tuple[dict, int]:
        """Extract metadata from a transcript using the Mistral model.

        Args:
            transcript_text: The transcript text to analyze.
            system_prompt: System prompt defining extraction instructions.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature. Defaults to 1.0 (required
                for magistral production use). Wave 1 strategies may use
                lower values (0.1, 0.3, 0.5) as experiments.

        Returns:
            Tuple of (parsed_metadata_dict, total_tokens_used).

        Raises:
            CreditExhaustedException: On 402 (Payment Required).
            RateLimitException: On 429 (Too Many Requests).
            SDKError: On other API errors.
            ValueError: If response cannot be parsed as JSON.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript_text},
        ]

        try:
            response = await self._client.chat.complete_async(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except SDKError as e:
            if e.status_code == 402:
                raise CreditExhaustedException(
                    f"Mistral credits exhausted (HTTP 402): {e}"
                ) from e
            if e.status_code == 429:
                raise RateLimitException(
                    f"Mistral rate limit exceeded (HTTP 429): {e}"
                ) from e
            raise

        parsed = parse_magistral_response(response)
        total_tokens = response.usage.total_tokens if response.usage else 0

        return parsed, total_tokens
