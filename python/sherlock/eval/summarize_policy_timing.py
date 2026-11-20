"""Validate the paired timing design and summarize at the question level."""
import csv
import sys
from collections import Counter, defaultdict
from statistics import mean


def summarize(rows):
    strata = defaultdict(set)
    times = defaultdict(dict)
    forks = Counter()
    transports = set()
    for row in rows:
        case, faults, repeat = row["question"], row["faults"], int(row["repeat"])
        strata[row["source"], row["benchmark"]].add(case)
        transports.add(row["transport"])
        policy = row["policy"]
        key = (case, faults, repeat)
        assert policy in ("direct", "production") and policy not in times[key]
        assert int(row["elapsed_ns"]) > 0 and int(row["forks"]) > 0
        times[key][policy] = (int(row["position"]), int(row["elapsed_ns"]) / 1e9)
        forks[policy] += int(row["forks"])
    assert len(strata) == 6 and all(len(cases) == 2 for cases in strata.values())
    assert len(transports) == 1 and len(times) == 144
    per_question = defaultdict(list)
    decoy_differences = defaultdict(list)
    for (case, faults, repeat), pair in times.items():
        assert repeat in (0, 1) and len(pair) == 2
        production_position, production = pair["production"]
        direct_position, direct = pair["direct"]
        assert {production_position, direct_position} == {0, 1}
        assert times[case, faults, 1 - repeat]["production"][0] == direct_position
        per_question[case].append((production, direct))
        decoy_differences["bias.flag" in faults.split("+")].append(production - direct)
    assert len(per_question) == 12 and all(len(pairs) == 12 for pairs in per_question.values())
    questions = [(mean(p for p, d in pairs), mean(d for p, d in pairs)) for pairs in per_question.values()]
    differences = [p - d for p, d in questions]
    for decoy, paired in sorted(decoy_differences.items()):
        assert len(paired) == 72
        print(f"decoy={decoy}: mean paired difference {mean(paired):.4f} s/search")
    for i, policy in enumerate(("production", "direct")):
        print(f"{policy}: {forks[policy]} forks, mean {mean(q[i] for q in questions):.4f} s/search")
    print(f"production minus direct: mean {mean(differences):.4f} s/search, question range "
          f"[{min(differences):.4f}, {max(differences):.4f}], positive on "
          f"{sum(d > 0 for d in differences)}/{len(differences)}")


if __name__ == "__main__":
    with open(sys.argv[1], newline="") as stream:
        summarize(csv.DictReader(stream))
