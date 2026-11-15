# 4-gate pipeline with an LLM-backed G1 (seed 20261014, 5 passes, tight B=10)



Backend: vertex / gemini-2.5-flash (https://us-central1-aiplatform.googleapis.com); prompt version g1_api_prompt_v1; config hash cdda62e3dcb3ebc3.



E1 = small cards (the laya card budget), E2 = big cards (8x budget, GOOD_IN/UPSTREAM/WRITES_ALL). Same system prompt, same call parameters; the card is the only manipulated variable. G1 only reorders trials (variant A): EM must not move.



## Effectiveness (every case, every pass)



| variant | case-passes | exact | wrong | abstain | EM (abstains excluded) | mean J (wrong) | abstain reasons |
|---|---|---|---|---|---|---|---|
| off | 86 | 84 | 0 | 2 | 1.0 | - | {'unrecorded_call': 2} |
| small | 266 | 256 | 0 | 10 | 1.0 | - | {'unrecorded_call': 10} |
| big | 266 | 256 | 0 | 10 | 1.0 | - | {'unrecorded_call': 10} |
| full | 266 | 256 | 0 | 10 | 1.0 | - | {'unrecorded_call': 10} |



## Invariants



- answers changed vs no-G1: 0 case-passes (of 798)

- trials to final verdict (B2) changed: 0 (counted, not assumed: reordering changes which supersets are pruned)

- artifact honesty violations: 0

- abstain-by-design cases abstaining in every variant: 2/2



## Efficiency, G1-relevant subset (>= 2 candidates; t_i pooled over passes)



| variant | cases | median t_i | IQR | mean t_i | pass@tight-B | exhausted (tight) | wall s median |
|---|---|---|---|---|---|---|---|
| off | 45 | 1.0 | 1.0–2.0 | 1.4 | 1.0 | 0 | 3.654 |
| small | 45 | 1.0 | 1.0–2.0 | 1.458 | 1.0 | 0 | 3.831 |
| big | 45 | 1.0 | 1.0–2.0 | 1.431 | 1.0 | 0 | 3.803 |
| full | 45 | 1.0 | 1.0–2.0 | 1.413 | 1.0 | 0 | 6.165 |



## Pass@t curves (pooled per-pass t_i, censored at the tight budget)



| variant | t=1 | t=2 | t=3 | t=4 | t=5 | t=6 | t=7 | t=8 | t=9 | t=10 | KM median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 0.6667 | 0.9333 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| small | 0.6667 | 0.8667 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| big | 0.6667 | 0.8889 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |
| full | 0.6667 | 0.8889 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1 |



## Cost (§4)



| variant | cards | mean chars | max chars | builder-cut | calls ok | calls failed | tokens in | tokens out | USD |
|---|---|---|---|---|---|---|---|---|---|
| small | 91 | 1408.0 | 2391 | 22 | 455 | 0 | 360965 | 7300 | 0.1265 |
| big | 91 | 4727.6 | 11991 | 16 | 455 | 0 | 1057215 | 7353 | 0.3355 |
| full | 91 | 6911.1 | 31436 | 0 | 455 | 0 | 1546845 | 7284 | 0.4823 |



### Truncation by card size



| variant | bucket | cards | builder-cut | api-context-cut |
|---|---|---|---|---|
| small | 1200-2399 | 53 | 22 | 0 |
| small | <1200 | 38 | 0 | 0 |
| big | 1200-2399 | 12 | 0 | 0 |
| big | <1200 | 28 | 0 | 0 |
| big | >=2400 | 51 | 16 | 0 |
| full | 1200-2399 | 12 | 0 | 0 |
| full | <1200 | 28 | 0 | 0 |
| full | >=2400 | 51 | 0 | 0 |



## Stability (§6.7): across-pass agreement of the produced order



| variant | cases with passes | mean pairwise Kendall tau |
|---|---|---|
| small | 45 | 0.7689 |
| big | 45 | 0.8667 |
| full | 45 | 0.8133 |



## Tests (§6.2–§6.4, pre-registered families only)



| family | test | statistic | p (exact) | p (Holm) | effect | MDE | TOST |
|---|---|---|---|---|---|---|---|
| (ii) | small vs off (subset, tight B=10) | Wilcoxon W+ = 11.5 over 45 pairs (0 censored) | 0.375 | 1.0 | HL shift 0.0 (CI95 [-1.0, 1.0]), rank-biserial 0.5333 | 0.1322 | - |
| (ii) | big vs off (subset, tight B=10) | Wilcoxon W+ = 3.0 over 45 pairs (0 censored) | 0.5 | 1.0 | HL shift 0.0 (CI95 [0.0, 0.8]), rank-biserial 1.0 | 0.063 | - |
| (ii) | full vs off (subset, tight B=10) | Wilcoxon W+ = 4.0 over 45 pairs (0 censored) | 0.75 | 1.0 | HL shift 0.0 (CI95 [-0.4, 0.8]), rank-biserial 0.3333 | 0.0588 | - |
| (iii) | small vs big (subset, tight B=10) | Wilcoxon W+ = 10.0 over 45 pairs (0 censored) | 0.625 | 1.0 | HL shift 0.0 (CI95 [-1.0, 1.0]), rank-biserial 0.3333 | 0.1147 | True |
| (iii) | small vs full (subset, tight B=10) | Wilcoxon W+ = 12.0 over 45 pairs (0 censored) | 0.312 | 0.936 | HL shift 0.0 (CI95 [-0.6, 1.0]), rank-biserial 0.6 | 0.1013 | True |
| (iii) | big vs full (subset, tight B=10) | Wilcoxon W+ = 5.0 over 45 pairs (0 censored) | 0.5 | 1.0 | HL shift 0.0 (CI95 [-0.2, 0.6]), rank-biserial 0.6667 | 0.0476 | True |



## Per team (pooled t_i on the G1-relevant subset)



| team | cases | off | small | big |
|---|---|---|---|---|
| invoice_pipeline | 3 | 2.333 | 2.333 | 2.333 |
| loan_underwriting | 7 | 1.571 | 1.657 | 1.686 |
| order_desk | 5 | 1.0 | 1.0 | 1.0 |
| revenue_report | 11 | 1.273 | 1.273 | 1.273 |
| support_bot | 4 | 1.5 | 1.75 | 1.5 |
| support_desk | 10 | 1.2 | 1.3 | 1.26 |
| vendor_brief | 5 | 1.6 | 1.6 | 1.6 |



## Probes (planted-harmless runs: the diagnosis must say already_passes)



| case | status | reason | ok |
|---|---|---|---|
| support_desk:pii_redact.miss_card | abstain | already_passes | True |
| loan_underwriting:fraud_velocity.threshold_one | abstain | already_passes | True |
| revenue_report:skip_first_row | abstain | already_passes | True |



## Cases



| case | team | tags | G1-relevant | off t_i | small t_i | big t_i | off outcome | small outcome | big outcome |
|---|---|---|---|---|---|---|---|---|---|
| vendor_brief:router.wrong_source | vendor_brief | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:writer.stale_template | vendor_brief | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:reviewer.false_block | vendor_brief | - | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:retriever.drop_latest+extractor.legacy_pattern | vendor_brief | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:retriever.reverse_order+writer.stale_template | vendor_brief | silent_decoy,last_step_ok | True | 3 | 2.0 | 3.0 | exact | exact | exact |
| order_desk:no_bulk_discount | order_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:qty_off_by_one | order_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:stale_inventory+drops_shipping_line | order_desk | two_cause | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| invoice_pipeline:normalize.stale_rate | invoice_pipeline | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| invoice_pipeline:extract.comma_split+normalize.trust_parsed | invoice_pipeline | or_fix,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| invoice_pipeline:extract.comma_split+post.round_down | invoice_pipeline | silent_decoy | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| support_bot:fmt.shout | support_bot | - | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:prep.truncate | support_bot | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:ask.terse_instruction | support_bot | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:customer_lookup.stale_cache | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:customer_lookup.stale_cache+urgency.threshold_off | support_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:order_lookup.timeout | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:intake.ref_lowercase | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:pii_redact.miss_card+compliance_check.skip_pii_scan | support_desk | or_fix,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| support_desk:sla_standard.hours_typo+customer_lookup.stale_cache | support_desk | silent_decoy,last_step_ok | True | 2 | 3.0 | 2.6 | exact | exact | exact |
| support_desk:refund_calc.cap_off+rerank.ascending | support_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:merge_results.drop_history | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:draft_reply.terse_instruction | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:approval_gate.limit_off+audit_log.drops_ticket_id+send.dry_run | support_desk | - | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:policy_check.short_window | support_desk | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:application_intake.thousands_sep | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:fraud_velocity.threshold_one+fraud_device.default_device | loan_underwriting | or_fix,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| loan_underwriting:fraud_aggregate.threshold_two+fraud_velocity.threshold_one | loan_underwriting | or_fix,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| loan_underwriting:bank_parse.credit_debit_swap | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:credit_bureau.stale_report | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:employer_verify.stale_registry+risk_score.min_balance_x4 | loan_underwriting | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:limit_check.stale_exposure | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:income_normalise.net_not_gross | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:letter_draft.terse_instruction | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:policy_rules.dti_limit_low | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:id_parse.swap_dates | loan_underwriting | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:pricing.floor_payment+ledger_write.drop_decision | loan_underwriting | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:quarter_off_by_one | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:swap_cols | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:stale_eur_rate+gbp_inverted | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:skip_first_row+key_ignores_month | revenue_report | silent_decoy,last_step_ok | True | 3 | 3.0 | 3.0 | exact | exact | exact |
| revenue_report:sign_flip+sum_abs | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:cap_1000 | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:always_warn | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:drop_limit_5pct | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:wrong_prior+no_dampening | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:terse_instruction+quarter_off_by_one | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:drop_refunds+locale_comma | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:mean_not_median | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:stale_segments | revenue_report | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:extractor.legacy_pattern+router.wrong_source | vendor_brief | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:retriever.drop_latest+writer.stale_template | vendor_brief | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| vendor_brief:retriever.reverse_order+router.wrong_source | vendor_brief | silent_decoy,last_step_ok | True | 2 | 3.0 | 2.0 | exact | exact | exact |
| vendor_brief:retriever.drop_latest+retriever.reverse_order | vendor_brief | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:no_bulk_discount+stale_inventory | order_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:no_bulk_discount+qty_off_by_one | order_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:drops_shipping_line+qty_off_by_one | order_desk | two_cause | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| order_desk:drops_shipping_line+no_bulk_discount | order_desk | two_cause | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| invoice_pipeline:normalize.trust_parsed+post.round_down | invoice_pipeline | silent_decoy | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| invoice_pipeline:validate.reject_large | invoice_pipeline | last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| invoice_pipeline:extract.comma_split+validate.reject_large | invoice_pipeline | silent_decoy,last_step_ok | True | 3 | 3.0 | 3.0 | exact | exact | exact |
| invoice_pipeline:normalize.trust_parsed+validate.reject_large | invoice_pipeline | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:ask.terse_instruction+fmt.trailing_newline | support_bot | silent_decoy,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| support_bot:fmt.shout+fmt.trailing_newline | support_bot | - | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:ask.terse_instruction+fmt.shout | support_bot | two_cause | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:fmt.trailing_newline+prep.truncate | support_bot | silent_decoy,last_step_ok | True | 2 | 3.0 | 2.0 | exact | exact | exact |
| support_desk:compliance_check.skip_pii_scan+faq_score.no_normalise | support_desk | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:compliance_check.skip_pii_scan+policy_check.short_window | support_desk | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:draft_reply.terse_instruction+merge_results.drop_history | support_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:faq_search.stale_index+lang_detect.swap_codes | support_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:approval_gate.limit_off+send.dry_run | support_desk | two_cause | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_desk:faq_search.stale_index+rerank.ascending | support_desk | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:decision_router.always_refer+fraud_identity.months_as_days | loan_underwriting | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:fraud_aggregate.threshold_two+pricing.floor_payment | loan_underwriting | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:employer_verify.stale_registry+kyc_match.exact_case | loan_underwriting | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:credit_bureau.thin_file+risk_score.util_cutoff | loan_underwriting | silent_decoy,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| loan_underwriting:id_parse.swap_dates+policy_rules.kyc_ignored | loan_underwriting | silent_decoy,last_step_ok | False | 1 | 1.0 | 1.0 | exact | exact | exact |
| loan_underwriting:fraud_identity.months_as_days+id_parse.swap_dates | loan_underwriting | silent_decoy,last_step_ok | True | 2 | 2.6 | 2.8 | exact | exact | exact |
| revenue_report:drop_selfserve+key_ignores_month | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:drop_last_bar+sign_flip | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:exclude_refunds+wrong_prior | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:cap_1000+wrong_text | revenue_report | silent_decoy,last_step_ok | True | 2 | 2.0 | 2.0 | exact | exact | exact |
| revenue_report:key_ignores_month+stale_segments | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| revenue_report:always_warn+drop_refunds | revenue_report | two_cause,last_step_ok | True | 1 | 1.0 | 1.0 | exact | exact | exact |
| support_bot:prep.truncate+ask.terse_instruction | support_bot | two_cause,abstain_by_design,last_step_ok | True | 1 | 1.0 | 1.0 | abstain | abstain | abstain |
| support_desk:intent_classify.bias_shipping+draft_reply.terse_instruction | support_desk | two_cause,abstain_by_design,last_step_ok | True | 1 | 1.0 | 1.0 | abstain | abstain | abstain |



Card text is never written to the artifact; scores are P(restore) per card per pass.

Generated by eval/pipeline_g1.py; do not edit.
