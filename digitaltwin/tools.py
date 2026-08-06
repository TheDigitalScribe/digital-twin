"""Tool definitions and their async implementations.

Pydantic models define the schemas exposed to the model AND are used at
runtime to validate/normalize arguments (the model may send malformed JSON,
extra fields, or wrong types — we never trust the model blindly).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .config import get_settings
from .logger import get_logger, log_security_event
from .observability import Metrics

logger = get_logger(__name__)


# ---------------------------------------------------------
# 1. Pydantic Models for Tool Schemas + Runtime Validation
# ---------------------------------------------------------

class RetrieveBackground(BaseModel):
    """No arguments required."""


class RetrieveAchievements(BaseModel):
    """Search the achievements knowledge base for content matching the visitor's question."""
    question: str = Field(
        description="The visitor's question about the candidate's work achievements."
    )


# ---------------------------------------------------------
# 2. Convert Pydantic Models to OpenAI Tool Format
# ---------------------------------------------------------

tools = [
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
    {
        "type": "function",
        "function": {
            "name": "retrieve_achievements",
            "description": (
                "Search the candidate's work-achievement knowledge base (semantic RAG "
                "over markdown achievement files) and return the most relevant "
                "achievements for the visitor's question. Call this when the user asks "
                "about specific work achievements, results, project impact, metrics, or "
                "accomplishments that may not be in the Identity section. Pass the "
                "visitor's question as the 'question' argument. Returns the relevant "
                "achievement chunks as text."
            ),
            "parameters": RetrieveAchievements.model_json_schema(),
        },
    },
]


# ---------------------------------------------------------
# 3. Async Tool Implementation & Execution
# ---------------------------------------------------------

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


async def retrieve_achievements(question: str) -> str:
    """Return the top-k achievement chunks semantically relevant to the question.

    The model passes the visitor's question as the ``question`` argument; this
    function embeds it, queries the local index, and returns a bounded
    plain-text set of chunks for the model to synthesize. Gracefully degrades
    when the index is missing or no match is found.
    """
    from .rag import retrieve_achievements as _retrieve

    return await _retrieve(question)


TOOL_MAP: dict[str, Any] = {
    "retrieve_background": retrieve_background,
    "retrieve_achievements": retrieve_achievements,
}

# Name -> Pydantic model used for runtime argument validation.
_TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "retrieve_background": RetrieveBackground,
    "retrieve_achievements": RetrieveAchievements,
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

    The invocation is counted per-tool-name so ``/metrics`` can show how often
    ``retrieve_achievements`` ran versus the other tools.
    """
    Metrics.tool_calls.inc(1.0, labels={"tool": tool_name})
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