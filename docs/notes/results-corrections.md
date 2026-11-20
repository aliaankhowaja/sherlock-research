# Results-section corrections

This note is for the team. It says what changed in `docs/paper/sherlock.tex`, why, and what we left alone. The source of the numbers is this repository, not the product checkout.

## Why we changed the paper

A reader who clones this repo can regenerate the planted table, the ablation CSVs, and the 1,110-row solver table. Several sentences in the draft described a different experiment, named the wrong cases, or treated 1,110 template copies as independent failures. Those sentences are what a reviewer would check first.

## What changed

All edits are in [docs/paper/sherlock.tex](../paper/sherlock.tex).

1. **Completeness on the 86 planted runs.** Eligible sets are 41 of size 1, 44 of size 2, and 1 of size 3 (`docs/eval/results.json`). Duality starts only above six candidates, so this run enumerated every nonempty subset. The file does not store the completeness flag. Of 84 exact rows, 82 have `cannot_say_trials` 0. The other two are `support_desk:sla_standard.hours_typo+customer_lookup.stale_cache` and `revenue_report:cap_1000+wrong_text`. The joint restore was marked off track because a restored node did not run again. They are not cassette misses. The cassette misses are the two `unrecorded_call` abstentions. The single-fault rows `customer_lookup.stale_cache` and `cap_1000` have no unknown trial. The abstract, introduction, results, and conclusion now say this.

2. **Public-trace ranking.** `docs/eval/public_traces/public_g1.md` is a Laya run, not the hosted Gemini card study. Aggregate Laya is reciprocal rank 0.759 and 6.745 trials to the label. G0 is 0.745 and 6.328. Path order is 6.098. Random is 0.732. The old sentence (0.762 and 6.375) mixed the masked Who&When cell into the aggregate. No committed cell is 6.375.

3. **The 1,110 solver rows.** They are six fault templates on 185 questions that share one recorded reply. Fork counts are constant inside a template (1, 3, or 7), so a question-level interval on the mean has no width. Of 300 attempts, 115 failed the clean match. The yield is 185/300. The 185 wrong “all changed writes” claims beyond the 555 decoy-on rows are the extraction-only, decoy-off rows: the formatter’s write changes even when only extraction is faulty (`docs/eval/replay_corpus/final/results.md`).

4. **The closest published method.** Li, Song, Yao, and Li, arXiv:2608.29228, already recover inclusion-minimal repair families by replay, with a size bound of two, family exact match 1.000 on 90 in-scope DAGs, an abstention on 30 ordered pairs, and a 24-case model pilot. The related-work table and the bibliography now say so, and they say we did not run a head-to-head.

5. **Invoice figure.** The reference row dropped the recovered amount. Both restores recover 1,200.50 EUR and post 1,320.55 USD, which is what `invoice_pipeline` computes at rate 1.10. The behaviour and the amount are now separate columns.

6. **MAST citation.** The author is Matei Zaharia. The venue is the 39th NeurIPS (2025), Datasets and Benchmarks track. The DOI is unchanged.

7. **Limitations.** The two closing paragraphs of the results section are now a subsection, and they state that the planted search never entered duality.

## What we did not change

- No ablation number that already matches `docs/eval/final_ablations/results.md`, `docs/eval/search_efficiency/results.md`, or `docs/eval/replay_corpus/final/results.md`. Tables 5 through 10 and 12, and the budget and size figures, stay.
- No new recording. Rerunning the 185 questions without the diagnosis-agreement line will not create a new fault: that line excluded nobody, and the faults are still our string edits. A separate 40-question GSM8K recording, with gold frozen before `diagnose` runs, is still the experiment that answers “these bugs are ours.”
- No census file. A direct-search comparison over the 127 three-node predicates is not in this repo. Do not put “21 incorrect completeness flags” back into the abstract until `evidence_search.csv` is committed. The production search function does return a wrong complete family on the predicate that passes only for `{b}` and `{a,b,c}`.
- Author block. The title page still says “Ali Aan” and “Wajih ur raza”. Confirm the full names before changing them.
- `docs/paper/sherlock.pdf`. This machine has no `pdflatex`. Recompile before treating the PDF as current.

## How to review

From `docs/paper/`:

```sh
pdflatex sherlock.tex && pdflatex sherlock.tex
```

Check these sentences against the files named above: the two off-track case ids, Laya 0.759 / 6.745, the 185/300 yield, and the arXiv:2608.29228 paragraph.

## How this was pushed

The edits are on branch `docs/correct-results-claims`. Open the pull request, read the diff of `sherlock.tex`, and merge when the recompiled PDF looks right. Do not commit the PDF from a machine that did not recompile it.
