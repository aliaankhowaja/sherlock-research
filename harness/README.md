# harness

Demo LangGraph teams, fault injection, and gold derivation for the Sherlock evaluation.

## Setup

```sh
cd harness
uv sync            # Python 3.12, pinned by uv.lock
uv run pytest      # in-process tests, no server needed
```

## Layout

| Path | What it is |
|---|---|
| `sherlock_harness/teams/vendor_brief.py` | Demo team #1: five deterministic nodes and its check Z. Loaded by path by `langgraph dev`, so it must not import the rest of the package |
| `sherlock_harness/teams/{order_desk,invoice_pipeline,support_bot}.py` | Demo teams #2 (parallel branches, unprefixed fault flags), #3 (redundant repair path, two gold sets), #4 (LLM node calling the echo stub; the honest-abstain team) |
| `sherlock_harness/teams/{support_desk,loan_underwriting,revenue_report}.py` + `_kit.py` | Large teams #5-#7 (33 / 32 / 33 nodes, 35-39 faults each; customer-support escalation, loan underwriting/KYC, quarterly revenue report). Built with `_kit.Pipeline`: nodes in execution order with `@P.node(name, after=..., any_of=..., route=..., faults={flag: text})`, plain code per node, fan-out/fan-in, conditional routes, one echo-stub LLM node each. Fan-ins are wired from the last-finishing predecessors with plain edges (a LangGraph list-edge join shows no tasks in the server history) |
| `sherlock_harness/catalog.py` | All seven teams, their faults and node maps; generic `gold_minimal_sets()`; visible cases, the seeded hidden set and the hard-slice tags |
| `sherlock_harness/stub.py` | Deterministic OpenAI-compatible echo server for team #4 (loopback only) |
| `sherlock_harness/faults.py` | Fault catalogue; `run_team()`; `gold_minimal_sets()`, which derives gold by restoring subsets |
| `langgraph.json` | Serves the demo teams with `langgraph dev` |
| `fixtures/` | Real server responses, for the Python tests |
| `tests/` | pytest |

Faults are switched on per run through LangGraph runtime context:

```json
{"assistant_id": "vendor_brief", "input": {"vendor": "acme"}, "context": {"faults": ["retriever.drop_latest"]}}
```

## Large teams

`uv run pytest tests/test_big_teams.py` checks shape (28-42 nodes, 3-way fan-out, a conditional route, all three node kinds), determinism, every fault against Z, and the gold sets of the planned cases. Cases per large team: single fault, two-cause chain, AND across parallel branches, redundant repair (two gold sets), silent decoy, a node that raises, a route change, an abstain-by-design pair; plus 6 seeded hidden cases each. `HARMLESS` lists planted-but-harmless runs (a diagnosis must say `already_passes`).

## Adding a demo team

1. Add `sherlock_harness/teams/<name>.py` exporting `graph`, `CHECK` and `check()`. Keep it self-contained.
2. Register its faults, each with the node it lives on and whether it is harmful.
3. Add it to `langgraph.json`.
4. Add tests: the clean run passes, every harmful fault fails, gold comes from restoration.
5. Keep faults on deterministic nodes unless the team exists to test cassette replay.
