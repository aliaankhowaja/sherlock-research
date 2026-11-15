# Scored tables (metrics spec §2–§8; seed 20261014, 10000 resamples, α=0.05, TOST δ=0.25)



Recomputed from the committed artifacts alone (§10). Abstains are excluded from EM's numerator and denominator; every rate carries a Wilson 95% CI, every mean/median a BCa or paired percentile bootstrap CI.



## Table 1 — effectiveness, planted full set (86)



| method | n | exact | wrong | abstain | EM | EM CI95 | coverage | abstain rate | mean J (wrong) | J CI95 |
|---|---|---|---|---|---|---|---|---|---|---|
| sherlock | 86 | 84 | 0 | 2 | 1.0 | [0.9563, 1.0] | 0.9767 | 0.0233 | - | - |
| last_node | 86 | 6 | 80 | 0 | 0.0698 | [0.0324, 0.144] | 1.0 | 0.0 | 0.0354 | [0.0125, 0.0687] |
| random_node | 86 | 7 | 79 | 0 | 0.0814 | [0.04, 0.1586] | 1.0 | 0.0 | 0.0443 | [0.0127, 0.0759] |
| g0_only | 86 | 38 | 48 | 0 | 0.4419 | [0.3416, 0.5471] | 1.0 | 0.0 | 0.2569 | [0.184, 0.3229] |
| paste_and_play | 86 | 5 | 79 | 2 | 0.0595 | [0.0257, 0.1319] | 0.9767 | 0.0233 | 0.0359 | [0.0127, 0.0696] |
| g0_g2 | 86 | 49 | 37 | 0 | 0.5698 | [0.4644, 0.6692] | 1.0 | 0.0 | 0.4549 | [0.3829, 0.4865] |
| plain_retry | 86 | 0 | 0 | 86 | - | - | 0.0 | 1.0 | - | - |
| llm_guess_stub | 86 | 6 | 80 | 0 | 0.0698 | [0.0324, 0.144] | 1.0 | 0.0 | 0.0354 | [0.0125, 0.0687] |



### Slice EM (abstains excluded)



| method | hard | two_cause | or_fix | silent_decoy | last_step_ok |
|---|---|---|---|---|---|
| sherlock | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| last_node | 0.0392 | 0.0 | 0.0 | 0.1111 | 0.0133 |
| random_node | 0.0588 | 0.0 | 0.0 | 0.1667 | 0.0933 |
| g0_only | 0.2549 | 0.0 | 0.0 | 0.7222 | 0.44 |
| paste_and_play | 0.0392 | 0.0 | 0.0 | 0.1111 | 0.0 |
| g0_g2 | 0.2941 | 0.0 | 0.0 | 0.8333 | 0.5867 |
| plain_retry | - | - | - | - | - |
| llm_guess_stub | 0.0392 | 0.0 | 0.0 | 0.1111 | 0.0133 |



## Table 3 — pre-registered tests (Holm within family)



