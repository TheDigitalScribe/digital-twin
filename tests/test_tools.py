"""Tests for the tools module: schemas, dispatch, and argument validation."""

import json
from types import SimpleNamespace

import pytest

from digitaltwin.tools import (
    TOOL_MAP,
    _dispatch_tool,
    handle_tool_calls_async,
    retrieve_background,
    tools,
)


def fake_tool_call(name: str, arguments: str, call_id: str = "call_1") -> SimpleNamespace:
    """Build a fake OpenAI tool-call object for tests."""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class TestToolSchemas:
    def test_all_tools_registered_in_map(self):
        for tool in tools:
            assert tool["function"]["name"] in TOOL_MAP

    def test_schema_is_valid_openai_format(self):
        for tool in tools:
            assert tool["type"] == "function"
            fn = tool["function"]
            assert fn["name"]
            assert fn["description"]
            assert fn["parameters"]["type"] == "object"


class TestDispatchTool:
    @pytest.mark.anyio
    async def test_unknown_tool_returns_error(self):
        result = await _dispatch_tool("no_such_tool", "{}")
        assert "unknown tool" in result.lower()

    @pytest.mark.anyio
    async def test_malformed_json_returns_error(self):
        result = await _dispatch_tool("retrieve_background", "{not json")
        assert "malformed" in result.lower()

    @pytest.mark.anyio
    async def test_non_object_arguments_return_error(self):
        result = await _dispatch_tool("retrieve_background", '"a string"')
        assert "object" in result.lower()

    @pytest.mark.anyio
    async def test_invalid_arguments_return_validation_error(self):
        # question is required; missing -> validation error.
        result = await _dispatch_tool("retrieve_achievements", "{}")
        assert "invalid arguments" in result.lower()

    @pytest.mark.anyio
    async def test_valid_arguments_accepted(self):
        result = await _dispatch_tool(
            "retrieve_achievements",
            json.dumps({"question": "What projects are you most proud of?"}),
        )
        # No index in the test env -> graceful degradation rather than an error.
        assert "invalid arguments" not in result.lower()


class TestHandleToolCallsAsync:
    @pytest.mark.anyio
    async def test_returns_openai_tool_messages(self):
        calls = [
            fake_tool_call("retrieve_background", "{}"),
            fake_tool_call("unknown_tool", "{}", call_id="call_2"),
        ]
        results = await handle_tool_calls_async(calls)

        assert len(results) == 2
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_1"
        assert json.loads(results[0]["content"])  # background text, non-empty
        assert results[1]["tool_call_id"] == "call_2"
        assert "unknown tool" in results[1]["content"].lower()

    @pytest.mark.anyio
    async def test_retrieve_background_returns_text(self):
        calls = [fake_tool_call("retrieve_background", "{}")]
        results = await handle_tool_calls_async(calls)
        assert results[0]["role"] == "tool"


# ---------------------------------------------------------------------------
# Direct async tool implementations
# ---------------------------------------------------------------------------

class TestToolImplementations:
    @pytest.mark.anyio
    async def test_retrieve_background_returns_non_empty(self):
        bg = await retrieve_background()
        assert isinstance(bg, str)
        assert len(bg) > 0