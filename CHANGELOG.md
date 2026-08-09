# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Semantic RAG over achievement files.** `digitaltwin/rag.py` chunks and
  embeds markdown achievement files into a lightweight JSON index
  (`python -m digitaltwin.rag`). The `retrieve_achievements` tool, plus an
  optional eager pre-fetch path, answers achievement-specific questions
  without a vector database (`RAG_*` settings; see `.env.example`).
- **Render deployment.** `render.yaml` Blueprint and `docker-entrypoint.sh`
  that stage a mounted secrets file and (re)build the RAG index at container
  start.
- `digitaltwin_llm_tokens_total` is now rendered in `/metrics`; request-ID
  injection switched from a custom Logger subclass to
  `logging.setLogRecordFactory`.

### Changed

- **App is now stateless.** Lead capture and SQLite persistence were removed
  (see Removed); `docker-compose.yml` no longer mounts a `data/` volume and
  the `Dockerfile` no longer creates `/data`.
- Per-IP rate limit raised from 5 to 30 requests per minute (default).
- Default model changed back to `gpt-4.1-mini`; chat UI styling reworked
  (including bullet-point rendering fixes).
- System prompt is now assembled lazily (cached) instead of at import time;
  tool and RAG registries deduplicated into single definitions.
- `MODEL_NAME` references fixed in docs and `.env.example`.
- README rewritten; live demo link added.

### Fixed

- **`MAX_OUTPUT_TOKENS` silently ignored with the default `gpt-4.1-mini`**
  model. The cap was being sent as `max_completion_tokens` (the previous
  default), which legacy chat models ignore — so responses could exceed the
  configured limit. The token-cap parameter is now auto-selected from the
  model name (`max_tokens` for `gpt-3.5/4/4o/4.1`, `max_completion_tokens`
  for `gpt-5.x`/`o`-series), with `MAX_TOKENS_PARAM` retained as an explicit
  override.

### Removed

- **Lead capture & SQLite persistence.** `digitaltwin/persistence.py`, the
  `record_user_details` / `record_unknown_question` tools, the `LEADS_DB_PATH`
  setting, Pushover notifications, and the `data/` volume were removed.
  Render's free tier is ephemeral, so visitor data cannot be persisted; the
  app no longer needs a volume or database.
- `./data` volume removed from `docker-compose.yml`; `/data` directory removed
  from the `Dockerfile`.

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
- **Hardening**:
  - `Dockerfile`: copies `README.md` (fixes broken `pip install .`),
    adds `HEALTHCHECK`, setuid stripping.
  - `.dockerignore` and hardened `docker-compose.yml`: non-root user,
    `no-new-privileges`, all caps dropped, read-only root fs, mem/pids
    limits, healthcheck.
  - CI: Python 3.13 added to the matrix; new `pip-audit` job for CVE
    scanning; `Dependabot` config for pip + GitHub Actions.
- **Docs**: `SECURITY.md`, `CONTRIBUTING.md`, `docs/deployment.md`
  (reverse-proxy runbook), `LICENSE`, `CHANGELOG`.

### Changed

- Version bumped to `0.3.0` (single source in `pyproject.toml` +
  `digitaltwin/__init__.py`).
- `.env.example` documents `MAX_OUTPUT_TOKENS`, `MAX_BACKGROUND_CHARS`,
  `LLM_TIMEOUT_SECONDS`, `TWIN_BEHAVIOR`.
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

- Docker image could not build: `pip install .` failed because `README.md`
  (declared as the package readme) was not copied into the build context.
  The Dockerfile now copies it before installing.
- LLM calls against newer models failed with
  `Unsupported parameter: 'max_tokens' ... Use 'max_completion_tokens' instead.`
  The token cap is now forwarded under the correct parameter name.

## [0.2.0] - Initial version

- Defense-in-depth guardrails (input sandboxing, output scrubbing,
  non-overridable system prompt), context minimization, rate limiting,
  retries, Gradio UI, tests + CI.