| family | test | statistic | exact p | Holm p | effect | MDE | TOST p(≤−δ) | TOST p(≥+δ) | equivalent |
|---|---|---|---|---|---|---|---|---|---|
| (i) engine vs baseline, EM (full set) | sherlock vs last_node | McNemar b=78, c=0 (d=78 of 84 both-attempted) | 6.62e-24 | 3.97e-23 | risk diff 0.9286 (CI95 [0.869, 0.9762]), OR None | 0.6116 | - | - | - |
| (i) engine vs baseline, EM (full set) | sherlock vs random_node | McNemar b=77, c=0 (d=77 of 84 both-attempted) | 1.32e-23 | 5.29e-23 | risk diff 0.9167 (CI95 [0.8571, 0.9762]), OR None | 0.6047 | - | - | - |
| (i) engine vs baseline, EM (full set) | sherlock vs g0_only | McNemar b=46, c=0 (d=46 of 84 both-attempted) | 2.84e-14 | 5.68e-14 | risk diff 0.5476 (CI95 [0.4405, 0.6548]), OR None | 0.3869 | - | - | - |
| (i) engine vs baseline, EM (full set) | sherlock vs paste_and_play | McNemar b=77, c=0 (d=77 of 82 both-attempted) | 1.32e-23 | 5.29e-23 | risk diff 0.939 (CI95 [0.8902, 0.9878]), OR None | 0.6194 | - | - | - |
| (i) engine vs baseline, EM (full set) | sherlock vs g0_g2 | McNemar b=35, c=0 (d=35 of 84 both-attempted) | 5.82e-11 | 5.82e-11 | risk diff 0.4167 (CI95 [0.3095, 0.5238]), OR None | 0.307 | - | - | - |
| (i) engine vs baseline, EM (full set) | sherlock vs llm_guess_stub | McNemar b=78, c=0 (d=78 of 84 both-attempted) | 6.62e-24 | 3.97e-23 | risk diff 0.9286 (CI95 [0.869, 0.9762]), OR None | 0.6116 | - | - | - |
| (ii) G1 variant vs no-G1, t_i | laya vs g0 (subset, B=2) | all 36 paired differences zero (7 censored) | 1.0 | 1.0 | HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0 | - | - | - | - |
| (ii) G1 variant vs no-G1, t_i | laya_masked vs g0 (subset, B=2) | all 35 paired differences zero (8 censored) | 1.0 | 1.0 | HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0 | - | - | - | - |
| (iii) G1 variant vs G1 variant, t_i | laya vs laya_masked (subset, B=2) | all 36 paired differences zero (7 censored) | 1.0 | 1.0 | HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0 | - | 1.0 | 1.0 | False |
| (ii) G1 variant vs no-G1, t_i | laya vs g0 (subset, B=10) | Wilcoxon W+ = 295.0 over 59 pairs (39 censored) | 0.000109 | 0.000218 | HL shift 0.5 (CI95 [-0.5, 3.0]), rank-biserial 0.8154 | 0.7134 | - | - | - |
| (ii) G1 variant vs no-G1, t_i | laya_masked vs g0 (subset, B=10) | Wilcoxon W+ = 429.0 over 61 pairs (37 censored) | 0.0013 | 0.0013 | HL shift 1.0 (CI95 [0.0, 2.5]), rank-biserial 0.625 | 0.8435 | - | - | - |
| (iii) G1 variant vs G1 variant, t_i | laya vs laya_masked (subset, B=10) | Wilcoxon W+ = 99.0 over 59 pairs (39 censored) | 0.829 | 0.829 | HL shift 0.0 (CI95 [-2.0, 2.0]), rank-biserial -0.0571 | 0.7067 | 0.016 | 0.0 | True |
| (ii) G1 variant vs no-G1, t_i | small vs off (subset, tight B=10) | Wilcoxon W+ = 11.5 over 45 pairs (0 censored) | 0.375 | 0.75 | HL shift 0.0 (CI95 [-1.0, 1.0]), rank-biserial 0.5333 | 0.1322 | - | - | - |
| (ii) G1 variant vs no-G1, t_i | big vs off (subset, tight B=10) | Wilcoxon W+ = 3.0 over 45 pairs (0 censored) | 0.5 | 0.75 | HL shift 0.0 (CI95 [0.0, 0.8]), rank-biserial 1.0 | 0.063 | - | - | - |
| (iii) G1 variant vs G1 variant, t_i | small vs big (subset, tight B=10) | Wilcoxon W+ = 10.0 over 45 pairs (0 censored) | 0.625 | 0.625 | HL shift 0.0 (CI95 [-1.0, 1.0]), rank-biserial 0.3333 | 0.1147 | 0.0 | 0.0 | True |

## Table 2 — efficiency + cost, G1-relevant subset, planted (B=2) (43 cases with ≥2 candidates; B2 order-invariance violations: 0)



