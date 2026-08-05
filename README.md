# Digital Twin

A self-representing AI chat agent that answers career questions on a candidate — built on Gradio + OpenAI function calling with **defense-in-depth prompt-injection guardrails** and a **context-minimization architecture**.

> **Why this project?** Most AI portfolio apps are thin wrappers around an API key. This one treats the model as an untrusted component and applies security engineering principles (least privilege, defense-in-depth, failure containment) to LLM application design.

---

## Highlights

- **Three independent guardrail layers**
  1. **Non-overridable system prompt** — hardcoded security protocols that env vars and operator config can never weaken.
  2. **Input sandboxing (pre-model)** — heuristic scanner blocking prompt injection / prompt-extraction _before_ the request reaches the model. Detects homoglyphs, zero-width characters, letter-spacing, and fragment-fusion obfuscations. Now also scans conversation **history** turns for injected payloads.
  3. **Output scrubbing (post-model)** — scans the model's reply for leaked secrets, prompt text, API-key-shaped tokens, and internal tool names before display.
- **Context minimization** — the full CV is never embedded in the system prompt; only a ≤400-char identity sketch lives there. The full background is fetched **on demand** via the `retrieve_background` tool (output capped by `MAX_BACKGROUND_CHARS`), so a leaked prompt exposes the bare minimum.
- **Semantic RAG over work achievements** — markdown achievement files are chunked, embedded, and queried on demand via the `retrieve_achievements` tool, so the twin can answer specific questions about accomplishments and metrics without a vector database. The achievement source files and index live under `data/` (gitignored), keeping them out of the public repo.
- **Function-calling tools with runtime Pydantic argument validation** — the model's JSON output is never trusted blindly.
- **Production readiness**
  - FastAPI app (`digitaltwin.app.build_app`) serving `/` (Gradio), `/healthz` (liveness), `/metrics` (Prometheus).
  - Structured JSON logs with per-request `request_id` correlation; LLM token-usage tracking (`/metrics` → `digitaltwin_llm_tokens_total`).
  - Durable SQLite storage for captured leads and unknown questions.
  - TTL-based per-IP rate limiting (trusted-proxy aware), bounded conversation history, exponential-backoff retries with `Retry-After` support, token-cap + timeout bounds, graceful degradation, graceful shutdown.
  - Hardened container: non-root user, read-only rootfs, dropped capabilities, mem/pids limits, healthcheck.

- **CI**: tests on Python 3.11/3.12/3.13 with a ≥80% coverage gate, ruff, mypy, and a `pip-audit` CVE scan on every push/PR.

---

## Architecture

```
                       ┌─────────────────────────────────────────────┐
  User message ──────► │  1. Request-ID generation                  │
                       │  2. Trusted-proxy IP resolution             │
                       │  3. TTL rate limiting (per IP)              │
                       │  4. Validation (empty / length caps)        │
                       │  5. LAYER A: input sandboxing (msg+history) │
                       │  6. History bounding (max turns)            │
                       │  7. Model call + tool loop (retries)        │
                       │  8. LAYER B: output scrubbing               │
                       └─────────────────────────────────────────────┘
                                      │
                        ┌─────────────▼─────────────┐
                        │  FastAPI (uvicorn)         │
                        │  /        Gradio UI        │
                        │  /healthz  liveness probe  │
                        │  /metrics  Prometheus      │
                        └────────────────────────────┘
```

| Module                         | Responsibility                                                        |
| ------------------------------ | --------------------------------------------------------------------- |
| `digitaltwin/app.py`           | FastAPI app, uvicorn entry point, `/healthz` + `/metrics`, UI mount   |
| `digitaltwin/chat.py`          | End-to-end request handler (steps 1–8)                                |
| `digitaltwin/llm.py`           | OpenAI-compatible client, retry/timeout logic, tool loop, token usage |
| `digitaltwin/tools.py`         | Tool schemas + async implementations + argument validation            |
| `digitaltwin/rag.py`           | Lightweight semantic RAG (markdown chunking, embeddings, JSON index)  |
| `digitaltwin/security.py`      | Layer A (input) + Layer B (output) guardrails                         |
| `digitaltwin/context.py`       | System prompt assembly + context minimization                         |
| `digitaltwin/config.py`        | Centralized, validated settings (pydantic-settings)                   |
| `digitaltwin/rate_limiter.py`  | TTL-bucketed per-client rate limiting                                 |
| `digitaltwin/persistence.py`   | SQLite persistence for leads & unknown questions                      |
| `digitaltwin/observability.py` | Structured JSON logs, request IDs, Prometheus-style metrics           |
| `digitaltwin/logger.py`        | Compatibility shim (re-exports `observability`)                       |
| `digitaltwin/styles.py`        | CSS/JS theming for the Gradio UI                                      |

