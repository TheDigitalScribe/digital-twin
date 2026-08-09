# Digital Twin

A self-representing AI chat agent that answers career questions on a candidate — built on Gradio + OpenAI function calling with **defense-in-depth prompt-injection guardrails** and a **context-minimization architecture**.

**Live demo:** https://digital-twin-6ije.onrender.com

> Note: this demo runs on Render's free tier, so the first visit may take around a minute while the service wakes up.

## Highlights

- **Three independent guardrail layers**
  1. **Non-overridable system prompt** — hardcoded security protocols that env vars and operator config can never weaken.
  2. **Input sandboxing (pre-model)** — heuristic scanner blocking prompt injection / prompt-extraction before the request reaches the model. Detects homoglyphs, zero-width characters, letter-spacing, and fragment-fusion obfuscations. Now also scans conversation **history** turns for injected payloads.
  3. **Output scrubbing (post-model)** — scans the model's reply for leaked secrets, prompt text, API-key-shaped tokens, and internal tool names before display.
- **Context minimization** — the full CV is never embedded in the system prompt; only a ≤400-char identity sketch lives there. The full background is fetched **on demand** via the `retrieve_background` tool (output capped by `MAX_BACKGROUND_CHARS`), so a leaked prompt exposes the bare minimum.
- **Semantic RAG over work achievements** — markdown achievement files are chunked, embedded, and queried on demand via the `retrieve_achievements` tool, so the twin can answer specific questions about accomplishments and metrics without a vector database. The achievement source files and index live under `data/` (gitignored), keeping them out of the public repo.
- **Function-calling tools with runtime Pydantic argument validation** — the model's JSON output is never trusted blindly.
- **Production readiness**
  - FastAPI app (`digitaltwin.app.build_app`) serving `/` (Gradio), `/healthz` (liveness), `/metrics` (Prometheus).
  - Structured JSON logs with per-request `request_id` correlation; LLM token-usage tracking (`/metrics` → `digitaltwin_llm_tokens_total`).
  - TTL-based per-IP rate limiting (trusted-proxy aware), bounded conversation history, exponential-backoff retries with `Retry-After` support, token-cap + timeout bounds, graceful degradation, graceful shutdown.
- **CI**: tests on Python 3.11/3.12/3.13 with a ≥80% coverage gate, ruff, mypy, and a `pip-audit` CVE scan on every push/PR.

---

## Architecture Diagram

```text
User
  │
  ▼
Gradio Chat UI
  │
  ▼
Chat Handler
  ├─ request ID + logging
  ├─ trusted-proxy IP resolution
  ├─ rate limiting
  ├─ validation
  ├─ input guardrails (message + history)
  ├─ bounded history
  ├─ eager RAG retrieval (optional)
  ▼
LLM Service
  ├─ tool calling
  ├─ retries / timeouts
  └─ token accounting
  ▼
Output Scrubber
  │
  ▼
Final assistant reply
```

```text
                         ┌──────────────────────────┐
                         │  /healthz   /metrics     │
                         │  FastAPI + Prometheus    │
                         └─────────────┬────────────┘
                                       │
User ──► Gradio UI ──► Chat Handler ───┼──► LLM + tools
                                       │
                                       └──► Security + observability
```

---

## Why This Architecture

This project is intentionally split into small, focused layers instead of being built as one large prompt or one monolithic chat handler. That design gives the app better security, clearer failure modes, and easier testability.

- **Separate concerns**: chat orchestration, LLM calls, retrieval, security checks, and observability live in different modules so each piece can be reasoned about and tested independently.
- **Defense in depth**: the system prompt, input sandbox, and output scrubber each protect the app from a different failure mode. If one layer misses something, the others still provide protection.
- **Least privilege for context**: only a small identity sketch is always in the prompt. Sensitive or bulky background material is fetched only when needed, which reduces exposure if anything is leaked.
- **Bounded cost and latency**: rate limiting, history trimming, token caps, timeouts, and retry limits keep the app predictable instead of allowing an expensive or runaway request.
- **Operational visibility**: request IDs, structured logs, health checks, and metrics make the service easier to run in a container or behind a proxy.
- **LLM-safe defaults**: the model is treated as an untrusted component. Tool calls are validated, suspicious inputs fail closed, and responses are scrubbed before display.
- **Simple retrieval layer**: achievement data is stored in a lightweight JSON index because it is easy to build, inspect, version, and regenerate for a personal portfolio project.

In short, the architecture is optimized for a personal AI assistant that is secure, understandable, and deployable without unnecessary infrastructure.

## Senior Notes

A few design choices were made deliberately to keep the project credible at production scale, even though it is a personal portfolio app:

- **Design constraints**
  - Secure by default: the app treats the model as an untrusted component.
  - Low operational complexity: avoid heavy infrastructure where a lightweight in-process solution is sufficient.
  - Minimal secret exposure: keep only a short identity sketch in the prompt and retrieve richer context on demand.
  - Easy local deployment: the project should run cleanly in a container or on a single host without extra services.

- **Failure modes**
  - Model/API outage: return a friendly fallback response instead of surfacing a stack trace.
  - Suspicious input: fail closed rather than trying to infer intent.
  - Missing RAG index: degrade gracefully and continue without retrieval.
  - Proxy misconfiguration: rate limiting remains conservative by relying on trusted proxies only.
  - Output leakage risk: scrub replies before they are shown to the user.

- **Security limitations**
  - Heuristic guardrails reduce risk but do not guarantee perfect safety.
  - Prompt injection cannot be eliminated entirely; the goal is layered mitigation and containment.
  - The system prompt is protected by convention and architecture, not by a cryptographic boundary.
  - Retrieval quality depends on the underlying source material being accurate and well maintained.

