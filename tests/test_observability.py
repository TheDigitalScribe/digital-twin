"""Tests for the observability layer: JSON logging, request IDs, and metrics."""

import json
import logging
import threading

import pytest

from digitaltwin.observability import (
    JSONFormatter,
    Metrics,
    _Gauge,
    get_logger,
    new_request_id,
    request_id,
)


class TestRequestId:
    def test_new_request_id_is_hex_str(self):
        rid = new_request_id()
        assert isinstance(rid, str)
        assert len(rid) == 32
        assert all(c in "0123456789abcdef" for c in rid)

    def test_request_id_token_reset(self):
        # Default is empty outside any handler.
        assert request_id.get() == ""
        token = request_id.set("abc")
        assert request_id.get() == "abc"
        request_id.reset(token)
        assert request_id.get() == ""


class TestJSONFormatter:
    @pytest.fixture
    def logger(self):
        logger = get_logger("test.observability")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        yield logger

    def _capture(self, logger):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = Capture()
        logger.addHandler(handler)
        return records, handler

    def test_formatter_emits_valid_json(self, logger):
        records, handler = self._capture(logger)
        try:
            logger.info("hello", extra={"event": "test"})
        finally:
            logger.removeHandler(handler)

        line = JSONFormatter().format(records[-1])
        payload = json.loads(line)
        assert payload["level"] == "INFO"
        assert payload["message"] == "hello"
        assert payload["event"] == "test"
        assert payload["ts"]

    def test_formatter_includes_request_id(self, logger):
        records, handler = self._capture(logger)
        try:
            token = request_id.set("req-123")
            try:
                logger.info("with rid")
            finally:
                request_id.reset(token)
        finally:
            logger.removeHandler(handler)

        line = JSONFormatter().format(records[-1])
        assert json.loads(line)["request_id"] == "req-123"

    def test_formatter_handles_exc_info(self, logger):
        records, handler = self._capture(logger)
        try:
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("failed")
        finally:
            logger.removeHandler(handler)

        line = JSONFormatter().format(records[-1])
        payload = json.loads(line)
        assert "exc_info" in payload
        assert "ValueError" in payload["exc_info"]


class TestMetricsThreadSafety:
    def test_counter_increments(self):
        Metrics.llm_calls.inc()
        before = Metrics.llm_calls.render("x", "h")[-1]
        Metrics.llm_calls.inc()
        after = Metrics.llm_calls.render("x", "h")[-1]
        # Values are cumulative floats rendered as ints.
        assert before != after

    def test_labelled_counter(self):
        Metrics.llm_tokens_total.inc(5, labels={"kind": "prompt"})
        lines = Metrics.llm_tokens_total.render("m", "h", ("kind",))
        assert any('kind="prompt"' in line for line in lines)

    def test_gauge_atomic_inc_dec(self):
        gauge = _Gauge()
        gauge.inc()
        gauge.inc()
        assert gauge.get() == 2.0
        gauge.dec()
        assert gauge.get() == 1.0
        gauge.dec(5)
        assert gauge.get() == 0.0  # never below zero

    def test_gauge_concurrent_inc_no_lost_updates(self):
        gauge = _Gauge()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    gauge.inc()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert gauge.get() == 800.0

    def test_render_prometheus_contains_type_headers(self):
        text = Metrics.render_prometheus()
        assert "# TYPE digitaltwin_messages_received_total counter" in text
        assert "# TYPE digitaltwin_inflight_requests gauge" in text

    def test_snapshot_is_json_serializable(self):
        snapshot = Metrics.snapshot()
        json.dumps(snapshot)  # must not raise