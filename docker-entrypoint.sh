#!/bin/sh
# ---------------------------------------------------------------------------
# Digital Twin — container entrypoint.
#
# Privacy model (see docs/deployment.md §7): the achievements markdown is NEVER
# baked into the image or committed to git. It is supplied privately via a
# Render "Secret File" and encrypted at rest on Render's side. On every
# container start this script:
#
#   1. Stages any achievement .md secret file(s) from /etc/secrets/ (where
#      Render mounts every secret file) into /app/data/achievements/.
#   2. Builds the RAG index from those staged files into /app/data/rag_index.json
#      — an ephemeral file that lives only for the lifetime of the container.
#   3. Launches the app.
#
# NOTE: Render mounts ALL secret files at /etc/secrets/<filename>. There is NO
# way to choose a different mount path, and filenames cannot contain '/'.
# So a secret file named `achievements.md` lands at /etc/secrets/achievements.md
# and is copied here into the directory the RAG build expects. See
# https://render.com/docs/configure-environment-variables#secret-files.
#
# Because the index is rebuilt on each start, re-deploys / restarts need no
# manual action, and the raw achievements never ship in the public image.
#
# Runs as the non-root "appuser"; /app/data is owned by appuser (see
# Dockerfile) and is writable (tmpfs in compose, or the writable app dir on
# Render). appuser must be in the host group 1000 to read /etc/secrets/ files
# (see Dockerfile) — required by Render's Docker secret-file permissions.
# ---------------------------------------------------------------------------
set -e

# Staging dir the RAG build reads from (matches RAG_ACHIEVEMENTS_DIR default
# "data/achievements" resolved against WORKDIR /app).
STAGE_DIR="/app/data/achievements"
mkdir -p "$STAGE_DIR"

# Stage any achievement markdown found in Render's secret files directory.
# Render places every secret file at /etc/secrets/<filename>; we pick up any
# .md files there so the secret filename does not have to be hardcoded.
SECRET_MD_COUNT=0
for secret in /etc/secrets/*.md; do
  [ -e "$secret" ] || continue
  cp "$secret" "$STAGE_DIR/"
  SECRET_MD_COUNT=$((SECRET_MD_COUNT + 1))
done

if [ "$SECRET_MD_COUNT" -gt 0 ]; then
  echo "[entrypoint] Staged $SECRET_MD_COUNT achievement secret file(s) from /etc/secrets/. Rebuilding RAG index..."
  python -m digitaltwin.rag
else
  echo "[entrypoint] No achievement secret files found under /etc/secrets/ — skipping RAG index build."
fi

echo "[entrypoint] Starting Digital Twin..."
exec "$@"
