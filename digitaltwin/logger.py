"""Legacy logging compatibility shim.

All implementation lives in :mod:`digitaltwin.observability`. This module
re-exports the same public names the older ``logger.py`` exposed so existing
imports keep working without modification:

- ``setup_logging`` — configured once with the JSON formatter.
- ``get_logger`` — module-scoped logger factory.
- ``log_security_event`` — structured security event with a metric bump.
"""

from __future__ import annotations

from .observability import get_logger, log_security_event, setup_logging

__all__ = ["get_logger", "log_security_event", "setup_logging"]