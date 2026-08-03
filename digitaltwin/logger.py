"""Structured logging setup for the Digital Twin app.

Provides a single ``get_logger`` factory so every module logs consistently
with timestamps and level. Security events are logged through the same
pipeline so they land in the same stream as application events.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once with a simple structured formatter.

    ``level`` may be any of DEBUG/INFO/WARNING/ERROR/CRITICAL.
    Safe to call multiple times (idempotent).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Don't double-log through inherited handlers (e.g. from libraries).
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger for ``name`` (defaults to the calling module name)."""
    return logging.getLogger(name or __name__)


def log_security_event(logger: logging.Logger, event: str, **details: Any) -> None:
    """Log a security event with structured detail fields.

    Example::

        log_security_event(logger, "input_blocked", ip="1.2.3.4", reason="extraction")
    """
    fields = " ".join(f"{k}={v!r}" for k, v in details.items())
    logger.warning("SECURITY: %s %s", event, fields)