| method | n | median t | IQR | mean t | median CI95 | pass@B | exhausted | exh. CI95 | G1 ms median | G1 ms IQR | calls | cache hits | cut cards |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 43 | 1.0 | [1.0, 2.0] | 1.2632 | [1.0, 1.0] | 0.8837 | 5 | [0.0507, 0.2448] | - | - | - | - | 0 |
| g0 | 43 | 1.0 | [1.0, 2.0] | 1.3 | [1.0, 1.0] | 0.9302 | 3 | [0.024, 0.1861] | - | - | - | - | 0 |
| rule | 43 | 1 | [1.0, 2.0] | 1.2821 | [1, 1] | 0.907 | 4 | [0.0368, 0.216] | - | - | - | - | 0 |
| hint | 43 | 1.0 | [1.0, 2.0] | 1.2632 | [1.0, 1.0] | 0.8837 | 5 | [0.0507, 0.2448] | - | - | - | - | 0 |
| laya | 43 | 1.0 | [1.0, 2.0] | 1.2632 | [1.0, 1.0] | 0.8837 | 5 | [0.0507, 0.2448] | 0 | [0.0, 71.0] | 27 | 60 | 22 |
| laya_masked | 43 | 1 | [1.0, 1.5] | 1.2432 | [1, 1] | 0.8605 | 6 | [0.0656, 0.2726] | 0 | [0.0, 72.0] | 27 | 60 | 22 |



### Figure 1 (data) — pass@t, KM with censoring at B, planted (B=2)



| method | t=1 | t=2 | KM median | median CI95 |
|---|---|---|---|---|
| random | 0.6512 | 0.8837 | 1 | [1, 1] |
| g0 | 0.6512 | 0.9302 | 1 | [1, 1] |
| rule | 0.6512 | 0.907 | 1 | [1, 1] |
| hint | 0.6512 | 0.8837 | 1 | [1, 1] |
| laya | 0.6512 | 0.8837 | 1 | [1, 1] |
| laya_masked | 0.6512 | 0.8605 | 1 | [1, 1] |

## Table 2 — efficiency + cost, G1-relevant subset, generated (B=10) (98 cases with ≥2 candidates; B2 order-invariance violations: 15)



| method | n | median t | IQR | mean t | median CI95 | pass@B | exhausted | exh. CI95 | G1 ms median | G1 ms IQR | calls | cache hits | cut cards |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 98 | 5 | [3.0, 7.0] | 5.1408 | [4, 5] | 0.7245 | 27 | [0.1968, 0.3712] | - | - | - | - | 0 |
| g0 | 98 | 5.0 | [3.0, 7.0] | 5.1974 | [3.0, 5.0] | 0.7755 | 22 | [0.1532, 0.3166] | - | - | - | - | 0 |
| rule | 98 | 5.0 | [3.0, 7.0] | 5.1974 | [4.0, 5.0] | 0.7755 | 22 | [0.1532, 0.3166] | - | - | - | - | 0 |
| hint | 98 | 5.0 | [3.0, 7.0] | 5.1974 | [3.0, 5.0] | 0.7755 | 22 | [0.1532, 0.3166] | - | - | - | - | 0 |
| laya | 98 | 7 | [5.0, 8.0] | 6.2381 | [5, 7] | 0.6429 | 35 | [0.2693, 0.4557] | 0.0 | [0.0, 1.0] | 0 | 473 | 0 |
| laya_masked | 98 | 7.0 | [5.0, 7.0] | 6.2419 | [5.0, 7.0] | 0.6327 | 36 | [0.2786, 0.4661] | 0.0 | [0.0, 0.0] | 0 | 473 | 0 |



### Figure 1 (data) — pass@t, KM with censoring at B, generated (B=10)



| method | t=1 | t=2 | t=3 | t=4 | t=5 | t=6 | t=7 | t=8 | t=9 | t=10 | KM median | median CI95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| random | 0.0306 | 0.1224 | 0.2041 | 0.3061 | 0.398 | 0.4898 | 0.6327 | 0.6429 | 0.6939 | 0.7245 | 7 | [5, 7] |
| g0 | 0.0306 | 0.102 | 0.2347 | 0.3163 | 0.4184 | 0.5306 | 0.6837 | 0.6837 | 0.7245 | 0.7755 | 6 | [5, 7] |
| rule | 0.0306 | 0.102 | 0.2347 | 0.3163 | 0.4184 | 0.5306 | 0.6837 | 0.6837 | 0.7245 | 0.7755 | 6 | [5, 7] |
| hint | 0.0306 | 0.102 | 0.2347 | 0.3163 | 0.4184 | 0.5306 | 0.6837 | 0.6837 | 0.7245 | 0.7755 | 6 | [5, 7] |
| laya | 0.0306 | 0.0714 | 0.1224 | 0.1531 | 0.2143 | 0.2857 | 0.4796 | 0.4898 | 0.5714 | 0.6429 | 9 | [7, 10] |
| laya_masked | 0.0306 | 0.051 | 0.1122 | 0.1224 | 0.2143 | 0.2755 | 0.4898 | 0.5 | 0.5816 | 0.6327 | 8 | [7, 10] |



