"""Evaluate direct-evidence certificates on the paper's fixed eligible universes.

Run with the locked Sherlock interpreter and write the CSV on stdout. The empty
set is the observed failed run. Each oracle returns pass, fail, or abstain.
"""
import csv
import json
import sys
from itertools import combinations, product

from ablate_search import ROOT, fresh, minimal, trajectory


def direct_search(n, oracle, cap):
    """Query subsets in cardinality order. A known passing subset excludes minimality."""
    passing, unresolved, confirmed, trace = [], [], [], []
    for k in range(1, n + 1):
        for indices in combinations(range(n), k):
            mask = sum(1 << i for i in indices)
            if any(witness & mask == witness for witness in passing):
                continue
            if len(trace) == cap:
                return confirmed, False, trace
            verdict = oracle(mask)
            trace.append(mask)
            if verdict == "pass":
                passing.append(mask)
                if not any(child & mask == child for child in unresolved):
                    confirmed.append(mask)
            elif verdict == "abstain":
                unresolved.append(mask)
            elif verdict != "fail":
                raise ValueError(verdict)
    return confirmed, not unresolved, trace


def validate():
    # Independent specification: intersect the minimal families of all compatible
    # complete Boolean tables; certainty of the whole family means all agree.
    for pattern in product(("pass", "fail", "abstain"), repeat=7):
        table = dict(enumerate(pattern, start=1))
        unknown = [s for s, v in table.items() if v == "abstain"]
        passing = {s for s, v in table.items() if v == "pass"}
        families = []
        for bits in product((False, True), repeat=len(unknown)):
            extra = {s for s, b in zip(unknown, bits) if b}
            families.append(set(minimal(passing | extra)))
        found, complete, _ = direct_search(3, table.__getitem__, 7)
        assert set(found) == set.intersection(*families)
        assert complete == all(f == families[0] for f in families)


def records():
    def row(group, case, size, cap, policy, trace, found, complete, gold):
        exact = int(set(found) == set(gold)) if gold is not None else ""
        return group, case, size, cap, policy, len(trace), exact, int(complete), int(bool(exact and complete)) if gold is not None else ""

    for r in map(json.loads, (ROOT / "docs/eval/replay_corpus/final/langgraph/results.jsonl").read_text().splitlines()):
        for c in r["conditions"]:
            names = sorted({node for subset, _ in c["forks"] for node in subset})

            def mask(nodes):
                return sum(1 << names.index(node) for node in nodes)

            table = {mask(nodes): result[0] for nodes, result in c["forks"]}
            assert len(table) == 2 ** len(names) - 1
            control = r["id"] == "abstain"
            gold = None if control else [mask([f.split(".")[0] for f in c["faults"] if f != "bias.flag"])]
            group = "missing_request" if control else "runtime"
            case = r["id"] + "/" + ",".join(c["faults"])
            for cap in (3, 40):
                found, complete, trace = direct_search(len(names), table.__getitem__, cap)
                yield row(group, case, len(names), cap, "direct", trace, found, complete, gold)
                old = c["budgets"][str(cap)]
                yield row(group, case, len(names), cap, "production", old["trials"],
                          list(map(mask, old["sets"])), old["complete"], gold)

    circuits = [(r["id"], len(r["candidates"]), set(r["passed_masks"])) for r in
                map(json.loads, (ROOT / "docs/eval/search_efficiency/cases.jsonl").read_text().splitlines())]
    for n, seed in product((5, 6, 7, 9), range(10)):
        passes, _ = fresh(n, seed, "antagonist")
        circuits.append((f"antagonist:{n}:{seed}", n, passes))
    # Complete census of nonempty repair behaviors over three active nodes.
    # Four inert candidates exercise the deployed large-list search branch.
    for bits in range(1, 128):
        passes = {mask for mask in range(1, 128)
                  if mask & 7 and bits & (1 << ((mask & 7) - 1))}
        circuits.append((f"census:{bits}", 7, passes))
    for case, n, passes in circuits:
        group = "antagonist" if case.startswith("antagonist:") else "monotone"
        if case.startswith("census:"):
            group = "census"
        gold = minimal(passes)
        for cap_label in (40, "full"):
            cap = 2 ** n - 1 if cap_label == "full" else cap_label
            found, complete, trace = direct_search(n, lambda m: "pass" if m in passes else "fail", cap)
            yield row(group, case, n, cap_label, "direct", trace, found, complete, gold)
            for policy in ("production", "exhaustive", "dual"):
                trace, found, complete, _ = trajectory(list(range(n)), policy, cap, passes, None)
                yield row(group, case, n, cap_label, policy, trace, found, complete, gold)


def placement_sensitivity(writer):
    """Full-budget production census for every placement of the three active nodes."""
    writer.writerow(["active_positions", "predicates", "exact", "complete", "incorrect_complete"])
    for positions in combinations(range(7), 3):
        projections = [sum(((mask >> pos) & 1) << bit for bit, pos in enumerate(positions))
                       for mask in range(128)]
        exact = flags = incorrect = 0
        for bits in range(1, 128):
            passing = {m for m, active in enumerate(projections)
                       if active and bits & (1 << (active - 1))}
            _, found, complete, _ = trajectory(list(range(7)), "production", 127, passing, None)
            matches = found == minimal(passing)
            exact += matches
            flags += complete
            incorrect += complete and not matches
        writer.writerow([" ".join(map(str, positions)), 127, exact, flags, incorrect])


if __name__ == "__main__":
    validate()
    writer = csv.writer(sys.stdout, lineterminator="\n")
    if sys.argv[1:] == ["--placements"]:
        placement_sensitivity(writer)
        sys.exit(0)
    writer.writerow(["group", "case", "size", "cap", "policy", "queries", "exact", "complete", "certified_exact"])
    writer.writerows(records())
