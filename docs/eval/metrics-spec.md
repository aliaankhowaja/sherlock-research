# Metrics spec — Sherlock pipeline evaluation (v1)

Status: pre-registered decision protocol. Commit and freeze this file **before** running any
4-gate (G1 variant) experiment. Any deviation after results are seen goes in §14 (deviation log),
never silently.

Purpose: one metric cannot decide this paper, because the G1 gate only reorders trials — it cannot
change the diagnosis. The evaluation therefore has two pre-registered axes, decided separately:

- **A. Effectiveness** — is the verdict right? (decides: engine vs baselines)
- **B. Efficiency/cost** — how much is paid to reach the verdict? (decides: G1 variant vs no-G1, and G1 variant vs G1 variant)

---

## 1. Notation and outcome space

A case `i` has gold `G_i = {S_1, ..., S_k}`, a collection of minimal culprit node sets (k ≥ 1;
`or_fix` cases have two alternative gold sets). A method returns prediction `P_i`, a collection of
node sets, or abstains. Three mutually exclusive outcomes per case:

| Outcome | Definition |
|---|---|
| exact | `P_i == G_i` (collection equality, order-free) |
| wrong | `P_i` non-empty and differs from `G_i` (adds, drops, splits or merges sets) |
| abstain | `P_i` empty, with a recorded reason code |

Abstains are reported beside accuracy and are **never** counted as correct or as wrong. Every
abstain must carry a reason code (`unrecorded_call`, `cannot_attribute`, `no_known_good`,
`already_passes`, budget-exhausted, ...).

For the planted set: 86 cases, 7 teams (4 small, 3 large with 32–33 nodes). Slice tags are frozen
in `harness/sherlock_harness/catalog.py`: `two_cause`, `or_fix`, `silent_decoy`,
`abstain_by_design`, hard-slice = any of these, `last_step_ok`.

## 2. Effectiveness metrics

**Primary (A1): exact-match rate.** `EM = (# exact) / N` over all 86 cases, abstains excluded from
both numerator and denominator, with a 95% Wilson CI.

**A2 — selective accuracy and coverage.** Attempted cases = non-abstain. `SelAcc = #exact / #attempted`,
`Coverage = #attempted / N`. Report both together; either alone is misleading.

**A3 — abstention quality.** (a) abstain rate with reason distribution; (b) *justified abstains*:
the two `abstain_by_design` cases must abstain, and no deterministic-node case may abstain; this is
an asserted invariant, not a metric; (c) on wrong claims, per-case union-Jaccard
`J_i = |U(P_i) ∩ U(G_i)| / |U(P_i) ∪ U(G_i)|` where `U` = union of a collection's sets — partial
credit distinguishing "right set, one extra node" from "wrong node". Report mean J over wrong cases.

**A4 — slice reporting.** EM broken out by: hard slice, two-cause, or_fix, silent_decoy,
last_step_ok, and per team. Pooled numbers always accompanied by per-team tables.

## 3. Efficiency metrics (axis B — where the G1 variants are decided)

Per case, with budget `B` trials (default tight budget pre-registered before the runs):

**B1 — trials to first fix** `t_i`: number of G3 trials until the first trial whose restored set
matches a member of `G_i`. For `or_fix` cases, any one gold set counts. Cases where no trial within
`B` matches are budget-exhausted (`t_i = ∞` for summaries; see B3).

**B2 — trials to final verdict** `t'_i`: trials until the search terminates with the final
collection. G1 should leave this unchanged — an *asserted invariant* across variants; any
difference is a bug, not a finding.

**B3 — pass@t curve.** Fraction of cases with `t_i ≤ t` as t goes 1..B, as a step plot per variant,
with budget-exhaustion shown as right-censoring at `B` (Kaplan–Meier estimate; median time-to-fix
reported with CI only when ≥ 50% of cases are solved). Curves over means: reviewers must see the
distribution.

**B4 — budget-exhaustion rate** under the tight budget, with Wilson CI.

**B5 — wall-clock** seconds from diagnose-start to verdict, recorded per case, aggregated as median
(IQR) per variant.

## 4. Cost metrics (required for LLM-backed G1)

