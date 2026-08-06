#!/bin/sh
# ---------------------------------------------------------------------------
# Digital Twin — container entrypoint.
#
# Privacy model (see docs/deployment.md §7): the achievements markdown is NEVER
# baked into the image or committed to git. It is supplied privately via a
# Render "Secret File" mounted at /app/data/achievements/achievements.md and
# encrypted at rest on Render's side. On every container start this script:
#
#   1. Builds the RAG index from that secret file (if present) into
#      /app/data/rag_index.json — an ephemeral file that lives only for the
#      lifetime of the container.
#   2. Launches the app.
#
# Because the index is rebuilt on each start, re-deploys / restarts need no
# manual action, and the raw achievements never ship in the public image.
#
# Runs as the non-root "appuser"; /app/data is owned by appuser (see
# Dockerfile) and is writable (tmpfs in compose, or the writable app dir on
# Render).
# ---------------------------------------------------------------------------
set -e

# Guard: if a secret file was mounted, rebuild the index from it. If none was
# provided, skip gracefully — the app still runs, it just has no achievement
# retrieval (it returns the friendly "no index" message instead of crashing).
if [ -n "$(find /app/data/achievements -maxdepth 1 -type f -name '*.md' 2>/dev/null | head -n 1)" ]; then
  echo "[entrypoint] Rebuilding RAG index from achievement secret file..."
  python -m digitaltwin.rag
else
  echo "[entrypoint] No achievement secret files found under /app/data/achievements — skipping RAG index build."
fi

echo "[entrypoint] Starting Digital Twin..."
exec "$@"