## Invariants



- abstain reasons (engine): ['unrecorded_call', 'unrecorded_call']; expect-abstain violations: [] (expect_abstain cases: 2)

- B2 (trials to final verdict) is order-invariant: violations 0 (planted), 15 (generated)



## Table 4 — per team, planted (exact/n and EM)



| team | sherlock exact/n | sherlock EM | last_node exact/n | last_node EM | random_node exact/n | random_node EM | g0_only exact/n | g0_only EM | paste_and_play exact/n | paste_and_play EM | g0_g2 exact/n | g0_g2 EM | plain_retry exact/n | plain_retry EM | llm_guess_stub exact/n | llm_guess_stub EM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| invoice_pipeline | 7/7 | 1.0 | 2/7 | 0.2857 | 1/7 | 0.1429 | 4/7 | 0.5714 | 2/7 | 0.2857 | 5/7 | 0.7143 | 0/7 | - | 2/7 | 0.2857 |
| loan_underwriting | 18/18 | 1.0 | 0/18 | 0.0 | 0/18 | 0.0 | 11/18 | 0.6111 | 0/18 | 0.0 | 13/18 | 0.7222 | 0/18 | - | 0/18 | 0.0 |
| order_desk | 7/7 | 1.0 | 0/7 | 0.0 | 0/7 | 0.0 | 0/7 | 0.0 | 0/7 | 0.0 | 2/7 | 0.2857 | 0/7 | - | 0/7 | 0.0 |
| revenue_report | 19/19 | 1.0 | 0/19 | 0.0 | 0/19 | 0.0 | 7/19 | 0.3684 | 0/19 | 0.0 | 9/19 | 0.4737 | 0/19 | - | 0/19 | 0.0 |
| support_bot | 7/8 | 1.0 | 2/8 | 0.25 | 1/8 | 0.125 | 6/8 | 0.75 | 2/8 | 0.25 | 6/8 | 0.75 | 0/8 | - | 2/8 | 0.25 |
| support_desk | 17/18 | 1.0 | 1/18 | 0.0556 | 3/18 | 0.1667 | 8/18 | 0.4444 | 0/18 | 0.0 | 9/18 | 0.5 | 0/18 | - | 1/18 | 0.0556 |
| vendor_brief | 9/9 | 1.0 | 1/9 | 0.1111 | 2/9 | 0.2222 | 2/9 | 0.2222 | 1/9 | 0.1111 | 5/9 | 0.5556 | 0/9 | - | 1/9 | 0.1111 |



## Table 5 — public-trace ordering (ordering claims only; 4112 headline rows, seed 1)



| method | metric | mean | CI95 |
|---|---|---|---|
| random | rank | 1.6792 | [1.6539, 1.7053] |
| random | reciprocal rank | 0.7318 | [0.7229, 0.7406] |
| random | recall@3 | 0.8665 | [0.8588, 0.8738] |
| random | ndcg@3 | 0.7314 | [0.7234, 0.739] |
| random | trials_to_label | 6.5182 | [6.3534, 6.6826] |
| path | rank | 1.6274 | [1.6019, 1.6522] |
| path | reciprocal rank | 0.7473 | [0.7384, 0.7557] |
| path | recall@3 | 0.8553 | [0.8477, 0.8627] |
| path | ndcg@3 | 0.7471 | [0.7389, 0.7552] |
| path | trials_to_label | 6.098 | [5.9596, 6.2349] |
| g0 | rank | 1.6564 | [1.6299, 1.6826] |
| g0 | reciprocal rank | 0.7453 | [0.7365, 0.7539] |
| g0 | recall@3 | 0.854 | [0.8463, 0.8615] |
| g0 | ndcg@3 | 0.7451 | [0.7365, 0.7536] |
| g0 | trials_to_label | 6.3281 | [6.171, 6.4854] |
| laya | rank | 1.634 | [1.6065, 1.6605] |
| laya | reciprocal rank | 0.759 | [0.7501, 0.7677] |
| laya | recall@3 | 0.8502 | [0.842, 0.8583] |
| laya | ndcg@3 | 0.7447 | [0.7362, 0.753] |
| laya | trials_to_label | 6.7449 | [6.564, 6.9261] |
| laya_masked | rank | 1.6376 | [1.6104, 1.6644] |
| laya_masked | reciprocal rank | 0.7567 | [0.7477, 0.7655] |
| laya_masked | recall@3 | 0.8476 | [0.8394, 0.8558] |
| laya_masked | ndcg@3 | 0.7428 | [0.7341, 0.7512] |
| laya_masked | trials_to_label | 6.787 | [6.6046, 6.9735] |