Per diagnosis and per case: number of G1 calls, calls failed, calls truncated (card did not fit the
model's context — the mechanism under test), tokens in/out, latency per call, cache hits, and
implied USD cost at the published price. Reported per variant, per team, and against card size
(node count of the candidate set) — the "is context length the issue" analysis is this table.

## 5. Analysis populations (pre-registered)

- **Full set** (86): all headline effectiveness numbers.
- **G1-relevant subset**: cases where ≥ 2 candidates remain when G1 is consulted. G1 cannot matter
  elsewhere; *primary* efficiency comparisons (R2, R3) run on this subset, full-set comparisons are
  secondary. Subset membership must be derivable from the artifact (per-case candidate count), not
  hand-picked after results.
- **Slices** as listed in §1.

## 6. Statistical protocol

1. **CIs everywhere**: Wilson 95% for every rate; BCa bootstrap (10,000 resamples, case-level) for
   every mean/median; CIs shown in every table, not only significance.
2. **Paired tests on the same cases**, never aggregate-vs-aggregate:
   - effectiveness differences between two methods: exact McNemar (all discordant pairs counted),
     plus risk difference with bootstrap CI;
   - trials/seconds differences: exact Wilcoxon signed-rank (n small; ties handled by the
     shift method), with Hodges–Lehmann location-shift estimate and CI; paired bootstrap as
     cross-check.
3. **Multiplicity**: pre-registered families only — (i) engine vs 7 baselines on EM, (ii) each G1
   variant vs no-G1 on t_i over the G1-relevant subset, (iii) pairwise G1-variant comparisons on
   t_i. Holm–Bonferroni within each family. Nothing else is tested; post-hoc observations are
   labelled exploratory.
4. **Equivalence/non-inferiority, not "no significant difference"**: variant A may replace variant B
   only by TOST (two one-sided tests) on t_i with pre-registered margin δ = 0.25 trials on the
   median, or by showing exactness is identical and pass@t curves are nested with overlapping CIs.
   Absence of significance is never reported as "equivalent".
5. **Effect sizes with every p-value**: risk difference / odds ratio for proportions, Cliff's delta
   for t_i.
6. **Small-n honesty**: state the minimum detectable effect at n = 86 (α = .05, power .80) next to
   each primary test; do not claim "no difference" where MDE exceeds the observed effect.
7. **Randomness protocol**:
   - deterministic engine: re-run twice, require byte-identical artifacts (existing AC check);
   - `random_node` and any sampled baseline: ≥ 100 seeds, report mean and CI;
   - hosted LLM G1: temperature 0 (or lowest supported), ≥ 5 passes, report per-pass and pooled
     results plus across-pass agreement of the produced order (Kendall's W or mean pairwise
     Kendall τ); laya local: ≥ 3 passes, identical-order rate;
   - one shared seed list, committed before the runs.

## 7. Pre-registered hypotheses and decision rules

- **H1 (engine beats baselines):** EM(Sherlock) > EM(best baseline) on the full set, McNemar p < .05
  after Holm, abstains not counted. *Decision: claim contribution of the search; otherwise report
  as-is.*
- **H2 (G1 helps efficiency):** for each G1 variant, median `t_i` < no-G1 on the G1-relevant subset,
  Holm-corrected Wilcoxon p < .05, with EM unchanged (asserted). *Decision: report as an ordering
  gain, never as an accuracy gain.*
- **H3 (upgraded grading fixes the context-length failure):** LLM-G1-upgraded vs LLM-G1-current:
  truncation rate strictly lower, EM identical, and `t_i` non-inferior by TOST margin. *Decision:
  the upgrade is validated only if all three hold.*
- **H4 (laya vs LLM-G1):** equivalence on `t_i` by TOST; secondary: cost per diagnosis. *Decision:
  whichever is reported as default, the tie-breaker is cost and failure rate, not accuracy.*

## 8. Public-trace protocol (AEGIS / Who&When; ordering validity only)

Gold here is the published blamed agents, **not** a verified minimal fix. Therefore this dataset
supports only ordering claims; no diagnosis-accuracy claim may be made from it. Metrics:
mean rank, MRR (reciprocal rank), recall@3, NDCG@3, trials-to-label (cost proxy) — as already
computed by `eval/public_g1.py`. Paired per-row bootstrap CIs (10,000 resamples); the random-order
reference gets ≥ 100 seeds for its CI. `mathchat` two-role rows excluded from the headline table
and reported in the appendix, as before. Dataset version and row filters recorded in the artifact.

## 9. Baselines

The planted evaluation reports against: `last_node`, `random_node` (100 seeds), `g0_only`,
`paste_and_play`, `g0_g2`, `plain_retry`, and `llm_guess_stub`. Additionally **required for tier-1**:
one *real-model* LLM baseline — a GPT/Claude-class model given the failed run's trace (and the
passing run for parity with Sherlock's known-good input) asked to name the culprit set(s), scored
on the same cases, same scoring. The stub is labelled a stub in every table and never described as
an LLM result.

## 10. Artifact contract (fields each run must record for the metrics above)

Per case: `case_id`, `team`, slice tags, gold sets, predicted collection, outcome, abstain reason
code, per-trial list (restored set, verdict, outcome), candidate shortlist size at the moment G1
was consulted, G1 calls/tokens/latency/truncation flags per call, wall clock per stage, backend id +
config hash, model id, seed list id, and the corpus/dataset version for public rows. The scoring
script computes every number in §2–§6 from these fields alone; nothing is computed by hand.

## 11. Reporting plan

- Table 1: effectiveness (EM, SelAcc, coverage, abstain rate, mean Jaccard-on-wrong) — engine, all
  baselines, all G1 variants.
- Table 2: efficiency + cost on the G1-relevant subset (median/IQR t_i, pass@B, budget exhaustion,
  wall clock, G1 calls/tokens/$/truncation).
- Figure 1: pass@t curves per variant with censoring marks.
- Table 3: test summary (test statistic, exact p, Holm-adjusted p, effect size, CI, MDE) for every
  pre-registered test.
- Table 4: per-team breakdown (appendix).
- Table 5: public-trace ordering metrics (appendix; ordering claim only).
- Every figure/table reproducible by one script from committed artifacts (§12).

## 12. Reproducibility checklist

- [ ] This spec committed before any 4-gate run; case catalogue and seeds frozen in the same commit.
- [ ] All headline numbers emitted by `eval/score.py` (to be added) from committed artifacts; a
      unit test re-derives the committed tables from the artifacts.
- [ ] Re-run determinism check (byte-identical) for deterministic variants.
- [ ] Public dataset gzip + row-filter code committed; filters printed into the artifact.
- [ ] Environment recorded (model ids, package versions, date) inside each artifact.

## 13. Threats to validity (stated in the paper)

- Internal: faults planted by us; gold defined by the same restore operation the engine performs.
- Construct: EM measures set-recovery, not "true cause"; the restore-based definition is argued, not
  proven, to capture causation.
- External: 86 synthetic cases and one public ordering corpus; no real production incidents.
- Statistical: small n; CIs and MDEs reported; equivalence claimed only via TOST.

## 14. Deviation log

Any change to populations, budgets, tests or margins made after first results must be appended here
with the reason and the date, and marked as post-hoc in every table it affects.
