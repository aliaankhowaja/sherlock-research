"""Zero-shot evaluation of the G1 node scorer.

    cd python/sherlock
    uv run python eval/g1_eval.py --out ../../docs/eval/g1                 # needs eval/.g1/cases.jsonl from run_eval.py
    uv run python eval/g1_eval.py --cases cases.jsonl --backend fake       # no network; fake scores for laya
    uv run python eval/g1_eval.py --stability                              # two extra uncached laya passes

Reads the cases that run_eval.py wrote, orders each case's candidates six ways (random, g0, rule, hint, laya,
laya_masked), and replays the search against a planted-set oracle to count trials to the first fix. Planted data
cannot show a gain when G0 or the rule order is already optimal: the gate reports that. `laya_alone`, `q2` and
`optimal` are analysis columns, not methods. Writes g1_results.json and g1_results.md (no probabilities, no card
text); the markdown is always printed.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "src")]

from sherlock.clues import Clue, order_candidates  # noqa: E402
from sherlock.g1 import QUESTION_VERSION, rank  # noqa: E402
from sherlock.g3 import Verdict  # noqa: E402
from sherlock.search import Budget, search  # noqa: E402

METHODS = ("random", "g0", "rule", "hint", "laya", "laya_masked")
ANALYSIS = ("laya_alone", "q2", "optimal")


class Oracle:
    """Monotone: a restored set passes iff it contains a planted set (as in tests/test_scale.py)."""

    def __init__(self, planted):
        self.planted = [frozenset(p) for p in planted]

    def __call__(self, restore):
        ok = any(p <= frozenset(restore) for p in self.planted)
        return Verdict("pass" if ok else "fail", "ok" if ok else "still wrong", restored=list(restore),
                       check={"pass": ok, "results": [{"score": 1.0 if ok else 0.0}]})


def search_fix(order, gold, budget):
    """(smallest trial n whose restored set is one of the minimal sets or None, reason_code, SearchResult).

    The result's `budget.trials_used` is B2, the trials-to-final-verdict count (metrics spec §3):
    the search decides every set the cutoff allows, so it terminates at its own pace regardless
    of the order — recording it lets the run assert the G1-does-not-change-B2 invariant."""
    res = search(order, Oracle(gold), 0.0, budget)
    found = {frozenset(s) for s in res.minimal_sets}
    fix = min((t["n"] for t in res.trials if frozenset(t["restored"]) in found), default=None)
    return fix, res.reason_code, res


def first_fix(order, gold, budget):
    """(smallest trial n whose restored set is one of the minimal sets or None, reason_code)."""
    fix, code, _res = search_fix(order, gold, budget)
    return fix, code


def metrics(order, gold):
    pos = [i + 1 for i, n in enumerate(order) if n in gold]
    dcg = sum(1 / math.log2(i + 2) for i, n in enumerate(order[:3]) if n in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 3)))
    return {"rank": pos[0] if pos else None, "rr": 1 / pos[0] if pos else 0.0,
            "recall3": len(gold & set(order[:3])) / len(gold), "ndcg3": dcg / idcg}


def rule_order(case):
    flagged = {n for n, (text, _) in case["cards"].items() if "output_same_as_good=no" in text}
    pos = {n: i for i, n in enumerate(case["on_path"])}
    return sorted(case["candidates"], key=lambda n: (n not in flagged, pos.get(n, len(pos))))


def shuffled_order(case, seed):
    """The `random` order for one seed: the shared `{seed}:{case id}` formula (metrics spec §6)."""
    shuffled = list(case["candidates"])
    random.Random(f"{seed}:{case['id']}").shuffle(shuffled)
    return shuffled


def orders(case, cfg, gold):
    cands, cost = case["candidates"], {}
    clues = [Clue("stand_in", n, "", w) for n, w in case["clue_score"].items() if w]
    out = {"random": shuffled_order(case, cfg["seed"]), "g0": cands, "rule": rule_order(case),
           "hint": order_candidates(cands, clues, case["hint"])}
    for name, cards in (("laya", case["cards"]), ("laya_masked", case["masked"])):
        g1 = rank(cfg["g1"], cands, lambda n, c=cards: tuple(c[n]))
        out[name] = order_candidates(cands, clues, [s["node"] for s in g1["scores"]])
        cost[name] = g1
        if name == "laya":
            scores = g1["scores"]
            out["laya_alone"] = [s["node"] for s in scores] if scores else cands
            ans = [s for s in scores if s.get("answers")]
            origin = lambda s: s["answers"]["fault_origin"]["originated_here"]  # noqa: E731
            out["q2"] = order_candidates(cands, clues, [s["node"] for s in sorted(ans, key=lambda s: (-origin(s), s["node"]))]) \
                if ans else out["g0"]
    out["optimal"] = sorted(cands, key=lambda n: n not in gold)
    return out, cost


def mean(xs):
    return round(statistics.mean(xs), 3) if xs else None


def evaluate(cases, cfg):
    rows, cost, passes, reasons = [], {m: {"calls": 0, "hits": 0, "ms": 0, "status": {}} for m in ("laya", "laya_masked")}, [], []
    for case in cases:
        gold = {n for s in case["gold"] for n in s}
        order, g1s = orders(case, cfg, gold)
        row = {"id": case["id"], "team": case["team"], "candidates": len(case["candidates"]), "methods": {}}
        for m, o in order.items():
            fix, code, res = search_fix(o, case["gold"], Budget(auto=True))
            _, tight = first_fix(o, case["gold"], Budget(max_trials=cfg["tight"]))
            row["methods"][m] = {"first_fix": fix, "first_gold_rank": metrics(o, gold)["rank"], "_m": metrics(o, gold),
                                 "final_trials": res.budget.get("trials_used"),
                                 "_exh": (code == "budget_exhausted", tight == "budget_exhausted")}
        for m, g1 in g1s.items():
            c = cost[m]
            cache = g1.get("cache")
            c["calls"] += cache["misses"] if isinstance(cache, dict) else 0
            c["hits"] += cache["hits"] if isinstance(cache, dict) else 0
            c["ms"] += g1["ms"]
            c["status"][g1["status"]] = c["status"].get(g1["status"], 0) + 1
            if g1["status"] == "unavailable":
                reasons.append(f"{case['id']} ({m}): {g1.get('reason') or 'unavailable'}")
            # per-case cost record (metrics spec §10): wall-clock in g1, truncation and card
            # pressure per node; card lengths stand in for tokens (chars / 3 is the CARD_CHARS rule)
            row.setdefault("cost", {})[m] = {"ms": g1["ms"], "cache": cache,
                                             "truncated_cards": g1["truncated_cards"],
                                             "card_chars": g1.get("card_chars", {})}
        if cfg["stability"] and len(case["candidates"]) > 1:
            runs = [[s["node"] for s in rank({**cfg["g1"], "cache_dir": None}, case["candidates"],
                                             lambda n: tuple(case["cards"][n]))["scores"]] for _ in range(2)]
            passes.append(runs[0] == runs[1] == [s["node"] for s in g1s["laya"]["scores"]])
        rows.append(row)
    return rows, cost, passes, reasons


def summarize(rows):
    out = {}
    for m in METHODS + ANALYSIS:
        ms = [r["methods"][m] for r in rows]
        fixes = [x["first_fix"] for x in ms if x["first_fix"] is not None]
        out[m] = {"cases": len(ms), "multi_candidate": sum(r["candidates"] > 1 for r in rows),
                  "mrr": mean([x["_m"]["rr"] for x in ms]), "recall3": mean([x["_m"]["recall3"] for x in ms]),
                  "ndcg3": mean([x["_m"]["ndcg3"] for x in ms]), "fix_mean": mean(fixes),
                  "fix_median": statistics.median(fixes) if fixes else None, "no_fix": len(ms) - len(fixes),
                  "exhausted_default": sum(x["_exh"][0] for x in ms), "exhausted_tight": sum(x["_exh"][1] for x in ms),
                  "final_mean": mean([x["final_trials"] for x in ms if x["final_trials"] is not None])}
    return out


def random_ref(cases, cfg, seeds):
    """§6/§9: the `random` baseline over a committed seed list (1..seeds), mean + percentile 95% CI.

    The headline `random` row stays paired (one shared seed); this reference exists so no table
    reads a one-seed random number as if it had no variance."""
    if seeds < 2:
        return None
    per_seed = []
    for seed in range(1, seeds + 1):
        cells = []
        for case in cases:
            gold = {n for s in case["gold"] for n in s}
            order = shuffled_order(case, seed)
            fix, _code = first_fix(order, case["gold"], Budget(auto=True))
            _, tight = first_fix(order, case["gold"], Budget(max_trials=cfg["tight"]))
            m = metrics(order, gold)
            cells.append({"fix_mean": fix, "no_fix": fix is None, "exhausted_tight": tight == "budget_exhausted",
                          "mrr": m["rr"], "recall3": m["recall3"], "ndcg3": m["ndcg3"]})
        per_seed.append({key: (statistics.mean([c[key] for c in cells if c[key] is not None])
                               if any(c[key] is not None for c in cells) and not isinstance(cells[0][key], bool)
                               else sum(bool(c[key]) for c in cells) / len(cells))
                         for key in ("fix_mean", "no_fix", "exhausted_tight", "mrr", "recall3", "ndcg3")})
    out = {"seeds": seeds, "metrics": {}}
    for key in ("fix_mean", "no_fix", "exhausted_tight", "mrr", "recall3", "ndcg3"):
        vals = sorted(p[key] for p in per_seed if p[key] is not None)
        if not vals:
            continue
        out["metrics"][key] = {"mean": round(statistics.mean(vals), 3),
                               "ci95": [round(vals[int(0.025 * len(vals))], 3),
                                        round(vals[min(len(vals) - 1, int(0.975 * len(vals)))], 3)]}
    return out


def canonical(res):
    """The artifact minus the fields that legitimately differ run to run: per-call wall ms, the
    cache hit/miss counters (a re-run is all hits) and the stability share. Everything a scoring
    script needs — first_fix, final_trials, truncated_cards, card_chars — stays in."""
    out = json.loads(json.dumps(res))
    out.pop("stability", None)

    def strip(cost, aggregate=False):
        if isinstance(cost, dict):
            for k in ("ms", "cache", "calls", "hits") if aggregate else ("ms", "cache"):
                cost.pop(k, None)

    for v in (out.get("cost") or {}).values():
        strip(v, aggregate=True)
    for row in out.get("cases", []):
        for c in (row.get("cost") or {}).values():
            strip(c)
    return out


def cost_analysis(cases):
    """§4, the 'is context length the issue' tables: truncation against card size and team size.

    card_chars is the character count of each node's card (2400 chars = the 800-token cut line)."""
    buckets = ("<1200", "1200-2399", ">=2400")

    def bucket(chars):
        return "<1200" if chars < 1200 else ">=2400" if chars >= 2400 else "1200-2399"

    by_card, by_team, sizes = {}, {}, {}
    for case in cases:
        for m, c in (case.get("cost") or {}).items():
            truncated = set(c.get("truncated_cards") or [])
            for n, chars in (c.get("card_chars") or {}).items():
                for key in ((m, bucket(chars)), (m, "all")):
                    by_card[key] = by_card.get(key, [0, 0])
                    by_card[key][0] += 1
                    by_card[key][1] += n in truncated
            teams = by_team.setdefault((m, case["candidates"]), [0, 0])
            teams[0] += 1
            teams[1] += bool(truncated)
            sizes.setdefault(m, []).extend((c.get("card_chars") or {}).values())
    def team_label(k):
        return "2" if k <= 2 else "3-5" if k <= 5 else ">=6"
    grouped = {}
    for (m, k), (n, t) in by_team.items():
        grouped.setdefault((m, team_label(k)), [0, 0])
        grouped[(m, team_label(k))][0] += n
        grouped[(m, team_label(k))][1] += t
    out = {"by_card_size": [[m, b, *by_card.get((m, b), [0, 0]),
                             round(by_card[(m, b)][1] / by_card[(m, b)][0], 3) if by_card.get((m, b)) else None]
                            for m in ("laya", "laya_masked") for b in buckets + ("all",)],
           "by_candidate_count": [[m, k, *v, round(v[1] / v[0], 3) if v[0] else None]
                                  for (m, k), v in sorted(grouped.items())],
           "card_chars_mean": {m: round(statistics.mean(v), 1) for m, v in sizes.items() if v},
           "card_chars_max": {m: max(v) for m, v in sizes.items() if v}}
    return out


