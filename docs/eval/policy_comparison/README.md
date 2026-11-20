# Shared replay task and live search timing

These two post-hoc comparisons answer different questions. The symbolic task holds the intervention outcomes fixed across methods. The solver run measures elapsed time for two search procedures driving real LangGraph checkpoint forks.

## Reproduction

Run `make setup` at the repository root. The timing comparison also requires the solver export behind `data.dvc` (`dvc pull`) and the LangGraph development runtime specified in the Sherlock lockfile. From `python/sherlock/`, run

```sh
.venv/bin/python eval/shared_gcjr.py > /tmp/shared_gcjr.csv
.venv/bin/python eval/live_policy_timing.py --transport asgi > /tmp/live_timing.csv
.venv/bin/python eval/summarize_policy_timing.py /tmp/live_timing.csv
```

The symbolic rows are deterministic. Elapsed times depend on the host. To measure loopback client/server transport on a machine that permits listeners, run the same timing command with `--transport tcp`. The archived run uses ASGI.

## Shared task

We implemented the fixed-outcome GCJR rule in Section II of [Li et al.](https://arxiv.org/html/2608.29228v2). Each of three distinct agents sends one message to a common output check. In the parallel graph the agents have no edges between them. In the ordered variant agent B additionally reads A. All three lie in the backward slice. A clean configuration emits 1. A faulty configuration emits 0 except that faulty B in the ordered graph emits twice A's message. Replacement intervenes on the outgoing message and downstream agents read the replacement. Restoring the corresponding clean configurations yields the same message tuple for every intervention. The runner verifies this equality before scoring.

There are eight distinct message tuples per graph. The check rejects the unmodified failed execution and accepts the fully clean one. The 64 assignments to the other six tuples exhaust the remaining Boolean checks. These are the 64 full-restore-passing predicates from the three-active-node census, reused on both graphs with no inert candidates. These are two designed graphs, not independently sampled workflows. Exhaustive evaluation determines the inclusion-minimal passing subsets. An instance is in GCJR's domain when every member of this gold family is a singleton or an admissible pair. The three possible pairs satisfy the join and different-agent tests; the ordered graph excludes A+B by reachability.

All policies reuse the original failed check, receive deterministic outcomes and get up to seven distinct nonempty queries. We count additional queries only. GCJR uses message replacement. Sherlock production and direct search restore configurations. The full-restore configuration is available to Sherlock as a query, and the reference provides the clean values to each method. Each output row includes the returned family and query order as bit masks (A=1, B=2, C=4). An empty family is encoded as an empty field. Full-domain exactness and recovery within GCJR's declared domain can be checked separately. The code compares search policies on our task; it does not use the original authors' benchmark or software.

## Timing design

Select the two lowest retained question IDs within each source/benchmark stratum, independent of timings. Execute one worker at a time, with a fresh server application and private cassette copy for each of 12 questions. Run all six authored fault/decoy conditions. Before timing a condition, produce a clean thread and a failed thread as appropriate, and run one untimed production diagnosis to obtain the actual candidate order and patch values. Both measured policies receive those inputs and drive G3 on the failed thread. Each subset query creates a new checkpoint fork. Both policies receive cap 40. Validate the observed family against the authored repair, require completeness, and check that no request missed the tape. No measured trial reads a table of archived verdicts.

Time the search with a monotonic clock through return of its family. This includes policy decisions, fork creation, suffix execution, verdict checking and ASGI dispatch. It excludes collection, server startup, candidate planning, and remote network transit. Execute two paired repeats per condition, reversing policy order on the second repeat. Each policy runs first exactly once per condition. Average repeats and the six conditions within each question before summarizing paired differences. The question-level range describes these selected recordings. It is not a population confidence interval.

The timing host ran Ubuntu 26.04.1 on an Intel Core i5-7300U with Python 3.13.16, LangGraph 1.2.15, LangGraph API 0.16.0, in-memory runtime 0.36.0, Starlette 1.8.0 and uvloop 0.23.0. A socket restriction prevented measuring TCP on this host. The public preprint reports the archived ASGI run separately from the previous 185-question server matrix.

The archived ASGI run contains 288 timed searches on 72 question/condition pairs. Production averaged 3.131 seconds (432 forks total) and direct search 2.590 seconds (360 forks). All returned the exact family with a completeness flag. The mean paired difference was 0.540 seconds, with question means ranging from 0.513 to 0.581 seconds. The raw nanosecond timings and execution order are in [live_timing.csv](live_timing.csv). The symbolic interventions and per-policy queries are in [shared_gcjr.csv](shared_gcjr.csv).
