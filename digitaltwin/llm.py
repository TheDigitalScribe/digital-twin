"""LLM orchestration: client construction, retries, and the chat loop.

Separates model-API concerns (retries, timeouts, tool-call loop) from the
Gradio handler so the chat function stays thin and testable with a mocked
client.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Settings, get_settings
from .tools import handle_tool_calls_async, tools

logger = logging.getLogger(__name__)

# Upper bound on how many tool-call rounds we allow per user message. The
# model could theoretically loop forever on its own tool calls; this keeps a
# runaway loop from burning unbounded tokens/cost.
MAX_TOOL_ROUNDS = 5


class LLMError(RuntimeError):
    """Raised when the model API cannot be reached after retries."""


@dataclass
class LLMService:
    """Wraps an OpenAI-compatible chat client with retry/timeout behavior.

    Designed to be instantiated once per process (the underlying client holds
    connection-pool state). Tests may inject a fake client.
    """

    settings: Settings = field(default_factory=get_settings)
    client: Any = field(default=None)
    max_tool_rounds: int = field(default=MAX_TOOL_ROUNDS)

    def __post_init__(self) -> None:
        if self.client is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {"api_key": self.settings.openai_api_key.get_secret_value() if self.settings.openai_api_key else None}
            if self.settings.openai_base_url:
                kwargs["base_url"] = self.settings.openai_base_url
            self.client = AsyncOpenAI(**kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_chat(
        self,
        messages: list[dict[str, Any]],
        retries: int = 3,
    ) -> str:
        """Run the full chat loop (tools included) and return the final text.

        Raises LLMError if the API is unreachable after ``retries`` attempts,
        or if the tool-call loop exceeds ``max_tool_rounds``.
        """
        response = await self._create_with_retry(messages, retries=retries)

        for _ in range(self.max_tool_rounds):
            if response.choices[0].finish_reason != "tool_calls":
                break

            msg = response.choices[0].message
            tool_calls = msg.tool_calls

            results = await handle_tool_calls_async(tool_calls)
            messages.append(msg)
            messages.extend(results)
            response = await self._create_with_retry(messages, retries=retries)
        else:
            raise LLMError(
                f"Model exceeded max tool-call rounds ({self.max_tool_rounds})."
            )

        content = response.choices[0].message.content
        return content if content is not None else ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_with_retry(self, messages: list[dict[str, Any]], retries: int = 3) -> Any:
        """Call chat.completions.create with exponential backoff on failure.

        Retries on network errors, 5xx, and 429 (rate-limit), respecting any
        ``Retry-After`` header the API returns. Non-retryable 4xx errors
        (e.g. invalid auth) raise immediately.
        """
        attempt = 0
        while True:
            try:
                return await self.client.chat.completions.create(
                    model=self.settings.model_name,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:  # noqa: BLE001 - see conditions below
                if not self._should_retry(exc):
                    raise LLMError(f"Non-retryable API error: {exc}") from exc
                if attempt >= retries:
                    raise LLMError(f"API unreachable after {retries} retries: {exc}") from exc

                wait = self._retry_delay(exc, attempt)
                logger.warning(
                    "Model API error (attempt %s/%s): %s; retrying in %.1fs",
                    attempt + 1, retries + 1, exc, wait,
                )
                await asyncio.sleep(wait)
                attempt += 1

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """True for transient network errors / HTTP 5xx / 429 rate limits."""
        status = getattr(exc, "status_code", None)
        if status is not None:
            return status >= 500 or status == 429
        # Connection-level errors (httpx.TransportError and friends).
        return isinstance(exc, (ConnectionError, TimeoutError, OSError))

    @staticmethod
    def _retry_delay(exc: Exception, attempt: int) -> float:
        """Seconds to wait before the next retry: exponential + jitter.

        Honors a Retry-After header if present; otherwise 2^attempt seconds
        with up to 0.5s of random jitter to avoid thundering-herd sync.
        """
        import random

        retry_after = getattr(exc, "response", None)
        if retry_after is not None:
            header = getattr(retry_after, "headers", {}).get("retry-after")
            if header:
                try:
                    return float(header)
                except (TypeError, ValueError):
                    pass
        return min(2**attempt, 30) + random.uniform(0, 0.5)