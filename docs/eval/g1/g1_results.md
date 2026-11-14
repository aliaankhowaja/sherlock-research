# G1 zero-shot evaluation (laya, g1_questions_v1)

## Methods

| method | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight | final_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 | 2.071 |
| g0 | 84 | 43 | 0.982 | 1.0 | 0.987 | 1.214 | 1.0 | 0 | 0 | 31 | 2.071 |
| rule | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 | 2.071 |
| hint | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 | 2.071 |
| laya | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 | 2.071 |
| laya_masked | 84 | 43 | 0.964 | 1.0 | 0.974 | 1.25 | 1.0 | 0 | 0 | 34 | 2.071 |

## Analysis columns (not methods)

| column | cases | multi_candidate | mrr | recall3 | ndcg3 | fix_mean | fix_median | no_fix | exhausted_default | exhausted_tight | final_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| laya_alone | 84 | 43 | 0.97 | 1.0 | 0.978 | 1.238 | 1.0 | 0 | 0 | 33 | 2.071 |
| q2 | 84 | 43 | 0.976 | 1.0 | 0.982 | 1.226 | 1.0 | 0 | 0 | 32 | 2.071 |
| optimal | 84 | 43 | 1.0 | 1.0 | 1.0 | 1.179 | 1.0 | 0 | 0 | 28 | 2.071 |

## Per team (mean trials to first fix)

| team | cases | g0 | rule | laya | optimal |
|---|---|---|---|---|---|
| invoice_pipeline | 7 | 1.571 | 1.714 | 1.571 | 1.429 |
| loan_underwriting | 18 | 1.222 | 1.222 | 1.222 | 1.222 |
| order_desk | 7 | 1 | 1 | 1 | 1 |
| revenue_report | 19 | 1.158 | 1.158 | 1.158 | 1.105 |
| support_bot | 7 | 1.286 | 1.286 | 1.571 | 1.286 |
| support_desk | 17 | 1.118 | 1.118 | 1.176 | 1.118 |
| vendor_brief | 9 | 1.333 | 1.333 | 1.222 | 1.222 |

## Gate
min(g0, rule) matches optimal in 0.964 of cases; gate_fires=True (true: planted data cannot show a gain)

## Cost
| method | calls | cache hits | ms | statuses |
|---|---|---|---|---|
| laya | 27 | 60 | 1569 | {'skipped': 41, 'ok': 40, 'partial': 3} |
| laya_masked | 27 | 60 | 1543 | {'skipped': 41, 'ok': 34, 'partial': 9} |

## Random reference (100 seeds, mean + 95% CI)
| metric | mean | ci95 |
|---|---|---|
| fix_mean | 1.245 | [1.202, 1.286] |
| no_fix | 0.0 | [0.0, 0.0] |
| exhausted_tight | 0.4 | [0.357, 0.44] |
| mrr | 0.967 | [0.946, 0.988] |
| recall3 | 1.0 | [1.0, 1.0] |
| ndcg3 | 0.975 | [0.96, 0.991] |

## Truncation by card size (2400 chars = the 800-token cut line)
| method | card chars | nodes | truncated | rate |
|---|---|---|---|---|
| laya | <1200 | 36 | 0 | 0.0 |
| laya | 1200-2399 | 51 | 22 | 0.431 |
| laya | >=2400 | 0 | 0 | - |
| laya | all | 87 | 22 | 0.253 |
| laya_masked | <1200 | 36 | 0 | 0.0 |
| laya_masked | 1200-2399 | 51 | 22 | 0.431 |
| laya_masked | >=2400 | 0 | 0 | - |
| laya_masked | all | 87 | 22 | 0.253 |

## Truncation by candidate-set size
| method | candidates | cases | with a cut card | rate |
|---|---|---|---|---|
| laya | 2 | 83 | 13 | 0.157 |
| laya | 3-5 | 1 | 1 | 1.0 |
| laya_masked | 2 | 83 | 13 | 0.157 |
| laya_masked | 3-5 | 1 | 1 | 1.0 |

## Stability
laya order identical in 3 passes: 1.0 of 43 cases with 2+ candidates
