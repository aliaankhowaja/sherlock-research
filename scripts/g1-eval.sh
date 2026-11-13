#!/usr/bin/env bash
# G1 ordering evaluation: every live run in one place.
# Usage: make g1-eval   (or: bash scripts/g1-eval.sh)
#
# Inference is local only: the `laya` package runs in this process through `uv run --with laya`
# (first run downloads the CPU/CUDA package set; use the GPU box for speed) and sends nothing
# anywhere. Answers are cached in python/sherlock/eval/.g1/cache, so a re-run after a failure
# only pays for what is missing.
# Writes docs/eval/g1 (86 planted cases) and docs/eval/g1_gen (generated test half); commit both afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

section() { echo; echo "=== $1 ==="; }

RUN=(uv run --with laya)
smoke=("${RUN[@]}" sherlock-rec g1-check)

cd python/sherlock

section "1/6 smoke test: Laya answers the sample card twice (local)"
"${smoke[@]}"

if [ ! -f eval/.g1/cases.jsonl ]; then
  section "2/6 node cards for the 86 planted cases (runs the full evaluation, about 10 to 20 minutes)"
  "${RUN[@]}" python eval/run_eval.py --out ../../docs/eval
else
  section "2/6 node cards for the 86 planted cases: already built (delete eval/.g1/cases.jsonl to rebuild)"
fi

section "3/6 Laya on the 86 planted cases, with the 3-pass stability check"
"${RUN[@]}" python eval/g1_eval.py --tight 2 --stability --out ../../docs/eval/g1

section "4/6 Laya on the generated test half"
"${RUN[@]}" python eval/g1_gen.py
"${RUN[@]}" python eval/g1_eval.py --cases eval/.g1/gen_v1/test.jsonl --tight 10 --out ../../docs/eval/g1_gen

section "5/6 reproducibility: two more runs from the cache give byte-identical results"
for i in 1 2; do
  "${RUN[@]}" python eval/g1_eval.py --tight 2 --out "eval/.g1/rerun_$i" > /dev/null
  "${RUN[@]}" python eval/g1_eval.py --cases eval/.g1/gen_v1/test.jsonl --tight 10 --out "eval/.g1/rerun_gen_$i" > /dev/null
  cmp ../../docs/eval/g1/g1_results.json "eval/.g1/rerun_$i/g1_results.json"
  cmp ../../docs/eval/g1_gen/g1_results.json "eval/.g1/rerun_gen_$i/g1_results.json"
done
echo "reproducibility check: identical"

section "6/6 the pre-declared ship rule"
"${RUN[@]}" python - <<'EOF'
import json
from pathlib import Path

res = {name: json.loads(Path(f"../../docs/eval/{name}/g1_results.json").read_text())["summary"]
       for name in ("g1", "g1_gen")}
s = res["g1_gen"]
base = min(("g0", "rule"), key=lambda m: s[m]["fix_mean"])
cut = 1 - s["laya"]["fix_mean"] / s[base]["fix_mean"]
worse = [f"{name} {key}" for name, r in res.items() for key in ("exhausted_default", "exhausted_tight")
         if r["laya"][key] > r[base][key]]
print(f"generated test half: laya {s['laya']['fix_mean']} vs {base} {s[base]['fix_mean']} mean trials to first fix "
      f"= {100 * cut:.1f}% fewer (rule: at least 20%)")
print(f"budget_exhausted higher with laya: {', '.join(worse) or 'nowhere'}")
ship = cut >= 0.20 and not worse
print("decision:", "Laya may become the default backend (all acceptance checks must also pass)" if ship
      else "Laya stays optional, off by default; report the result as it is")
EOF

echo
echo "Done. Commit docs/eval/g1 and docs/eval/g1_gen."
