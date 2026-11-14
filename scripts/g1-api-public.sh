#!/usr/bin/env bash
# E1/E2 public leg: hosted-LLM G1 ordering on the public trace corpus (metrics spec §8).
# Usage: make g1-api-public   (or: bash scripts/g1-api-public.sh)
#
# Same records, budget and scoring as the committed laya run; `api_small` (the laya card budget) and
# `api_big` (8x budget + GOOD_IN/UPSTREAM/WRITES_ALL where a known-good run exists). One scored pass
# per row, plus the pre-registered 200-row 5-pass stability subsample (§14.1). The random-order
# reference is the committed public_g1.json one; it is not recomputed.
#
# Needs a configured .env (.env-example documents every key). About 30k hosted calls at the paper's
# configuration; cached in python/sherlock/eval/.g1/public_api_cache/{small,big}, so an interrupted
# run only pays for what is missing. Writes docs/eval/public_traces/public_g1_api.{json,md}.
set -euo pipefail
cd "$(dirname "$0")/.."

cd python/sherlock

echo "=== 1/3 smoke test: the configured provider answers the sample card (3 calls) ==="
uv run sherlock-rec g1-api-check --passes 3 > /dev/null
echo "smoke ok"

echo
echo "=== 2/3 5-row pilot (catches corpus surprises before the long run) ==="
uv run python eval/public_g1_api.py --limit 5 --stability 2 --out eval/.g1/pilot_public_api

echo
echo "=== 3/3 the full public corpus: 4,112 headline rows, both card variants ==="
uv run python eval/public_g1_api.py --out ../../docs/eval/public_traces

echo
echo "Done. Commit docs/eval/public_traces/public_g1_api.{json,md}."
