# Digital Twin

A self-representing AI chat assistant that answers career questions about the
candidate it represents. It runs a Gradio chat UI backed by an
OpenAI-compatible model with function calling, layered prompt-injection
defenses, and on-demand retrieval of the candidate's background and
achievements.

**Live demo:** https://digital-twin-6ije.onrender.com (Render free tier — the
first visit may take ~a minute while the service wakes up)

## Features

- **Layered prompt-injection defenses.** A non-overridable system prompt,
  heuristic input sandboxing (message + conversation history), and
  post-response output scrubbing. Anything suspicious fails closed before it
  reaches the model or the user.
- **Context minimization.** The full background (CV) is never embedded in the
  prompt — only a short identity sketch is. The rest is fetched on demand via
  the `retrieve_background` tool, with the returned text capped.
- **Semantic retrieval over achievements.** Markdown achievement files are
  chunked and embedded into a lightweight JSON index (no vector database).
  Achievement-related questions fetch the most relevant chunks via the
  `retrieve_achievements` tool, with optional eager pre-fetching.
- **Production-ready runtime.** Served as a FastAPI app exposing `/` (chat UI),
  `/healthz` (liveness), and `/metrics` (Prometheus). Includes per-IP rate
  limiting (trusted-proxy aware), bounded conversation history, retries with
  backoff, token/timeout caps, structured JSON logs, and graceful degradation.
- **Tested and linted.** Tests on Python 3.11–3.13 with a ≥80% coverage gate,
  plus Ruff, mypy, and a `pip-audit` CVE scan in CI.

## How it works

```text
User → Gradio UI → chat handler → input guardrails → model (with tools)
                                                        ↓
                                    output scrubber ← LLM + retries/timeouts
```

Each request gets a request ID, is validated and rate-limited, then scanned for
prompt injection before reaching the model. The model may call
`retrieve_background` or `retrieve_achievements`; tool arguments are validated
with Pydantic, and the final reply is scrubbed before being shown to the user.

## Quick start

1. Install: `pip install -e .` (or `pip install -e ".[dev]"` for tests/lint).
2. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `TWIN_BACKGROUND`
   (the candidate's full background text).
3. Run:

   ```bash
   python -m digitaltwin.app
   ```

4. Open http://localhost:7860 for the chat UI, `/healthz` for liveness, and
   `/metrics` for Prometheus metrics.

If you deploy behind a reverse proxy, set `TRUSTED_PROXIES` to the proxy's IP
so rate limiting sees the real client IP.

## Configuration

See [`.env.example`](.env.example) for the full list of settings. The important
ones:

| Variable          | Required | Default        | Description                                          |
| ----------------- | -------- | -------------- | ---------------------------------------------------- |
| `OPENAI_API_KEY`  | yes      | —              | OpenAI (or compatible) API key                       |
| `TWIN_BACKGROUND` | yes      | —              | Full candidate background (CV) text                  |
| `MODEL_NAME`      | no       | `gpt-4.1-mini` | Chat model (must support tools)                      |
| `RAG_*`           | no       | —              | Achievements retrieval settings (see `.env.example`) |

## Achievements

Achievement source files are markdown documents under `data/achievements/`
(gitignored — they never enter the repo). Build the semantic index with:

```bash
python -m digitaltwin.rag
```

The index is written to `data/rag_index.json`. In Docker, the entrypoint
rebuilds it at container start (see `docs/deployment.md`).

## Deployment

- **Docker:** `docker compose up --build`. The image runs as a non-root user
  with a read-only root filesystem, dropped capabilities, and resource limits.
  Secrets come from a local `.env` file.
- **Render:** use the included `render.yaml` Blueprint. `OPENAI_API_KEY` and
  `TWIN_BACKGROUND` are set in the dashboard; achievements are provided as a
  Secret File that the entrypoint stages and indexes at startup.
- See [`docs/deployment.md`](docs/deployment.md) for a reverse-proxy runbook
  and operational details.

## Development

```bash
pip install -e ".[dev]"
pytest                       # run the test suite
ruff check digitaltwin tests # lint
mypy digitaltwin             # type check
```

## Security notes

The defenses are heuristic and layered, not absolute: prompt injection cannot
be fully eliminated, and the goal is to reduce blast radius and fail closed.
The app is intended for a single-candidate, personal deployment, not a
multi-tenant SaaS platform.