### Random-order reference (100 seeds, mean + percentile 95% CI)



| metric | mean | CI95 |
|---|---|---|
| ndcg@3 | 0.73 | [0.723, 0.736] |
| no_trial | 0.0 | [0.0, 0.0] |
| rank | 1.685 | [1.664, 1.708] |
| recall@3 | 0.867 | [0.861, 0.872] |
| reciprocal rank | 0.729 | [0.722, 0.737] |
| trials_to_label | 6.566 | [6.479, 6.65] |



## Table 6 — E1/E2, the 4-gate pipeline with the hosted G1 (vertex / gemini-2.5-flash, 5 passes, tight B=10; prompt g1_api_prompt_v1)



Effectiveness (every case, every pass; EM = exact / answered):



| variant | case-passes | exact | wrong | abstain | EM | EM CI95 | mean J (wrong) |
|---|---|---|---|---|---|---|---|
| off | 86 | 84 | 0 | 2 | 1.0 | [0.9563, 1.0] | - |
| small | 266 | 256 | 0 | 10 | 1.0 | [0.9852, 1.0] | - |
| big | 266 | 256 | 0 | 10 | 1.0 | [0.9852, 1.0] | - |



Efficiency on the G1-relevant subset (pooled t_i over passes; pass@B at the tight budget; exhaustion on the tight-budget diagnosis):



| variant | n | median t | IQR | mean t | median CI95 | pass@B | exhausted | exh. CI95 |
|---|---|---|---|---|---|---|---|---|
| off | 45 | 1.0 | [1.0, 2.0] | 1.4 | [1.0, 1.0] | 1.0 | 0 | [0.0, 0.0787] |
| small | 45 | 1.0 | [1.0, 2.0] | 1.4578 | [1.0, 1.0] | 1.0 | 0 | [0.0, 0.0787] |
| big | 45 | 1.0 | [1.0, 2.0] | 1.4311 | [1.0, 1.0] | 1.0 | 0 | [0.0, 0.0787] |



### Figure 1 (data) — pass@t, KM with censoring at the tight budget



| variant | t=1 | t=2 | t=3 | t=4 | t=5 | t=6 | t=7 | t=8 | t=9 | t=10 | KM median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 0.6667 | 0.9333 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| small | 0.6667 | 0.8667 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| big | 0.6667 | 0.8889 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |



Cost (§4; tokens from the API usage fields, USD at the recorded published price):



| variant | cards | mean chars | max chars | builder-cut | calls ok | calls failed | tokens in | tokens out | USD |
|---|---|---|---|---|---|---|---|---|---|
| small | 91 | 1407.989 | 2391 | 22 | 455 | 0 | 360965 | 7300 | 0.1265 |
| big | 91 | 4727.6154 | 11991 | 16 | 455 | 0 | 1057220 | 7353 | 0.3355 |



Invariants: answers changed by G1 0 case(s), B2 changed 0, honesty violations 0 (of 532 case-passes).



Across-pass agreement of the produced order (mean pairwise Kendall tau): {'big': {'cases_with_passes': 45, 'mean_tau': 0.8667}, 'small': {'cases_with_passes': 45, 'mean_tau': 0.7689}}



## Table 5b — public-trace ordering with the hosted G1 (api; 4112 headline rows, seed 1)



