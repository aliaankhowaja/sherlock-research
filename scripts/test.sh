#!/usr/bin/env bash
# Verification for a reviewer: offline unit tests in both packages, then re-check that the
# committed evaluation results (docs/eval/results.json) are exactly what the pipeline produces.
# Usage: bash scripts/test.sh   (or: make test)
set -euo pipefail
cd "$(dirname "$0")/.."

section() { echo; echo "=== $1 ==="; }

section "harness (python)"
(cd harness && uv run pytest -q)

section "recorder (python/sherlock)"
(cd python/sherlock && uv run pytest -q)

section "evaluation check (regenerates docs/eval/results.json and diffs it against the committed file)"
(cd python/sherlock && uv run python eval/run_eval.py --check ../../docs/eval/results.json)

echo
echo "All green."
