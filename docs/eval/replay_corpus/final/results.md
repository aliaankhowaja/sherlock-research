# Final replay evaluation

Sherlock recovered the assigned minimal repair in **1110/1110** crossed fault conditions on 185 retained questions. The design reused the same recorded reply for all six interventions on each question. There were 185 distinct normalized question clusters.

## Paired comparisons

| Method | Exact | Wrong nonempty | No set | Bias named | Mean forks |
|---|---:|---:|---:|---:|---:|
| sherlock | 1110 | 0 | 0 | 0 | 3.00 |
| all_changed | 370 | 740 | 0 | 555 | 0.00 |
| singleton | 740 | 0 | 370 | 0 | 1.83 |
| exhaustive | 1110 | 0 | 0 | 0 | 3.00 |

All-changed proposes all nodes whose writes differ. A downstream formatter can change its write even when only extraction is faulty. The singleton policy cannot recover a two-node repair. Exhaustive enumerates all nonempty subsets with a context patch. The observed failed output supplies the empty-set verdict for every method.

Exact McNemar tests use one binary outcome per question cluster (all six diagnoses correct). Positive differences below are percentage points of mean condition-level recovery. Percentile intervals resample whole question clusters.

| Comparator | Sherlock-only / comparator-only perfect clusters | Difference [95% interval], pp | Holm p |
|---|---:|---:|---:|
| all_changed | 185 / 0 | 66.67 [66.67, 66.67] | 1.22e-55 |
| singleton | 185 / 0 | 33.33 [33.33, 33.33] | 1.22e-55 |
| exhaustive | 0 / 0 | 0.00 [0.00, 0.00] | 1 |

Zero-width empirical intervals arise when all sampled clusters have identical contrasts. They describe variation across these questions under fixed software faults. They provide no uncertainty estimate for new fault families.

## Interventions and budget

| Faults | Sherlock exact | Mean forks |
|---|---:|---:|
| extract.drop_last | 185/185 | 1.00 |
| extract.drop_last,bias.flag | 185/185 | 3.00 |
| extract.drop_last,format.prefix | 185/185 | 3.00 |
| extract.drop_last,format.prefix,bias.flag | 185/185 | 7.00 |
| format.prefix | 185/185 | 1.00 |
| format.prefix,bias.flag | 185/185 | 3.00 |

| Fork cap | Sherlock exact | Search complete and exact |
|---:|---:|---:|
| 1 | 370/1110 | 370/1110 |
| 2 | 391/1110 | 370/1110 |
| 3 | 925/1110 | 925/1110 |
| 4 | 925/1110 | 925/1110 |
| 5 | 925/1110 | 925/1110 |
| 6 | 946/1110 | 925/1110 |
| 7 | 1110/1110 | 1110/1110 |
| 40 | 1110/1110 | 1110/1110 |

With three forks, Sherlock completed every single-cause condition and every joint condition without the decoy. Adding the decoy raised certification cost from one to three forks for single causes and from three to seven for the joint fault. At the default budget, exhaustive enumeration and Sherlock used the same number of forks in every design cell.

| Method | Assigned repair verified | Median forks through first verification, among verified |
|---|---:|---:|
| sherlock | 1110/1110 | 3 |
| all_changed | 0/1110 | — |
| singleton | 740/1110 | 1.5 |
| exhaustive | 1110/1110 | 2 |

Verification requires an observed passing assigned repair and a failure for each proper subset. The already observed failed run supplies the empty subset. This endpoint can be reached before the search certifies that all minimal sets have been found. Individual costs are in [verification_cost.csv](verification_cost.csv).

The full method-by-budget curves are in [budget_curves.csv](budget_curves.csv) with a [Vega-Lite figure](budget_figure.vl.json). Baseline curves replay the fixed cardinality-first, graph-order trial sequence up to each cap. A partial search can name the right set before establishing completeness. The all-changed baseline performs zero verification forks. Within-question effect sizes for accuracy and fork count are in [effects.csv](effects.csv).

## Selection, controls and reproducibility

| Source / benchmark | Kept / attempted |
|---|---:|
| Fancylalala/AEGIS/GSM8K | 50/50 |
| Fancylalala/AEGIS/MATH | 44/50 |
| Fancylalala/AEGIS/SciBench | 30/50 |
| Leoxx/whowhen_pro/math | 36/50 |
| Leoxx/whowhen_pro/scibench | 21/50 |
| Leoxx/whowhen_pro/simpleqa_verified | 4/50 |

The original generation report supplies the 300 attempted questions. The export contains the 185 exact-match successes. 185 original conditions were re-executed and compared with the exported outputs, minimal sets and individual trials. 0 recordings have discrepancies in the failure ledger.

Clean and bias-only controls and matched withholding/restoration checks met their expectations on 185/185 questions. Suppressing the model tape caused a miss at solve, before a failed thread was available for diagnosis. Restoring the tape recovered the clean output. In the separate two-request case, the joint restore passed, the two singleton requests missed, and diagnosis returned **unrecorded_call** with 0 certified repairs. This is one concrete abstention test.

The study covers one linear graph, one recorded model response per headline question, and two deterministic output faults. The original case selection included a diagnosis agreement check. The crossed variants test the same mechanisms. The experiment establishes conditional intervention behavior. Natural agent fault localization and unseen mechanisms require independent data.

Replay ran locally on Debian 13, KVM, Intel Xeon 3.10 GHz (8 cores, 16 logical CPUs), with 62 GiB visible RAM. The first pass ran serially. The repeat used six worker processes. Default diagnosis latency under the adapter was median 5.96 ms and p95 12.18 ms, excluding tape loading and baseline enumeration. Both passes together took 16.0 s. These measurements cover the in-process adapter; HTTP serving and LangGraph scheduling overhead are outside the measurement.

The exported graph's node functions ran in order against strict request-hash SQLite replay. Production diagnose and G3 created and checked forks through a linear checkpoint adapter because the LangGraph server dependencies were unavailable on this host. Recorded server trials provide the parity check. Budget sweeps re-executed the production search policy against independently enumerated trial outcomes. The author confirmed completion of the 30-transcript pilot review.

Reproduce from the repository root with `python3 python/sherlock/eval/final_replay.py && python3 python/sherlock/eval/final_replay_report.py`. To regenerate tables alone, run the second command. The input hashes, environment, raw outcomes, tables, and discrepancy ledger are stored beside this report.
