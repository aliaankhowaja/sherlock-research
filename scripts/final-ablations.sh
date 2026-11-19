#!/usr/bin/env bash
# Usage: bash scripts/final-ablations.sh NEW_OUTPUT_DIRECTORY
set -euo pipefail
cd "$(dirname "$0")/.."
out=${1:?supply a fresh output directory}
mkdir "$out"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
export PYTHONHASHSEED=0
export PYTHONPATH="$PWD/python/sherlock/src"
export ablation_python="$PWD/python/sherlock/.venv/bin/python"
for pass in primary repeat; do
    export pass_dir="$scratch/$pass"
    mkdir "$pass_dir"
    seq 0 88 | xargs -P "${WORKERS:-8}" -I '{}' bash -c '
        "$ablation_python" python/sherlock/eval/ablate_planted.py "$1" "$pass_dir/$1.json" >"$pass_dir/$1.log" 2>&1 ||
            { tail -15 "$pass_dir/$1.log" >&2; exit 1; }
    ' _ '{}'
    "$ablation_python" python/sherlock/eval/ablate_search.py "$pass_dir/matrix.gz"
done
"$ablation_python" python/sherlock/eval/report_ablations.py "$scratch/primary" "$scratch/repeat" "$out"
