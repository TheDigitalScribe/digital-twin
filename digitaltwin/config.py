"""Application configuration.

Centralized settings loaded from environment variables (via .env for local
dev). Single source of truth for tunables so that no module reads
``os.getenv`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Model client settings (OpenAI-compatible). The base URL can be pointed at
# any OpenAI-compatible endpoint (Azure, local vLLM, etc.) for portability.
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- OpenAI / model client -------------------------------------------
    openai_api_key: SecretStr | None = Field(
        default=None, description="OpenAI (or compatible) API key."
    )
    openai_base_url: str | None = Field(
        default=None, description="Optional base URL for an OpenAI-compatible endpoint."
    )
    model_name: str = Field(default="gpt-5.4-mini", description="Chat model name.")

    # --- Conversation limits (cost / injection-surface control) ----------
    max_message_chars: int = Field(
        default=500, ge=1, description="Maximum characters per user message."
    )
    max_history_turns: int = Field(
        default=10, ge=0, description="Max prior conversation turns sent to the model."
    )
    max_output_tokens: int = Field(
        default=1024,
        ge=1,
        description="Maximum tokens the model may generate per response (cost/latency bound).",
    )
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = Field(
        default="max_completion_tokens",
        description=(
            "API parameter used to send the per-response token cap. Newer OpenAI "
            "models (e.g. gpt-5.x, o-series) require 'max_completion_tokens'; "
            "older chat models (gpt-3.5/4) require 'max_tokens'."
        ),
    )
    max_background_chars: int = Field(
        default=25000,
        ge=1,
        description="Maximum characters of the background (CV) returned by retrieve_background.",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Per-attempt timeout (seconds) for a single chat-completions call.",
    )

    # --- Rate limiting (per client IP) ------------------------------------
    rate_limit_requests: int = Field(
        default=5, ge=1, description="Max requests per IP per window."
    )
    rate_limit_window_seconds: int = Field(
        default=60, ge=1, description="Rate-limit window length in seconds."
    )

    # --- Web-origin restriction (CORS) -------------------------------------
    # Comma-separated list of allowed browser origins. Empty = any origin
    # (Gradio's default). Set this when embedding on a known domain.
    allowed_origins: tuple[str, ...] = Field(
        default=(),
        description="Comma-separated allowed browser origins for CORS.",
    )

    # --- Trusted proxies ---------------------------------------------------
    # Only these proxy addresses (or 0.0.0.0/0 to trust all — NOT recommended)
    # are allowed to set X-Forwarded-For. Everything else falls back to the
    # direct TCP peer address. Empty tuple = no proxy trusted.
    trusted_proxies: tuple[str, ...] = Field(
        default=(), description="Trusted proxy IPs for X-Forwarded-For handling."
    )

    # --- Background source -------------------------------------------------
    twin_background: str | None = Field(
        default=None, description="Full candidate background (CV) text."
    )
    twin_behavior: str | None = Field(
        default=None,
        description=(
            "Operator-tunable behavior text appended AFTER the core (non-overridable) "
            "security protocols. Can never weaken the core protocols."
        ),
    )

    # --- Achievements RAG -----------------------------------------------------
    # Lightweight semantic retrieval over the candidate's markdown achievement
    # files. Source markdown and the JSON index live under data/ (gitignored)
    # so private achievements never reach the public repo.
    rag_achievements_dir: str = Field(
        default="data/achievements",
        description="Directory of markdown achievement files to index.",
    )
    rag_index_path: str = Field(
        default="data/rag_index.json",
        description="JSON index file produced by `python -m digitaltwin.rag`.",
    )
    rag_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI-compatible embedding model used for the RAG index.",
    )
    rag_top_k: int = Field(
        default=3,
        ge=1,
        description="Number of retrieved achievement chunks returned per query.",
    )
    rag_chunk_chars: int = Field(
        default=1000,
        ge=100,
        description="Approximate character cap for a single achievement chunk.",
    )
    rag_min_score: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum cosine/dot-product similarity for a chunk to be returned by "
            "retrieval. Queries with no chunk above this threshold return a "
            "genuine no-match instead of generic filler."
        ),
    )
    rag_eager_enabled: bool = Field(
        default=True,
        description=(
            "Pre-fetch achievement context for achievement-like questions and "
            "inject it before the model call. When disabled, retrieval relies "
            "solely on the model choosing to call the retrieve_achievements tool."
        ),
    )

    # --- Logging ------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Root log level (noisier = more verbose)."
    )

    # --- Lead persistence ---------------------------------------------------
    # SQLite file path for durable lead/unknown-question storage. When unset,
    # leads are only logged (best-effort). Path is resolved relative to
    # the repository root.
    leads_db_path: str | None = Field(
        default="data/leads.db",
        description="SQLite database path for lead capture persistence.",
    )

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _parse_proxies(cls, v: object) -> object:
        """Allow a single comma-separated string or a list/tuple of IPs.

        Env vars are always strings; this keeps ``TRUSTED_PROXIES=10.0.0.1,10.0.0.2``
        usable without JSON-style quoting.
        """
        if isinstance(v, str) and v.strip():
            return tuple(part.strip() for part in v.split(",") if part.strip())
        return v

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v: object) -> object:
        """Allow a single comma-separated list of origins."""
        if isinstance(v, str) and v.strip():
            return tuple(part.strip() for part in v.split(",") if part.strip())
        return v


# ---------------------------------------------------------------------------
# Lightweight auto-validation of non-empty secret strings.
# ---------------------------------------------------------------------------


def _non_empty(v: str) -> str:
    if not v.strip():
        raise ValueError("value must not be empty")
    return v


NonEmptyStr = Annotated[str, AfterValidator(_non_empty)]


# ---------------------------------------------------------------------------
# Process bootstrap helpers.
# ---------------------------------------------------------------------------


def load_dotenv() -> None:
    """Load the .env file at the project root if present.

    Never overrides already-set environment variables; real deploy-time env
    vars win over the checked-in example file.
    """
    from dotenv import load_dotenv as _dotenv_load

    # The .env is resolved relative to the repository root (parent of the
    # package directory), so this works regardless of the CWD.
    root = Path(__file__).resolve().parent.parent
    _dotenv_load(root / ".env", override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (read env vars & the .env file once)."""
    load_dotenv()
    return Settings()


# ---------------------------------------------------------------------------
# SECRET_KEYS — single source of truth for the output scrubber.
# Keep the names in sync with the Settings fields above.
# ---------------------------------------------------------------------------
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "OPENAI_API_KEY",
        "TWIN_BACKGROUND",
        "TWIN_SYSTEM_PROMPT",
        "TWIN_BEHAVIOR",
    }
)
