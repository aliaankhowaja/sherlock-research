#!/usr/bin/env bash
# Install dependencies for the research repo: the recorder/diagnosis engine and the harness teams.
# Usage: bash scripts/setup.sh   (or: make setup)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== python/sherlock (engine + eval) ==="
(cd python/sherlock && uv sync)

echo "=== harness (demo teams) ==="
(cd harness && uv sync)

echo
echo "Setup done. Try: make test"
