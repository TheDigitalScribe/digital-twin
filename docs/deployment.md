# Deployment Runbook

Production deployment is: **reverse proxy (TLS) → Gradio/FastAPI app → OpenAI-compatible API**.

The app is a containerized FastAPI application that serves:

| Path       | Purpose                          | Auth                 |
| ---------- | -------------------------------- | -------------------- |
| `/`        | Gradio chat UI                   | optional (see below) |
| `/healthz` | Liveness probe for orchestration | none (keep private)  |
| `/metrics` | Prometheus text exposition       | none (keep private)  |

## Prerequisites

- Docker (or a Python 3.11+ host for the non-container path).
- An `OPENAI_API_KEY` and a `TWIN_BACKGROUND` (the CV text).

## 1. Reverse proxy with TLS

Put a reverse proxy in front of the container. Only the proxy's IP may be
listed in `TRUSTED_PROXIES` so that rate limiting sees the real client IP.

### Caddy (recommended for single-host)

```
chat.example.com {
    reverse_proxy 127.0.0.1:7860
}
```

Caddy terminates TLS automatically. With this setup:

- Set `TRUSTED_PROXIES` to the IP Caddy connects from (usually the Docker
  bridge or the host loopback, e.g. `127.0.0.1` or `172.17.0.1`).
- Caddy strips/forwards `X-Forwarded-For`; the app reads the leftmost entry
  as the client IP.

### nginx

Sample server block (WebSocket upgrade headers are required by Gradio):

```nginx
server {
    listen 443 ssl;
    server_name chat.example.com;

    ssl_certificate /etc/letsencrypt/live/chat.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Gradio requires WebSocket upgrade.
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Set `TRUSTED_PROXIES` to the nginx container's IP (e.g. `172.17.0.1` if nginx
runs on the host, or the nginx container IP in a compose network).

> **Do not** use `0.0.0.0/0` in `TRUSTED_PROXIES` on a public deployment:
> anyone can then spoof `X-Forwarded-For` and bypass rate limiting.

## 2. Run the container

```bash
cp .env.example .env
# fill in OPENAI_API_KEY, TWIN_BACKGROUND,
# TRUSTED_PROXIES (if behind a proxy)

docker compose up -d --build
```

The compose file already applies hardening:

- non-root user, `no-new-privileges`, all capabilities dropped
- read-only root filesystem (only `/data` is writable)
- mem/pids limits (512 MB / 512 processes)
- port bound to `127.0.0.1:7860` — expose it to the internet **only** through
  the reverse proxy
- healthcheck polling `/healthz`
- `./data` bind-mounted for the SQLite leads DB

Check status:

```bash
docker compose ps          # health column should be "(healthy)"
curl -s http://127.0.0.1:7860/healthz
```

## 3. Monitoring

- **Prometheus**: scrape `http://127.0.0.1:7860/metrics`. Useful alerts:
  - `digitaltwin_security_events_total{kind="input_blocked"} rate > 0` over
    a short window → possible attack. Correlate with `request_id` in logs.
  - `digitaltwin_llm_errors_total rate > 0` → provider/API outage.
  - `digitaltwin_rate_limited_total rate > 0` → noisy client or misconfigured
    proxy (all users behind one IP).
  - `digitaltwin_llm_tokens_total` → cost tracking.
- **Logs** are JSON on stdout. Correlate a single user turn by `request_id`.
  Security events carry `"security_event": "input_blocked" | "output_scrubbed"
| "rate_limited" | "unknown_tool_requested"` plus `ip`.

Example log line:

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

## 4. Scaling

The rate limiter and message history are **in-memory, per process**. If you
run more than one worker/replica, each has its own counters — an attacker can
spread requests across replicas to dodge the limit. Before going multi-replica:

1. Replace the rate-limiter storage with a shared backend (e.g. Redis).
2. Ensure the leads DB is on shared storage (or move to a proper DB).

Until then, keep it to **one worker** for correct rate limiting.

## 5. Backups & hygiene

- `./data/leads.db` holds captured leads + unknown questions. Back it up.
- Rotate `OPENAI_API_KEY` per your org's policy. Secrets are read from `.env`
  (compose) or environment; never commit `.env`.
- Pin the image tag in production (e.g. `digital-twin:0.3.0`) rather than
  `latest`.

## 6. Rollback

`git checkout <previous-tag>` + rebuild is the simplest path since state is
just the SQLite file and the container image. Keep the previous image tag:

```bash
docker compose up -d --build digital-twin   # rebuilds with current tag
# if things break:
docker compose up -d --build --force-recreate digital-twin@<old-tag>
```
