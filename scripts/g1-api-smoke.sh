#!/usr/bin/env bash
# Hosted G1 smoke test: the sample card, N calls, provider/model from the environment or .env.
# Usage: make g1-api-smoke   (or: bash scripts/g1-api-smoke.sh [vertex|gemini_api|openai_compat])
#
# Requires a configured .env (see .env-example): SHERLOCK_G1_PROVIDER, SHERLOCK_G1_MODEL and the
# provider's credential (GOOGLE_CLOUD_PROJECT for vertex/ADC, SHERLOCK_G1_API_KEY for gemini_api,
# SHERLOCK_G1_BASE_URL for openai_compat). With no argument the script smokes the .env provider;
# `openai_compat` additionally smokes a second call set against ollama if SMOKE_OLLAMA=1 is set.
set -euo pipefail
cd "$(dirname "$0")/.."

provider="${1:-}"

cd python/sherlock
if [ -n "$provider" ]; then
  echo "=== G1 API smoke ($provider) ==="
  uv run sherlock-rec g1-api-check --provider "$provider" --passes 3
else
  echo "=== G1 API smoke (provider from .env) ==="
  uv run sherlock-rec g1-api-check --passes 3
fi

if [ "${SMOKE_OLLAMA:-0}" = "1" ]; then
  echo
  echo "=== G1 API smoke (openai_compat against local ollama) ==="
  uv run sherlock-rec g1-api-check --provider openai_compat \
    --base-url "${SHERLOCK_G1_BASE_URL_OLLAMA:-http://127.0.0.1:11434/v1}" \
    --model "${SHERLOCK_G1_MODEL_OLLAMA:-gemma4:e2b}" --passes 2
fi

echo
echo "Smoke passed: every call answered, every reply parsed, scores shown above."
