"""The full 4-gate pipeline with an LLM-backed G1 (metrics spec §2–§7; experiments E1 and E2).

    cd python/sherlock
    GOOGLE_CLOUD_PROJECT=... uv run python eval/pipeline_g1.py --out ../../docs/eval/pipeline_g1
    uv run python eval/pipeline_g1.py --only vendor_brief          # a quick partial run (never with --out you keep)
    uv run python eval/pipeline_g1.py --check ../../docs/eval/pipeline_g1/pipeline_g1.json  # re-run from cache

E1 = the planted cases through the real pipeline (record good+failed runs against the echo stub,
replay under the socket trap, G0/G2/G3 exactly as run_eval.py) with G1 = one hosted-LLM call per
candidate node card, the SMALL cards (CARD_VARIANTS["small"]: byte-identical to the cards the local
laya checkpoint was scored on). E2 = the same, with the BIG cards (8x the character budget, 4x the
snippets, GOOD_IN + UPSTREAM + WRITES_ALL). Same system prompt, same model, same call parameters for
both (the configuration is recorded in the artifact's `config` block); the card text is the only
manipulated variable.

Per case the no-G1 diagnosis runs first (pairing), then `--passes` G1 passes per variant on the
G1-relevant subset (candidates >= 2; a single pass elsewhere, where G1 has nothing to order). Each
pass records t_i (first trial whose restored set is in gold), trials to the final verdict (B2), the
outcome against gold, wall clock and the G1 cost record (§4/§10: calls, tokens, truncation, USD).
A tight-budget (B = --tight, pre-registered 10) diagnosis per variant gives the exhaustion rate (B4)
independently of the prefix assumption; its G1 calls are cache hits on the full-budget pass.

Invariants: G1 must not change the answer (sets, status, reason — AC-G1-1). Trials to the final
verdict (B2) and artifact honesty violations are counted and reported, not assumed. A variant whose
API came back `unavailable` fails the run loudly (exit 2); there is never a silent G0 fallback.

The harmless probe cases (split "probe") are diagnosed like run_eval.py and reported separately; they
are not in the effectiveness tables because a passing run has nothing to order.

Writes pipeline_g1.json and pipeline_g1.md (the markdown is also printed). Card text is never written
out; the artifact keeps per-node card hashes/chars, P(restore) scores per pass, token counts and
truncation flags. `canonical()` strips only wall clock and latencies, so a re-run from the API cache
must reproduce the committed artifact byte for byte (--check).
"""

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "harness"), str(HERE.parent / "tests"), str(HERE.parent / "src")]

import run_eval  # noqa: E402  (supplies _lab and answer; its own committed run is untouched)
import score as stats  # noqa: E402  (eval/score.py: the exact test machinery; `score` below is sherlock's scorer)
from sherlock_harness.catalog import HARMLESS, SEED, TEAMS, Case, build_cases  # noqa: E402

from sherlock import __version__, envfile, g1_api  # noqa: E402
from sherlock.checks import Checks  # noqa: E402
from sherlock.diagnose import diagnose  # noqa: E402
from sherlock.evaluation import artifact_violations, from_artifact  # noqa: E402
from sherlock.evaluation import score as case_score  # noqa: E402
from sherlock.g1 import CARD_VARIANTS  # noqa: E402
from sherlock.g3 import Client  # noqa: E402
from sherlock.search import Budget  # noqa: E402

VARIANTS = ("off", "small", "big")
TIGHT = 10          # pre-registered tight budget (metrics spec §3 B4); the full budget stays run_eval's Budget()
B2_COUNTED_NOT_ASSUMED = True   # trials to the final verdict may legitimately differ across orders; counted


# --- one diagnosis ------------------------------------------------------------------------------------------

def _t_i(art, gold_sets):
    """B1: the first trial whose restored set is a member of the gold collection (None when none is)."""
    return min((t["n"] for t in art.get("trials", []) if frozenset(t["restored"]) in gold_sets), default=None)


def _run_diagnose(client, tid, checks, cassette, good_tid, team, budget, g1_cfg):
    started = time.monotonic()
    art = diagnose(client, tid, None, checks, cassette, budget, good_runs=[good_tid], node_map=team.node_map,
                   g1=g1_cfg)
    return art, round(time.monotonic() - started, 3)


def _pass_row(art, gold, gold_sets, wall):
    pred = from_artifact(art)
    sc = case_score(gold, pred)
    return {"t_i": _t_i(art, gold_sets), "trials_used": (art.get("budget") or {}).get("trials_used"),
            "wall_s": wall, "outcome": sc["outcome"], "jaccard": sc["jaccard"], "reason": sc["reason"],
            "status": art["status"], "reason_code": art.get("reason_code"),
            "minimal_sets": art.get("minimal_sets", []), "unverified_sets": art.get("unverified_sets", []),
            "violations": artifact_violations(art)}


