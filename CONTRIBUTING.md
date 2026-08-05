# Contributing

Thanks for helping make this project better. This document covers the
development workflow and the standards the codebase enforces.

## Setup

```bash
git clone https://github.com/TheDigitalScribe/digtal-twin.git
cd digtal-twin

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install ".[dev]"

cp .env.example .env             # fill in OPENAI_API_KEY + TWIN_BACKGROUND
```

## Running the checks

All checks are run in CI on every push/PR; run them locally before pushing:

```bash
pytest                                 # unit tests
pytest --cov=digitaltwin --cov-report=term-missing   # with coverage (gate: ≥80%)
ruff check digitaltwin tests           # lint
mypy digitaltwin                       # type-check
```

## Code style & structure

- **Type hints everywhere.** `mypy` runs non-strict but we keep `-> None` on
  all procedures and annotate public signatures. Add `# type: ignore` only
  with a comment explaining why.
- **No new module reads env vars directly.** Everything goes through
  `Settings` in `config.py`. New settings get a `Settings` field, a line in
  `.env.example`, and (if surfaced) a row in the README config table.
- **Keep the pipeline obvious.** `chat.py` documents the 8-step request flow
  in its docstring; keep it in sync when you touch the order.
- **Security controls are opt-out-by-absent, not opt-in.** When adding a
  guardrail, prefer failing closed (blocking) and make bypasses explicit and
  difficult.
- **Logging is structured.** Use `get_logger(__name__)` and pass
  `extra={"event": "...", ...}`. Never log secrets — the `OPENAI_API_KEY`
  and `TWIN_BACKGROUND` values must stay out of logs.
- **Metrics: one counter per user-visible event.** Extend `Metrics` in
  `observability.py` when you add a new event type; the `/metrics` endpoint
  picks it up automatically via `_COLLECTORS`.
- **Persistence is best-effort.** DB writes must never raise into the tool
  path; return a bool and let the caller decide.

## Testing expectations

- New behavior ships with tests.
- Use `pytest` fakes/clients (never hit the network or the real OpenAI API).
- Security-related changes should add regression cases to the attack corpus
  in `tests/test_security.py` and, if relevant, the history-scan tests in
  `tests/test_chat.py`.
- Persistence tests use `tmp_path` and the `isolated_db` fixture — never the
  real `data/`.

## Docs

- README changes: keep the module table, configuration table, and the
  security model diagrams accurate.
- User-facing config changes: update `.env.example` and the README table.
- New endpoints / infra: update the deployment runbook (`docs/deployment.md`).

## Suggesting changes

Open an issue or PR. For security issues, see `SECURITY.md` — do **not**
file a public issue.
