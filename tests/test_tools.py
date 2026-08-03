"""Tests for the tools module: schemas, dispatch, and argument validation."""

import json
from types import SimpleNamespace

import pytest

from digitaltwin.tools import (
    _dispatch_tool,
    handle_tool_calls_async,
    record_unknown_question,
    record_user_details,
    retrieve_background,
    tools,
    TOOL_MAP,
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
        result = await _dispatch_tool("record_user_details", "{not json")
        assert "malformed" in result.lower()

    @pytest.mark.anyio
    async def test_non_object_arguments_return_error(self):
        result = await _dispatch_tool("record_user_details", '"a string"')
        assert "object" in result.lower()

    @pytest.mark.anyio
    async def test_invalid_arguments_return_validation_error(self):
        # Email is required; missing -> validation error.
        result = await _dispatch_tool("record_user_details", "{}")
        assert "invalid arguments" in result.lower()

    @pytest.mark.anyio
    async def test_best_effort_email_accepted(self):
        # Email is deliberately a plain non-empty string (best-effort lead
        # capture): the model may have to record a visitor's details before
        # a strictly-valid address is confirmed ("unknown", typo, etc.).
        result = await _dispatch_tool(
            "record_user_details",
            json.dumps({"email": "unknown", "name": "Jane"}),
        )
        assert result == "OK"

    @pytest.mark.anyio
    async def test_valid_arguments_accepted(self, monkeypatch):
        import digitaltwin.tools as tools_module

        pushed = []
        async def fake_push(text: str) -> None:
            pushed.append(text)

        # Patch the module-level push_async so we don't hit the network, and
        # capture what the tool would have sent on success.
        monkeypatch.setattr(tools_module, "push_async", fake_push)

        result = await _dispatch_tool(
            "record_user_details",
            json.dumps({"email": "jane@example.com", "name": "Jane"}),
        )
        assert result == "OK"
        assert pushed and "jane@example.com" in pushed[0]
        assert "Jane" in pushed[0]


class TestHandleToolCallsAsync:
    @pytest.mark.anyio
    async def test_returns_openai_tool_messages(self):
        calls = [
            fake_tool_call("record_unknown_question", json.dumps({"question": "How old are you?"})),
            fake_tool_call("unknown_tool", "{}", call_id="call_2"),
        ]
        results = await handle_tool_calls_async(calls)

        assert len(results) == 2
        assert results[0]["role"] == "tool"
        assert results[0]["tool_call_id"] == "call_1"
        assert results[0]["content"] == '"OK"'
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
    async def test_record_user_details_returns_ok(self):
        assert await record_user_details("a@b.com", "Alice") == "OK"

    @pytest.mark.anyio
    async def test_record_unknown_question_returns_ok(self):
        assert await record_unknown_question("What is X?") == "OK"

    @pytest.mark.anyio
    async def test_retrieve_background_returns_non_empty(self):
        bg = await retrieve_background()
        assert isinstance(bg, str)
        assert len(bg) > 0