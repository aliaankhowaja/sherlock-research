# Evaluation (planted fault cases)

Tables: [`results.md`](results.md). Raw data (every case, every method's prediction, gold, trial counts): [`results.json`](results.json).

## Limitations, first

1. **Sherlock diagnoses deterministic nodes exactly and abstains honestly on stochastic ones**. Plant faults in routers, parsers, retrievers, tool calls and validators and no model call sits on the counterfactual path, so every trial resolves. On a team whose faults are purely prompt-level, Sherlock abstains: when a bad node is a prompt variant of an LLM call, every cross-combination of "this node fixed, that node still bad" is a request that was never recorded, and a trial that needs an unrecorded call is reported as "cannot say", never guessed. The case `support_bot:prep.truncate+ask.terse_instruction` shows this: abstain, reason `unrecorded_call`, no culprit named. Single faults on the same team resolve, because the passing run's tape supplies the restored request.
2. **The teams are ours and the faults are planted by us.** Seven teams: four small (3 to 5 nodes) and three large (32 to 33 nodes: customer support, loan underwriting, revenue report), each fault a clean context flag. 84 of 86 cases exact is a statement about this setup, not about real agent failures. The claim that most real bugs live in deterministic nodes is still unmeasured on real failures (the public-trace ordering evaluation is a first step).
3. **The "hidden" set is hidden from tuning, not from us.** It is a seeded sample (seed 20261014, 4 per team) of fault combinations that are not in the visible list, drawn from the same hand-written fault catalogue. It guards against tuning the engine on the visible cases; it is not an independent benchmark.
4. **Gold and Sherlock share a definition of "restore a node"**: remove that node's fault flags. Gold is derived in-process by restoring subsets and re-running the whole graph, never the planted names. Sherlock gets there through the fork, replay and search path over HTTP. Agreement shows the pipeline matches the oracle; it does not show the oracle is the right notion of cause for arbitrary code.
5. **Attribution needs a node map for flags not named after their node** (`--node-map`). Team 2 (`order_desk`) uses flags like `stale_inventory`; without the map `diagnose` abstains `cannot_attribute`. Teams 1, 3 and 4 use the `node.flag` naming convention and need none (the runner passes the map to all four). A restore goes only through run context; a node whose behaviour is not configurable through context cannot be restored.
6. **We recover ancestry, not read-dependencies.** Pruning is conservative.
7. **One known-good run per team, and one failing check Z per team.** Multi-source disagreement is not tested in this evaluation.
8. Small numbers: 86 cases. No confidence intervals; counts are given, not rates to be compared across papers. Do not compare these figures with AgentRx, AgentTrace or Who&When numbers.
9. **The "plain LLM guess" baseline is a stub, not a model.** `llm_guess_stub` (`python/sherlock/eval/baselines.py`) is a fixed local heuristic that stands in for "ask an LLM which node is wrong": it blames the node whose recorded output looks most anomalous (empty values, alarming words) from the failed run alone. It is deterministic and needs no provider. It shows what skimming the trace yields (6 of 86 exact, same as `last_node`); it says nothing about what GPT/Claude-class models would score. Do not quote it as an LLM result.
10. **Live time-travel is a check on one two-cause case, not a scored row.** See "CI invariants".

## Method

- Cases: 52 visible (hand-picked) plus 34 hidden (seeded sample: 4 per small team, 6 per large team), over 7 teams. Defined in `harness/sherlock_harness/catalog.py`, including the hard-slice tags, before any method ran: `two_cause`, `or_fix` (two gold sets), `silent_decoy` (a harmless fault planted beside the real one), `abstain_by_design` (LLM prompt cross-combination). Hard slice = any of those (51 of 86 cases). `last_step_ok` (the node writing the output is not a culprit) is reported as its own slice.
- Pipeline per team group (`python/sherlock/eval/run_eval.py`): `sherlock-rec run langgraph dev` records one passing run per team and one failing run per case against a local echo stub; the stub goes away; the server restarts under `sherlock-rec run --replay` inside a socket trap that forbids every non-loopback connection; `diagnose` runs on each failing run with the team's passing run as the known-good source. The LLM team's cases each get their own lab and cassette holding only that case's own two tapes. (A shared cassette let other cases' requests turn the never-recorded combination into a hit; the first run did exactly that and showed no abstain. It was fixed before the results here.)
- Same tapes, same check Z, same cause definition for all methods. A prediction is a collection of node sets. **exact** = the collection equals the gold collection; **wrong claim** = it names sets that differ; **abstain** = no claim. Abstains are reported beside accuracy and never counted as correct or wrong. Jaccard is over the union of nodes named.
- Added baselines (`python/sherlock/eval/baselines.py`, same cases, same Z, same scoring): `llm_guess_stub` (above; one node), `g0_g2` (G0 clue weights over the nodes G2's pruning leaves as candidates, top node, no G3 trial), `plain_retry` (re-run the failed run's own input and context 3 times on new threads and apply Z; a retry names no node, so it is always scored abstain `no_diagnosis`; it passed 0 of 258 retries).
- Baselines (`python/sherlock/src/sherlock/evaluation.py`): `last_node` (blame the node writing the output), `random_node` (seeded), `g0_only` (sum the G0 clue weights per node, blame the earliest top node, abstain with no clue), `paste_and_play` (restore by pasting the passing run's recorded output and keep every other recorded output; apply Z).

## Results (full tables in `results.md`)

All 86 cases:

| method | exact | wrong claim | abstain |
|---|---|---|---|
| sherlock | 84 | 0 | 2 |
| g0_only | 38 | 48 | 0 |
| random_node | 7 | 79 | 0 |
| last_node | 6 | 80 | 0 |
| paste_and_play | 5 | 79 | 2 |
| g0_g2 (clues + pruning, no G3) | 49 | 37 | 0 |
| llm_guess_stub (STUB) | 6 | 80 | 0 |
| plain_retry | 0 | 0 | 86 (no diagnosis) |

Hidden set (34): Sherlock 34 exact. Hard slice (51): Sherlock 49 exact, 2 abstain (the by-design LLM cases); best baseline 13 exact. Two-node gold (30): Sherlock 28 exact and 2 abstain; every baseline 0 exact. Sherlock used 174 trials where exhaustive enumeration over the same recorded paths (2^n - 1 subsets of the nodes on the path) would use 158,913,790,468 (100.0% fewer).

### At scale (the three large teams, 55 cases)

Pipelines of 32-33 nodes, up to 32 on a path: Sherlock used 1 trial on 27 cases, 3 on 27 and 7 on one, against up to 2^32 - 1 = 4,294,967,295 exhaustive subsets, and returned exactly the gold sets (single, two-cause, AND across parallel branches, two gold sets for a redundant repair). What removed the nodes: the passing run's outputs (a node that wrote the same thing is not tested) and no-op restores (491 / 503 / 578 removals on the three teams); ancestry pruning removed none, since every node here feeds the output. Per-team numbers are in the `Scale` table of `results.md`, and `Gate probes` there show each gate on one run per large team: G1 naming a wrong node first (still exact, it only reorders), G2 cutting a shortlist node that never ran, G2 with only such nodes (abstain), no known-good run (abstain), and a planted-but-harmless run (`already_passes`). The 30+ node teams are the same kind of synthetic as the small ones: a search that stays this small on them says the context-flag setup prunes well, not that real hundred-agent failures are this easy.

The baselines are deliberately cheap. They show that the cases are not solvable by blaming the last node or reading error clues (most faults are silent), not that Sherlock beats a strong learned method.

## Hosted-LLM G1 (E1/E2/E3): the planted leg

Pre-registered in [`metrics-spec.md`](metrics-spec.md) §14.1 (E1/E2, 2026-11-14) and §14 (E3, 2026-11-15) before any scored run. G1's local scoring is replaced by a hosted LLM call over the node card — the same replacement the public-corpus ordering evaluation (§8) needs — and the card is the only manipulated variable: **E1 `small`** is the laya card budget (2,400 chars, byte-identical to the cards the committed local-laya run was scored on, unit-test pinned), **E2 `big`** is 12,000 chars plus `GOOD_IN`/`UPSTREAM`/`WRITES_ALL`, and **E3 `full`** (2026-11-15 amendment) is uncut: no character budget, no per-field cap — the model's own context window is the only limit. Same system prompt, temperature 0, no thinking tokens, 256 output tokens, `gemini-2.5-flash` on Vertex AI. The provider layer (`python/sherlock/src/sherlock/g1_api.py`) also speaks `gemini_api` and any OpenAI-compatible endpoint, configured via `.env`, so the runs can be re-done with a reviewer's own key. Artifact: [`pipeline_g1/pipeline_g1.json`](pipeline_g1/pipeline_g1.json) (+`.md`); scored tables: `table6_pipeline` in [`score.json`](score.json).

86 cases + 3 harmless probes, 5 passes per variant on the G1-relevant subset (candidates ≥ 2), one pass elsewhere — 266 case-passes per variant. As pre-registered, the planted leg is the degenerate/invariant leg (G0 is near-optimal here, §5): what it certifies is that an LLM-backed G1 does not damage the pipeline, and its cost/truncation/stability profile. The ordering signal comes from the public corpus below.

- **Effectiveness**: EM 1.0 in all four variants (off: 84 exact / 2 abstain of 86; small, big and full: 256 exact / 10 abstain each of 266 case-passes; abstains are the by-design LLM cases). Zero wrong answers.
- **Invariants (AC-G1-1)**: 0 answer changes and 0 honesty violations across 798 case-passes (86 + 3×266); trials-to-final-verdict changes: 0 (counted, not asserted).
- **Efficiency** (45 G1-relevant cases, tight B = 10): median t_i = 1.0 in every variant (mean 1.40 off / 1.46 small / 1.43 big / 1.41 full), pass@10 = 1.0, 0 exhausted.
- **Tests** (exact Wilcoxon + Holm within the pre-registered families; family (ii) = each variant vs no-G1, family (iii) = each variant pair — the families grow with the variant and the committed Holm p-values were recomputed, exact p unchanged): exact p 0.375–0.75 in every family-(ii) test and 0.312–0.625 in family (iii); Holm-adjusted all ≥ 0.936; TOST at δ = 0.25 trials: every variant pair equivalent. No trial-count regression from LLM ordering — expected, planted t_i is almost everywhere 1.
- **Cost** (§4, published price recorded verbatim in the artifact): small — 91 cards, mean 1,408 chars, 455 calls, 361k/7.3k tokens in/out, $0.1265; big — mean 4,728 chars (max 11,991), 1.06M/7.4k tokens, $0.3355; full — mean 6,911 chars (max 31,436), 1.55M/7.3k tokens, $0.4823. 0 failed calls in any variant.
- **Truncation**: builder-side cut 22/91 small cards, 16/91 big, **0/91 full** (that is the point of E3: nothing is cut); API-context cuts 0 in every variant (planted cards are far below the 1M-token window; the server's silent truncation behaviour, see the public leg below, never fires here).
- **Stability** (§6.7): mean pairwise Kendall τ of the produced order across 5 passes — 0.77 small, 0.87 big, 0.81 full: the extra context makes the ordering more reproducible, and uncut cards sit between (the uncut tail adds prompt length but not signal on these small planted cases).
- **Reproducibility**: a full re-run from the call cache (`--check`) must be byte-identical modulo wall clock — it passed (`results identical`) for all four variants; every call is cached under `python/sherlock/eval/.g1/api_cache/{variant}/` keyed by card, pass index and call parameters, so an interrupted run only pays for what is missing.

## Hosted-LLM G1 (E1/E2/E3): the public-corpus leg

Same layer, same protocol on the public trace corpus (§8): 4,112 headline rows (aegis 2,364; whowhen 1,748), one scored pass per row (pinned in code; see the §14 disclosure — the first run accidentally scored 5 passes per card, and the superseded pooled artifact stays in git history) plus the pre-registered 200-row × 5-pass stability subsample, orders compared against the published labels with the same rank metrics as the committed laya run, and the committed 100-seed random-order reference reused (not recomputed). Three card variants: `api_small` (the laya budget), `api_big` (8× + extra fields) and, from the 2026-11-15 E3 amendment, `api_full` (no cut at all; mean card 39,196 chars, max 3.74M). Artifact: [`public_traces/public_g1_api.json`](public_traces/public_g1_api.json) (+`.md`); scored table: `table5_public_api` in [`score.json`](score.json), including paired diffs against the committed `public_g1.json` rows (aligned by id). Cost at the 1-pass protocol (recorded from the call usage; the superseded 5-pass run actually sent 5× of the small/big amounts — $21.76 + $75.64 — before the correction): small $4.35 (12.6M/231k tokens), big $15.13 (48.5M/233k), full $53.92 (177.8M/230k). 0 failed calls. The `--check` re-run from the call cache is byte-identical.

**Ordering (lower rank is better):**

| method | rank | reciprocal rank | recall@3 | ndcg@3 | trials→label |
|---|---|---|---|---|---|
| api_big | **1.607** | **0.762** | 0.864 | **0.759** | 6.375 |
| api_full | 1.611 | 0.758 | **0.866** | 0.757 | 6.379 |
| api_small | 1.626 | 0.759 | 0.858 | 0.752 | 6.520 |
| path | 1.627 | 0.747 | 0.855 | 0.747 | **6.098** |
| g0 | 1.656 | 0.745 | 0.854 | 0.745 | 6.328 |
| random (100-seed ref) | 1.679 | 0.732 | 0.866 | 0.731 | 6.518 |

- **Hosted G1 beats path, g0 and random on rank, MRR and ndcg@3 overall**; per-corpus it is honest to note the split: on aegis the committed random reference has the best rank (1.550 vs api_big 1.598), while on whowhen path (1.570) leads the api variants (1.614–1.636) and api beats random by a wide margin (1.854). The api edge over the strongest non-random baseline is concentrated, not uniform.
- **Paired vs the committed laya run (same rows, by id; bootstrap CI95 over rows)**: api_big − laya ndcg@3 +0.014 (0.006…0.023), recall@3 +0.013 (0.005…0.021), trials→label −0.37 (−0.48…−0.26) — all clear of zero; rank −0.027 (−0.056…+0.002) is marginal at 1 pass (the superseded 5-pass pooled run had put it at −0.078, clearly negative). api_full − laya is the same shape (ndcg +0.012, trials −0.37, rank −0.023 crossing zero). Since `api_small`'s cards are byte-identical to laya's, its diffs (rank −0.008 crossing zero, ndcg +0.008 marginal) are the pure scorer effect at 1 pass: the hosted scorer's advantage shows up in ranking quality and trial cost, not decisively in rank.
- **Card budget buys little (E1/E2 at 1 pass)**: api_big − api_small ndcg@3 +0.006 (0.000…0.013), rank −0.020 (−0.040…0.0), trials→label −0.145 (−0.230…−0.062) — the 8× budget helps slightly and consistently, mostly in trial cost.
- **Removing the budget entirely changes nothing measurable (E3)**: api_full − api_big has every paired CI crossing zero (rank +0.004 −0.011…+0.019, ndcg −0.002 −0.007…+0.003, trials +0.005 −0.061…+0.070) while sending 3.7× the prompt characters. Seventy percent of full cards (10,119/14,367) exceed the 12k budget that big would cut; the extra content does not help the hosted scorer pick the culprit faster. Truncation honesty note (§14): Vertex silently truncates over-window prompts, so `api_cut=0` means the server never refused — 3 cards of 14,367 (2.5M–3.7M chars) were window-limited; they are identified in the artifact.
- **Stability** (200 rows × 5 passes): mean pairwise Kendall τ 0.804 small / 0.877 big / 0.874 full — full's τ matches big despite prompts up to 3.7M chars; on the tiny planted cards τ(full) = 0.81 sits between small and big.
- Caveat kept from §8: these are label-ordering metrics; a lower trial count does not mean the named agents are a minimal fix, and on this corpus no known-good run exists, so big/full cards carry no `GOOD_IN` fields (documented asymmetry, §14.1).

## CI invariants

`./scripts/test.sh` stage "evaluation check" regenerates the whole table (about 5 minutes: it records and replays real `langgraph dev` servers) and diffs it with the committed `results.json`, so:

- **Live time-travel must fail the two-cause case**: `invariants.live_time_travel` in `results.json`. The baseline forks the failed run before each node on its path, restores that ONE node, resumes with no cassette (`cassette_path=None`: no replay-session requirement, a cassette miss is not turned into "cannot say", a call nobody recorded would run live) and applies Z. On `vendor_brief:retriever.drop_latest+extractor.legacy_pattern` all five single restores fail Z, so it names nothing (outcome abstain), while Sherlock returns `{retriever, extractor}` exactly. Control `vendor_brief:router.wrong_source`: the same baseline passes on `router`, so it is not a straw man. The run fails (`failures`) if live time-travel ever solves the two-cause case or cannot solve the control. What this proves: one-point time-travel cannot localize two independent causes, each sufficient to break Z. What it does not prove: that cassette blocking matters here. vendor_brief makes no model call, so live and replayed re-runs are identical; a live resume could only pass this case by restoring both nodes at once, which is the set search Sherlock does. Blocking matters on LLM nodes (a live call would return something other than the recorded tape), and that is covered by the `support_bot` abstain case, not by this invariant.
- **Reproducible and freeze-stable**: new processes, ports and thread ids, identical minimal sets, trial counts and baselines. The runner exits 1 on any difference.
- **Replay made zero network calls**: the replay server runs in a socket trap; any attempt is recorded and fails the run.
- **Original thread unchanged after forks**: each failing run's checkpoint history is compared before and after its diagnosis.
- **Verdicts never claim culprits on abstain; every abstain has a reason**: checked on every artifact; the offline test `tests/test_eval_results.py` re-checks the committed file, plus Sherlock >= every baseline, exact on deterministic cases, abstain on the by-design case, and paste-and-play failing every two-cause case.

## What we did not do

- Baselines not built as originally planned: a real-model LLM guess (only the stub exists), random-node averaged over many seeds. `g0_g2` uses G2's pruning, not the suspect path check (that needs G1 suspects, which are off in this eval).
- No real provider, no real agent failures, no human-labelled failures, no stochastic-node measurement beyond the one prompt-variant case. The LLM team talks to a deterministic echo stub, so "the model call differs" is modelled by a request-body change, not by sampling noise.
- No loop or tool-using demo team; teams are DAGs of plain functions plus one httpx call.
- No cross-method statistics, confidence intervals, or ablation of pruning and ordering.
