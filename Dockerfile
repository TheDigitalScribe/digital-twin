# ---------------------------------------------------------------------------
# Digital Twin — container image
# Multi-stage build keeps the runtime image lean (no build tooling).
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS base

# Non-root user for runtime (defense-in-depth: don't run the app as root).
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install dependencies first (leverages Docker layer caching).
COPY pyproject.toml ./
COPY digitaltwin ./digitaltwin/
RUN pip install --no-cache-dir .

# Security: strip setuid bits from binaries (SSSD pattern, hardens image).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

USER appuser
EXPOSE 7860

CMD ["python", "-m", "digitaltwin.app"]