def _tight_row(art, gold_sets):
    return {"t_i": _t_i(art, gold_sets), "trials_used": (art.get("budget") or {}).get("trials_used"),
            "budget_exhausted": art.get("reason_code") == "budget_exhausted", "status": art["status"],
            "reason_code": art.get("reason_code")}


def _g1_record(art):
    """The compact §10 G1 record of one diagnose call: identity, scores, per-pass order, cost, truncation."""
    g1 = art.get("g1") or {}
    return {"status": g1.get("status"), "reason": g1.get("reason"), "model": g1.get("model"),
            "question_version": g1.get("question_version"), "endpoint": g1.get("endpoint"),
            "config_hash": g1.get("config_hash"), "cache": g1.get("cache"), "calls": g1.get("calls"),
            "cost": g1.get("cost"), "card_hashes": g1.get("card_hashes"), "card_chars": g1.get("card_chars"),
            "truncated_cards": g1.get("truncated_cards"), "ms": g1.get("ms"),
            "scores": [{"node": s["node"], "score": s["score"]} for s in g1.get("scores", [])],
            "order": ((g1.get("per_pass") or {}).get("orders") or [None])[0],
            "tau": (g1.get("per_pass") or {}).get("tau"),
            "per_node": {n: {k: rec[k] for k in ("scores", "tokens_in", "tokens_out", "truncated", "errors", "ms")}
                         for n, rec in (g1.get("per_node") or {}).items()}}


def _merge_g1(g1s, variant):
    """One compact G1 record per case/variant: pass-0 card identity, per-pass scores/orders, pooled totals."""
    if not g1s:
        return None
    out = dict(g1s[0])
    out["card_variant"] = variant
    out["per_pass_scores"] = [{s["node"]: s["score"] for s in g1["scores"]} for g1 in g1s]
    out["per_pass_orders"] = [g1["order"] for g1 in g1s]
    out["per_pass_status"] = [g1["status"] for g1 in g1s]
    out["per_pass_tau"] = [g1["tau"] for g1 in g1s]
    tokens_in = sum((g1.get("cost") or {}).get("tokens_in") or 0 for g1 in g1s)
    tokens_out = sum((g1.get("cost") or {}).get("tokens_out") or 0 for g1 in g1s)
    out["cost"] = {"tokens_in": tokens_in, "tokens_out": tokens_out, "usd": (g1s[0].get("cost") or {}).get("usd")}
    out["calls"] = {"ok": sum((g1.get("calls") or {}).get("ok") or 0 for g1 in g1s),
                    "failed": sum((g1.get("calls") or {}).get("failed") or 0 for g1 in g1s)}
    hits = [c.get("hits") for g1 in g1s for c in [g1.get("cache")] if isinstance(c, dict)]
    out["cache_hits_total"] = sum(hits)
    merged = {}
    for g1 in g1s:
        for n, rec in (g1.get("per_node") or {}).items():
            m = merged.setdefault(n, {k: [] for k in ("scores", "tokens_in", "tokens_out", "truncated", "errors", "ms")})
            for k in m:
                m[k] += rec[k]
    out["per_node"] = merged
    return out


def _case_invariants(off, variants):
    """AC-G1-1: G1 may reorder trials, never change the answer. B2 differences are counted, not assumed."""
    changed, b2 = [], []
    base = run_eval.answer(off)
    base_t2 = (off.get("budget") or {}).get("trials_used")
    for v in ("small", "big"):
        for i, p in enumerate(variants[v]["passes"]):
            got = run_eval.answer({"minimal_sets": p["minimal_sets"], "unverified_sets": p["unverified_sets"],
                                   "status": p["status"], "reason_code": p["reason_code"]})
            if got != base:
                changed.append(f"{v}:{i}")
            if B2_COUNTED_NOT_ASSUMED and p["trials_used"] != base_t2:
                b2.append(f"{v}:{i}")
    return {"answer_changed": changed, "b2_changed": b2}


