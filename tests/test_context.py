"""Tests for the context-minimization architecture in context.py.

The system prompt must contain only a short identity sketch of the candidate,
never the full background (CV). The full background is loaded lazily via the
``retrieve_background`` tool (tools.py) so that a leaked system prompt exposes
the bare minimum.
"""

import importlib

import pytest

from digitaltwin import context
from digitaltwin import tools
from digitaltwin.tools import retrieve_background


# ---------------------------------------------------------------------------
# Identity sketch
# ---------------------------------------------------------------------------

class TestIdentitySketch:
    def test_short_background_kept_intact(self):
        bg = "Jane Doe\nSoftware Engineer"
        assert context._build_identity_sketch(bg) == bg

    def test_long_background_truncated_at_word_boundary(self):
        bg = "Jane Doe\nSoftware Engineer from Dublin. " + "x" * 1000
        sketch = context._build_identity_sketch(bg)
        assert len(sketch) <= context._IDENTITY_SKETCH_CHARS
        assert sketch.startswith("Jane Doe")
        # Never contains the truncated tail.
        assert "x" not in sketch[-10:]

    def test_empty_background_returns_empty(self):
        assert context._build_identity_sketch("") == ""
        assert context._build_identity_sketch(None) == ""

    def test_whitespace_only_background_returns_empty(self):
        assert context._build_identity_sketch("   \n\t  ") == ""


# ---------------------------------------------------------------------------
# Background loading & caching
# ---------------------------------------------------------------------------

class TestLoadBackground:
    def test_returns_non_empty_background(self):
        bg = context.load_background()
        assert isinstance(bg, str)
        assert len(bg) > 0

    def test_results_are_cached(self):
        first = context.load_background()
        second = context.load_background()
        assert first is second


# ---------------------------------------------------------------------------
# System prompt minimization
# ---------------------------------------------------------------------------

class TestSystemPromptMinimization:
    def test_full_background_not_in_system_prompt(self):
        full_bg = context.load_background()
        prompt = context.TWIN_SYSTEM_PROMPT
        # The full background must never be embedded verbatim in the prompt.
        # The sketch is at most 400 chars, so a long background can never fit.
        if len(full_bg) > context._IDENTITY_SKETCH_CHARS:
            assert full_bg not in prompt
        # The opening identity line is allowed (it forms the sketch).
        assert "You represent:" in prompt

    def test_system_prompt_stays_compact(self):
        # The prompt should be far smaller than the full background would be.
        assert len(context.TWIN_SYSTEM_PROMPT) < 5000

    def test_sketch_only_in_identity_section(self):
        # Only the short sketch (<=400 chars) may appear in the prompt, while
        # the rest of the background text must never be embedded.
        full_bg = context.load_background()
        sketch = context._build_identity_sketch(full_bg)
        assert len(sketch) <= context._IDENTITY_SKETCH_CHARS
        assert sketch in context.TWIN_SYSTEM_PROMPT
        # If the background is longer than the sketch cap, the remainder must
        # not appear verbatim in the prompt.
        remainder = context._build_identity_sketch(full_bg[context._IDENTITY_SKETCH_CHARS:])
        if remainder:
            assert remainder not in context.TWIN_SYSTEM_PROMPT

    def test_retrieve_background_tool_referenced_in_system_prompt(self):
        assert "retrieve_background" in context.TWIN_SYSTEM_PROMPT

    def test_core_security_still_present(self):
        assert "NON-NEGOTIABLE" in context.TWIN_SYSTEM_PROMPT
        assert "S3. NO FABRICATION" in context.TWIN_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# retrieve_background tool integration
# ---------------------------------------------------------------------------

class TestRetrieveBackgroundTool:
    @pytest.mark.anyio
    async def test_tool_returns_full_background(self):
        result = await retrieve_background()
        assert isinstance(result, str)
        assert len(result) > 0
        # The tool returns the full background, not the truncated sketch.
        assert len(result) >= len(context.load_background())

    def test_tool_registered_in_map(self):
        assert "retrieve_background" in tools.TOOL_MAP

    def test_tool_present_in_openai_tool_schema(self):
        names = [t["function"]["name"] for t in tools.tools]
        assert "retrieve_background" in names

    def test_tool_schema_requires_no_arguments(self):
        for t in tools.tools:
            if t["function"]["name"] == "retrieve_background":
                assert t["function"]["parameters"] == {"type": "object", "properties": {}}
                break
        else:
            raise AssertionError("retrieve_background not found in tools schema")


def test_module_import_idempotent():
    """Re-importing the package modules must not raise."""
    importlib.reload(context)
    importlib.reload(tools)