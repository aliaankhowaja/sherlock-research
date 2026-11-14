#!/usr/bin/env bash
# Experiments E1/E2: the full 4-gate pipeline on the planted cases with a hosted-LLM G1.
# Usage: make g1-pipeline   (or: bash scripts/g1-pipeline.sh)
#
# E1 = small cards (the laya card budget, byte-identical to what laya was scored on),
# E2 = big cards (8x budget + GOOD_IN/UPSTREAM/WRITES_ALL). Same system prompt, same model,
# same call parameters; the card is the only manipulated variable. Pre-registered in
# docs/eval/metrics-spec.md §14.1 — read it before reading any number below.
#
# Needs a configured .env (.env-example documents every key; the paper runs used vertex + ADC).
# API calls are cached in python/sherlock/eval/.g1/api_cache/{small,big}, so an interrupted run
# only pays for what is missing. Writes docs/eval/pipeline_g1; commit it afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

cd python/sherlock

echo "=== 1/3 smoke test: the configured provider answers the sample card (3 calls) ==="
uv run sherlock-rec g1-api-check --passes 3 > /dev/null
echo "smoke ok"

echo
echo "=== 2/3 E1+E2: 86 planted cases + 3 probes, 5 passes per variant on the G1-relevant subset ==="
echo "(recording labs takes a few minutes; the hosted calls are the cached minority)"
uv run python eval/pipeline_g1.py --out ../../docs/eval/pipeline_g1

echo
echo "=== 3/3 reproducibility: a re-run from the cache must be identical (canonical projection) ==="
uv run python eval/pipeline_g1.py --check ../../docs/eval/pipeline_g1/pipeline_g1.json

echo
echo "Done. Commit docs/eval/pipeline_g1."