---

## Security Model

The app treats the LLM as an **untrusted component**. Three independent layers provide defense-in-depth:

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER A (input)     LAYER B (output)    SYSTEM PROMPT       │
│  is_suspicious       scrub_output        _CORE_SECURITY      │
│   · extraction       · secret name leaks  · S1 no secrets   │
│   · role injection   · API-key tokens     · S2 no unrelated │
│   · obfuscations     · prompt text        · S3 no fabricate │
│     (homoglyph,      · internal tool      (non-negotiable)  │
│      zero-width,       names                                 │
│      letter-space)                                          │
└─────────────────────────────────────────────────────────────┘
```

- The **system prompt** is the strongest guarantee but is not a technical control (it can be coaxed).
- The **input sandbox** catches known attacks before the model sees them — including attacks hidden in earlier conversation turns.
- The **output scrubber** catches successful extractions on the way out — including paraphrased and obfuscated leaks.

### Context Minimization (Least Privilege)

```
System prompt (always in context)       Retrieved on demand (tool only)
┌──────────────────────────────┐       ┌──────────────────────────────┐
│ Role + Identity sketch        │       │ Full background (CV)         │
│ (≤400 chars of the CV)        │       │   - skills / experience      │
│ + Core security protocols     │ ────► │   - education / certs        │
│ + Behavior rules              │       │   - projects / contact       │
└──────────────────────────────┘       └──────────────────────────────┘
```

The `retrieve_background` tool response is capped at `MAX_BACKGROUND_CHARS`, so a single tool call cannot blow up the context window/cost. See [SECURITY.md](SECURITY.md) for the full threat model and known limitations.

---

## Quick Start

### Local

```bash
git clone https://github.com/TheDigitalScribe/digtal-twin.git
cd digtal-twin

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install ".[dev]"

cp .env.example .env             # then fill in OPENAI_API_KEY + TWIN_BACKGROUND

# Optional: index your achievement markdown files (data/achievements/*.md) for semantic RAG
python -m digitaltwin.rag

python -m digitaltwin.app
```

Open http://localhost:7860 — the app serves `/healthz` and `/metrics` on the same port.

### Docker

```bash
cp .env.example .env             # fill in your values
docker compose up --build
```

`docker compose ps` should report `(healthy)` once the service is up.

### Deployment

See [docs/deployment.md](docs/deployment.md) — reverse-proxy/TLS setup (Caddy & nginx), monitoring alerts, scaling notes, backups, and rollback.

---

## Configuration

See [`.env.example`](.env.example) for the full list. Key settings:

| Variable                    | Required | Default                  | Description                                                                                                      |
| --------------------------- | -------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY`            | ✅       | —                        | OpenAI (or compatible) API key                                                                                   |
| `TWIN_BACKGROUND`           | ✅       | —                        | Full candidate background (CV) text                                                                              |
| `MODEL_NAME`                |          | `gpt-5.4-mini`           | Chat model (must support tools)                                                                                  |
| `MAX_MESSAGE_CHARS`         |          | `500`                    | Per-message length cap                                                                                           |
| `MAX_HISTORY_TURNS`         |          | `10`                     | Conversation turns sent to model                                                                                 |
| `MAX_OUTPUT_TOKENS`         |          | `1024`                   | Per-response token cap (cost/latency bound)                                                                      |
| `MAX_TOKENS_PARAM`          |          | `max_completion_tokens`  | API param used for the token cap (`max_completion_tokens` for newer models, `max_tokens` for legacy chat models) |
| `MAX_BACKGROUND_CHARS`      |          | `25000`                  | Cap on `retrieve_background` output                                                                              |
| `RAG_ACHIEVEMENTS_DIR`      |          | `data/achievements`      | Directory of markdown achievement files to index (gitignored)                                                    |
| `RAG_INDEX_PATH`            |          | `data/rag_index.json`    | JSON vector index produced by `python -m digitaltwin.rag` (gitignored)                                           |
| `RAG_EMBEDDING_MODEL`       |          | `text-embedding-3-small` | Embedding model used to build/query the index                                                                    |
| `RAG_TOP_K`                 |          | `3`                      | Number of achievement chunks returned per retrieval                                                              |
| `RAG_CHUNK_CHARS`           |          | `1000`                   | Approximate character cap for a single achievement chunk                                                         |
| `RAG_MIN_SCORE`             |          | `0.25`                   | Minimum similarity for a chunk to be returned (filters generic filler)                                           |
| `RAG_EAGER_ENABLED`         |          | `true`                   | Pre-fetch achievement context before the model call (recommended)                                                |
| `LLM_TIMEOUT_SECONDS`       |          | `60`                     | Per-attempt timeout for chat-completions calls                                                                   |
| `RATE_LIMIT_REQUESTS`       |          | `5`                      | Requests per IP per window                                                                                       |
| `RATE_LIMIT_WINDOW_SECONDS` |          | `60`                     | Rate-limit window                                                                                                |
| `TRUSTED_PROXIES`           |          | empty                    | Comma-separated proxy IPs allowed to set `X-Forwarded-For`                                                       |
| `LEADS_DB_PATH`             |          | `data/leads.db`          | SQLite path for durable lead/question storage                                                                    |
| `TWIN_BEHAVIOR`             |          | default behavior         | Operator-tunable behavior text (never weakens core rules)                                                        |
| `LOG_LEVEL`                 |          | `INFO`                   | `DEBUG` / `INFO` / `WARNING` / `ERROR`                                                                           |