| method | metric | mean | CI95 |
|---|---|---|---|
| random | rank | 1.6792 | [1.653, 1.705] |
| random | reciprocal rank | 0.7318 | [0.7228, 0.7404] |
| random | recall@3 | 0.8665 | [0.8588, 0.874] |
| random | ndcg@3 | 0.7314 | [0.7236, 0.7393] |
| random | trials_to_label | 6.5182 | [6.3548, 6.6885] |
| path | rank | 1.6274 | [1.6026, 1.6525] |
| path | reciprocal rank | 0.7473 | [0.7386, 0.7557] |
| path | recall@3 | 0.8553 | [0.8476, 0.863] |
| path | ndcg@3 | 0.7471 | [0.7388, 0.7553] |
| path | trials_to_label | 6.098 | [5.9606, 6.2376] |
| g0 | rank | 1.6564 | [1.6304, 1.6821] |
| g0 | reciprocal rank | 0.7453 | [0.7363, 0.754] |
| g0 | recall@3 | 0.854 | [0.8463, 0.8618] |
| g0 | ndcg@3 | 0.7451 | [0.7365, 0.7536] |
| g0 | trials_to_label | 6.3281 | [6.1712, 6.4903] |
| laya | rank | 1.634 | [1.6072, 1.6607] |
| laya | reciprocal rank | 0.759 | [0.7501, 0.7676] |
| laya | recall@3 | 0.8502 | [0.842, 0.8586] |
| laya | ndcg@3 | 0.7447 | [0.7362, 0.7532] |
| laya | trials_to_label | 6.7449 | [6.5647, 6.9295] |
| api_small | rank | 1.5654 | [1.5401, 1.5905] |
| api_small | reciprocal rank | 0.7795 | [0.7709, 0.7881] |
| api_small | recall@3 | 0.8762 | [0.8689, 0.8836] |
| api_small | ndcg@3 | 0.7742 | [0.7665, 0.7823] |
| api_small | trials_to_label | 6.1736 | [6.0088, 6.34] |
| api_big | rank | 1.5562 | [1.5316, 1.5805] |
| api_big | reciprocal rank | 0.7793 | [0.7707, 0.7878] |
| api_big | recall@3 | 0.8774 | [0.87, 0.8847] |
| api_big | ndcg@3 | 0.7768 | [0.7688, 0.7847] |
| api_big | trials_to_label | 6.0834 | [5.9212, 6.2478] |



Paired differences on the same rows (api order − reference order):



| pair | metric | mean diff | n | CI95 |
|---|---|---|---|---|
| api_small - laya | rank | -0.0686 | 4112 | [-0.0975, -0.0389] |
| api_small - laya | reciprocal rank | 0.0205 | 4112 | [0.0106, 0.0306] |
| api_small - laya | recall@3 | 0.026 | 4112 | [0.0181, 0.0342] |
| api_small - laya | ndcg@3 | 0.0296 | 4112 | [0.0206, 0.0388] |
| api_small - laya | trials_to_label | -0.5713 | 4112 | [-0.6873, -0.4565] |
| api_big - laya | rank | -0.0778 | 4112 | [-0.1077, -0.0479] |
| api_big - laya | reciprocal rank | 0.0203 | 4112 | [0.0105, 0.0303] |
| api_big - laya | recall@3 | 0.0271 | 4112 | [0.0188, 0.0353] |
| api_big - laya | ndcg@3 | 0.0321 | 4112 | [0.0233, 0.0409] |
| api_big - laya | trials_to_label | -0.6615 | 4112 | [-0.777, -0.5479] |
| api_big - api_small | rank | -0.0092 | 4112 | [-0.0294, 0.0119] |
| api_big - api_small | reciprocal rank | -0.0002 | 4112 | [-0.0076, 0.0071] |
| api_big - api_small | recall@3 | 0.0012 | 4112 | [-0.0046, 0.007] |
| api_big - api_small | ndcg@3 | 0.0026 | 4112 | [-0.0038, 0.009] |
| api_big - api_small | trials_to_label | -0.0902 | 4112 | [-0.1792, -0.0012] |



G1 wall ms is the per-scoring-pass clock of the local backends (B5 proxy); the hosted-G1 artifacts record calls, tokens and USD from the API usage fields (§14.1), and their truncation flags distinguish the builder-side cut from the model-context cut.
