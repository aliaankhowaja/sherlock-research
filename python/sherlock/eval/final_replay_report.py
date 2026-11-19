"""Regenerate writeup, tables and budget curves from the saved CPU replay observations."""
import csv
import itertools
import json
import math
import random
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[3] / "docs/eval/replay_corpus/final"
METHODS = ["sherlock", "all_changed", "singleton", "exhaustive"]
CAPS = [1, 2, 3, 4, 5, 6, 7, 40]


def write_csv(name, records):
    with (OUT/name).open("w") as f:
        w = csv.DictWriter(f, list(records[0]))
        w.writeheader()
        w.writerows(records)


def signature(sets):
    return sorted(sorted(s) for s in sets)


def correct(c, method):
    return signature(c[method]) == [c["expected"]]


def forks(c, method):
    if method == "sherlock":
        return len(c["trials"])
    if method == "singleton":
        return sum(len(t["restored"]) == 1 for t in c["forks"])
    return 0 if method == "all_changed" else len(c["forks"]) - 1


def quantile(values, p):
    x = sorted(values)
    ix = (len(x)-1)*p
    return x[math.floor(ix)] + (x[math.ceil(ix)]-x[math.floor(ix)])*(ix % 1)


def bootstrap(values):
    if min(values) == max(values):
        return [values[0]]*2
    rng = random.Random(185)
    means = [st.fmean(rng.choices(values, k=len(values))) for _ in range(10000)]
    return [quantile(means,p) for p in (.025,.975)]


def counts(cases, method):
    return {"n": len(cases), "exact": sum(correct(c, method) for c in cases),
            "wrong_nonempty": sum(bool(c[method]) and not correct(c, method) for c in cases),
            "no_set": sum(not c[method] for c in cases),
            "bias_named": sum(any("bias" in s for s in c[method]) for c in cases),
            "mean_forks": st.fmean(forks(c,method) for c in cases),
            "fork_distribution": json.dumps(dict(sorted(Counter(forks(c,method) for c in cases).items())))}


