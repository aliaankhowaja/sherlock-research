"""Every pre-registered statistic of docs/eval/metrics-spec.md §2–§8, from the committed artifacts.

    cd python/sherlock
    uv run python eval/score.py --out ../../docs/eval       # writes score.json and score.md

§10/§12: nothing is computed by hand and nothing is read from live state — the script loads the
committed `results.json`, `g1/g1_results.json`, `g1_gen/g1_results.json` and
`public_traces/public_g1.json` and re-derives Tables 1–5 and the Figure-1 pass@t data. A unit test
(test_score_tables.py) re-derives the committed score.json byte for byte.

Pure stdlib, exact where the spec demands exact: Wilson CIs (§6.1), BCa bootstrap CIs (10,000
case-level resamples, §6.1), exact McNemar (§6.2), exact Wilcoxon signed-rank with mid-ranks and a
DP null distribution, Hodges–Lehmann shift with an exact Walsh-average CI, the matched-pairs
rank-biserial (the paired Cliff's delta, §6.5), Holm–Bonferroni (§6.3), TOST at the pre-registered
margin δ = 0.25 trials (§6.4), minimum detectable effects at α=.05/power=.80 (§6.6) and the
Kaplan–Meier pass@t curve with budget-exhaustion as right-censoring (§3 B3). Every bootstrap draws
from one shared seed list (§6.7) derived from SEED, so the output is byte-reproducible.
"""

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from itertools import count
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "src")]

SEED = 20261014            # the committed seed (§6.7); every bootstrap stream derives from it
BOOTSTRAP = 10_000         # §6.1: 10,000 case-level resamples
ALPHA = 0.05
POWER = 0.80
TOST_DELTA = 0.25          # §6.4: pre-registered equivalence margin, in trials
ARE = 0.955                # asymptotic relative efficiency of Wilcoxon vs t, normal data
Z975 = 1.959963984540054
Z95 = 1.6448536269514722
Z80 = 0.8416212335729143
ND = statistics.NormalDist()

ENGINE = "sherlock"
BASELINES = ("last_node", "random_node", "g0_only", "paste_and_play", "g0_g2", "plain_retry",
             "llm_guess_stub")
ORDERS = ("random", "g0", "rule", "hint", "laya", "laya_masked")     # g1 artifacts
PUBLIC_ORDERS = ("random", "path", "g0", "laya", "laya_masked")      # public artifact
PUBLIC_COLS = ("rank", "reciprocal rank", "recall@3", "ndcg@3", "trials_to_label")
NO_G1 = "g0"               # the un-ordered G0 candidate list is the no-G1 comparator (§7 H2)
HARD_TAGS = frozenset({"two_cause", "or_fix", "silent_decoy", "abstain_by_design"})
SLICES = ("hard", "two_cause", "or_fix", "silent_decoy", "last_step_ok")

_seed = count()


def stream():
    """The shared seed list (§6.7): deterministic given the fixed execution order of this module."""
    return random.Random(SEED + next(_seed) * 7919)


def rnd(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, list):
        return [rnd(v) for v in x]
    return x


def rp(p):
    """p-values keep significant digits (round(x, 4) flattens 3.6e-24 to 0.0)."""
    if p is None:
        return None
    return float(f"{p:.3g}")


# --------------------------------------------------------------------------- §6.1 CIs

