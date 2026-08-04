# Security Policy

## Security model & known limitations

This app treats the LLM as an **untrusted component** and layers
defense-in-depth controls around it:

| Layer | Control                                          | Strength                                          | Limitation                                              |
| ----- | ------------------------------------------------ | ------------------------------------------------- | ------------------------------------------------------- |
| 1     | Non-overridable system prompt (`_CORE_SECURITY`) | Strong (prompt-level)                             | Not a technical control; can be coaxed by novel attacks |
| 2     | Input sandboxing (`is_suspicious_request`)       | Good against known attacks                        | Heuristic, regex-based; novel obfuscations may bypass   |
| 3     | Conversation-history bounding + scanning         | Reduces injection surface, catches known payloads | Old turns are scanned but not a guarantee               |
| 4     | Output scrubbing (`scrub_output`)                | Catches secret-name/key-shaped leaks              | Heuristic; paraphrased leaks may pass                   |
| 5     | Context minimization (≤400-char identity sketch) | Limits damage if the prompt leaks                 | Full CV still fetched on demand                         |

**Do not put truly sensitive information in `TWIN_BACKGROUND`.** The whole
point of the context-minimization architecture is that a leaked system prompt
does not contain the CV — but a successful extraction via the
`retrieve_background` tool result, or a leak of the `TWIN_BACKGROUND` env var
itself, would expose whatever is in there.

### Runtime hardening (deployment)

- Run behind a reverse proxy with TLS. Only the proxy's IP belongs in
  `TRUSTED_PROXIES`; never `0.0.0.0/0` in multi-tenant deployments.
- The container runs as a non-root user with `no-new-privileges`, all
  capabilities dropped, a read-only root filesystem, and mem/pids limits.
- Rate limiting is **per-process, in-memory**. If you scale to multiple
  workers/replicas, each worker has its own counter — use a shared backend
  (Redis, etc.) before exposing publicly across replicas. See `rate_limiter.py`.
- `/metrics` and `/healthz` are unauthenticated. Keep them behind a private
  network / authenticated proxy if your infrastructure allows.
- Structured logs include `request_id`; correlate on that field. Security
  events are prefixed with `security_event` and expose `security_event`, `ip`.