def _case_rows(client, cases, good, failed, work, cfg, passes, tight):
    """All variants for the cases of one lab group. Returns (rows, probes)."""
    rows, probes = [], []
    for c in cases:
        team = TEAMS[c.team]
        checks = Checks(team.check, "final_output", work, work / "sherlock.yaml")   # exactly as run_eval._run_group
        if c.split == "probe":  # planted but harmless: the run passes, a diagnosis must say so
            cassette = work / ".sherlock" / "cassette.db"
            art, _ = _run_diagnose(client, failed[c.id], checks, cassette, good[c.team], team, Budget(), None)
            probes.append({"case": c.id, "team": c.team, "status": art["status"],
                           "reason_code": art.get("reason_code"),
                           "ok": art.get("reason_code") == "already_passes"})
            continue
        tid = failed[c.id]
        cassette = work / ".sherlock" / "cassette.db"
        gold_sets = {frozenset(s) for s in c.gold}
        off, off_wall = _run_diagnose(client, tid, checks, cassette, good[c.team], team, Budget(), None)
        off_tight, _ = _run_diagnose(client, tid, checks, cassette, good[c.team], team,
                                     Budget(max_trials=tight), None)
        candidates = (off.get("pruning") or {}).get("candidates", [])
        relevant = len(candidates) >= 2
        n_passes = passes if relevant else 1
        variants = {"off": {"passes": [_pass_row(off, c.gold, gold_sets, off_wall)],
                            "tight": _tight_row(off_tight, gold_sets)}}
        for v in ("small", "big"):
            g1_base = {**cfg, "backend": "api", "card_variant": v,
                       "cache_dir": str(Path(cfg["cache_dir"]) / v)}
            per_pass, g1s, tight_row = [], [], None
            for p in range(n_passes):
                g1_cfg = {**g1_base, "passes": 1, "pass_offset": p}
                art, wall = _run_diagnose(client, tid, checks, cassette, good[c.team], team, Budget(), g1_cfg)
                if p == 0:  # the tight-budget run shares the pass-0 API cache (same cards, same pass index)
                    t_art, _ = _run_diagnose(client, tid, checks, cassette, good[c.team], team,
                                             Budget(max_trials=tight), g1_cfg)
                    tight_row = _tight_row(t_art, gold_sets)
                per_pass.append(_pass_row(art, c.gold, gold_sets, wall))
                g1s.append(_g1_record(art))
            variants[v] = {"passes": per_pass, "g1": _merge_g1(g1s, v), "tight": tight_row}
        rows.append({"id": c.id, "team": c.team, "split": c.split, "tags": c.tags, "hard": c.hard,
                     "gold": c.gold, "size": max((len(s) for s in c.gold), default=0),
                     "expect_abstain": c.expect_abstain, "candidates": len(candidates),
                     "g1_relevant": relevant, "candidate_list": candidates,
                     "variants": variants, "invariants": _case_invariants(off, variants),
                     "off": {"violations": artifact_violations(off)}})
    return rows, probes


# --- pooled statistics --------------------------------------------------------------------------------------

def _pooled_t(row, variant):
    """The case's pooled t_i: the mean over the variant's passes (None when no pass fixed inside B)."""
    vals = [p["t_i"] for p in row["variants"][variant]["passes"] if p["t_i"] is not None]
    return round(statistics.fmean(vals), 3) if vals else None


def _censored_t(row, variant, tight):
    """Pooled t_i, right-censored at the tight budget (None = censored), for the pass@t curve and tests."""
    t = _pooled_t(row, variant)
    return t if t is not None and t <= tight else None


def _km_pass_at(ts, tight):
    """Kaplan–Meier pass@t for t = 1..tight with right-censoring at the tight budget.

    Same estimator as eval/score.py:pass_at but events accumulate at t with `<=` because the pooled
    t_i is a mean over passes and may be fractional."""
    n = len(ts)
    finite = [x for x in ts if x is not None]
    curve, surv, at_risk, prev = [], 1.0, n, 0
    for t in range(1, tight + 1):
        events = sum(1 for x in finite if prev < x <= t)   # pooled t_i is a mean: events use a window
        if events:
            surv *= 1 - events / at_risk
            at_risk -= events
        prev = t
        if t == tight:
            at_risk -= n - len(finite)                     # budget-exhausted cases are censored at B
        curve.append(round(1 - surv, 4))
    solved = finite
    median = None
    if n and len(solved) >= n / 2:
        reach = [t for t in range(1, tight + 1)
                 if sum(1 for x in solved if x <= t) >= 0.5 * n]
        median = reach[0] if reach else None
    return {"pass_at": curve, "median": median, "solved": len(solved), "n": n}