def wilson(k, n):
    """Wilson 95% CI for a rate k/n."""
    if not n:
        return None
    p = k / n
    d = 1 + Z975 * Z975 / n
    c = (p + Z975 * Z975 / (2 * n)) / d
    h = Z975 * math.sqrt(p * (1 - p) / n + Z975 * Z975 / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def bca(xs, stat, B=BOOTSTRAP):
    """BCa bootstrap CI (§6.1): bias-correction z0 from the bootstrap share below the estimate,
    acceleration a from the jackknife. Case-level resampling, percentile of the adjusted alphas."""
    n = len(xs)
    if n == 0:
        return None
    theta = stat(xs)
    rng = stream()
    boots = sorted(stat([xs[i] for i in rng.choices(range(n), k=n)]) for _ in range(B))
    share = sum(b < theta for b in boots) / B
    z0 = ND.inv_cdf(min(max(share, 0.5 / B), 1 - 0.5 / B))
    jack = [stat(xs[:i] + xs[i + 1:]) for i in range(n)]
    bar = statistics.fmean(jack)
    den = 6.0 * sum((bar - j) ** 2 for j in jack) ** 1.5
    acc = sum((bar - j) ** 3 for j in jack) / den if den else 0.0
    out = []
    for z in (ND.inv_cdf(ALPHA / 2), ND.inv_cdf(1 - ALPHA / 2)):
        t = z0 + (z0 + z) / (1 - acc * (z0 + z))
        idx = min(max(int(ND.cdf(t) * B), 0), B - 1)
        out.append(boots[idx])
    return rnd(out)


def percentile_ci(vals_by_resample):
    """Percentile 95% CI over precomputed resample values."""
    vals = sorted(vals_by_resample)
    b = len(vals)
    return rnd([vals[min(b - 1, int(ALPHA / 2 * b))], vals[min(b - 1, int((1 - ALPHA / 2) * b))]])


def mean_ci(xs, stat=statistics.fmean):
    return bca(xs, stat) if xs else None


# --------------------------------------------------------------------------- §6.2 exact tests

def signed_rank(diffs):
    """Wilcoxon signed-rank machinery: mid-ranks (×2 so they stay integers; the §6.2 tie
    treatment), W+ and the exact null distribution of W+ by DP over the rank multiset."""
    ds = [d for d in diffs if d != 0]
    if not ds:
        return None
    order = sorted(range(len(ds)), key=lambda i: abs(ds[i]))
    ranks2 = [0] * len(ds)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and abs(ds[order[j + 1]]) == abs(ds[order[i]]):
            j += 1
        mid2 = (i + 1) + (j + 1)          # average of 1-based ranks a..b, scaled ×2
        for t in range(i, j + 1):
            ranks2[order[t]] = mid2
        i = j + 1
    total = sum(ranks2)
    dist = [0] * (total + 1)              # dist[s] = #subsets of ranks summing to s
    dist[0] = 1
    for r in ranks2:
        for s in range(total, r - 1, -1):
            dist[s] += dist[s - r]
    w2 = sum(r for d, r in zip(ds, ranks2) if d > 0)
    return {"diffs": diffs, "ranks2": ranks2, "total": total, "dist": dist, "w2": w2, "n": len(ds)}


def _tail(dist, w, side):
    cdf = sum(dist[: w + 1])
    total = sum(dist)
    below, above = cdf, total - cdf + (dist[w] if side == "ge" else 0)
    if side == "ge":
        p = above
    elif side == "le":
        p = below
    else:                                  # two-sided
        p = 2 * min(below, total - below + dist[w])
    return max(0.0, min(1.0, p / total))


def wilcoxon_p(sr, side="two"):
    """Exact p for W+ (side: 'two' | 'ge' | 'le')."""
    if sr is None:
        return None
    return _tail(sr["dist"], sr["w2"], side)


def rank_biserial(sr):
    """Matched-pairs rank-biserial correlation — the paired Cliff's delta (§6.5)."""
    if sr is None:
        return None
    return rnd(2 * sr["w2"] / sr["total"] - 1)


def hodges_lehmann(sr, alpha=ALPHA):
    """HL location shift + exact CI from the Walsh averages and the W+ null distribution."""
    if sr is None:
        return None, None
    diffs = sr["diffs"]
    wal = sorted((di + dj) / 2 for i, di in enumerate(diffs) for dj in diffs[i:])
    m = len(wal)
    total = sum(sr["dist"])
    cum, nu = 0, 0
    for k, cnt in enumerate(sr["dist"]):
        if cum + cnt <= total * alpha / 2:
            cum += cnt
            nu = k + 1
        else:
            break
    lo = wal[min(nu, m - 1)]
    hi = wal[max(0, m - 1 - nu)]
    point = statistics.median(wal)
    return rnd(point), rnd([lo, hi])


def mcnemar(b, c):
    """Exact McNemar on the discordant pairs (§6.2)."""
    d = b + c
    if d == 0:
        return 1.0, d
    smaller = min(b, c)
    p = sum(math.comb(d, k) for k in range(0, smaller + 1)) / 2 ** d
    return min(1.0, 2 * p), d


def mde_mcnemar(d, n):
    """§6.6: smallest detectable EM difference at α=.05/power=.80 given d discordant pairs.
    Among d discordant pairs the split must reach p* = .5 + (z_.975+z_.8)/(2·√d); each discordant
    pair moves EM by 1/n."""
    if not d or not n:
        return None
    pstar = 0.5 + (Z975 + Z80) / (2 * math.sqrt(d))
    return rnd(min(1.0, pstar) * d / n)


def mde_shift(diffs):
    """§6.6: smallest detectable median shift for the signed-rank test,
    (z_.975 + z_.8)·sd(diff)/(√n·√ARE) (ARE 0.955, normal data)."""
    if len(diffs) < 2:
        return None
    sd = statistics.stdev(diffs)
    return rnd((Z975 + Z80) * sd / (math.sqrt(len(diffs)) * math.sqrt(ARE)))


def holm(ps):
    """§6.3 Holm–Bonferroni adjusted p-values (order preserved, monotone)."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out = [0.0] * m
    prev = 0.0
    for k, i in enumerate(order):
        adj = max(prev, min(1.0, (m - k) * ps[i]))
        out[i] = adj
        prev = adj
    return [rp(p) for p in out]


# --------------------------------------------------------------------------- §3 B3 pass@t

def pass_at(rows, B):
    """§3 B3/B4: Kaplan–Meier pass@t for t = 1..B with budget-exhaustion right-censored at B,
    the KM median (only when ≥50% solve, with a case-level bootstrap CI) and the exhaustion rate.

    rows: [(trial_i or None, ...)] where None = budget-exhausted (censored at B)."""
    n = len(rows)
    curve, surv = [], 1.0
    at_risk = n
    for t in range(1, B + 1):
        events = sum(1 for x in rows if x == t)
        if events:
            surv *= 1 - events / at_risk
            at_risk -= events
        censored = sum(1 for x in rows if x is None) if t == B else 0
        curve.append(round(1 - surv, 4))
    solved = [x for x in rows if x is not None]
    median, med_ci = None, None
    if len(solved) >= n / 2:
        reaches = [t for t in range(1, B + 1) if 1 - _km_at(rows, t) >= 0.5]
        median = reaches[0] if reaches else None
        rng = stream()
        meds = []
        for _ in range(BOOTSTRAP):
            sample = [rows[i] for i in rng.choices(range(n), k=n)]
            sol = [x for x in sample if x is not None]
            if len(sol) < n / 2:
                continue
            hit = [t for t in range(1, B + 1) if sum(1 for x in sol if x <= t) >= 0.5 * n]
            meds.append(hit[0] if hit else None)
        meds = sorted(m for m in meds if m is not None)
        if len(meds) > BOOTSTRAP / 2:
            med_ci = percentile_ci(meds)
    return {"pass_at": curve, "median": median, "median_ci95": med_ci,
            "solved": len(solved), "n": n}


def _km_at(rows, t):
    """KM S(t) (survival) at time t — used for the median search above."""
    n = len(rows)
    surv, at_risk = 1.0, n
    for k in range(1, t + 1):
        events = sum(1 for x in rows if x == k)
        if events:
            surv *= 1 - events / at_risk
            at_risk -= events
    return surv


# --------------------------------------------------------------------------- Table 1 (§2)

def effectiveness_table(planted):
    """A1–A4 on the full planted set: EM (abstains excluded both sides) + Wilson CI, SelAcc,
    coverage, abstain rate + reasons, mean Jaccard on wrong (+BCa), slice EMs."""
    cases = planted["cases"]
    n = len(cases)
    out = {}
    for m in (ENGINE, *BASELINES):
        cells = [c["methods"][m] for c in cases]
        exact = sum(x["outcome"] == "exact" for x in cells)
        wrong = sum(x["outcome"] == "wrong" for x in cells)
        abstain = sum(x["outcome"] == "abstain" for x in cells)
        attempted = n - abstain
        reasons = {}
        for x in cells:
            if x["outcome"] == "abstain":
                reasons[x.get("reason") or "none"] = reasons.get(x.get("reason") or "none", 0) + 1
        jac = [x["jaccard"] for x in cells if x["outcome"] == "wrong" and x["jaccard"] is not None]
        slices = {}
        for sl in SLICES:
            sel = [x for c, x in zip(cases, cells)
                   if (frozenset(c["tags"]) & HARD_TAGS if sl == "hard" else sl in c["tags"])]
            ex = sum(x["outcome"] == "exact" for x in sel)
            ab = sum(x["outcome"] == "abstain" for x in sel)
            slices[sl] = {"n": len(sel), "em": rnd(ex / (len(sel) - ab)) if len(sel) - ab else None}
        out[m] = {
            "n": n, "exact": exact, "wrong": wrong, "abstain": abstain,
            "em": rnd(exact / attempted) if attempted else None,
            "em_ci95": wilson(exact, attempted),
            "selacc": rnd(exact / attempted) if attempted else None,
            "coverage": rnd(attempted / n),
            "abstain_rate": rnd(abstain / n), "abstain_rate_ci95": wilson(abstain, n),
            "abstain_reasons": reasons,
            "mean_j_wrong": rnd(statistics.fmean(jac)) if jac else None,
            "mean_j_wrong_ci95": mean_ci(jac),
            "slices": slices,
        }
    return out


def table1_tests(planted):
    """Family (i), §6.3/§7 H1: engine vs each baseline on EM, exact McNemar over the cases both
    attempted, risk difference + paired-bootstrap CI, paired odds ratio, MDE; Holm within family."""
    cases = planted["cases"]
    rows, raw = [], []
    for m in BASELINES:
        b = c = 0
        d_em, diff_pairs = [], []
        for case in cases:
            mine, other = case["methods"][ENGINE], case["methods"][m]
            if mine["outcome"] == "abstain" or other["outcome"] == "abstain":
                continue
            me_ex, ot_ex = mine["outcome"] == "exact", other["outcome"] == "exact"
            b += me_ex and not ot_ex
            c += ot_ex and not me_ex
            diff_pairs.append((1.0 if me_ex else 0.0, 1.0 if ot_ex else 0.0))
        p, d = mcnemar(b, c)
        both = len(diff_pairs)
        if not both:
            continue
        em_me = sum(a for a, _ in diff_pairs) / both
        em_ot = sum(x for _, x in diff_pairs) / both
        rd = em_me - em_ot
        rng = stream()
        boots = []
        for _ in range(BOOTSTRAP):
            idx = rng.choices(range(both), k=both)
            a = statistics.fmean([diff_pairs[i][0] for i in idx])
            o = statistics.fmean([diff_pairs[i][1] for i in idx])
            boots.append(a - o)
        raw.append({"method": m, "b": b, "c": c, "d": d, "p": p, "rd": rd,
                    "rd_ci95": percentile_ci(boots),
                    "or": rnd(b / c) if c else None, "mde": mde_mcnemar(d, both), "n_both": both})
    holms = holm([r["p"] for r in raw])
    for r, hp in zip(raw, holms):
        rows.append({"family": "(i) engine vs baseline, EM (full set)", "test": f"{ENGINE} vs {r['method']}",
                     "statistic": f"McNemar b={r['b']}, c={r['c']} (d={r['d']} of {r['n_both']} both-attempted)",
                     "p_exact": rp(r["p"]), "p_holm": hp,
                     "effect": f"risk diff {rnd(r['rd'])} (CI95 {r['rd_ci95']}), OR {r['or']}",
                     "mde": r["mde"]})
    return rows


# --------------------------------------------------------------------------- Table 2 (§3)

def efficiency_table(g1res, tight):
    """B1/B3/B4/B5 on the G1-relevant subset (§5: ≥2 candidates): median t (IQR), pass@t curve,
    KM median, exhaustion + Wilson CI, G1 wall ms and truncation. t_i is the trial whose restored
    set first matched gold; cases with no match inside B are censored at B."""
    rows = [r for r in g1res["cases"] if r["candidates"] >= 2]
    n_sub = len(rows)
    out = {"n_subset": n_sub, "tight_budget": tight, "methods": {}}
    curves = {}
    for m in ORDERS:
        ts = []
        for r in rows:
            fix = r["methods"][m]["first_fix"]
            ts.append(fix if fix is not None and fix <= tight else None)
        finite = [t for t in ts if t is not None]
        ex_k = sum(1 for x in ts if x is None)
        ms = [r["cost"][m]["ms"] for r in rows if m in r.get("cost", {})]
        cut = sum(len(r["cost"][m]["truncated_cards"]) for r in rows if m in r.get("cost", {}))
        calls = g1res["cost"].get(m, {}).get("calls")
        stats = {"n": n_sub,
                 "median_t": rnd(statistics.median(finite)) if finite else None,
                 "iqr_t": [rnd(q) for q in _iqr(finite)],
                 "mean_t": rnd(statistics.fmean(finite)) if finite else None,
                 "t_ci95": mean_ci(finite, statistics.median),
                 "pass@B": rnd(len(finite) / n_sub),
                 "exhausted": ex_k, "exhausted_ci95": wilson(ex_k, n_sub),
                 "g1_ms_median": rnd(statistics.median(ms)) if ms else None,
                 "g1_ms_iqr": [rnd(q) for q in _iqr(ms)] if ms else None,
                 "g1_calls": calls, "g1_cache_hits": g1res["cost"].get(m, {}).get("hits"),
                 "cut_cards": cut}
        out["methods"][m] = stats
        curves[m] = pass_at(ts, tight)
    out["pass_at_curves"] = curves
    out["b2_invariant_violations"] = sum(
        1 for r in rows if len({r["methods"][m]["final_trials"] for m in ORDERS}) > 1)
    out["tests"] = efficiency_tests(rows, tight)
    return out


def _iqr(xs):
    if len(xs) < 2:
        return [None, None]
    q = statistics.quantiles(xs, n=4)
    return [q[0], q[2]]


def efficiency_tests(rows, tight):
    """Families (ii)/(iii), §6.3/§6.4/§7 H2: t_i on the subset, exact Wilcoxon + HL CI + paired
    effect size + MDE; family (iii) adds TOST at δ = 0.25. Wilcoxon runs on the pairs with both
    trials inside the budget; censored pairs are reported separately."""
    pairs = {}
    for a, b in (("laya", NO_G1), ("laya_masked", NO_G1), ("laya", "laya_masked")):
        diffs, both_cens = [], 0
        for r in rows:
            ta = _t(r, a, tight)
            tb = _t(r, b, tight)
            if ta is None or tb is None:
                both_cens += 1
                continue
            diffs.append(ta - tb)
        sr = signed_rank(diffs)
        if sr is None:                       # every paired difference is zero: no test to run
            fam = "(ii) G1 variant vs no-G1, t_i" if b == NO_G1 else "(iii) G1 variant vs G1 variant, t_i"
            row = {"family": fam, "test": f"{a} vs {b} (subset, B={tight})",
                   "statistic": f"all {len(diffs)} paired differences zero ({both_cens} censored)",
                   "p_exact": 1.0, "p_holm": None,
                   "effect": "HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0", "mde": None}
            if b != NO_G1:
                row["tost"] = {"delta": TOST_DELTA, "p_lower": 1.0, "p_upper": 1.0,
                               "equivalent": False, "note": "degenerate: no non-zero differences"}
            pairs[(a, b)] = row
            continue
        p = wilcoxon_p(sr)
        hl, hl_ci = hodges_lehmann(sr)
        fam = "(ii) G1 variant vs no-G1, t_i" if b == NO_G1 else "(iii) G1 variant vs G1 variant, t_i"
        row = {"family": fam, "test": f"{a} vs {b} (subset, B={tight})",
               "statistic": f"Wilcoxon W+ = {sr['w2'] / 2 if sr else None} over {len(diffs)} pairs "
                            f"({both_cens} censored)",
               "p_exact": rp(p), "p_holm": None,
               "effect": f"HL shift {hl} (CI95 {hl_ci}), rank-biserial {rank_biserial(sr)}",
               "mde": mde_shift(diffs)}
        if b != NO_G1:                                   # §6.4 TOST, margin δ = 0.25 trials
            p_lo = wilcoxon_p(signed_rank([d + TOST_DELTA for d in diffs]), "ge")
            p_hi = wilcoxon_p(signed_rank([d - TOST_DELTA for d in diffs]), "le")
            row["tost"] = {"delta": TOST_DELTA, "p_lower": rnd(p_lo), "p_upper": rnd(p_hi),
                           "equivalent": bool(p_lo < ALPHA and p_hi < ALPHA)}
        pairs[(a, b)] = row
    for fam in ("(ii)", "(iii)"):
        grp = [r for r in pairs.values() if r["family"].startswith(fam)]
        holms = holm([r["p_exact"] for r in grp])
        for r, hp in zip(grp, holms):
            r["p_holm"] = hp
    return list(pairs.values())


def _t(row, m, tight):
    fix = row["methods"][m]["first_fix"]
    return fix if fix is not None and fix <= tight else None


# --------------------------------------------------------------------------- Table 4 (§2 A4)

def per_team(planted):
    out = {}
    for m in (ENGINE, *BASELINES):
        teams = {}
        for c in planted["cases"]:
            x = c["methods"][m]
            t = teams.setdefault(c["team"], {"n": 0, "exact": 0, "wrong": 0, "abstain": 0})
            t["n"] += 1
            t["exact"] += x["outcome"] == "exact"
            t["wrong"] += x["outcome"] == "wrong"
            t["abstain"] += x["outcome"] == "abstain"
        out[m] = {t: {**v, "em": rnd(v["exact"] / (v["n"] - v["abstain"])) if v["n"] - v["abstain"] else None}
                  for t, v in sorted(teams.items())}
    return out


# --------------------------------------------------------------------------- Table 5 (§8)

def public_table(pub):
    """Mean rank, MRR, recall@3, NDCG@3, trials-to-label with paired per-row percentile bootstrap
    CIs (§8): one resample of rows per metric, shared across methods so the CIs stay paired."""
    rows = pub["rows"]
    n = len(rows)
    out = {"rows": n, "backend": pub["backend"], "seed": pub["seed"], "methods": {},
           "random_ref": pub.get("random_ref")}
    for m in PUBLIC_ORDERS:
        out["methods"][m] = {"means": {}, "ci95": {}}
    vals = {m: {col: [r["methods"][m][col] for r in rows] for col in PUBLIC_COLS} for m in PUBLIC_ORDERS}
    for col in PUBLIC_COLS:
        for m in PUBLIC_ORDERS:
            colvals = [v for v in vals[m][col] if v is not None]
            out["methods"][m]["means"][col] = rnd(statistics.fmean(colvals)) if colvals else None
        rng = stream()
        boots = {m: [] for m in PUBLIC_ORDERS}
        # one resample of rows per metric, shared across methods: the CIs stay paired (§6.2)
        for _ in range(BOOTSTRAP):
            idx = rng.choices(range(n), k=n)
            for m in PUBLIC_ORDERS:
                v = vals[m][col]
                boots[m].append(sum(map(v.__getitem__, idx)) / n)
        for m in PUBLIC_ORDERS:
            out["methods"][m]["ci95"][col] = percentile_ci(boots[m])
    return out


# --------------------------------------------------------------------------- E1/E2 (hosted G1)

def _pooled_t(case, variant):
    """The case's pooled t_i (mean over its passes), as pipeline_g1 records it."""
    vals = [p["t_i"] for p in case["variants"][variant]["passes"] if p["t_i"] is not None]
    return round(statistics.fmean(vals), 3) if vals else None


def _km_pass_at_frac(ts, tight):
    """Kaplan–Meier pass@t for pooled (possibly fractional) t_i: events accumulate over a window
    (x <= t minus x <= t-1), right-censoring budget-exhausted rows at the tight budget. Same
    estimator as `pass_at` above; the window replaces the exact-match step because a pooled t_i
    is a mean over passes."""
    n = len(ts)
    finite = [x for x in ts if x is not None]
    curve, surv, at_risk, prev = [], 1.0, n, 0
    for t in range(1, tight + 1):
        events = sum(1 for x in finite if prev < x <= t)
        if events:
            surv *= 1 - events / at_risk
            at_risk -= events
        prev = t
        if t == tight:
            at_risk -= n - len(finite)
        curve.append(round(1 - surv, 4))
    solved = finite
    median = None
    if n and len(solved) >= n / 2:
        reach = [t for t in range(1, tight + 1) if sum(1 for x in solved if x <= t) >= 0.5 * n]
        median = reach[0] if reach else None
    return {"pass_at": curve, "median": median, "solved": len(solved), "n": n}


def pipeline_tables(pipe):
    """E1/E2 tables re-derived from the per-case rows of pipeline_g1.json (§10: the scoring layer
    does not trust the run script's own summary blocks)."""
    tight = pipe["tight_budget"]
    variants = tuple(pipe["variants"])
    cases = pipe["cases"]
    eff = {}
    for v in variants:
        cells = [p for c in cases for p in c["variants"][v]["passes"]]
        exact = sum(x["outcome"] == "exact" for x in cells)
        wrong = sum(x["outcome"] == "wrong" for x in cells)
        ab = sum(x["outcome"] == "abstain" for x in cells)
        jac = [x["jaccard"] for x in cells if x["outcome"] == "wrong" and x["jaccard"] is not None]
        eff[v] = {"case_passes": len(cells), "exact": exact, "wrong": wrong, "abstain": ab,
                  "em": rnd(exact / (len(cells) - ab)) if len(cells) - ab else None,
                  "em_ci95": wilson(exact, len(cells) - ab) if len(cells) - ab else None,
                  "mean_j_wrong": rnd(statistics.fmean(jac)) if jac else None}
    subset = [c for c in cases if c["g1_relevant"]]
    series = {}
    efficiency = {}
    for v in variants:
        pooled = [_pooled_t(c, v) for c in subset]
        series[v] = [t if (t is not None and t <= tight) else None for t in pooled]
        finite, finite_all = [t for t in series[v] if t is not None], [t for t in pooled if t is not None]
        exh = sum(1 for t in series[v] if t is None)
        efficiency[v] = {"n": len(subset),
                         "median_t": rnd(statistics.median(finite)) if finite else None,
                         "iqr_t": [rnd(q) for q in _iqr(finite)],
                         "mean_t": rnd(statistics.fmean(finite_all)) if finite_all else None,
                         "t_ci95": mean_ci(finite, statistics.median) if finite else None,
                         "pass@B": rnd(len(finite) / len(subset)) if subset else None,
                         "exhausted": exh, "exhausted_ci95": wilson(exh, len(subset)) if subset else None}
    cost = {}
    for v in ("small", "big"):
        chars, truncated, tokens_in, tokens_out, calls_ok, calls_failed = [], 0, 0, 0, 0, 0
        for c in cases:
            g1 = c["variants"][v].get("g1")
            if not g1:
                continue
            cut = set(g1.get("truncated_cards") or [])
            for n, size in (g1.get("card_chars") or {}).items():
                chars.append(size)
                truncated += n in cut
            tokens_in += (g1.get("cost") or {}).get("tokens_in") or 0
            tokens_out += (g1.get("cost") or {}).get("tokens_out") or 0
            calls_ok += (g1.get("calls") or {}).get("ok") or 0
            calls_failed += (g1.get("calls") or {}).get("failed") or 0
        usd = None
        if pipe["config"].get("price_in") and pipe["config"].get("price_out"):
            usd = round(tokens_in / 1e6 * float(pipe["config"]["price_in"])
                        + tokens_out / 1e6 * float(pipe["config"]["price_out"]), 4)
        cost[v] = {"cards": len(chars),
                   "card_chars_mean": rnd(statistics.fmean(chars)) if chars else None,
                   "card_chars_max": max(chars) if chars else None, "builder_truncated": truncated,
                   "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd,
                   "calls_ok": calls_ok, "calls_failed": calls_failed}
    invars = {"answer_changed": sum(1 for c in cases if c["invariants"]["answer_changed"]),
              "b2_changed": sum(1 for c in cases if c["invariants"]["b2_changed"]),
              "violations": sum(1 for c in cases if c["off"]["violations"]
                                or any(p["violations"] for v in ("small", "big")
                                       for p in c["variants"][v]["passes"])),
              "case_passes_total": sum(len(c["variants"][v]["passes"]) for c in cases for v in ("small", "big"))}
    tests = pipeline_tests(series, tight)
    return {"config": {k: pipe["config"].get(k) for k in
                       ("provider", "model", "config_hash", "prompt_version", "price_source")},
            "seed": pipe["seed"], "passes": pipe["passes"], "tight_budget": tight,
            "prompt_version": pipe.get("prompt_version"),
            "stability": pipe.get("stability"),
            "truncation_by_card_size": pipe.get("truncation_by_card_size"),
            "effectiveness": eff, "efficiency": efficiency,
            "pass_at": {v: _km_pass_at_frac(series[v], tight) for v in variants},
            "cost": cost, "invariants": invars, "tests": tests}


def pipeline_tests(series, tight):
    """Families (ii)/(iii) on the pooled t_i series (censored pairs excluded and counted), the same
    exact machinery as `efficiency_tests` above."""
    tests = []
    for a, b in (("small", "off"), ("big", "off"), ("small", "big")):
        diffs, censored = [], 0
        for ta, tb in zip(series[a], series[b]):
            if ta is None or tb is None:
                censored += 1
                continue
            diffs.append(round(ta - tb, 3))
        fam = "(ii) G1 variant vs no-G1, t_i" if b == "off" else "(iii) G1 variant vs G1 variant, t_i"
        row = {"family": fam, "test": f"{a} vs {b} (subset, tight B={tight})"}
        sr = signed_rank(diffs)
        if sr is None:
            row.update(statistic=f"all {len(diffs)} paired differences zero ({censored} censored)",
                       p_exact=1.0, p_holm=None,
                       effect="HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0", mde=None)
            if b != "off":
                row["tost"] = {"delta": TOST_DELTA, "p_lower": 1.0, "p_upper": 1.0,
                               "equivalent": False, "note": "degenerate: no non-zero differences"}
            tests.append(row)
            continue
        p = wilcoxon_p(sr)
        hl, hl_ci = hodges_lehmann(sr)
        row.update(statistic=f"Wilcoxon W+ = {sr['w2'] / 2} over {len(diffs)} pairs ({censored} censored)",
                   p_exact=rp(p), p_holm=None,
                   effect=f"HL shift {hl} (CI95 {hl_ci}), rank-biserial {rank_biserial(sr)}",
                   mde=mde_shift(diffs))
        if b != "off":
            p_lo = wilcoxon_p(signed_rank([d + TOST_DELTA for d in diffs]), "ge")
            p_hi = wilcoxon_p(signed_rank([d - TOST_DELTA for d in diffs]), "le")
            row["tost"] = {"delta": TOST_DELTA, "p_lower": rnd(p_lo), "p_upper": rnd(p_hi),
                           "equivalent": bool(p_lo < ALPHA and p_hi < ALPHA)}
        tests.append(row)
    for fam in ("(ii)", "(iii)"):
        grp = [r for r in tests if r["family"].startswith(fam)]
        for r, hp in zip(grp, holm([t["p_exact"] for t in grp])):
            r["p_holm"] = hp
    return tests


def public_api_table(pub_api, laya_pub):
    """Table 5 extended with the hosted G1 orders: paired per-row percentile bootstrap CIs as in
    `public_table`, plus paired api-vs-laya differences (same corpus rows, same budgets — the
    pairing is over the corpus, rows aligned by id). The laya means/CIs are re-computed here on
    the api rows so every cell of the table is paired; the random-order reference is the
    committed laya artifact's (order-only, model-independent)."""
    laya_rows = {r["id"]: r for r in laya_pub["rows"]}
    orders = ("random", "path", "g0", "laya", *(f"api_{v}" for v in pub_api["variants"]))

    def cell(row, m, col):
        if m in ("random", "path", "g0") or m.startswith("api_"):
            return row["methods"][m][col]
        laya_row = laya_rows.get(row["id"])
        return laya_row["methods"][m][col] if laya_row else None

    rows = pub_api["rows"]
    n = len(rows)
    out = {"rows": n, "backend": pub_api["backend"], "seed": pub_api["seed"], "methods": {},
           "random_ref": laya_pub.get("random_ref")}
    for m in orders:
        out["methods"][m] = {"means": {}, "ci95": {}}
    vals = {m: {col: [cell(r, m, col) for r in rows] for col in PUBLIC_COLS} for m in orders}
    for col in PUBLIC_COLS:
        for m in orders:
            colvals = [v for v in vals[m][col] if v is not None]
            out["methods"][m]["means"][col] = rnd(statistics.fmean(colvals)) if colvals else None
        rng = stream()
        boots = {m: [] for m in orders}
        for _ in range(BOOTSTRAP):
            idx = rng.choices(range(n), k=n)
            for m in orders:
                v = vals[m][col]
                boots[m].append(sum(map(v.__getitem__, idx)) / n)
        for m in orders:
            out["methods"][m]["ci95"][col] = percentile_ci(boots[m])
    # paired differences against the laya orders (same corpus rows)
    diffs_out = {}
    for a, b in (("api_small", "laya"), ("api_big", "laya"), ("api_big", "api_small")):
        if a not in vals or b not in vals:
            continue
        diffs_out[f"{a} - {b}"] = {}
        for col in PUBLIC_COLS:
            pairs = [(va, vb) for va, vb in zip(vals[a][col], vals[b][col])
                     if va is not None and vb is not None]
            if not pairs:
                continue
            d = [va - vb for va, vb in pairs]
            rng = stream()
            boots = []
            for _ in range(BOOTSTRAP):
                idx = rng.choices(range(len(d)), k=len(d))
                boots.append(sum(map(d.__getitem__, idx)) / len(d))
            diffs_out[f"{a} - {b}"][col] = {"mean": rnd(statistics.fmean(d)), "n": len(d),
                                            "ci95": percentile_ci(boots)}
    out["paired_diffs"] = diffs_out
    return out


# --------------------------------------------------------------------------- invariants (§2 A3b)

def invariants(planted):
    """Asserted invariants, not metrics: the abstain_by_design cases abstain (engine) and no other
    case does; the final-verdict trial count (B2) is order-invariant."""
    reasons = [c["methods"][ENGINE].get("reason") for c in planted["cases"]
               if c["methods"][ENGINE]["outcome"] == "abstain"]
    bad = [c["id"] for c in planted["cases"]
           if c["expect_abstain"] != (c["methods"][ENGINE]["outcome"] == "abstain")]
    return {"abstain_reasons": reasons, "abstain_invariant_violations": bad,
            "expect_abstain_cases": sum(c["expect_abstain"] for c in planted["cases"])}


# --------------------------------------------------------------------------- driver

def compute(root):
    root = Path(root)
    artifacts = {name: str(p) for name, p in (
        ("results", root / "results.json"), ("g1", root / "g1" / "g1_results.json"),
        ("g1_gen", root / "g1_gen" / "g1_results.json"),
        ("public", root / "public_traces" / "public_g1.json"))}
    planted = json.loads(Path(artifacts["results"]).read_text())
    g1 = json.loads(Path(artifacts["g1"]).read_text())
    gen = json.loads(Path(artifacts["g1_gen"]).read_text())
    pub = json.loads(Path(artifacts["public"]).read_text())
    res = {
        "meta": {"seed": SEED, "bootstrap": BOOTSTRAP, "alpha": ALPHA, "tost_delta": TOST_DELTA,
                 "artifact_sha256": {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()[:16]
                                     for k, v in artifacts.items()}},
        "table1": effectiveness_table(planted),
        "table1_tests": table1_tests(planted),
        "table2_planted": efficiency_table(g1, g1["tight_budget"]),
        "table2_generated": efficiency_table(gen, gen["tight_budget"]),
        "invariants": invariants(planted),
        "table4_per_team": per_team(planted),
        "table5_public": public_table(pub),
    }
    res["table3_tests"] = res["table1_tests"] + res["table2_planted"]["tests"] \
        + res["table2_generated"]["tests"]
    # E1/E2 artifacts (hosted G1) are optional: the committed tables above are unchanged without
    # them, and every block below is re-derived from the per-case rows (§10), never from the run
    # script's own summary.
    pipeline_path = root / "pipeline_g1" / "pipeline_g1.json"
    if pipeline_path.is_file():
        pipe = json.loads(pipeline_path.read_text())
        res["meta"]["artifact_sha256"]["pipeline"] = hashlib.sha256(pipeline_path.read_bytes()).hexdigest()[:16]
        res["table6_pipeline"] = pipeline_tables(pipe)
        res["table3_tests"] += res["table6_pipeline"]["tests"]
    public_api_path = root / "public_traces" / "public_g1_api.json"
    if public_api_path.is_file():
        pub_api = json.loads(public_api_path.read_text())
        res["meta"]["artifact_sha256"]["public_api"] = hashlib.sha256(public_api_path.read_bytes()).hexdigest()[:16]
        res["table5_public_api"] = public_api_table(pub_api, pub)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=HERE.parents[2] / "docs" / "eval")
    ap.add_argument("--out", type=Path, help="write score.json and score.md here")
    a = ap.parse_args()
    res = compute(a.root)
    md = render(res)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "score.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8", newline="\n")
        (a.out / "score.md").write_text(md, encoding="utf-8", newline="\n")
    print(md, end="")


