# Digital Twin

A self-representing AI chat agent that answers career questions on a candidate — built on Gradio + OpenAI function calling with **defense-in-depth prompt-injection guardrails** and a **context-minimization architecture**.

> **Why this project?** Most AI portfolio apps are thin wrappers around an API key. This one treats the model as an untrusted component and applies security engineering principles (least privilege, defense-in-depth, failure containment) to LLM application design.

---

## Highlights

- **Three independent guardrail layers**
  1. **Non-overridable system prompt** — hardcoded security protocols that env vars and operator config can never weaken.
  2. **Input sandboxing (pre-model)** — heuristic scanner blocking prompt injection / prompt-extraction _before_ the request reaches the model. Detects homoglyphs, zero-width characters, letter-spacing, and fragment-fusion obfuscations.
  3. **Output scrubbing (post-model)** — scans the model's reply for leaked secrets, prompt text, API-key-shaped tokens, and internal tool names before display.
- **Context minimization** — the full CV is never embedded in the system prompt; only a ≤400-char identity sketch lives there. The full background is fetched **on demand** via the `retrieve_background` tool, so a leaked prompt exposes the bare minimum.
- **Function-calling tools with runtime Pydantic argument validation** — the model's JSON output is never trusted blindly (malformed / wrong-typed / extra args rejected gracefully).
- **Production hardening** — TTL-based per-IP rate limiting (trusted-proxy aware), bounded conversation history (cost + injection-surface control), exponential-backoff retries with `Retry-After` support, graceful degradation on API errors, structured logging.

---

## Architecture

```
                       ┌─────────────────────────────────────────────┐
  User message ──────► │  1. Trusted-proxy IP resolution             │
                       │  2. TTL rate limiting (per IP)              │
                       │  3. Validation (empty / length caps)        │
                       │  4. LAYER A: input sandboxing               │
                       │  5. History bounding (max turns)            │
                       │  6. Model call + tool loop (retries)        │
                       │  7. LAYER B: output scrubbing               │
                       └─────────────────────────────────────────────┘
                                      │
                              ┌───────▼────────┐
                              │   Gradio UI    │
                              └────────────────┘
```

| Module                        | Responsibility                                             |
| ----------------------------- | ---------------------------------------------------------- |
| `digitaltwin/app.py`          | Gradio entry point, env validation, UI assembly            |
| `digitaltwin/chat.py`         | End-to-end request handler (steps 1–7)                     |
| `digitaltwin/llm.py`          | OpenAI-compatible client, retry/timeout logic, tool loop   |
| `digitaltwin/tools.py`        | Tool schemas + async implementations + argument validation |
| `digitaltwin/security.py`     | Layer A (input) + Layer B (output) guardrails              |
| `digitaltwin/context.py`      | System prompt assembly + context minimization              |
| `digitaltwin/config.py`       | Centralized, validated settings (pydantic-settings)        |
| `digitaltwin/rate_limiter.py` | TTL-bucketed per-client rate limiting                      |
| `digitaltwin/logger.py`       | Structured logging setup                                   |
| `digitaltwin/styles.py`       | CSS/JS theming for the Gradio UI                           |

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
- The **input sandbox** catches known attacks before the model sees them.
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

If the system prompt leaks, an attacker gets only a 400-char identity sketch — **not** the candidate's full career history.

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

python -m digitaltwin.app
```

Open http://localhost:7860

### Docker

```bash
cp .env.example .env             # fill in your values
docker compose up --build
```

---

## Configuration

See [`.env.example`](.env.example) for the full list. Key settings:

| Variable                           | Required | Default        | Description                                                |
| ---------------------------------- | -------- | -------------- | ---------------------------------------------------------- |
| `OPENAI_API_KEY`                   | ✅       | —              | OpenAI (or compatible) API key                             |
| `TWIN_BACKGROUND`                  | ✅       | —              | Full candidate background (CV) text                        |
| `MODEL_NAME`                       |          | `gpt-5.4-mini` | Chat model (must support tools)                            |
| `MAX_MESSAGE_CHARS`                |          | `500`          | Per-message length cap                                     |
| `MAX_HISTORY_TURNS`                |          | `10`           | Conversation turns sent to model                           |
| `RATE_LIMIT_REQUESTS`              |          | `5`            | Requests per IP per window                                 |
| `RATE_LIMIT_WINDOW_SECONDS`        |          | `60`           | Rate-limit window                                          |
| `TRUSTED_PROXIES`                  |          | empty          | Comma-separated proxy IPs allowed to set `X-Forwarded-For` |
| `PUSHOVER_USER` / `PUSHOVER_TOKEN` |          | —              | Optional lead-capture notifications                        |
| `LOG_LEVEL`                        |          | `INFO`         | `DEBUG` / `INFO` / `WARNING` / `ERROR`                     |

> **Security note:** always set `TRUSTED_PROXIES` when running behind a reverse proxy; otherwise `X-Forwarded-For` is ignored and rate limiting keys on the proxy's IP. Never use `0.0.0.0/0` in a multi-tenant deployment.

---

## Tooling

```bash
python -m pytest                     # run the test suite
python -m pytest --cov=digitaltwin --cov-report=term-missing   # with coverage
ruff check digitaltwin tests         # lint
mypy digitaltwin                     # type-check
```

CI (GitHub Actions) runs tests on Python 3.11/3.12 with a **≥80% coverage gate**, plus ruff and mypy, on every push and PR: [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## License

MIT — add a `LICENSE` file before publishing.
