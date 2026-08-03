"""Tests for the LLM service: retry logic, tool loop, and error handling."""

import json
from types import SimpleNamespace

import pytest

from digitaltwin.config import Settings
from digitaltwin.llm import LLMError, LLMService

from digitaltwin.tools import tools


class FakeError(Exception):
    def __init__(self, status_code=None, response=None):
        self.status_code = status_code
        self.response = response
        super().__init__("fake error")


class FakeResponse:
    def __init__(self, headers=None):
        self.headers = headers or {}


class FakeChoice:
    def __init__(self, finish_reason, content=None, tool_calls=None, message=None):
        self.finish_reason = finish_reason
        # A simple namespace mimicking the OpenAI ChatCompletionMessage.
        self.message = message or SimpleNamespace(content=content, tool_calls=tool_calls)


class FakeCompletion:
    def __init__(self, choice):
        self.choices = [choice]


class FakeChatCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if isinstance(self._responses[0], Exception):
            exc = self._responses.pop(0)
            raise exc
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeChatCompletions(responses))


def make_service(responses, **settings_overrides):
    settings = Settings(**settings_overrides)
    return LLMService(settings=settings, client=FakeClient(responses))


def tool_call_message(name="retrieve_background", arguments=None, call_id="call_1"):
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(
                    name=name, arguments=json.dumps(arguments or {})
                ),
            )
        ],
    )


class TestRetryLogic:
    def test_should_retry_on_5xx_and_429(self):
        assert LLMService._should_retry(FakeError(status_code=500)) is True
        assert LLMService._should_retry(FakeError(status_code=429)) is True
        assert LLMService._should_retry(FakeError(status_code=400)) is False

    def test_should_retry_on_network_errors(self):
        assert LLMService._should_retry(ConnectionError()) is True
        assert LLMService._should_retry(TimeoutError()) is True
        assert LLMService._should_retry(OSError()) is True
        assert LLMService._should_retry(ValueError()) is False

    def test_retry_delay_honors_retry_after_header(self):
        exc = FakeError(status_code=429, response=FakeResponse(headers={"retry-after": "7"}))
        assert LLMService._retry_delay(exc, 0) == 7.0

    def test_retry_delay_exponential(self):
        # Without Retry-After, delay grows with attempt (with jitter).
        d0 = LLMService._retry_delay(FakeError(status_code=500), 0)
        d3 = LLMService._retry_delay(FakeError(status_code=500), 3)
        assert 0 <= d0 < 8.5  # 2^0 + jitter
        assert 3.5 <= d3 < 8.5  # 2^3 capped at 30, jitter 0..0.5


class TestRunChat:
    @pytest.mark.anyio
    async def test_simple_chat_returns_content(self):
        service = make_service([FakeCompletion(FakeChoice("stop", content="Hello!"))])
        reply = await service.run_chat([{"role": "user", "content": "hi"}], retries=0)
        assert reply == "Hello!"

    @pytest.mark.anyio
    async def test_tool_loop_resolves_and_continues(self):
        # First response requests a tool call; second returns final content.
        responses = [
            FakeCompletion(FakeChoice("tool_calls", message=tool_call_message())),
            FakeCompletion(FakeChoice("stop", content="Final answer")),
        ]
        service = make_service(responses)
        reply = await service.run_chat([{"role": "user", "content": "about me"}], retries=0)
        assert reply == "Final answer"
        assert service.client.chat.completions.calls == 2

    @pytest.mark.anyio
    async def test_retries_then_raises_llm_error(self):
        service = make_service(
            [FakeError(status_code=500), FakeError(status_code=500), FakeError(status_code=500)],
        )
        with pytest.raises(LLMError):
            await service.run_chat([{"role": "user", "content": "hi"}], retries=2)

    @pytest.mark.anyio
    async def test_non_retryable_error_raises_immediately(self):
        service = make_service([FakeError(status_code=400)])
        with pytest.raises(LLMError):
            await service.run_chat([{"role": "user", "content": "hi"}])

    @pytest.mark.anyio
    async def test_tool_loop_cap_raises(self):
        # max_tool_rounds=1: a second tool_calls response trips the guard.
        responses = [
            FakeCompletion(FakeChoice("tool_calls", message=tool_call_message())),
            FakeCompletion(FakeChoice("tool_calls", message=tool_call_message())),
        ]
        service = make_service(responses)
        service.max_tool_rounds = 1
        with pytest.raises(LLMError):
            await service.run_chat([{"role": "user", "content": "hi"}], retries=0)

    @pytest.mark.anyio
    async def test_tools_schema_passed_to_client(self):
        seen = {}

        class CapturingClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

            async def _create(self, **kwargs):
                seen.update(kwargs)
                return FakeCompletion(FakeChoice("stop", content="ok"))

        service = LLMService(settings=Settings(), client=CapturingClient())
        await service.run_chat([{"role": "user", "content": "hi"}], retries=0)
        assert seen["tools"] == tools
        assert seen["model"] == "gpt-5.4-mini"