def render(res):
    def table(head, body):
        lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        lines += ["| " + " | ".join("-" if v is None else str(v) for v in row) + " |" for row in body]
        return "\n".join(lines)

    meta = res["meta"]
    parts = [f"# Scored tables (metrics spec §2–§8; seed {meta['seed']}, "
             f"{meta['bootstrap']} resamples, α={meta['alpha']}, TOST δ={meta['tost_delta']})",
             "",
             "Recomputed from the committed artifacts alone (§10). Abstains are excluded from EM's "
             "numerator and denominator; every rate carries a Wilson 95% CI, every mean/median a "
             "BCa or paired percentile bootstrap CI.",
             "", "## Table 1 — effectiveness, planted full set (86)", ""]
    t1 = res["table1"]
    parts.append(table(["method", "n", "exact", "wrong", "abstain", "EM", "EM CI95", "coverage",
                        "abstain rate", "mean J (wrong)", "J CI95"],
                       [[m, v["n"], v["exact"], v["wrong"], v["abstain"], v["em"], v["em_ci95"],
                         v["coverage"], v["abstain_rate"], v["mean_j_wrong"], v["mean_j_wrong_ci95"]]
                        for m, v in t1.items()]))
    parts += ["", "### Slice EM (abstains excluded)", "",
              table(["method"] + [sl for sl in SLICES],
                    [[m] + [v["slices"][sl]["em"] for sl in SLICES] for m, v in t1.items()])]
    parts += ["", "## Table 3 — pre-registered tests (Holm within family)", "",
              table(["family", "test", "statistic", "exact p", "Holm p", "effect", "MDE",
                     "TOST p(≤−δ)", "TOST p(≥+δ)", "equivalent"],
                    [[r["family"], r["test"], r["statistic"], r["p_exact"], r["p_holm"],
                      r["effect"], r["mde"],
                      *(r.get("tost", {}).get(k) for k in ("p_lower", "p_upper", "equivalent"))]
                     for r in res["table3_tests"]])]
    for name, label in (("table2_planted", "planted (B=2)"), ("table2_generated", "generated (B=10)")):
        t2 = res[name]
        parts += [f"## Table 2 — efficiency + cost, G1-relevant subset, {label} "
                  f"({t2['n_subset']} cases with ≥2 candidates; B2 order-invariance violations: "
                  f"{t2['b2_invariant_violations']})", "",
                  table(["method", "n", "median t", "IQR", "mean t", "median CI95", "pass@B",
                         "exhausted", "exh. CI95", "G1 ms median", "G1 ms IQR", "calls", "cache hits",
                         "cut cards"],
                        [[m, v["n"], v["median_t"], v["iqr_t"], v["mean_t"], v["t_ci95"],
                          v["pass@B"], v["exhausted"], v["exhausted_ci95"], v["g1_ms_median"],
                          v["g1_ms_iqr"], v["g1_calls"], v["g1_cache_hits"], v["cut_cards"]]
                         for m, v in t2["methods"].items()])]
        fig = t2["pass_at_curves"]
        parts += ["", f"### Figure 1 (data) — pass@t, KM with censoring at B, {label}", "",
                  table(["method"] + [f"t={t}" for t in range(1, len(next(iter(fig.values()))["pass_at"]) + 1)]
                        + ["KM median", "median CI95"],
                        [[m] + c["pass_at"] + [c["median"], c["median_ci95"]] for m, c in fig.items()])]
    parts += ["", "## Invariants", "",
              f"- abstain reasons (engine): {res['invariants']['abstain_reasons']}; "
              f"expect-abstain violations: {res['invariants']['abstain_invariant_violations']} "
              f"(expect_abstain cases: {res['invariants']['expect_abstain_cases']})",
              "- B2 (trials to final verdict) is order-invariant: violations "
              f"{res['table2_planted']['b2_invariant_violations']} (planted), "
              f"{res['table2_generated']['b2_invariant_violations']} (generated)"]
    parts += ["", "## Table 4 — per team, planted (exact/n and EM)", ""]
    t4 = res["table4_per_team"]
    teams = sorted(next(iter(t4.values())))
    head = ["team"] + sum(([f"{m} exact/n", f"{m} EM"] for m in t4), [])
    body = [[t] + sum(([f"{t4[m][t]['exact']}/{t4[m][t]['n']}", t4[m][t]["em"]] for m in t4), [])
            for t in teams]
    parts.append(table(head, body))
    t5 = res["table5_public"]
    parts += ["", "## Table 5 — public-trace ordering (ordering claims only; "
              f"{t5['rows']} headline rows, seed {t5['seed']})", "",
              table(["method", "metric", "mean", "CI95"],
                    [[m, col, t5["methods"][m]["means"][col], t5["methods"][m]["ci95"][col]]
                     for m in PUBLIC_ORDERS for col in PUBLIC_COLS])]
    if t5.get("random_ref"):
        r = t5["random_ref"]
        parts += ["", "### Random-order reference (100 seeds, mean + percentile 95% CI)", "",
                  table(["metric", "mean", "CI95"],
                        [[k, v["mean"], v["ci95"]] for k, v in r["metrics"].items()])]
    if "table6_pipeline" in res:
        t6 = res["table6_pipeline"]
        parts += ["", f"## Table 6 — E1/E2, the 4-gate pipeline with the hosted G1 "
                  f"({t6['config']['provider']} / {t6['config']['model']}, {t6['passes']} passes, "
                  f"tight B={t6['tight_budget']}; prompt {t6['prompt_version']})", "",
                  "Effectiveness (every case, every pass; EM = exact / answered):", "",
                  table(["variant", "case-passes", "exact", "wrong", "abstain", "EM", "EM CI95",
                         "mean J (wrong)"],
                        [[v, e["case_passes"], e["exact"], e["wrong"], e["abstain"], e["em"],
                          e["em_ci95"], e["mean_j_wrong"]] for v, e in t6["effectiveness"].items()]),
                  "", "Efficiency on the G1-relevant subset (pooled t_i over passes; pass@B at the "
                      "tight budget; exhaustion on the tight-budget diagnosis):", "",
                  table(["variant", "n", "median t", "IQR", "mean t", "median CI95", "pass@B",
                         "exhausted", "exh. CI95"],
                        [[v, e["n"], e["median_t"], e["iqr_t"], e["mean_t"], e["t_ci95"], e["pass@B"],
                          e["exhausted"], e["exhausted_ci95"]] for v, e in t6["efficiency"].items()]),
                  "", "### Figure 1 (data) — pass@t, KM with censoring at the tight budget", "",
                  table(["variant"] + [f"t={t}" for t in range(1, t6["tight_budget"] + 1)] + ["KM median"],
                        [[v] + c["pass_at"] + [c["median"]] for v, c in t6["pass_at"].items()]),
                  "", "Cost (§4; tokens from the API usage fields, USD at the recorded published price):", "",
                  table(["variant", "cards", "mean chars", "max chars", "builder-cut", "calls ok",
                         "calls failed", "tokens in", "tokens out", "USD"],
                        [[v, c["cards"], c["card_chars_mean"], c["card_chars_max"], c["builder_truncated"],
                          c["calls_ok"], c["calls_failed"], c["tokens_in"], c["tokens_out"], c["usd"]]
                         for v, c in t6["cost"].items()]),
                  "", "Invariants: answers changed by G1 "
                  f"{t6['invariants']['answer_changed']} case(s), B2 changed {t6['invariants']['b2_changed']}, "
                  f"honesty violations {t6['invariants']['violations']} "
                  f"(of {t6['invariants']['case_passes_total']} case-passes).",
                  "", "Across-pass agreement of the produced order (mean pairwise Kendall tau): "
                  f"{t6['stability']}"]
    if "table5_public_api" in res:
        t5a = res["table5_public_api"]
        parts += ["", f"## Table 5b — public-trace ordering with the hosted G1 "
                  f"({t5a['backend']}; {t5a['rows']} headline rows, seed {t5a['seed']})", "",
                  table(["method", "metric", "mean", "CI95"],
                        [[m, col, t5a["methods"][m]["means"][col], t5a["methods"][m]["ci95"][col]]
                         for m in t5a["methods"] for col in PUBLIC_COLS]),
                  "", "Paired differences on the same rows (api order − reference order):", "",
                  table(["pair", "metric", "mean diff", "n", "CI95"],
                        [[pair, col, d["mean"], d["n"], d["ci95"]]
                         for pair, per_col in t5a["paired_diffs"].items() for col, d in per_col.items()])]
    note = ["", "G1 wall ms is the per-scoring-pass clock recorded in the artifacts (B5 proxy: "
            "diagnose-start→verdict stage timing is not in the artifact); tokens/USD are not "
            "recorded (card_chars/3 is the token stand-in; §14 deviation log)."]
    if "table6_pipeline" in res or "table5_public_api" in res:
        note = ["", "G1 wall ms is the per-scoring-pass clock of the local backends (B5 proxy); the "
                "hosted-G1 artifacts record calls, tokens and USD from the API usage fields "
                "(§14.1), and their truncation flags distinguish the builder-side cut from the "
                "model-context cut."]
    parts += note
    return "\n\n".join(parts) + "\n"


if __name__ == "__main__":
    main()