def _efficiency(rows, variant, tight):
    """B1–B4 on the G1-relevant subset: pooled t_i, pass@tight, exhaustion, wall clock."""
    subset = [r for r in rows if r["g1_relevant"]]
    ts = [_censored_t(r, variant, tight) for r in subset]
    finite = [t for t in ts if t is not None]
    pooled_all = [_pooled_t(r, variant) for r in subset]
    finite_all = [t for t in pooled_all if t is not None]
    walls = [p["wall_s"] for r in subset for p in r["variants"][variant]["passes"]]
    exh = sum(1 for t in ts if t is None)
    return {"n": len(subset),
            "median_t": round(statistics.median(finite), 3) if finite else None,
            "iqr_t": _iqr(finite), "mean_t": round(statistics.fmean(finite_all), 3) if finite_all else None,
            "t_ci95": stats.mean_ci(finite, statistics.median) if finite else None,
            "pass_at_tight": round(len(finite) / len(subset), 4) if subset else None,
            "exhausted": exh, "exhausted_ci95": stats.wilson(exh, len(subset)) if subset else None,
            "wall_median": round(statistics.median(walls), 3) if walls else None}


def _iqr(xs):
    if len(xs) < 2:
        return [None, None]
    q = statistics.quantiles(xs, n=4)
    return [round(q[0], 3), round(q[2], 3)]


def summarize(rows):
    out = {}
    for v in VARIANTS:
        cells = [p for r in rows for p in r["variants"][v]["passes"]]
        exact = sum(x["outcome"] == "exact" for x in cells)
        wrong = sum(x["outcome"] == "wrong" for x in cells)
        abst = [x for x in cells if x["outcome"] == "abstain"]
        reasons = {}
        for x in abst:
            reasons[x["reason"] or "none"] = reasons.get(x["reason"] or "none", 0) + 1
        jacs = [x["jaccard"] for x in cells if x["outcome"] == "wrong" and x["jaccard"] is not None]
        out[v] = {"case_passes": len(cells), "exact": exact, "wrong": wrong, "abstain": len(abst),
                  "abstain_reasons": reasons,
                  "em": round(exact / (len(cells) - len(abst)), 4) if len(cells) - len(abst) else None,
                  "mean_j_wrong": round(statistics.fmean(jacs), 4) if jacs else None}
    return out


def cost_summary(rows, cfg):
    """§4: calls, tokens, USD, truncation against card size, per variant."""
    out = {}
    for v in ("small", "big"):
        chars, truncated, statuses = [], 0, {}
        tokens_in = tokens_out = calls_ok = calls_failed = 0
        for r in rows:
            g1 = r["variants"][v]["g1"]
            if not g1:
                continue
            statuses[g1["status"]] = statuses.get(g1["status"], 0) + 1
            cut = set(g1.get("truncated_cards") or [])
            for n, size in (g1.get("card_chars") or {}).items():
                chars.append(size)
                truncated += n in cut
            tokens_in += (g1.get("cost") or {}).get("tokens_in") or 0
            tokens_out += (g1.get("cost") or {}).get("tokens_out") or 0
            calls_ok += (g1.get("calls") or {}).get("ok") or 0
            calls_failed += (g1.get("calls") or {}).get("failed") or 0
        usd = None
        if cfg.get("price_in") and cfg.get("price_out"):
            usd = round(tokens_in / 1e6 * float(cfg["price_in"]) + tokens_out / 1e6 * float(cfg["price_out"]), 4)
        out[v] = {"cards": len(chars),
                  "card_chars_mean": round(statistics.fmean(chars), 1) if chars else None,
                  "card_chars_max": max(chars) if chars else None, "builder_truncated": truncated,
                  "calls_ok": calls_ok, "calls_failed": calls_failed,
                  "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd,
                  "price_in": cfg.get("price_in"), "price_out": cfg.get("price_out"),
                  "price_source": cfg.get("price_source"), "statuses": statuses}
    return out


def truncation_by_card_size(rows):
    """§4's 'is context length the issue' table: builder-truncation and API-context truncation by size bucket."""
    out = {}
    for v in ("small", "big"):
        buckets = {}
        for r in rows:
            g1 = r["variants"][v]["g1"]
            if not g1:
                continue
            built = set(g1.get("truncated_cards") or [])
            api_cut = {n for n, rec in (g1.get("per_node") or {}).items() if any(rec["truncated"])}
            for n, size in (g1.get("card_chars") or {}).items():
                b = "<1200" if size < 1200 else ">=2400" if size >= 2400 else "1200-2399"
                agg = buckets.setdefault(b, [0, 0, 0])
                agg[0] += 1
                agg[1] += n in built
                agg[2] += n in api_cut
        out[v] = {b: {"cards": a[0], "builder_cut": a[1], "api_cut": a[2]} for b, a in sorted(buckets.items())}
    return out


