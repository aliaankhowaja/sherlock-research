"""Run from repo root: python3 python/sherlock/eval/search_efficiency.py"""
import csv
import itertools
import json
import random
import statistics
from pathlib import Path

import g1_gen as gen
from sherlock.checks import evaluate
from sherlock.g3 import Verdict
from sherlock.search import Budget, search

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/eval/search_efficiency"
METHODS = ("sherlock", "exhaustive", "ascending_pruned", "descending_pruned")


def benchmark(case_id):
    _, seed, index = case_id.split(":")
    case = gen.make_case(int(seed), int(index), "test")
    rng = random.Random(f"{int(seed)}:{int(index)}")
    team = gen.build_team(rng)
    changes, _, _ = gen.make_changes(team, rng)
    checks = [{"type": "contains", "value": f["value"]} for f in team["facts"]]
    checks.extend({"type": "not-contains", "value": team["facts"][c[1]]["wrong"]}
                  for c in changes.values() if c[0] == "corrupt")
    order = case["candidates"]
    n = len(order)
    full = (1 << n) - 1
    outcomes = {}
    minimal = []
    for k in range(n + 1):
        for indices in itertools.combinations(range(n), k):
            mask = sum(1 << i for i in indices)
            restored = {order[i] for i in indices}
            _, output = gen.run(team, {node:v for node,v in changes.items() if node not in restored})
            outcomes[mask] = evaluate(checks, output).passed
            has_passing_child = any(outcomes[mask ^ (1 << i)] for i in indices)
            assert not has_passing_child or outcomes[mask], (case_id, "nonmonotone", mask)
            if outcomes[mask] and not has_passing_child:
                minimal.append(mask)
    assert not outcomes[0] and outcomes[full]
    def mask_of(nodes):
        return sum(1 << order.index(node) for node in nodes)
    assert sorted(minimal) == sorted(map(mask_of,case["gold"]))
    def product(budget):
        def oracle(nodes):
            return Verdict("pass" if outcomes[mask_of(nodes)] else "fail", "")
        result = search(order,oracle,0,budget)
        trace = [mask_of(t["restored"]) for t in result.trials]
        return trace, result.complete and sorted(map(mask_of,result.minimal_sets))==sorted(minimal)
    sherlock, complete = product(Budget(max_trials=full,max_size=n))
    traces = {"sherlock":sherlock, "exhaustive":[m for m in outcomes if m]}
    ascending, found = [], []
    for m in traces["exhaustive"]:
        if any(s & m == s for s in found):
            continue
        ascending.append(m)
        if outcomes[m]:
            found.append(m)
    assert sorted(found)==sorted(minimal)
    traces["ascending_pruned"] = ascending
    descending, seen, found = [], {0}, []
    def visit(m):
        if m in seen:
            return
        seen.add(m)
        descending.append(m)
        if outcomes[m]:
            children = [m ^ (1 << i) for i in range(n) if m & (1 << i)]
            for child in children:
                visit(child)
            if all(not outcomes[c] for c in children):
                found.append(m)
    visit(full)
    assert sorted(found)==sorted(minimal)
    traces["descending_pruned"] = descending
    _, default_ok = product(Budget())
    return {"id":case_id,"candidates":order,"passed_masks":[m for m in outcomes if outcomes[m]],
            "minimal_masks":minimal,"queries":traces,"sherlock_complete_exact":complete,"default_complete_exact":default_ok}


def main():
    archived = json.loads((ROOT/"docs/eval/g1_gen/g1_results.json").read_text())["cases"]
    rows = [benchmark(c["id"]) for c in archived]
    assert len({r["id"] for r in rows})==100 and all(len(r["candidates"])==c["candidates"] for r,c in zip(rows,archived))
    (OUT/"cases.jsonl").write_text("".join(json.dumps(r,separators=(",",":"))+"\n" for r in rows))
    stats = []
    for label,group in [("all", rows),("1-6",[r for r in rows if len(r["candidates"])<=6]),
                        ("7+",[r for r in rows if len(r["candidates"])>6])]:
        for method in METHODS:
            counts = [len(r["queries"][method]) for r in group]
            saved = [c-len(r["queries"]["sherlock"]) for c,r in zip(counts,group)]
            rng = random.Random(185)
            means = sorted(statistics.fmean(rng.choices(saved,k=len(saved))) for _ in range(10000))
            exact = [r["sherlock_complete_exact"] if method=="sherlock" else True for r in group]
            stats.append(dict(group=label,method=method,n=len(group),mean=statistics.mean(counts),
                              complete_exact=sum(exact),within_40=sum(ok and c<=40 for c,ok in zip(counts,exact)),
                              mean_queries_saved_by_sherlock=statistics.mean(saved),ci_low=means[249],ci_high=means[9749],
                              wins=sum(d>0 for d in saved),ties=saved.count(0),losses=sum(d<0 for d in saved)))
    with (OUT/"summary.csv").open("w") as f:
        writer = csv.DictWriter(f,list(stats[0]))
        writer.writeheader()
        writer.writerows(stats)
    print("Default complete and exact:",sum(r["default_complete_exact"] for r in rows))
    for s in stats:
        print(s)

if __name__ == "__main__":
    main()
