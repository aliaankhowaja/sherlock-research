# What verification, pruning, and search contribute

Requiring an observed passing restore prevented 33 of 37 wrong top-singleton diagnoses across seven planted teams. Four proposals passed and still omitted a second valid repair. Searching for alternative repairs accounted for a distinction that matters in this study: a valid intervention can be an incomplete diagnosis.

The planted experiments used fresh LangGraph threads, the installed ASGI API, and isolated per-case cassettes. Every one of the 86 default runs reproduced the archived repair collection, reason code, and fork count. All three harmless controls returned `already_passes`. Every one of the 100 archived generated workflows reproduced its oracle table and baseline query traces. The two new executions agreed on all 89 planted records and all 29,200 search rows, including the subset query sequences. The 29,200 rows include repeated measurements on the same workflows.

## Gate ablations

| Paired contrast | Effect | Paired 95% interval | Wins / ties / losses | Holm-adjusted sign-test p |
|---|---:|---:|---:|---:|
| G2 on minus off, complete exact recovery at cap 10, G0 on | 0 pp | [0, 0] | 0 / 86 / 0 | 1 |
| Wrong claims prevented by verifying the same singleton | 38.37 pp | [29.07, 47.67] | 33 / 53 / 0 | 4.66 × 10⁻¹⁰ |
| Forced enumeration minus forced duality, queries per archived workflow | 29.35 | [21.54, 38.18] | 91 / 9 / 0 | 2.42 × 10⁻²⁷ |

Intervals resample cases within the seven fixed teams or entire generated workflows. The search contrast averages over the archived order and ten seeded permutations within each workflow. Intervals describe mean effects. Sign tests describe directional concordance and omit ties. Each planted fault template and each generated oracle has equal weight within its analysis. [Frozen protocol](protocol.md) · [Primary estimates](primary.csv)

- At cap 10, G2 reduced logical fork queries from 194 to 180. All four G0/G2 combinations recovered the exact collection in 84/86 cases, certified completion on 82/86, and retained all gold nodes. The cap of three reduced exact recovery to 83 and complete exact recovery to 81 in all four configurations. The pruning contrast covers executed nodes with a non-noop known-good patch. Identifiable patches already make that universe small. [Full gate matrix by team and fault type](gates.csv)
- The raw and verified singleton both recovered exactly 49/56 cases whose gold repairs were all singletons and 0/30 cases requiring a joint repair. Verification changed 33 wrong claims to abstentions. In the other four wrong cases it returned one of two valid singleton repairs. The wrong-claim reduction remained between 34.3 and 44.1 percentage points when each team was omitted in turn. [Verification](verification.csv) · [Team sensitivity](team_sensitivity.csv)
- Of 86 matched hosted-G1 cases, 45 had at least two candidates. Across their 225 passes per variant, the reconstructed effective search order changed 79 times with small cards, 32 with big cards, and 31 with full cards. Each variant had zero missing eligible scores and zero mean change in total fork queries or exact recovery. This reanalysis used archived scores and fresh G0 clue weights. [Matched hosted results](hosted.csv)

## Search mechanism and certification

On the original candidate order, the 81 workflows below the production switch averaged **18.21 queries with enumeration**, **17.27 with ascending-pruned search**, and **6.10 with forced duality**. On the 19 larger workflows the same methods averaged **112.16**, **111.16**, and **9.11**. Across orders, the mean enumeration-minus-duality effect was 12.09 queries below the switch and 102.90 above it. Forced duality retains the production feasibility probe, small-budget guard, and enumeration fallback. This comparison isolates the branch on the same workflows. It measures deterministic query cost and gives no out-of-sample estimate of the best production threshold. [Size contrasts](size_effect.csv) · [Search matrix](search.csv)

| Production search on fresh circuits | Full-range complete and exact | Complete and exact at 40 queries | Full-range mean queries |
|---|---:|---:|---:|
| One singleton | 40/40 | 40/40 | 16.23 |
| One joint pair | 40/40 | 30/40 | 24.15 |
| Two disjoint pairs | 40/40 | 40/40 | 24.73 |
| Two overlapping pairs | 40/40 | 30/40 | 26.20 |

The 160 circuits cross four Boolean repair structures, four candidate counts and ten seeded node assignments. They exercise alternative passing paths and decoy positions. The 80 alternative-repair cases all yielded the entire gold collection at full range. Seeds vary assignments within a structure, so the four templates bound the generalization claim.

With one verdict withheld per circuit, production search still certified the full collection in **42/160** full-range runs. Other failing supersets can determine an unobserved subset under monotonicity. Across the withheld matrix, every reported minimal set had support in the method's own observations, and every complete claim agreed with all compatible monotone completions. The evaluator checked a passing witness and a failing superset of every immediate child, then tested for undecided masks on complete claims. This is a finite stress test.

In all **40 nonmonotone controls**, the full restore failed while a singleton passed. Production search stopped after the full-set probe on all 40, returned no repairs, and marked each search incomplete. Exhaustive search recovered all 40. The efficiency and completeness claims require monotone restore outcomes. The data establish this property for the enumerated monotone test tables only. [Query traces](search.jsonl.gz) · [Discrepancies and incomplete full-range outcomes on the original order](failures.json)

## Reproduction and interpretation

From the repository root, run `bash scripts/final-ablations.sh /tmp/sherlock-final-new` with the locked Sherlock environment installed. The destination must be new. Each pass uses fresh worker processes, an in-process deterministic echo during recording, and the replay interceptor during diagnosis. Caching repeated verdicts within a case preserves query trajectories and excludes server overhead from cost comparisons. The reference 185-question study previously reran its full server matrix twice. The present experiments add gate attribution and controlled search tests. Public traces remain evidence for ranking against published labels.

The protocol was written locally before collecting these outcomes. The workspace contains no timestamped external preregistration for these ablations. The reproducibility manifest records source and artifact hashes and installed versions. The case ledger retains designed missing-evidence failures and nonmonotone failures. [Environment and hashes](manifest.json) · [Planted case records](planted.jsonl)
