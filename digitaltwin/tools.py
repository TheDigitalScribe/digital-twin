"""Tool definitions and their async implementations.

Pydantic models define the schemas exposed to the model AND are used at
runtime to validate/normalize arguments (the model may send malformed JSON,
extra fields, or wrong types — we never trust the model blindly).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import get_settings
from .logger import get_logger, log_security_event
from .observability import Metrics
from .persistence import persist_lead, persist_unknown_question

logger = get_logger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Shared HTTP client for outbound notifications (connection pooling).
_http_client: httpx.AsyncClient | None = None
_http_client_loop: asyncio.AbstractEventLoop | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return a lazily-created httpx.AsyncClient bound to the current loop.

    In production there is exactly one event loop, so a single process-wide
    client is reused (connection pooling). Test frameworks (anyio) create a
    fresh loop per test; reusing a client whose keep-alive connections are
    bound to a closed loop raises "Event loop is closed". We therefore key
    the cache by the running loop and build a new client when it changes.
    """
    global _http_client, _http_client_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _http_client is None or (loop is not None and _http_client_loop is not loop):
        _http_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        _http_client_loop = loop
    return _http_client


# ---------------------------------------------------------
# 1. Pydantic Models for Tool Schemas + Runtime Validation
# ---------------------------------------------------------

class RecordUserDetails(BaseModel):
    """Record that a visitor is interested in getting in touch and provided contact info.

    ``email`` is deliberately a plain non-empty string rather than an
    EmailStr: the model sometimes has to record a visitor's details before a
    valid address is confirmed (e.g. the user says "it's my work email",
    "unknown", or a typo). Best-effort lead capture means we record what was
    given and let a human review it — silently dropping the lead because the
    address didn't pass strict validation is worse than capturing "unknown".
    """

    email: str = Field(min_length=1, description="The email address provided by the user.")
    name: str = Field(default="Name not provided", description="The user's name, if provided.")
    notes: str = Field(default="Not provided", description="Any additional conversation context worth recording.")


class RecordUnknownQuestion(BaseModel):
    """Always use this tool to record any question about the person that couldn't be answered."""
    question: str = Field(description="The question that couldn't be answered.")


class RetrieveBackground(BaseModel):
    """No arguments required."""


# ---------------------------------------------------------
# 2. Convert Pydantic Models to OpenAI Tool Format
# ---------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "record_user_details",
            "description": RecordUserDetails.__doc__,
            "parameters": RecordUserDetails.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_unknown_question",
            "description": RecordUnknownQuestion.__doc__,
            "parameters": RecordUnknownQuestion.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_background",
            "description": (
                "Load the candidate's full background (skills, experience, education, "
                "certifications, projects, contact details). Call this BEFORE answering "
                "any specific question about the candidate when the answer is not already "
                "in the Identity section. Returns the complete background text."
            ),
            # Deliberately the minimal schema (unchanged from the original
            # hand-authored tool definition): no title/description clutter.
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ---------------------------------------------------------
# 3. Async Tool Implementation & Execution
# ---------------------------------------------------------

async def push_async(text: str) -> None:
    """Non-blocking HTTP call to Pushover (best-effort, never raises).

    Falls back to logging when credentials are absent or the call fails.
    Uses the shared connection-pooled client.
    """
    settings = get_settings()
    user = settings.pushover_user
    token = settings.pushover_token
    if not user or not token:
        logger.info("Push skipped (missing credentials): %s", text)
        return

    try:
        client = _get_http_client()
        resp = await client.post(
            PUSHOVER_URL,
            data={"token": token, "user": user, "message": text},
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - best-effort, never raises
        logger.error("Failed to send push notification: %s", exc)


async def record_user_details(
    email: str, name: str = "Name not provided", notes: str = "Not provided"
) -> str:
    """Persist the lead durably, then best-effort push a notification."""
    Metrics.leads_recorded.inc()
    persist_lead(email, name, notes)
    await push_async(f"Recording interest from {name} ({email}). Notes: {notes}")
    return "OK"


async def record_unknown_question(question: str) -> str:
    """Persist the unanswered question durably, then best-effort push."""
    Metrics.unmatched_questions.inc()
    persist_unknown_question(question)
    await push_async(f"Unknown question asked: {question}")
    return "OK"


async def retrieve_background() -> str:
    """Return the background text (CV), bounded to ``max_background_chars``.

    Loads lazily and caches the background on first use so the env var / file
    is only read once per process. The returned text is deliberately NOT part
    of the system prompt (context minimization); it is fetched on demand.

    The returned text is capped at ``settings.max_background_chars`` characters
    so a single tool call cannot blow up the context window / cost.
    """
    from .context import load_background

    return load_background()[: get_settings().max_background_chars]


TOOL_MAP: dict[str, Any] = {
    "record_user_details": record_user_details,
    "record_unknown_question": record_unknown_question,
    "retrieve_background": retrieve_background,
}

# Name -> Pydantic model used for runtime argument validation.
_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "record_user_details": RecordUserDetails,
    "record_unknown_question": RecordUnknownQuestion,
    "retrieve_background": RetrieveBackground,
}


async def handle_tool_calls_async(tool_calls: list[Any]) -> list[dict[str, str]]:
    """Dispatch tool calls to their implementations with validated arguments.

    Returns a list of tool-result messages in OpenAI format. Never raises:
    parse/validation errors and unknown tool names become structured error
    results (the model will see the failure and can adapt).

    The ``Any`` import is a typing simplification; the OpenAI SDK types vary
    enough across versions that we intentionally avoid a hard dependency here.
    """
    results: list[dict[str, str]] = []
    for tool_call in tool_calls:
        tool_name = getattr(tool_call.function, "name", "")
        args_text = getattr(tool_call.function, "arguments", "{}")
        result = await _dispatch_tool(tool_name, args_text)
        results.append(
            {
                "role": "tool",
                "content": json.dumps(result),
                "tool_call_id": getattr(tool_call, "id", ""),
            }
        )
    return results


async def _dispatch_tool(tool_name: str, args_text: str) -> str:
    """Resolve and invoke a single tool call, never raising.

    Returns the tool result as a plain string; the caller JSON-encodes it for
    the OpenAI tool-message format. Error conditions are returned as
    descriptive strings so the model can see exactly what went wrong.
    """
    Metrics.tool_calls.inc()
    try:
        arguments = json.loads(args_text or "{}")
    except json.JSONDecodeError as exc:
        Metrics.tool_errors.inc()
        logger.error("Tool %s sent malformed JSON args: %s", tool_name, exc)
        return f"Error: malformed JSON arguments: {exc}"

    if not isinstance(arguments, dict):
        Metrics.tool_errors.inc()
        return "Error: tool arguments must be a JSON object."

    schema = _TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        log_security_event(logger, "unknown_tool_requested", tool=tool_name)
        return f"Error: unknown tool: {tool_name}"

    try:
        validated = schema.model_validate(arguments)
    except ValidationError as exc:
        Metrics.tool_errors.inc()
        logger.warning("Tool %s received invalid arguments: %s", tool_name, exc)
        return f"Error: invalid arguments: {exc}"

    func = TOOL_MAP[tool_name]
    try:
        result = await func(**validated.model_dump())
    except Exception as exc:
        Metrics.tool_errors.inc()
        logger.exception("Tool %s raised during execution", tool_name)
        return f"Error: tool execution failed: {exc}"
    return result if isinstance(result, str) else json.dumps(result)
