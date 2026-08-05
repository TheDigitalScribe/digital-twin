"""Structured logging and lightweight metrics for the Digital Twin app.

Provides:
- ``JSONFormatter`` / ``setup_logging``: machine-parseable JSON log lines with
  optional request-scoped context fields.
- ``request_id``: a context variable carrying the current request's trace ID so
  every log line emitted during one user turn can be correlated.
- ``Metrics``: a small set of process-wide Prometheus-style counters/gauges
  (thread-safe) that a ``/metrics`` endpoint can scrape, without pulling in a
  heavy metrics dependency.

Design notes
------------
* Metrics are deliberately minimal: counters that answer "how many X happened"
  and gauges for things like in-flight requests. Histograms (latency buckets)
  are out of scope; latency is surfaced through structured logs instead.
* Structured fields are passed via logging ``extra=`` kwargs; Python flattens
  them onto the LogRecord as attributes, so the formatter scans the record's
  ``__dict__`` for safe, non-reserved names and merges them into the payload.
* The request id is captured onto the record at *creation* time (inside the
  request's context) by ``_RequestIdInjector`` so it survives buffered or
  queued handlers that format records later.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------

# Carries the current request's trace id through async handlers. A fresh UUID
# is generated per incoming request; handlers and tools log with it attached.
request_id: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """Return a fresh, URL-safe trace id for the current request."""
    return uuid4().hex


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

# Safe attribute names for structured fields (via logging ``extra=``).
_SAFE_ATTR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Standard LogRecord attributes we never duplicate into the JSON payload.
_RESERVED_ATTRS = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "asctime",
    }
)


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Standard-logging ``extra={"key": value}`` kwargs are flattened onto the
    LogRecord as attributes (e.g. ``record.event``), so we scan the record's
    ``__dict__`` for safe, non-reserved attributes and merge them into the
    payload. Also embeds the current request id when set.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge structured fields passed via logging ``extra=``. The request
        # id is captured onto the record at dispatch time (see
        # ``_RequestIdInjector``) so it survives buffered/queued handlers that
        # format records later, possibly outside the request's context.
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key in payload:
                continue
            if not _SAFE_ATTR.match(key):
                continue
            payload[key] = (
                value
                if isinstance(value, (str, int, float, bool)) or value is None
                else str(value)
            )

        # Exceptions: keep the traceback as a field so JSON stays parseable.
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class _RequestIdInjector(logging.Logger):
    """Logger subclass that stamps the current request id onto each record.

    The id is captured when the record is *created* (inside the request's
    context) rather than when it is formatted, so even handlers that batch or
    re-format records later keep the correct trace id.
    """

    def makeRecord(  # type: ignore[override]
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: tuple[Any, ...],
        exc_info: Any,
        func: str | None = None,
        extra: dict[str, Any] | None = None,
        sinfo: Any = None,
    ) -> logging.LogRecord:
        record = super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )
        rid = request_id.get()
        if rid:
            record.request_id = rid  # type: ignore[attr-defined]
        return record


# Make ``logging.getLogger`` return the request-id-aware subclass. This is
# safe for third-party modules too: the injector is a no-op outside a request
# context.
logging.setLoggerClass(_RequestIdInjector)


_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once with the JSON formatter.

    Idempotent; safe to call from tests and the app entry point.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Don't double-log through inherited handlers (e.g. from libraries).
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a request-id-aware logger for ``name`` (defaults to module name)."""
    return logging.getLogger(name or __name__)


def log_security_event(logger: logging.Logger, event: str, **details: Any) -> None:
    """Log a security event with structured detail fields and a metric bump.

    Example::

        log_security_event(logger, "input_blocked", ip="1.2.3.4", reason="extraction")
    """
    Metrics.security_events.inc(labels={"kind": event})
    extras = {"event": "security", "security_event": event}
    extras.update(details)
    logger.warning("security_event", extra=extras)


def record_llm_usage(
    logger: logging.Logger,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str,
    retries: int,
) -> None:
    """Record token usage for a single chat-completions response.

    These numbers come from the ``usage`` field of the API response. They are
    recorded as cumulative counters (labeled by kind) and logged as a
    structured event so cost can be tracked per model over time.
    """
    Metrics.llm_tokens_total.inc(prompt_tokens, labels={"kind": "prompt"})
    Metrics.llm_tokens_total.inc(completion_tokens, labels={"kind": "completion"})
    logger.info(
        "llm_usage",
        extra={
            "event": "llm_usage",
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "retries": retries,
        },
    )


# ---------------------------------------------------------------------------
# Minimal Prometheus-style metrics
# ---------------------------------------------------------------------------