- **Operational assumptions**
  - Intended primarily for a personal or single-candidate deployment.
  - Sensitive background and achievement data live outside the public repo in `data/`.
  - Health checks and metrics are exposed to support container orchestration and monitoring.
  - Trusted proxy configuration must be correct for client-IP-based rate limiting to work as intended.

- **Evidence of quality**
  - Guardrails, retrieval, and orchestration are covered by tests.
  - CI runs linting, type checking, coverage enforcement, and dependency scanning.
  - The code is structured so security, LLM orchestration, observability, and retrieval can be tested independently.

This section is the main reason the project reads as more than a demo: it documents the tradeoffs, the blast-radius controls, and the conditions under which the system is expected to behave well.

## Known Limitations

This project is intentionally defensive, but it is not perfect and should not be presented as such:

- Prompt-injection defenses are heuristic and best-effort, not mathematically complete.
- Output scrubbing reduces leakage risk, but novel paraphrases or unseen leak patterns may still slip through.
- Retrieval quality depends on the quality, freshness, and specificity of the source achievement files.
- The architecture is optimized for a personal or single-candidate deployment, not a multi-tenant SaaS platform.
- Trusted-proxy IP handling only works correctly when the proxy configuration is accurate.
- The project does not attempt to solve broader enterprise compliance, SSO, or data governance requirements.

This project aims to provide a secure and efficient AI-driven chat experience, specifically targeting career-related questions. The architecture guarantees robust security while delivering responsive and insightful conversations.

## Use Cases

- **Career Guidance:** Perfect for candidates seeking personalized advice on their careers.
- **Professional Development:** Use it to explore opportunities for growth and learning.
- **Interview Practice:** Obtain feedback and answers to common interview questions.

## Key Features (Expanded)

- **Security Architecture**:
  - Defense-in-depth against prompt injection to protect user data and maintain model integrity.
  - Input/output filtering to prevent leaks of sensitive information.
  - Context minimization to safeguard user details.

- **Production Readiness**:
  - Comprehensive metrics, logging, and health checks facilitate monitoring and operational support.
  - Containerization promotes consistent deployment experiences.
  - Graceful degradation strategies ensure a robust user experience even under load.

- **Testing and Quality**:
  - CI matrix implementations for automated testing and quality control.
  - Coverage gate to ensure sufficient test coverage.
  - Static analysis assists in maintaining code quality and adherence to standards.

## Tradeoffs and Technical Decisions

- **Choosing JSON Index over Vector DB**:
  The JSON index allows for simple data management without the overhead of a full vector database, while still supporting effective semantic RAG.

- **Eager RAG Implementation**:
  This approach provides immediate access to contextually relevant achievement data without the need for complex retrieval systems, improving response times.

- **Bounded Context and History Management**:
  Keeping conversation history bounded minimizes the risk of data leakage and prompt injection attacks.

- **Fail Closed on Suspicious Input**:
  Prioritizing security by failing closed ensures that potential threats are mitigated, maintaining system integrity.

## Configuration

See [`.env.example`](.env.example) for the list of environment variables, including:
| Variable | Required | Default | Description |
| --------------------------- | -------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY` | ✅ | — | OpenAI (or compatible) API key |
| `TWIN_BACKGROUND` | ✅ | — | Full candidate background (CV) text |
| `MODEL_NAME` | | `gpt-5.4-mini` | Chat model (must support tools) |

## Usage

### 1) Start the app

Once your `.env` file is configured, launch the service:

```bash
python -m digitaltwin.app
```

Then open:

- `http://localhost:7860` for the chat UI
- `http://localhost:7860/healthz` to confirm the process is up
- `http://localhost:7860/metrics` to view Prometheus metrics

If you deploy behind a reverse proxy, make sure `TRUSTED_PROXIES` is set so the rate limiter can use the real client IP instead of the proxy IP.

### 2) Ask career-focused questions

The assistant is designed to answer questions about the candidate's background, work history, achievements, projects, and interview preparation. Good prompts are specific and outcome-oriented.

Examples:

- "Can you summarize my work experience so far?"
- "What are my strongest achievements from my last role?"
- "Which projects best demonstrate leadership and technical impact?"
- "Help me prepare a concise interview answer for 'tell me about yourself'."
- "What skills should I highlight on my resume for a senior engineering role?"
- "What metrics or outcomes should I mention when describing my recent work?"

### 3) What happens when you send a message

A single turn goes through several checks before the model responds:

1. The request gets a unique `request_id` for tracing.
2. The client IP is resolved with trusted-proxy support.
3. Rate limiting is applied per IP.
4. The message is validated for emptiness and length.
5. Prompt-injection heuristics scan the new message and recent history.
6. The conversation is bounded to the configured history window.
7. The model is called with tools and retry logic.
8. The final response is scrubbed before display.

This means the app is intentionally conservative: if something looks like an injection attempt, it fails closed instead of trying to guess intent.

### 4) Expected behavior

- Career questions are answered using the candidate background, system prompt, and retrieved achievement context when relevant.
- Questions about specific accomplishments may trigger eager RAG so the answer can use retrieved evidence rather than relying only on the model's memory.
- Suspicious requests such as prompt extraction, role injection, or attempts to reveal hidden instructions will be blocked.
- If the LLM backend fails, the app returns a friendly fallback message instead of crashing.
- If the output appears to leak secrets or internal prompt text, it is replaced with a safe decline.
