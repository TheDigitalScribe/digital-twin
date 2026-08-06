# ---------------------------------------------------------------------------
# Digital Twin — container image
# Multi-stage build keeps the runtime image lean (no build tooling).
#
# Privacy model for Render:
#   * The achievements markdown is NEVER baked into the image — it is supplied
#     privately via a Render "Secret File". Render mounts every Secret File at
#     /etc/secrets/<filename> (no custom mount path available). The entrypoint
#     stages it into /app/data/achievements/ from there.
#   * docker-entrypoint.sh builds the RAG index from that file on each
#     container start, writing to /app/data/rag_index.json — so the public
#     image never ships the raw achievements, only the ephemeral index.
# ---------------------------------------------------------------------------

FROM python:3.12-slim AS base

# Non-root user for runtime (defense-in-depth: don't run the app as root).
# Group 1000 is added so the appuser can read Render's Secret Files: Render
# mounts them at /etc/secrets/<filename> owned by group 1000, and Render's own
# docs require the app user be in group 1000 to read them.
RUN useradd --create-home --shell /bin/bash -G 1000 appuser

WORKDIR /app

# Install dependencies first (leverages Docker layer caching).
# README.md must be present because pyproject.toml declares readme = "README.md".
COPY pyproject.toml README.md ./
COPY digitaltwin ./digitaltwin/
RUN pip install --no-cache-dir .

# Security: strip setuid bits from binaries (hardens image).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} \; 2>/dev/null || true

# Writable data directory. At runtime the entrypoint builds the RAG index here
# from the Render secret file (data/achievements/*.md). appuser owns it so the
# index can be written even though the container is non-root.
RUN mkdir -p /app/data/achievements && chown -R appuser:appuser /app/data

# Entrypoint: builds the RAG index (if achievements are present), then launches
# the app. It is public (no secrets) and runs as appuser.
COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

USER appuser
EXPOSE 7860

# Container health: the app exposes /healthz via the FastAPI mount.
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/healthz', timeout=2).read()" || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "-m", "digitaltwin.app"]