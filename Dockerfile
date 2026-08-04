# ---------------------------------------------------------------------------
# Digital Twin — container image
# Multi-stage build keeps the runtime image lean (no build tooling).
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS base

# Non-root user for runtime (defense-in-depth: don't run the app as root).
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install dependencies first (leverages Docker layer caching).
# README.md must be present because pyproject.toml declares readme = "README.md".
COPY pyproject.toml README.md ./
COPY digitaltwin ./digitaltwin/
RUN pip install --no-cache-dir .

# Security: strip setuid bits from binaries (hardens image).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

# Persistent lead-capture database lives here (mounted as a volume).
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser
EXPOSE 7860

# Container health: the app exposes /healthz via the FastAPI mount.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/healthz', timeout=2).read()" || exit 1

CMD ["python", "-m", "digitaltwin.app"]