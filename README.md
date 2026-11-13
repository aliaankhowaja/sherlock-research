# Sherlock

Sherlock finds which agent in a multi-agent LangGraph team broke a run. You give it a failed run and a run
that passed. It replays the recorded run offline (no live model calls), restores one agent's behaviour at a
time, and reports the smallest set of agents to blame, or says "cannot say".

This repository is the research fork: the engine, the evaluation harness and the experiment results.
There is no product UI or server here — every claim is backed by a script that re-runs the experiment and
by a committed result file a reviewer can diff against.

## What you can verify

Each experiment is reproducible from the code alone. Committed results live in `docs/eval/`:

| Result | Experiment | Script | Committed output |
|---|---|---|---|
| 3-gate diagnosis (planted cases) | full search with gates G0/G2/G3, no G1, over 86 planted fault cases | `python/sherlock/eval/run_eval.py` | `docs/eval/results.json` / `results.md` |
| G1 node ordering (planted cases) | the same cases, candidates ordered six ways (random / g0 / rule / hint / laya / laya_masked) | `python/sherlock/eval/g1_eval.py` | `docs/eval/g1/g1_results.json` / `.md` |
| G1 node ordering (generated cases) | harder generated multi-candidate cases, same methods | `python/sherlock/eval/g1_gen.py` | `docs/eval/g1_gen/g1_results.json` / `.md` |
| G1 ordering (public traces) | 5,032 public agent-run traces (AEGIS / Who&When), orders compared against the published labels | `python/sherlock/eval/public_g1.py` | `docs/eval/public_traces/public_g1.json` / `.md` |

Method, scoring and known limitations of the planted evaluation: `docs/eval/README.md`.
The pre-registered metrics, statistical protocol and decision rules for all experiments:
`docs/eval/metrics-spec.md` (commit it before running any 4-gate experiment; deviations go in its §14 log).
Headline numbers are generated from `results.json` by `python -I scripts/gen-facts.py` into `docs/eval/facts.md`.

## Layout

- `python/sherlock/` — the diagnosis engine (`sherlock-rec` console script): record, replay, gates
  (G0 clue weights, G2 pruning, G3 fork search), the G1 orderer (`g1.py`, Laya / LLM scoring), checks.
- `python/sherlock/eval/` — the experiment scripts listed above plus the trace converter.
- `python/sherlock/tests/` — offline unit tests; `test_eval_results.py` re-checks the committed results.
- `harness/` — seven demo LangGraph teams (four small, three 32-33 node), the planted fault catalogue,
  the echo stub, and the gold derivation.
- `scripts/` — `setup.sh`, `test.sh`, `g1-eval.sh`, `g1-public.sh`, `gen-facts.py`.
- `docs/eval/public_traces/cases.jsonl.gz` — the converted public trace corpus (uncompress to `cases.jsonl`,
  which is gitignored for size).

## Run it

```sh
make setup      # uv sync for python/sherlock and harness
make test       # unit tests + verify docs/eval/results.json matches a fresh pipeline run
```

Experiments:

```sh
make eval        # 3-gate planted evaluation, about 5 minutes, writes docs/eval/results.*
make g1-eval     # G1 ordering, planted + generated cases (local laya inference; GPU box recommended)
make g1-public   # G1 ordering on the public corpus (local laya; SHUTDOWN=0 keeps the machine on)
```

The planted 3-gate evaluation needs `langgraph-cli` and no network: runs are recorded against a local echo
stub, then replayed inside a socket trap that forbids every non-loopback connection. G1 runs the open-weight
`laya` checkpoint **locally** in-process (GPU box recommended; a CPU run works and is only slower): no endpoint,
no key, and no card text leaves the machine. Answers are cached in `python/sherlock/eval/.g1/` so a re-run
after a failure only pays for what is missing.

## Datasets

- **Planted**: 86 fault cases over the seven harness teams (52 visible, 34 seeded hidden), faults planted in
  deterministic nodes with clean context flags. Defined in `harness/sherlock_harness/catalog.py`.
- **Generated**: 100 harder cases with many co-culprit candidates (`g1_gen.py`).
- **Public**: AEGIS and Who&When agent-run traces converted to checkpoint histories
  (`python/sherlock/eval/convert_public_traces.py`); labels are the published blamed agents.
