"""Request handling: validation, rate limiting, guardrails, and the chat loop.

Everything a single user message goes through, in order:

1. Request-ID generation (trace correlation)
2. IP resolution (trusted-proxy aware)
3. Rate limiting (TTL-bucketed, per client)
4. Message validation (empty / too long)
5. Layer A guardrail (input sandboxing) — on the new message *and* history
6. History trimming (bounded conversation -> cost + injection-surface control)
7. Model call + tool loop
8. Layer B guardrail (output scrubbing)
"""

from __future__ import annotations

import threading
from typing import Any

from .config import Settings, get_settings
from .context import TWIN_SYSTEM_PROMPT
from .llm import LLMError, LLMService
from .observability import (
    Metrics,
    get_logger,
    log_security_event,
    new_request_id,
    request_id,
)
from .rate_limiter import RateLimiter, client_ip_from_request
from .security import DECLINE_INPUT, is_suspicious_request, scrub_output

logger = get_logger(__name__)

_FALLBACK_ERROR_MESSAGE = (
    "⚠️ Something went wrong while I was thinking. Please try again in a moment."
)

# Lazily-created default handler shared across requests (Gradio signature).
# Guarded by a lock so concurrent first requests cannot create two handlers
# (which would each own a distinct LLM client / rate-limiter state).
_default_handler: ChatHandler | None = None
_default_handler_lock = threading.Lock()


