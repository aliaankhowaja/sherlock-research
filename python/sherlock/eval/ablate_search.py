"""Paired search experiments. Pass a fresh output filename ending in .jsonl.gz."""
import gzip
import itertools
import json
import random
import sys
from pathlib import Path

from search_efficiency import ROOT, benchmark, Budget, Verdict
import sherlock.search as engine

ORIGINAL = engine.LOO_MIN


def minimal(passes):
    return sorted(m for m in passes if not any(k != m and k & m == k for k in passes))


def fresh(n, seed, shape):
    nodes = list(range(n))
    random.Random(seed).shuffle(nodes)
    a,b,c,d = nodes[:4]
    branches = {"singleton":[[a]], "pair":[[a,b]], "disjoint":[[a,b],[c,d]],
                "overlap":[[a,b],[b,c]], "antagonist":[[a]]}[shape]
    def execute(mask):
        # Each restored stage forwards its input. Broken stages discard it.
        for branch in branches:
            payload = "answer"
            for stage in branch:
                if not mask & (1 << stage):
                    payload = ""
            if payload and not (shape == "antagonist" and mask & (1 << b)):
                return payload
        return ""
    passing = {m for m in range(1 << n) if execute(m) == "answer"}
    assert minimal(passing) == sorted(sum(1 << i for i in branch) for branch in branches)
    return passing, 1 << a


def trajectory(order, method, cap, passes, missing):
    full = (1 << len(order)) - 1
    def verdict(m):
        return "abstain" if m == missing else "pass" if m in passes else "fail"
    if method in ("ascending","exhaustive"):
        trace, found = [], []
        for k in range(1,len(order)+1):
            for subset in itertools.combinations(order,k):
                m = sum(1 << i for i in subset)
                if method == "ascending" and any(s & m == s for s in found):
                    continue
                if len(trace) == cap:
                    return trace, minimal(found), False, method
                trace.append(m)
                if verdict(m) == "pass":
                    found.append(m)
        return trace, minimal(found), missing not in trace, method
    def oracle(nodes):
        return Verdict(verdict(sum(1 << int(i) for i in nodes)), "")
    engine.LOO_MIN = {"production":ORIGINAL,"enum":len(order),"dual":0}[method]
    try:
        r = engine.search(list(map(str, order)), oracle, 0, Budget(max_trials=cap,max_size=len(order)))
    finally:
        engine.LOO_MIN = ORIGINAL
    def mask(nodes):
        return sum(1 << int(i) for i in nodes)
    return ([mask(t["restored"]) for t in r.trials], sorted(map(mask,r.minimal_sets)),
            r.complete, r.screen["mode"])


def matrix(case, n, passes, gold, missing, archived):
    full = (1 << n)-1
    for perm in range(-1,10 if archived else 0):
        order = list(range(n))
        if perm >= 0:
            random.Random(perm).shuffle(order)
        for cap in (3,10,40,"full"):
            for method in ("production","enum","dual","ascending","exhaustive"):
                trace, sets, complete, mode = trajectory(order,method,full if cap=="full" else cap,passes,missing)
                known_fail = [0]+[m for m in trace if m not in passes and m!=missing]
                known_pass = [m for m in trace if m in passes and m!=missing]
                def certified(m):
                    return m in known_pass and all(any(sub & f == sub for f in known_fail)
                        for i in range(n) if m & (1<<i) for sub in [m ^ (1<<i)])
                # Exhaustive and ascending baselines explicitly withhold claims with unknown subsets.
                if method in ("ascending","exhaustive") and missing is not None:
                    sets = [m for m in sets if certified(m)]
                unsound = [m for m in sets if not certified(m)] if missing is not None else []
                ambiguous = False
                if complete and missing is not None:
                    ambiguous = any(not any(p&m==p for p in known_pass) and not any(f&m==m for f in known_fail)
                                    for m in range(full+1))
                first = None
                for g in gold:
                    if g not in known_pass:
                        continue
                    # First prefix establishing minimality from pass and failing supersets of each child.
                    times = [trace.index(g)+1]
                    for i in range(n):
                        if g & (1<<i):
                            child = g ^ (1<<i)
                            times.append(0 if not child else next((j for j,f in enumerate(trace,1)
                                if f not in passes and f!=missing and
                                (f==child if case.startswith("antagonist:") else f&child==child)),len(trace)+1))
                    t = max(times)
                    if t<=len(trace) and (first is None or t<first):
                        first=t
                yield dict(id=case,n=n,perm=perm,cap=cap,method=method,mode=mode,missing=missing,
                           gold=gold,trace=trace,sets=sets,complete=complete,first=first,
                           unsupported=unsound,false_complete=complete and (sets!=gold or ambiguous))


def rows():
    for line in (ROOT/"docs/eval/search_efficiency/cases.jsonl").read_text().splitlines():
        r=json.loads(line)
        assert benchmark(r["id"])==r, r["id"]
        yield from matrix(r["id"],len(r["candidates"]),set(r["passed_masks"]),r["minimal_masks"],None,True)
    for n,seed,shape in itertools.product((5,6,7,9),range(10),("singleton","pair","disjoint","overlap","antagonist")):
        passes,mask=fresh(n,seed,shape)
        for missing in ([None] if shape=="antagonist" else [None,mask]):
            yield from matrix(f"{shape}:{n}:{seed}",n,passes,minimal(passes),missing,False)


if __name__=="__main__":
    with gzip.open(Path(sys.argv[1]),"xt") as stream:
        for row in rows():
            stream.write(json.dumps(row,separators=(",",":"))+"\n")