def main():
    rows = [json.loads(x) for x in (OUT/"results.jsonl").read_text().splitlines()]
    dedicated, = [r for r in rows if r["id"]=="abstain"]
    rows = [r for r in rows if r is not dedicated]
    cases = [c for r in rows for c in r["conditions"]]
    clusters = defaultdict(list)
    for r in rows:
        clusters[r["cluster"]].extend(r["conditions"])
    summaries = []
    for factor, key in [("overall",lambda r,c:"all"),("condition",lambda r,c:",".join(c["faults"])),
                        ("benchmark",lambda r,c:r["source"]+"/"+r["benchmark"])]:
        groups = defaultdict(list)
        for r in rows:
            for c in r["conditions"]:
                groups[key(r,c)].append(c)
        for group, cs in sorted(groups.items()):
            for method in METHODS:
                summaries.append({"factor":factor,"group":group,"method":method,**counts(cs,method)})
    write_csv("tables.csv", summaries)
    # Charge each distinct trial through the first observed pass with all proper subsets failed.
    evidence_cost = []
    for r in rows:
        for c in r["conditions"]:
            trials = {frozenset(t["restored"]):t["verdict"] for t in c["forks"]}
            target = frozenset(c["expected"])
            needed = {frozenset(s) for k in range(len(target)+1) for s in itertools.combinations(target,k)}
            for method in METHODS:
                if method=="sherlock":
                    seq = [frozenset(t[0]) for t in c["trials"]]
                else:
                    seq = [s for s in trials if s and (method=="exhaustive" or (method=="singleton" and len(s)==1))]
                seen = {frozenset()}
                first = None
                for i,s in enumerate(seq,1):
                    seen.add(s)
                    if needed <= seen and trials[target]=="pass" and all(trials[u]=="fail" for u in needed-{target}):
                        first = i
                        break
                evidence_cost.append({"case_id":r["id"], "faults":",".join(c["faults"]), "method":method,
                                      "forks_to_verified_assigned_repair":first})
    write_csv("verification_cost.csv",evidence_cost)
    comparisons = []
    for method in METHODS[1:]:
        wins = losses = 0
        diffs = []
        for cs in clusters.values():
            a = [correct(c,"sherlock") for c in cs]
            b = [correct(c,method) for c in cs]
            wins += all(a) and not all(b)
            losses += all(b) and not all(a)
            diffs.append(st.fmean(a)-st.fmean(b))
        n = wins+losses
        p = min(1, 2*sum(math.comb(n,k) for k in range(min(wins,losses)+1))/2**n)
        comparisons.append(dict(comparator=method, wins=wins, losses=losses, exact_p=p,
                                difference=st.fmean(diffs), interval=bootstrap(diffs)))
    prev = 0
    for i, c in enumerate(sorted(comparisons,key=lambda c:c["exact_p"])):
        prev = max(prev,min(1,(3-i)*c["exact_p"]))
        c["holm_p"] = prev
    write_csv("comparisons.csv", comparisons)
    effects = []
    for factor,group in [("joint minus single",lambda c:len(c["expected"])==2),
                         ("bias on minus off",lambda c:"bias.flag" in c["faults"])]:
        for method in METHODS:
            for metric, fn in [("exact",correct),("forks",forks)]:
                diffs = [st.fmean(fn(c,method) for c in cs if group(c))-
                         st.fmean(fn(c,method) for c in cs if not group(c)) for cs in clusters.values()]
                effects.append(dict(contrast=factor,method=method,metric=metric,difference=st.fmean(diffs),
                                    interval=bootstrap(diffs)))
    write_csv("effects.csv",effects)
    curves = []
    for cap in CAPS:
        for method in METHODS:
            exact = verified = used = 0
            for c in cases:
                if method=="sherlock":
                    b = c["budgets"][str(cap)]
                    sets = b["sets"]
                    used += b["forks"]
                    certified = b["complete"]
                elif method=="all_changed":
                    sets = c[method]
                    certified = False
                else:
                    eligible = [t for t in c["forks"] if t["restored"] and
                                (method=="exhaustive" or len(t["restored"])==1)]
                    seen = eligible[:cap]
                    used += len(seen)
                    passed = [set(t["restored"]) for t in seen if t["verdict"]=="pass"]
                    sets = [sorted(s) for s in passed if not any(u<s for u in passed)]
                    certified = len(seen)==len(c["forks"])-1
                ok = signature(sets)==[c["expected"]]
                exact += ok
                verified += ok and certified
            curves.append(dict(cap=cap,method=method,n=len(cases),exact=exact,complete_and_exact=verified,
                               mean_forks=used/len(cases)))
    write_csv("budget_curves.csv",curves)
    # Self-contained Vega-Lite figure specification. Use integer ticks for the fork caps.
    figure = {"$schema":"https://vega.github.io/schema/vega-lite/v5.json",
              "description":"Budget-limited exact repair recovery across six interventions on 185 questions.",
              "width":420, "height":240, "data":{"values":[dict(b,accuracy=b["exact"]/b["n"])
                    for b in curves if b["cap"]<=7]},
              "mark":{"type":"line","point":True},
              "encoding":{"x":{"field":"cap","type":"quantitative","title":"Maximum restore forks",
                               "scale":{"domain":[1,7],"zero":False},"axis":{"tickMinStep":1}},
                          "y":{"field":"accuracy","type":"quantitative","title":"Exact minimal repair recovery",
                               "scale":{"domain":[0,1]},"axis":{"format":".0%"}},
                          "color":{"field":"method","type":"nominal","title":"Method"},
                          "strokeDash":{"field":"method","type":"nominal","title":"Method"}}}
    (OUT/"budget_figure.vl.json").write_text(json.dumps(figure, indent=2)+"\n")
    m = json.loads((OUT/"environment.json").read_text())
    failures = json.loads((OUT/"failures.json").read_text())
    lat = [1000*c["latency_s"] for c in cases]
    orig = [c for c in cases if c["original"]]
    lines = ["# Final replay evaluation", "",
        f"Sherlock recovered the assigned minimal repair in **{sum(correct(c,'sherlock') for c in cases)}/{len(cases)}** crossed fault conditions on {len(rows)} retained questions. The design reused the same recorded reply for all six interventions on each question. There were {len(clusters)} distinct normalized question clusters.",
        "", "## Paired comparisons", "", "| Method | Exact | Wrong nonempty | No set | Bias named | Mean forks |",
        "|---|---:|---:|---:|---:|---:|"]
    for s in summaries[:4]:
        lines.append(f"| {s['method']} | {s['exact']} | {s['wrong_nonempty']} | {s['no_set']} | {s['bias_named']} | {s['mean_forks']:.2f} |")
    lines += ["", "All-changed proposes all nodes whose writes differ. A downstream formatter can change its write even when only extraction is faulty. The singleton policy cannot recover a two-node repair. Exhaustive enumerates all nonempty subsets with a context patch. The observed failed output supplies the empty-set verdict for every method.",
        "", "Exact McNemar tests use one binary outcome per question cluster (all six diagnoses correct). Positive differences below are percentage points of mean condition-level recovery. Percentile intervals resample whole question clusters.",
        "", "| Comparator | Sherlock-only / comparator-only perfect clusters | Difference [95% interval], pp | Holm p |",
        "|---|---:|---:|---:|"]
    for c in comparisons:
        lo,hi = c["interval"]
        lines.append(f"| {c['comparator']} | {c['wins']} / {c['losses']} | {100*c['difference']:.2f} [{100*lo:.2f}, {100*hi:.2f}] | {c['holm_p']:.3g} |")
    lines += ["", "Zero-width empirical intervals arise when all sampled clusters have identical contrasts. They describe variation across these questions under fixed software faults. They provide no uncertainty estimate for new fault families.",
        "", "## Interventions and budget", "", "| Faults | Sherlock exact | Mean forks |","|---|---:|---:|"]
    for s in summaries:
        if s["factor"]=="condition" and s["method"]=="sherlock":
            lines.append(f"| {s['group']} | {s['exact']}/{s['n']} | {s['mean_forks']:.2f} |")
    lines += ["","| Fork cap | Sherlock exact | Search complete and exact |", "|---:|---:|---:|"]
    for b in curves:
        if b["method"]=="sherlock":
            lines.append(f"| {b['cap']} | {b['exact']}/{b['n']} | {b['complete_and_exact']}/{b['n']} |")
    lines += ["", "With three forks, Sherlock completed every single-cause condition and every joint condition without the decoy. Adding the decoy raised certification cost from one to three forks for single causes and from three to seven for the joint fault. At the default budget, exhaustive enumeration and Sherlock used the same number of forks in every design cell.",
              "", "| Method | Assigned repair verified | Median forks through first verification, among verified |",
              "|---|---:|---:|"]
    for method in METHODS:
        costs = [t["forks_to_verified_assigned_repair"] for t in evidence_cost if t["method"]==method
                 and t["forks_to_verified_assigned_repair"] is not None]
        median = f"{st.median(costs):g}" if costs else "—"
        lines.append(f"| {method} | {len(costs)}/{len(cases)} | {median} |")
    lines += ["", "Verification requires an observed passing assigned repair and a failure for each proper subset. The already observed failed run supplies the empty subset. This endpoint can be reached before the search certifies that all minimal sets have been found. Individual costs are in [verification_cost.csv](verification_cost.csv)."]
    lines += ["", "The full method-by-budget curves are in [budget_curves.csv](budget_curves.csv) with a [Vega-Lite figure](budget_figure.vl.json). Baseline curves replay the fixed cardinality-first, graph-order trial sequence up to each cap. A partial search can name the right set before establishing completeness. The all-changed baseline performs zero verification forks. Within-question effect sizes for accuracy and fork count are in [effects.csv](effects.csv).",
        "", "## Selection, controls and reproducibility", "", "| Source / benchmark | Kept / attempted |", "|---|---:|"]
    for key,v in sorted(Counter(r["source"]+"/"+r["benchmark"] for r in rows).items()):
        lines.append(f"| {key} | {v}/50 |")
    control_ok = sum(r["controls"]["withheld"]=="cassette_miss" and
                     r["controls"]["clean"]==r["controls"]["bias_only"]==r["controls"]["restored"] for r in rows)
    d = dedicated["conditions"][0]
    lines += ["", f"The original generation report supplies the 300 attempted questions. The export contains the 185 exact-match successes. {len(orig)} original conditions were re-executed and compared with the exported outputs, minimal sets and individual trials. {len(failures)} recordings have discrepancies in the failure ledger.",
        "", f"Clean and bias-only controls and matched withholding/restoration checks met their expectations on {control_ok}/{len(rows)} questions. Suppressing the model tape caused a miss at solve, before a failed thread was available for diagnosis. Restoring the tape recovered the clean output. In the separate two-request case, the joint restore passed, the two singleton requests missed, and diagnosis returned **{d['status']}** with {len(d['sherlock'])} certified repairs. This is one concrete abstention test.",
        "", "The study covers one linear graph, one recorded model response per headline question, and two deterministic output faults. The original case selection included a diagnosis agreement check. The crossed variants test the same mechanisms. The experiment establishes conditional intervention behavior. Natural agent fault localization and unseen mechanisms require independent data.",
        "", f"Replay ran locally on Debian 13, KVM, Intel Xeon 3.10 GHz (8 cores, 16 logical CPUs), with 62 GiB visible RAM. The first pass ran serially. The repeat used six worker processes. Default diagnosis latency under the adapter was median {st.median(lat):.2f} ms and p95 {quantile(lat,.95):.2f} ms, excluding tape loading and baseline enumeration. Both passes together took {m['total_wall_s']:.1f} s. These measurements cover the in-process adapter; HTTP serving and LangGraph scheduling overhead are outside the measurement.",
        "", "The exported graph's node functions ran in order against strict request-hash SQLite replay. Production diagnose and G3 created and checked forks through a linear checkpoint adapter because the LangGraph server dependencies were unavailable on this host. Recorded server trials provide the parity check. Budget sweeps re-executed the production search policy against independently enumerated trial outcomes. The author confirmed completion of the 30-transcript pilot review.",
        "", "Reproduce from the repository root with `python3 python/sherlock/eval/final_replay.py && python3 python/sherlock/eval/final_replay_report.py`. To regenerate tables alone, run the second command. The input hashes, environment, raw outcomes, tables, and discrepancy ledger are stored beside this report."]
    (OUT/"results.md").write_text("\n".join(lines)+"\n")

if __name__ == "__main__":
    main()