class ChatHandler:
    """Handles a single user message end-to-end.

    Accepts an injected settings/limiter/service so tests can construct a
    handler with a fake LLM client and arbitrary limits.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMService | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or LLMService(self.settings)
        self.rate_limiter = rate_limiter or RateLimiter(self.settings)

    # ------------------------------------------------------------------
    # Public entry point (Gradio signature)
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        history: list[Any] | None,
        request: object | None = None,
    ) -> str:
        """Process one user message and return the assistant's reply string."""
        # 0) Trace correlation — every log/metric emitted below carries this id.
        rid = new_request_id()
        token = request_id.set(rid)
        Metrics.inflight_requests.inc()
        try:
            return await self._handle_message_inner(message, history, request)
        finally:
            Metrics.inflight_requests.dec()
            request_id.reset(token)

    async def _handle_message_inner(
        self,
        message: str,
        history: list[Any] | None,
        request: object | None,
    ) -> str:
        # 1) Client IP (honors trusted proxies only).
        ip = client_ip_from_request(
            request, trusted_proxies=self.settings.trusted_proxies
        )
        Metrics.messages_received.inc()

        # 2) Rate limiting.
        if self.rate_limiter.is_limited(ip):
            Metrics.rate_limited.inc()
            log_security_event(
                logger, "rate_limited", ip=ip,
                reason="exceeded_per_window_limit",
            )
            return "⚠️ You're sending messages too quickly. Please wait a minute before asking another question."

        # 3) Validation.
        message_text = (message or "").strip()
        if not message_text:
            return "Please enter a valid question."
        if len(message_text) > self.settings.max_message_chars:
            return (
                "⚠️ Your message is too long "
                f"(maximum {self.settings.max_message_chars} characters)."
            )

        # 4) Layer A: input sandboxing on the new message.
        if is_suspicious_request(message_text):
            Metrics.input_blocked.inc()
            log_security_event(
                logger, "input_blocked", ip=ip, reason="suspicious_request"
            )
            return DECLINE_INPUT

        # 5) Layer A also applies to the bounded history we are about to send:
        #    an injected payload can arrive via an older turn. Bounding helps,
        #    but detection is better — scan the turns that will reach the model.
        history_turns = history or []
        if self.settings.max_history_turns > 0:
            history_turns = history_turns[-self.settings.max_history_turns :]
        for turn in history_turns:
            user_part = turn[0] if isinstance(turn, (list, tuple)) else turn
            user_text = self._extract_message_text(user_part)
            if user_text and is_suspicious_request(user_text):
                Metrics.input_blocked.inc()
                log_security_event(
                    logger,
                    "input_blocked",
                    ip=ip,
                    reason="suspicious_history_turn",
                )
                return DECLINE_INPUT

        # 6) Build a bounded message list.
        messages = self._build_messages(history or [], message_text)

        # 7) Model call (+ tool loop) with graceful degradation.
        try:
            reply = await self.llm.run_chat(messages)
        except LLMError as exc:
            logger.error("LLM call failed for ip=%s: %s", ip, exc)
            return _FALLBACK_ERROR_MESSAGE
        except Exception:
            logger.exception("Unexpected error handling message for ip=%s", ip)
            return _FALLBACK_ERROR_MESSAGE

        # 8) Layer B: output scrubbing.
        scrubbed = scrub_output(reply)
        if scrubbed != reply:
            Metrics.output_scrubbed.inc()
        return scrubbed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self, history: list[Any], user_text: str
    ) -> list[dict[str, Any]]:
        """Assemble the OpenAI message list from Gradio history.

        ``history`` is a list of [user_msg, assistant_msg] turn pairs. We keep
        only the most recent ``max_history_turns`` turns to bound both cost
        and the injection surface (older assistant turns are the ideal place
        to hide prompt-injection artifacts).

        History entries are normalized to plain strings: Gradio 6 may pass
        plain strings, dicts (``{"role", "content", ...}``), or ChatMessage
        objects with a ``.content`` attribute. Passing those raw as
        ``messages[].content`` makes the OpenAI API reject the request with a
        400 ("expected a string or array of objects").
        """
        turns = history[-self.settings.max_history_turns :] if self.settings.max_history_turns else []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": TWIN_SYSTEM_PROMPT}
        ]
        for turn in turns:
            user_part = turn[0] if isinstance(turn, (list, tuple)) else turn
            assistant_part = (
                turn[1]
                if isinstance(turn, (list, tuple)) and len(turn) > 1
                else ""
            )
            user_text_from_history = self._extract_message_text(user_part)
            if user_text_from_history:
                messages.append(
                    {"role": "user", "content": user_text_from_history}
                )
            assistant_text = self._extract_message_text(assistant_part)
            if assistant_text:
                messages.append(
                    {"role": "assistant", "content": assistant_text}
                )
        messages.append({"role": "user", "content": user_text})
        return messages

    @staticmethod
    def _extract_message_text(entry: Any) -> str:
        """Extract plain text from a Gradio history message entry.

        Handles plain strings, dicts (``{"content": ...}`` / ``{"text": ...}``),
        and objects with a ``content``/``text`` attribute (e.g. Gradio's
        ChatMessage). The content may itself be a list of parts
        (``[{"type": "text", "text": "..."}]``), which is flattened.
        """
        if entry is None:
            return ""
        if isinstance(entry, str):
            return entry

        # list-of-parts form: [{"type": "text", "text": "..."}, ...]
        if isinstance(entry, (list, tuple)):
            parts = [
                ChatHandler._extract_message_text(item) for item in entry
            ]
            return " ".join(part for part in parts if part)

        # dict form
        if isinstance(entry, dict):
            content = entry.get("content") or entry.get("text")
            return ChatHandler._extract_message_text(content)

        # object form (gr.ChatMessage, SimpleNamespace, etc.)
        content = getattr(entry, "content", None) or getattr(entry, "text", None)
        if content is None:
            return ""
        return ChatHandler._extract_message_text(content)


async def handle_message(
    message: str,
    history: list[Any] | None,
    request: object | None = None,
) -> str:
    """Module-level Gradio-compatible async entry point.

    Uses a lazily-created default ``ChatHandler`` shared across requests so
    the LLM client / rate limiter are constructed only once per process.
    Construction is guarded by a lock: two concurrent first requests would
    otherwise each build their own handler.
    """
    global _default_handler
    if _default_handler is None:
        with _default_handler_lock:
            if _default_handler is None:
                _default_handler = ChatHandler()
    return await _default_handler.handle_message(message, history, request)