def stability(rows):
    """§6.7: across-pass agreement of the produced order (mean pairwise Kendall tau), per variant."""
    out = {}
    for v in ("small", "big"):
        taus, cases_with = [], 0
        for r in rows:
            if not r["g1_relevant"]:
                continue
            orders = [o for o in (r["variants"][v]["g1"] or {}).get("per_pass_orders", []) if o]
            if len(orders) > 1:
                cases_with += 1
                taus += [g1_api._kendall_tau(orders[i], orders[j])
                         for i in range(len(orders)) for j in range(i + 1, len(orders))]
        out[v] = {"cases_with_passes": cases_with,
                  "mean_tau": round(statistics.fmean(taus), 4) if taus else None}
    return out


def _per_team(rows):
    out = {}
    for r in rows:
        if not r["g1_relevant"]:
            continue
        t = out.setdefault(r["team"], {"cases": 0})
        t["cases"] += 1
        for v in VARIANTS:
            vals = [_pooled_t(r, v)]
            t.setdefault(v, []).extend(x for x in vals if x is not None)
    for t in out.values():
        for v in VARIANTS:
            vals = t.get(v, [])
            t[v] = round(statistics.fmean(vals), 3) if vals else None
    return dict(sorted(out.items()))


def _tests(rows, tight):
    """Families (ii)/(iii), §6.2–§6.4: each variant vs no-G1 and pairwise variants on pooled t_i over the
    G1-relevant subset, exact Wilcoxon + HL shift CI + rank-biserial + MDE; family (iii) adds TOST δ = 0.25.
    Reuses eval/score.py's machinery; pairs with a censored member are excluded and counted."""
    subset = [r for r in rows if r["g1_relevant"]]
    series = {v: [_censored_t(r, v, tight) for r in subset] for v in VARIANTS}
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
        sr = stats.signed_rank(diffs)
        if sr is None:  # every paired difference is zero: no test to run
            row.update(statistic=f"all {len(diffs)} paired differences zero ({censored} censored)",
                       p_exact=1.0, p_holm=None,
                       effect="HL shift 0.0 (CI95 [0.0, 0.0]), rank-biserial 0.0", mde=None)
            if b != "off":
                row["tost"] = {"delta": stats.TOST_DELTA, "p_lower": 1.0, "p_upper": 1.0,
                               "equivalent": False, "note": "degenerate: no non-zero differences"}
            tests.append(row)
            continue
        p = stats.wilcoxon_p(sr)
        hl, hl_ci = stats.hodges_lehmann(sr)
        row.update(statistic=f"Wilcoxon W+ = {sr['w2'] / 2} over {len(diffs)} pairs ({censored} censored)",
                   p_exact=stats.rp(p), p_holm=None,
                   effect=f"HL shift {hl} (CI95 {hl_ci}), rank-biserial {stats.rank_biserial(sr)}",
                   mde=stats.mde_shift(diffs))
        if b != "off":  # §6.4 TOST at the pre-registered margin
            p_lo = stats.wilcoxon_p(stats.signed_rank([d + stats.TOST_DELTA for d in diffs]), "ge")
            p_hi = stats.wilcoxon_p(stats.signed_rank([d - stats.TOST_DELTA for d in diffs]), "le")
            row["tost"] = {"delta": stats.TOST_DELTA, "p_lower": stats.rnd(p_lo), "p_upper": stats.rnd(p_hi),
                           "equivalent": bool(p_lo < stats.ALPHA and p_hi < stats.ALPHA)}
        tests.append(row)
    for fam in ("(ii)", "(iii)"):
        grp = [r for r in tests if r["family"].startswith(fam)]
        for r, hp in zip(grp, stats.holm([t["p_exact"] for t in grp])):
            r["p_holm"] = hp
    return tests


def _invariant_summary(rows):
    changed = [f"{r['id']}:{x}" for r in rows for x in r["invariants"]["answer_changed"]]
    b2 = [f"{r['id']}:{x}" for r in rows for x in r["invariants"]["b2_changed"]]
    violations = [r["id"] for r in rows if r["off"]["violations"]
                  or any(p["violations"] for v in ("small", "big") for p in r["variants"][v]["passes"])]
    abstain_cases = [r for r in rows if r["expect_abstain"]]
    abstain_ok = sum(all(p["outcome"] == "abstain" for v in VARIANTS for p in r["variants"][v]["passes"])
                     for r in abstain_cases)
    unexpected = [r["id"] for r in rows if not r["expect_abstain"]
                  and any(p["outcome"] == "abstain" for v in VARIANTS for p in r["variants"][v]["passes"])]
    return {"answer_changed_total": len(changed), "answer_changed": changed,
            "b2_changed_total": len(b2), "b2_changed": b2,
            "violations_total": len(violations), "violations": violations,
            "case_passes_total": sum(len(r["variants"][v]["passes"]) for r in rows for v in ("small", "big")),
            "abstain_cases": len(abstain_cases), "abstain_ok": abstain_ok,
            "unexpected_abstains": unexpected}


