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
| Scored tables (statistics) | Tables 1–5 of `docs/eval/metrics-spec.md` §2–§8 (Wilson/BCa CIs, exact McNemar, exact Wilcoxon + Hodges–Lehmann, Holm, TOST, MDEs, pass@t) re-derived from the committed artifacts | `python/sherlock/eval/score.py` | `docs/eval/score.json` / `score.md` |

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

Hosted-LLM G1 experiments (E1 = small cards, E2 = big cards, E3 = uncut cards; see `docs/eval/metrics-spec.md` §14):

```sh
make g1-api-smoke    # the sample card through the configured provider (3 calls)
make g1-pipeline     # E1/E2/E3 on the 86 planted cases + 3 probes, paired vs no-G1 (about 1 hour)
make g1-api-public   # E1/E2/E3 on the public trace corpus (about 45k calls; run overnight)
```

The planted 3-gate evaluation needs `langgraph-cli` and no network: runs are recorded against a local echo
stub, then replayed inside a socket trap that forbids every non-loopback connection. G1 runs the open-weight
`laya` checkpoint **locally** in-process (GPU box recommended; a CPU run works and is only slower): no endpoint,
no key, and no card text leaves the machine. Answers are cached in `python/sherlock/eval/.g1/` so a re-run
after a failure only pays for what is missing.

### Run the hosted experiments with your own API key

The hosted G1 backend (`python/sherlock/src/sherlock/g1_api.py`) speaks to any of three provider
types, configured entirely through a `.env` file at the repository root (template: `.env-example`;
the file is git-ignored — never commit a key):

```sh
cp .env-example .env      # then edit; every key is documented there
make g1-api-smoke         # verify the provider answers before any experiment
```

- `SHERLOCK_G1_PROVIDER=vertex` — Google Vertex AI with Application Default Credentials
  (`gcloud auth application-default login`; no key in the file). The paper runs used
  `gemini-2.5-flash` this way.
- `SHERLOCK_G1_PROVIDER=gemini_api` — the Generative Language API with `SHERLOCK_G1_API_KEY`.
- `SHERLOCK_G1_PROVIDER=openai_compat` — any `/chat/completions` endpoint (OpenAI, ollama, Groq,
  Together, ...) via `SHERLOCK_G1_BASE_URL` (+ optional key).

The same system prompt and reply format are used for every provider and both card variants, so the
only thing that changes between E1 (small cards) and E2 (big cards) is the card text. Set
`SHERLOCK_G1_PRICE_IN/OUT/SOURCE` to your model's published per-million-token prices so the cost
tables are dated and reproducible; `SHERLOCK_G1_MAX_INPUT_TOKENS` is your model's context window
(a card over it gets no score — the truncation mechanism under test). Every call is cached under
`python/sherlock/eval/.g1/`, and the experiment scripts exit loudly rather than fall back if the
endpoint is dead.

## Datasets

- **Planted**: 86 fault cases over the seven harness teams (52 visible, 34 seeded hidden), faults planted in
  deterministic nodes with clean context flags. Defined in `harness/sherlock_harness/catalog.py`.
- **Generated**: 100 harder cases with many co-culprit candidates (`g1_gen.py`).
- **Public**: AEGIS and Who&When agent-run traces converted to checkpoint histories
  (`python/sherlock/eval/convert_public_traces.py`); labels are the published blamed agents.