> **Security note:** always set `TRUSTED_PROXIES` when running behind a reverse proxy; otherwise `X-Forwarded-For` is ignored and rate limiting keys on the proxy's IP. Never use `0.0.0.0/0` in a multi-tenant deployment.

---

## Achievements RAG

The twin can answer questions about specific work achievements (accomplishments, results, metrics, project impact) via semantic retrieval — without shipping a vector database.

```
data/achievements/*.md  ──►  chunk_markdown()  ──►  embed  ──►  data/rag_index.json
                                                                      │
visitor question ──► embed ──► top-k dot-product ──► retrieve_achievements tool ──► LLM answer
```

- **One command to build the index:** `python -m digitaltwin.rag`
- **Chunks** are split on `##` headings and bounded by `RAG_CHUNK_CHARS`.
- **Retrieval** is on demand: the `retrieve_achievements` tool embeds the visitor's question and returns the top-k most similar chunks — the full dataset is never injected into the prompt (context minimization).
- **Graceful degradation:** if the index is missing (e.g. fresh clone), the tool returns a friendly "run `python -m digitaltwin.rag`" message instead of crashing.
- **Privacy:** your achievement markdown and the JSON index live in `data/` — already gitignored, so they never reach the public repository. The index file is a deliberately simple JSON list of `{text, embedding}` pairs: for a personal dataset a single in-memory JSON file is the right-sized store. If the dataset ever grows beyond ~50k chunks, swap the storage layer for a vector DB behind the same `query_index`/`build_index` interface.

---

## Observability

- **Logs**: every line is a JSON object on stdout with `ts`, `level`, `logger`, `message`, and optional structured fields (`event`, `ip`, `reason`, ...). A `request_id` is attached to every log emitted during a user turn — correlate on it.
- **Metrics** (`/metrics`, Prometheus text format): request counters (`messages_received_total`, `rate_limited_total`, ...), LLM cost (`llm_tokens_total{kind="prompt|completion"}`), tool/security counters, in-flight gauge.
- Example security log:
  ```json
  {
    "ts": "2026-08-04T19:00:00.123Z",
    "level": "WARNING",
    "logger": "digitaltwin.chat",
    "message": "security_event",
    "event": "security",
    "security_event": "input_blocked",
    "ip": "203.0.113.5",
    "reason": "suspicious_request",
    "request_id": "a1b2c3..."
  }
  ```

---

## Tooling

```bash
python -m pytest                     # run the test suite
python -m pytest --cov=digitaltwin --cov-report=term-missing   # with coverage
ruff check digitaltwin tests         # lint
mypy digitaltwin                     # type-check
```

CI (GitHub Actions) runs tests on Python 3.11/3.12/3.13 with a **≥80% coverage gate**, ruff, mypy, and a **pip-audit** dependency scan on every push and PR: [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Project docs

- [SECURITY.md](SECURITY.md) — threat model, known limitations, disclosure policy.
- [CONTRIBUTING.md](CONTRIBUTING.md) — development workflow & standards.
- [docs/deployment.md](docs/deployment.md) — production deployment runbook.
- [CHANGELOG.md](CHANGELOG.md) — release history.
