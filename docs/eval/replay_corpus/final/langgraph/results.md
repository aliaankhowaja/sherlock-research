# LangGraph server replay results

The installed LangGraph API replayed all 185 questions under six interventions each, plus the dedicated missing-evidence case. All 185 original assignments reproduced the archived trial order, verdicts and minimal sets. The source data hashes matched before and after execution. Per pass, the full run made 8,888 separate production diagnoses across eight budgets, triggering 21,111 G3 forks. Independent subset enumeration executed 3,333 additional G3 forks. Each method below is scored against the assigned intervention.

| Method | Exact / 1,110 | Wrong nonempty | No set | Decoy named | Mean forks |
|---|---:|---:|---:|---:|---:|
| Sherlock | 1110 | 0 | 0 | 0 | 3.00 |
| All changed writes | 370 | 740 | 0 | 555 | 0.00 |
| Singleton restores | 740 | 0 | 370 | 0 | 1.83 |
| Exhaustive eligible restores | 1110 | 0 | 0 | 0 | 3.00 |

| Comparator | Mean paired recovery gain [95% interval], pp | Perfect-question discordance (Sherlock only / comparator only) | Holm p |
|---|---:|---:|---:|
| All changed writes | 66.67 [66.67, 66.67] | 185 / 0 | 1.22e-55 |
| Singleton restores | 33.33 [33.33, 33.33] | 185 / 0 | 1.22e-55 |
| Exhaustive eligible restores | 0.00 [0.00, 0.00] | 0 / 0 | 1 |

Recovery gains average the six fixed conditions within each question. Intervals resample questions. Identical within-question contrasts produce point intervals on this corpus. Exact paired McNemar tests use the binary endpoint of all six repairs recovered; Holm adjustment covers the three prespecified comparisons. Inference is conditional on these fault templates and the retained questions.

The observed failed output supplies the empty-set verdict at zero fork cost. All changed writes proposes every node with a different output. The singleton baseline tests all eligible singleton restorations. Exhaustive search tests every nonempty subset of the same eligible context patches. Each method receives the same passing and failed runs.

| Intervention | Complete and exact at the default budget | Mean Sherlock forks |
|---|---:|---:|
| extract.drop_last | 185/185 | 1.00 |
| extract.drop_last,bias.flag | 185/185 | 3.00 |
| format.prefix | 185/185 | 1.00 |
| format.prefix,bias.flag | 185/185 | 3.00 |
| extract.drop_last,format.prefix | 185/185 | 3.00 |
| extract.drop_last,format.prefix,bias.flag | 185/185 | 7.00 |

| Maximum forks | Exactly recovered | Complete and exact |
|---:|---:|---:|
| 1 | 370/1110 | 370/1110 |
| 2 | 391/1110 | 370/1110 |
| 3 | 925/1110 | 925/1110 |
| 4 | 925/1110 | 925/1110 |
| 5 | 925/1110 | 925/1110 |
| 6 | 946/1110 | 925/1110 |
| 7 | 1110/1110 | 1110/1110 |
| 40 | 1110/1110 | 1110/1110 |

All 185 headline questions passed the clean and decoy-only controls. Withholding the tape caused a miss before diagnosis and restoring it recovered the answer. The separate two-node request intervention passed under joint restoration, missed on both singleton requests and ended unrecorded_call with zero certified repairs. In each pass, the HTTP replay interceptor served 12,900 recorded replies and rejected 201 requests. All misses were accounted for by the prespecified missing-evidence controls. No outbound connection was observed.

A separate execution repeated the entire matrix from fresh server processes and new working cassette copies. All 186 records matched across passes on the controls, outputs, trial order, restore verdicts, search completeness and replay hit/miss counts. The two passes together made 17,776 diagnoses and executed 48,888 restore forks. Within the primary run, the seven-fork and 40-fork diagnoses agreed on every trial and outcome in 1110/1,110 headline conditions. [Repeat records](repeat.jsonl).

The six intervention cells contain 185 originally recorded assignments and 925 crossed assignments. With a three-fork cap the five simpler cells were fully certified. A second causal fault together with a decoy required seven forks on every question. Sherlock and exhaustive enumeration used identical counts in each cell. No evidence of search savings arises from this small candidate universe.

The paper can attribute exact recovery to the LangGraph runtime on this fixed seven-node graph. The corpus contains 185 distinct retained questions out of 300 attempts. The 1,110 conditions are paired measurements on those questions. The original selection included a diagnosis-agreement check and the two deterministic output faults are shared across questions. The previously reported reduction on larger generated workflows belongs to a separate experiment.

Starlette dispatched HTTP requests in process to the installed ASGI application. LangGraph ran the graph, maintained histories, scheduled resumes and produced checkpoint forks. The run used the CPU and recorded replies only. TCP listener throughput and GPU inference latency were outside this experiment. Latencies in the raw records are wall times under concurrent load.

The [environment manifest](environment.json) records machine, package and code versions. [Raw records](results.jsonl), [condition results](condition_results.csv), [budget results](budget_results.csv), [failure ledger](failures.json), and [protocol](protocol.md).

To reproduce, run the manifest command twice from the repository root with distinct new output paths. Name the resulting records results.jsonl and repeat.jsonl in one output directory. Score both files with `python/sherlock/.venv/bin/python python/sherlock/eval/report_server_replay.py OUTPUT_DIRECTORY`.
