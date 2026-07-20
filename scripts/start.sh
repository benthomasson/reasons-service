#!/usr/bin/env bash
# Start reasons-service with all environment variables.
# Copy to scripts/start.local.sh and fill in your secrets.

export OLLAMA_HOST="${OLLAMA_HOST:-http://threadripper2.local:11434}"

# Auth (optional — omit GOOGLE_CLIENT_ID to run in dev mode)
export GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
export GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"
export SECRET_KEY="${SECRET_KEY:-dev-insecure-key}"
export EXPERT_SERVICE_API_KEY="${EXPERT_SERVICE_API_KEY:-}"

exec uv run reasons-service
