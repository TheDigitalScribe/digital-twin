"""Gradio entry point for the Digital Twin chat app.

Kept deliberately thin: validation, rate limiting, and the LLM chat loop all
live in dedicated modules. This file wires them together behind a FastAPI app
that also serves operational endpoints (``/healthz`` and ``/metrics``) so the
container can be health-checked and scraped by monitoring tooling.

The app supports two launch modes:

- ``python -m digitaltwin.app``  — run the uvicorn server (production default)
- ``python -m uvicorn digitaltwin.app:build_app --factory`` — run under uvicorn
  with your own flags (workers, socket, etc.)
"""

from __future__ import annotations

import sys

import uvicorn
from fastapi import FastAPI, Response

from . import __version__
from .chat import handle_message
from .config import get_settings
from .logger import get_logger, setup_logging
from .observability import Metrics
from .styles import CSS, EXAMPLES, JS

logger = get_logger(__name__)

REQUIRED_ENV_VARS = ["OPENAI_API_KEY"]

# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def _validate_env() -> None:
    """Hard-fail fast with a clear message when required secrets are missing.

    Kept as an explicit startup check (rather than inside Settings) so the
    operator gets one actionable error line instead of a stack trace later.
    """
    if get_settings().openai_api_key is None:
        missing = ", ".join(REQUIRED_ENV_VARS)
        print(f"❌ CRITICAL ERROR: Missing environment variables: {missing}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Gradio interface
# ---------------------------------------------------------------------------


def build_interface():
    """Build (but do not launch) the Gradio ChatInterface.

    Returned as a ``gr.Blocks`` (actually a ChatInterface) so tests can
    inspect/reuse it without launching a server.
    """
    import gradio as gr

    return gr.ChatInterface(
        handle_message,
        examples=EXAMPLES,
        title="Digital Twin",
        description="Talk to my AI twin about my career",
        chatbot=gr.Chatbot(show_label=False),
    )


# ---------------------------------------------------------------------------
# FastAPI application (production mount point)
# ---------------------------------------------------------------------------


def build_app() -> FastAPI:
    """Assemble the production FastAPI application.

    Routes:
        /         -> Gradio chat UI (mounted at root)
        /healthz  -> liveness/readiness probe (returns {"status": "ok"})
        /metrics  -> Prometheus text exposition of process metrics

    The Gradio mount receives the custom CSS/JS/theme so the defacement work
    in ``styles.py`` keeps working under the FastAPI deployment.
    """
    import gradio as gr

    app = FastAPI(
        title="Digital Twin",
        version=__version__,
        # Disable interactive API docs in production (reduce attack surface).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        # Static liveness probe: the process is up and the route table is
        # serving. Readiness (dependencies like the API key) is checked at
        # startup via _validate_env() in main(); for containerized deploys
        # the HEALTHCHECK uses this endpoint.
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(
            content=Metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    interface = build_interface()
    app = gr.mount_gradio_app(
        app,
        interface,
        path="/",
        footer_links=[],
        css=CSS,
        js=JS,
        theme=gr.themes.Base(),
        # Never surface the interactive API docs / playground in production.
        show_error=False,
    )
    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the production server."""
    _validate_env()
    setup_logging(get_settings().log_level)

    logger.info(
        "starting server",
        extra={
            "event": "server_start",
            "host": "0.0.0.0",
            "port": 7860,
            "version": __version__,
        },
    )
    uvicorn.run(
        "digitaltwin.app:build_app",
        factory=True,
        host="0.0.0.0",
        port=7860,
        log_level="warning",
        # Graceful shutdown: allow in-flight requests to finish before exit.
        timeout_graceful_shutdown=10.0,
    )


if __name__ == "__main__":
    main()