def _expectations(res):
    """What must hold for the run to exit 0; every miss is listed, none is hidden."""
    bad = []
    inv = res["invariants"]
    if inv["answer_changed_total"]:
        bad.append(f"G1 changed the answer on: {inv['answer_changed'][:6]}")
    if inv["violations_total"]:
        bad.append(f"artifact honesty violations on: {inv['violations'][:6]}")
    if inv["abstain_ok"] != inv["abstain_cases"]:
        bad.append("an abstain-by-design case did not abstain in every variant")
    if inv["unexpected_abstains"]:
        bad.append(f"unexpected abstains: {inv['unexpected_abstains'][:6]}")
    for p in res["probes"]:
        if not p["ok"]:
            bad.append(f"probe {p['case']}: expected already_passes, got {p['status']} {p['reason_code']}")
    for v in ("small", "big"):
        if res["cost"][v]["calls_failed"]:
            bad.append(f"{v}: {res['cost'][v]['calls_failed']} failed G1 call(s)")
    if res["stability"]["small"]["mean_tau"] is None and res["stability"]["small"]["cases_with_passes"]:
        bad.append("no across-pass agreement recorded despite multi-pass cases")
    return bad


# --- artifact, markdown -------------------------------------------------------------------------------------

def _config_block(cfg):
    return {"provider": cfg["provider"], "model": cfg["model"], "endpoint": g1_api.endpoint_of(cfg),
            "location": cfg["location"], "temperature": cfg["temperature"],
            "max_output_tokens": cfg["max_output_tokens"], "thinking_budget": cfg["thinking_budget"],
            "max_input_tokens": cfg["max_input_tokens"], "concurrency": cfg["max_workers"],
            "config_hash": g1_api.config_hash(cfg), "price_in": cfg.get("price_in"),
            "price_out": cfg.get("price_out"), "price_source": cfg.get("price_source"),
            "client_version": __version__, "prompt_version": g1_api.PROMPT_VERSION}


def canonical(res):
    """The artifact minus the fields that legitimately differ run to run (wall clock, latencies, cache
    bookkeeping, the timestamp). Everything the tables are built from stays in; a re-run from the API
    cache must reproduce it byte for byte."""
    out = json.loads(json.dumps(res))

    def strip(v):
        if isinstance(v, dict):
            for k in ("wall_s", "elapsed_s", "ms", "ms_total", "created", "cache", "cache_hits_total"):
                v.pop(k, None)
            for c in v.values():
                strip(c)
        elif isinstance(v, list):
            for c in v:
                strip(c)

    strip(out)
    return out


def _fmt(v):
    if isinstance(v, list):
        return "–".join("-" if x is None else str(x) for x in v)
    return "-" if v is None else str(v)


