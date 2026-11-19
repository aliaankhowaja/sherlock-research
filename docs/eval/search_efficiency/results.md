# Search efficiency on generated workflows

On all 100 workflows in the repository's existing generated test split, full-range Sherlock search certified every inclusion-minimal repair using 1,648 distinct subset queries. Exhaustive enumeration needed 5,292 and ascending cardinality search with superset pruning needed 3,511. The reductions in total queries were 68.9% and 53.1%, respectively. Each method received the same candidate set and order and the same access to deterministic workflow outcomes. Every oracle entry was computed by executing the workflow and checking its output. All observed tables satisfied monotonicity. A second run reproduced the per-case traces and summary byte-for-byte.

| Method | Mean queries to complete | Complete and exact | Complete within 40 queries with full size range |
|---|---:|---:|---:|
| Sherlock | 16.48 | 100/100 | 89/100 |
| Exhaustive | 52.92 | 100/100 | 61/100 |
| Ascending with superset pruning | 35.11 | 100/100 | 70/100 |
| Descending with failed-subset pruning | 45.36 | 100/100 | 61/100 |

Relative to ascending search, Sherlock saved a mean of 18.63 queries per workflow (paired workflow-bootstrap 95% interval 10.56–27.88). Concentration matters. For all 19 workflows with at least seven eligible candidates, Sherlock entered its duality search and won, averaging 9.11 queries against 111.16 for ascending search. For the 81 smaller workflows it tied five times and lost 76 times, averaging 18.21 against 17.27. The overall reduction reflects large savings in that minority of larger cases. The standard product budget, including its maximum restore-set size of three, marked 50/100 searches complete and exact. The full-range result measures the search algorithm when allowed to finish.

The separate 185-question corpus has at most three eligible candidates. Across its 1,110 interventions, Sherlock and exhaustive search both needed 3.00 mean forks for completion. For first verification of the assigned minimal repair, Sherlock averaged 2.96 against 2.50 for cardinality-order exhaustive search. Sherlock tied on 597 interventions and took one more fork on the remaining 513. These counts come from [the per-condition verification costs](../replay_corpus/final/verification_cost.csv).

This is an exploratory result on synthetic monotone workflows with one or two causal nodes and one minimal repair. The generator and production search algorithm predate this comparison. The unit of analysis is a generated workflow, and the cost is distinct restore queries. Server latency, workloads with multiple alternative minimal repairs and performance on unseen natural failures remain open questions.

Reproduce with `python3 python/sherlock/eval/search_efficiency.py`. [Protocol](protocol.md) · [Paired results by candidate count](summary.csv) · [Per-workflow oracle and query traces](cases.jsonl)
