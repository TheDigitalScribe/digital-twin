# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Reduced input-sandbox false positives on legitimate career questions.**
  The extraction pattern for `summarize` was narrowed so that asking the twin
  to summarize the _candidate's_ skills/experience (e.g. "summarize the
  candidate's experience", "summarize the strongest skills by backend, cloud,
  data, or AI focus") is no longer blocked, while genuine prompt-extraction
  phrasing ("summarize everything / the instructions / the prompt") is still
  rejected before ever reaching the model.
- **Loosened the `S2` core protocol phrasing** so the model treats summarizing
  and discussing the candidate's skills, experience, and focus areas (backend,
  cloud, data, AI/ML, DevOps) as in-scope, rather than over-refusing vaguely
  framed but legitimate career questions. The actual boundaries (no unrelated
  code/math/trivia, no secret leakage, no fabrication) are unchanged.
- `MAX_TOKENS_PARAM` setting (`max_tokens` | `max_completion_tokens`)
  selects the API parameter used for the per-response token cap. Defaults
  to `max_completion_tokens`, which newer OpenAI models (e.g. `gpt-5.x`,
  `o`-series) require; set `MAX_TOKENS_PARAM=max_tokens` for legacy chat
  models (`gpt-3.5`/`gpt-4`).

### Fixed

- LLM calls against newer models failed with
  `Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead.`
  The token cap is now forwarded under the correct parameter name.

## [0.3.0] - 2026-08-04

### Added

- **Production runtime**: FastAPI application via `digitaltwin.app.build_app`
  serving the Gradio UI at `/` plus `/healthz` (liveness) and `/metrics`
  (Prometheus text exposition). Entry point now launches under uvicorn with
  graceful shutdown (`timeout_graceful_shutdown`).
- **Observability**:
  - `digitaltwin/observability.py` — JSON structured logging with
    request-ID correlation (per-request `request_id` via contextvars),
    thread-safe Prometheus-style counters/gauges, token-usage recording.
  - `response.usage` from the LLM API is now captured and logged
    (`llm_usage` event) and exposed as `digitaltwin_llm_tokens_total`.
  - Security events increment counters and carry structured fields
    (`security_event`, `ip`, `reason`, `request_id`).
- **Reliability**:
  - `digitaltwin/persistence.py` — SQLite-backed durable storage for leads
    (`record_user_details`) and unknown questions
    (`record_unknown_question`). Pushover notifications remain best-effort
    on top; persistence never raises.
  - Conversation **history turns are now scanned** through the input
    guardrail before being sent to the model, blocking injection payloads
    hidden in older turns.
  - `max_output_tokens`, `llm_timeout_seconds`, and
    `max_background_chars` settings bound cost/latency (sent as
    `max_tokens`/`timeout` to the chat API; `retrieve_background` output is
    capped).
  - Lazy-init race fixed in `chat.py` (double-checked locking around the
    shared default handler).
  - `TWIN_BEHAVIOR` moved into `Settings` (added `twin_behavior` field),
    removing the raw `os.getenv` in `context.py`.
  - Shared connection-pooled `httpx.AsyncClient` for Pushover, keyed by the
    running event loop (safe under per-test loops and production).
- **Hardening**:
  - `Dockerfile`: copies `README.md` (fixes broken `pip install .`),
    adds `HEALTHCHECK`, writable `/data`, setuid stripping.
  - `.dockerignore` and hardened `docker-compose.yml`: non-root user,
    `no-new-privileges`, all caps dropped, read-only root fs, mem/pids
    limits, healthcheck, `./data` volume for the leads DB.
  - CI: Python 3.13 added to the matrix; new `pip-audit` job for CVE
    scanning; `Dependabot` config for pip + GitHub Actions.
- **Docs**: `SECURITY.md`, `CONTRIBUTING.md`, `docs/deployment.md`
  (reverse-proxy runbook), `LICENSE`, `CHANGELOG`.

### Changed

- Version bumped to `0.3.0` (single source in `pyproject.toml` +
  `digitaltwin/__init__.py`).
- `.env.example` documents `MAX_OUTPUT_TOKENS`, `MAX_BACKGROUND_CHARS`,
  `LLM_TIMEOUT_SECONDS`, `LEADS_DB_PATH`, `TWIN_BEHAVIOR`.

### Fixed

- Docker image could not build: `pip install .` failed because `README.md`
  (declared as the package readme) was not copied into the build context.
  The Dockerfile now copies it before installing.

## [0.2.0] - Initial version

- Defense-in-depth guardrails (input sandboxing, output scrubbing,
  non-overridable system prompt), context minimization, rate limiting,
  retries, Gradio UI, tests + CI.