def report(res):
    def table(head, body):
        lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        lines += ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in body]
        return "\n".join(lines)

    s, cost, eff = res["summary"], res["cost"], res["efficiency"]
    parts = [f"# 4-gate pipeline with an LLM-backed G1 (seed {res['seed']}, {res['passes']} passes, "
             f"tight B={res['tight_budget']})", "",
             f"Backend: {res['config']['provider']} / {res['config']['model']} ({res['config']['endpoint']}); "
             f"prompt version {res['config']['prompt_version']}; config hash {res['config']['config_hash']}.", "",
             "E1 = small cards (the laya card budget), E2 = big cards (8x budget, GOOD_IN/UPSTREAM/WRITES_ALL). "
             "Same system prompt, same call parameters; the card is the only manipulated variable. G1 only "
             "reorders trials (variant A): EM must not move.", "",
             "## Effectiveness (every case, every pass)", "",
             table(["variant", "case-passes", "exact", "wrong", "abstain", "EM (abstains excluded)",
                    "mean J (wrong)", "abstain reasons"],
                   [[v, s[v]["case_passes"], s[v]["exact"], s[v]["wrong"], s[v]["abstain"], s[v]["em"],
                     s[v]["mean_j_wrong"], s[v]["abstain_reasons"] or "-"] for v in VARIANTS]), "",
             "## Invariants", "",
             f"- answers changed vs no-G1: {res['invariants']['answer_changed_total']} case-passes "
             f"(of {res['invariants']['case_passes_total']})",
             f"- trials to final verdict (B2) changed: {res['invariants']['b2_changed_total']} "
             f"(counted, not assumed: reordering changes which supersets are pruned)",
             f"- artifact honesty violations: {res['invariants']['violations_total']}",
             f"- abstain-by-design cases abstaining in every variant: "
             f"{res['invariants']['abstain_ok']}/{res['invariants']['abstain_cases']}", "",
             "## Efficiency, G1-relevant subset (>= 2 candidates; t_i pooled over passes)", "",
             table(["variant", "cases", "median t_i", "IQR", "mean t_i", "pass@tight-B", "exhausted (tight)",
                    "wall s median"],
                   [[v, eff[v]["n"], eff[v]["median_t"], eff[v]["iqr_t"], eff[v]["mean_t"],
                     eff[v]["pass_at_tight"], eff[v]["exhausted"], eff[v]["wall_median"]] for v in VARIANTS]), "",
             "## Pass@t curves (pooled per-pass t_i, censored at the tight budget)", "",
             table(["variant"] + [f"t={t}" for t in range(1, res["tight_budget"] + 1)] + ["KM median"],
                   [[v, *res["pass_at"][v]["pass_at"], res["pass_at"][v]["median"]] for v in VARIANTS]), "",
             "## Cost (§4)", "",
             table(["variant", "cards", "mean chars", "max chars", "builder-cut", "calls ok", "calls failed",
                    "tokens in", "tokens out", "USD"],
                   [[v, cost[v]["cards"], cost[v]["card_chars_mean"], cost[v]["card_chars_max"],
                     cost[v]["builder_truncated"], cost[v]["calls_ok"], cost[v]["calls_failed"],
                     cost[v]["tokens_in"], cost[v]["tokens_out"], cost[v]["usd"]] for v in ("small", "big")]), "",
             "### Truncation by card size", "",
             table(["variant", "bucket", "cards", "builder-cut", "api-context-cut"],
                   [[v, b, a["cards"], a["builder_cut"], a["api_cut"]]
                    for v in ("small", "big") for b, a in res["truncation_by_card_size"][v].items()]), "",
             "## Stability (§6.7): across-pass agreement of the produced order", "",
             table(["variant", "cases with passes", "mean pairwise Kendall tau"],
                   [[v, res["stability"][v]["cases_with_passes"], res["stability"][v]["mean_tau"]]
                    for v in ("small", "big")]), "",
             "## Tests (§6.2–§6.4, pre-registered families only)", "",
             table(["family", "test", "statistic", "p (exact)", "p (Holm)", "effect", "MDE", "TOST"],
                   [[t["family"].split(")")[0] + ")", t["test"], t["statistic"], t["p_exact"], t["p_holm"],
                     t["effect"], t["mde"], t.get("tost", {}).get("equivalent")
                      if "tost" in t else "-"] for t in res["tests"]]), "",
             "## Per team (pooled t_i on the G1-relevant subset)", "",
             table(["team", "cases", "off", "small", "big"],
                   [[t, *[v2[k] for k in ("cases", "off", "small", "big")]] for t, v2 in res["per_team"].items()]),
             "", "## Probes (planted-harmless runs: the diagnosis must say already_passes)", "",
             table(["case", "status", "reason", "ok"],
                   [[p["case"], p["status"], p["reason_code"], p["ok"]] for p in res["probes"]]), "",
             "## Cases", "",
             table(["case", "team", "tags", "G1-relevant", "off t_i", "small t_i", "big t_i",
                    "off outcome", "small outcome", "big outcome"],
                   [[r["id"], r["team"], ",".join(r["tags"]) or "-", r["g1_relevant"],
                     r["variants"]["off"]["passes"][0]["t_i"], _pooled_t(r, "small"), _pooled_t(r, "big"),
                     r["variants"]["off"]["passes"][0]["outcome"],
                     r["variants"]["small"]["passes"][0]["outcome"], r["variants"]["big"]["passes"][0]["outcome"]]
                    for r in res["cases"]]), "",
             "Card text is never written to the artifact; scores are P(restore) per card per pass.",
             "Generated by eval/pipeline_g1.py; do not edit."]
    return "\n\n".join(parts) + "\n"


# --- driver -------------------------------------------------------------------------------------------------

