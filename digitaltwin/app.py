"""Gradio entry point for the Digital Twin chat app.

Kept deliberately thin: validation, rate limiting, and the LLM chat loop all
live in dedicated modules. This file only wires them together behind the
Gradio UI.
"""

from __future__ import annotations

import sys

import gradio as gr

from .chat import handle_message
from .config import get_settings
from .logger import setup_logging
from .styles import CSS, EXAMPLES, JS

REQUIRED_ENV_VARS = ["OPENAI_API_KEY"]


def _validate_env() -> None:
    """Hard-fail fast with a clear message when required secrets are missing.

    Kept as an explicit startup check (rather than inside Settings) so the
    user gets one actionable error line instead of a stack trace later.
    """
    if get_settings().openai_api_key is None:
        missing = ", ".join(REQUIRED_ENV_VARS)
        print(f"❌ CRITICAL ERROR: Missing environment variables: {missing}")
        sys.exit(1)


def build_interface() -> gr.Blocks:
    """Build (but do not launch) the Gradio interface.

    Returned as a ``gr.Blocks`` so tests can inspect/reuse it without
    launching a server.
    """
    return gr.ChatInterface(
        handle_message,
        examples=EXAMPLES,
        title="Digital Twin",
        description="Talk to my AI twin about my career",
        chatbot=gr.Chatbot(show_label=False),
    )


if __name__ == "__main__":
    _validate_env()
    setup_logging(get_settings().log_level)
    build_interface().queue().launch(
        css=CSS,
        js=JS,
        theme=gr.themes.Base(),
    )