def table(head, body):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join("-" if v is None else str(v) for v in r) + " |" for r in body])


def report(res):
    cols = ["cases", "multi_candidate", "mrr", "recall3", "ndcg3", "fix_mean", "fix_median", "no_fix",
            "exhausted_default", "exhausted_tight", "final_mean"]
    s, g = res["summary"], res["gate"]
    parts = [f"# G1 zero-shot evaluation ({res['backend']}, {res['question_version']})", "## Methods",
             table(["method"] + cols, [[m] + [s[m][c] for c in cols] for m in METHODS]),
             "## Analysis columns (not methods)", table(["column"] + cols, [[m] + [s[m][c] for c in cols] for m in ANALYSIS]),
             "## Per team (mean trials to first fix)", table(["team", "cases", "g0", "rule", "laya", "optimal"],
                                                               [[t, *v.values()] for t, v in res["per_team"].items()]),
             f"## Gate\nmin(g0, rule) matches optimal in {g['share']} of cases; gate_fires={g['gate_fires']} "
             "(true: planted data cannot show a gain)",
             "## Cost\n" + table(["method", "calls", "cache hits", "ms", "statuses"],
                                 [[m, c["calls"], c["hits"], c["ms"], c["status"]] for m, c in res["cost"].items()])]
    if res["random_ref"]:
        r = res["random_ref"]["metrics"]
        parts.append("## Random reference (100 seeds, mean + 95% CI)\n"
                     + table(["metric", "mean", "ci95"],
                             [[k, v["mean"], v["ci95"]] for k, v in r.items()]))
    if res.get("cost_analysis"):
        ca = res["cost_analysis"]
        parts.append("## Truncation by card size (2400 chars = the 800-token cut line)\n"
                     + table(["method", "card chars", "nodes", "truncated", "rate"], ca["by_card_size"]))
        parts.append("## Truncation by candidate-set size\n"
                     + table(["method", "candidates", "cases", "with a cut card", "rate"], ca["by_candidate_count"]))
    if res["stability"]:
        parts.append(f"## Stability\nlaya order identical in 3 passes: {res['stability']['share']} "
                     f"of {res['stability']['cases']} cases with 2+ candidates")
    return "\n\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", type=Path, default=HERE / ".g1" / "cases.jsonl")
    ap.add_argument("--out", type=Path, help="write g1_results.json and g1_results.md here")
    ap.add_argument("--backend", choices=("laya", "fake"), default="laya")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--stability", action="store_true", help="two extra uncached laya passes")
    ap.add_argument("--tight", type=int, default=10, help="the tight trial budget (spec: e.g. 10; 2 for the planted cases)")
    ap.add_argument("--random-seeds", type=int, default=100,
                    help="seeds for the random baseline reference (spec 6: >=100; 0 disables)")
    a = ap.parse_args()
    cases = [json.loads(line) for line in a.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [c for c in cases if c["status"] == "found"]
    cfg = {"seed": a.seed, "stability": a.stability, "tight": a.tight,
           "g1": {"backend": a.backend, "cache_dir": HERE / ".g1" / "cache"}}
    rows, cost, passes, reasons = evaluate(cases, cfg)
    down = sum(c["status"].get("unavailable", 0) for c in cost.values())
    if a.backend == "laya" and down:  # the laya rows would silently be the G0 order
        shown = "; ".join(reasons[:6]) or "no reason recorded"
        sys.exit(f"g1_eval: Laya was unavailable for {down} scoring pass(es): {shown}")
    fixes = {r["id"]: {m: x["first_fix"] for m, x in r["methods"].items()} for r in rows}
    inf = float("inf")
    near = [min(f["g0"] if f["g0"] is not None else inf, f["rule"] if f["rule"] is not None else inf)
            == (f["optimal"] if f["optimal"] is not None else inf) for f in fixes.values()]
    share = round(sum(near) / len(near), 3) if near else None
    teams = {}
    for r in rows:
        teams.setdefault(r["team"], []).append(r)
    per_team = {t: {"cases": len(rs), **{m: mean([r["methods"][m]["first_fix"] for r in rs
                                                  if r["methods"][m]["first_fix"] is not None])
                                         for m in ("g0", "rule", "laya", "optimal")}} for t, rs in sorted(teams.items())}
    res = {"backend": a.backend, "question_version": QUESTION_VERSION, "seed": a.seed, "tight_budget": a.tight,
           "summary": summarize(rows),
           "per_team": per_team, "gate": {"share": share, "gate_fires": share is not None and share >= 0.95},
           "cost": cost,
           "stability": {"cases": len(passes), "share": mean([float(p) for p in passes])} if passes else None,
           "random_ref": random_ref(cases, cfg, a.random_seeds),
           "cost_analysis": cost_analysis(rows)}
    for r in rows:
        for x in r["methods"].values():
            x.pop("_m"), x.pop("_exh")
    res["cases"] = rows
    md = report(res)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "g1_results.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                                               newline="\n")
        (a.out / "g1_results.md").write_text(md, encoding="utf-8", newline="\n")
    print(md, end="")


if __name__ == "__main__":
    main()