def _alone(c):
    """A case needs its own lab when two restore-trials could ask for a never-recorded request (run_eval's rule)."""
    team = TEAMS[c.team]
    return team.llm and len({team.faults[f].node for f in c.faults} & team.request_nodes) >= 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write pipeline_g1.json and pipeline_g1.md here")
    ap.add_argument("--check", type=Path, help="re-run from the cache and compare with this artifact")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--passes", type=int, help="G1 passes on the G1-relevant subset (default SHERLOCK_G1_PASSES)")
    ap.add_argument("--tight", type=int, default=TIGHT)
    ap.add_argument("--only", help="comma-separated teams (a quick partial run; never use with --check)")
    args = ap.parse_args()
    if args.check and args.only:
        print("pipeline_g1: --only and --check do not mix", file=sys.stderr)
        return 2
    envfile.load()
    try:
        cfg = g1_api.env_config({"cache_dir": str(HERE / ".g1" / "api_cache")})
    except g1_api.ConfigError as exc:
        print(f"pipeline_g1: {exc}", file=sys.stderr)
        return 2
    passes = args.passes or cfg["passes"]
    cases = build_cases(args.seed)
    probe_cases = [Case(t, f, "probe") for t, f in HARMLESS]
    if args.only:
        want = set(args.only.split(","))
        cases = [c for c in cases if c.team in want]
        probe_cases = [c for c in probe_cases if c.team in want]
    everything = cases + probe_cases
    groups = [[c for c in everything if not _alone(c)]] + [[c] for c in everything if _alone(c)]
    all_rows, probes = [], []
    for group in groups:
        work = Path(tempfile.mkdtemp(prefix="sherlock-pipeline-"))
        try:
            server, good, failed, _cassette = run_eval._lab(work, group)
            client = Client(server.url)
            rows, group_probes = _case_rows(client, group, good, failed, work, cfg, passes, args.tight)
            all_rows += rows
            probes += group_probes
        finally:
            try:
                server.stop()
            except Exception:  # noqa: BLE001 - the lab is gone either way
                pass
            import shutil
            shutil.rmtree(work, ignore_errors=True)
    down = [(r["id"], v) for r in all_rows for v in ("small", "big")
            if (r["variants"][v]["g1"] or {}).get("status") == "unavailable"]
    if down:
        print(f"pipeline_g1: the G1 API was unavailable on {len(down)} case-variant(s), first: {down[0]} "
              f"({(all_rows[0]['variants'][down[0][1]]['g1'] or {}).get('reason')}) — stopping, never falling back",
              file=sys.stderr)
        return 2
    res = {"schema": 1, "seed": args.seed, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "passes": passes, "tight_budget": args.tight, "variants": list(VARIANTS),
           "card_variants": CARD_VARIANTS, "config": _config_block(cfg),
           "prompt": g1_api.SYSTEM, "prompt_version": g1_api.PROMPT_VERSION,
           "only": sorted(args.only.split(",")) if args.only else None,
           "probes": probes, "cases": all_rows,
           "summary": summarize(all_rows), "invariants": _invariant_summary(all_rows),
           "efficiency": {v: _efficiency(all_rows, v, args.tight) for v in VARIANTS},
           "pass_at": {v: _km_pass_at([_censored_t(r, v, args.tight) for r in all_rows if r["g1_relevant"]],
                                      args.tight) for v in VARIANTS},
           "cost": cost_summary(all_rows, cfg),
           "truncation_by_card_size": truncation_by_card_size(all_rows),
           "stability": stability(all_rows), "per_team": _per_team(all_rows),
           "tests": _tests(all_rows, args.tight)}
    res["failures"] = _expectations(res)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "pipeline_g1.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n",
                                                   encoding="utf-8", newline="\n")
        (args.out / "pipeline_g1.md").write_text(report(res), encoding="utf-8", newline="\n")
    if args.check:
        want = canonical(json.loads(Path(args.check).read_text(encoding="utf-8")))
        fresh = json.dumps(canonical(res), indent=2, sort_keys=True) + "\n"
        if json.dumps(want, indent=2, sort_keys=True) + "\n" != fresh:
            print("pipeline_g1: results differ from", args.check, "(not reproducible, or the code changed)",
                  file=sys.stderr)
            return 1
        print("pipeline_g1: results identical to", args.check)
    for f in res["failures"]:
        print(f"FAIL: {f}", file=sys.stderr)
    s = res["summary"]
    print(f"pipeline_g1: {len(all_rows)} cases, {len(probes)} probes; EM off={s['off']['em']} "
          f"small={s['small']['em']} big={s['big']['em']}; answer changes "
          f"{res['invariants']['answer_changed_total']}; {len(res['failures'])} expectation failure(s)")
    return 1 if res["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