class _Counter:
    """Thread-safe monotonically-increasing counter with optional labels."""

    __slots__ = ("_labels", "_lock", "_value")

    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()
        self._labels: dict[str, float] = {}

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            if labels:
                key = _label_key(labels)
                self._labels[key] = self._labels.get(key, 0.0) + amount
            else:
                self._value += amount

    def render(self, name: str, help_text: str, label_names: tuple[str, ...] | None = None) -> list[str]:
        lines = [f"# HELP {name} {help_text}", f"# TYPE {name} counter"]
        with self._lock:
            if not self._labels:
                lines.append(f"{name} {_fmt(self._value)}")
            else:
                for key, value in sorted(self._labels.items()):
                    labels = _unlabel_key(key)
                    rendered = ", ".join(f'{k}="{v}"' for k, v in labels.items())
                    lines.append(f"{name}{{{rendered}}} {_fmt(value)}")
        return lines


class _Gauge:
    """Thread-safe gauge (can go up and down)."""

    __slots__ = ("_lock", "_value")

    def __init__(self) -> None:
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = float(value)

    def get(self) -> float:
        with self._lock:
            return self._value

    def inc(self, amount: float = 1.0) -> None:
        """Atomically increment the gauge (avoids read-modify-write races)."""
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        """Atomically decrement the gauge, never going below zero."""
        with self._lock:
            self._value = max(0.0, self._value - amount)

    def render(self, name: str, help_text: str) -> list[str]:
        with self._lock:
            return [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", f"{name} {_fmt(self._value)}"]


def _fmt(value: float) -> str:
    return f"{value:.0f}" if value.is_integer() else f"{value:.6f}"


def _label_key(labels: dict[str, str]) -> str:
    return json.dumps(labels, sort_keys=True)


def _unlabel_key(key: str) -> dict[str, str]:
    return dict(json.loads(key))


class Metrics:
    """Process-wide metric registry.

    All methods are thread-safe. ``render_prometheus()`` returns the text
    exposition format one could serve at ``/metrics``.
    """

    # Counters
    messages_received = _Counter()
    rate_limited = _Counter()
    input_blocked = _Counter()
    output_scrubbed = _Counter()
    llm_calls = _Counter()
    llm_errors = _Counter()
    tool_calls = _Counter()
    tool_errors = _Counter()
    unmatched_questions = _Counter()
    leads_recorded = _Counter()
    security_events = _Counter()
    llm_tokens_total = _Counter()

    # Gauges
    inflight_requests = _Gauge()
    background_cache_size = _Gauge()

    # Precomputed metadata used for rendering.
    _COLLECTORS: tuple[tuple[str, Any, str, tuple[str, ...] | None], ...] = (
        ("digitaltwin_messages_received_total", messages_received, "User messages received.", None),
        ("digitaltwin_rate_limited_total", rate_limited, "Requests dropped by rate limiting.", None),
        ("digitaltwin_input_blocked_total", input_blocked, "Messages blocked by input sandboxing.", None),
        ("digitaltwin_output_scrubbed_total", output_scrubbed, "Model replies scrubbed by output guardrail.", None),
        ("digitaltwin_llm_calls_total", llm_calls, "Chat completions API calls (including retries).", None),
        ("digitaltwin_llm_errors_total", llm_errors, "LLM API calls that failed after retries.", None),
        (
            "digitaltwin_tool_calls_total",
            tool_calls,
            "Tool invocations dispatched, by tool name.",
            ("tool",),
        ),
        ("digitaltwin_tool_errors_total", tool_errors, "Tool invocations that errored.", None),
        ("digitaltwin_unmatched_questions_total", unmatched_questions, "Unknown questions recorded.", None),
        ("digitaltwin_leads_recorded_total", leads_recorded, "Leads captured via record_user_details.", None),
        (
            "digitaltwin_security_events_total",
            security_events,
            "Security events by kind (input_blocked, output_scrubbed, rate_limited).",
            ("kind",),
        ),
    )

    _GAUGES: tuple[tuple[str, Any, str], ...] = (
        ("digitaltwin_inflight_requests", inflight_requests, "Requests currently being processed."),
        ("digitaltwin_background_cache_size", background_cache_size, "Bytes of background (CV) text in cache."),
    )

    @classmethod
    def render_prometheus(cls) -> str:
        """Return the Prometheus text exposition of all registered metrics."""
        lines: list[str] = []
        for name, collector, help_text, label_names in cls._COLLECTORS:
            lines.extend(collector.render(name, help_text, label_names))
        for name, collector, help_text in cls._GAUGES:
            lines.extend(collector.render(name, help_text))
        return "\n".join(lines) + "\n"

    @classmethod
    def snapshot(cls) -> dict[str, Any]:
        """Return a JSON-serializable snapshot (for the /_internal status route)."""
        result: dict[str, Any] = {}
        for name, collector, *_ in cls._COLLECTORS:
            result[name] = collector.render(name, "n/a")
        for name, collector, *_ in cls._GAUGES:
            result[name] = collector.render(name, "n/a")
        return {"metrics": result, "generated_at": time.time()}