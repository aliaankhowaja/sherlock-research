"""Emit the assignment-level results for the manuscript's post-hoc selector comparison."""
import csv
import sys
from itertools import product

from ablate_search import fresh, minimal, trajectory


def main():
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["candidates", "seed", "template", "budget", "policy",
                     "queries", "exact", "certified_exact"])
    templates = ("singleton", "pair", "disjoint", "overlap")
    for size, seed, template in product((4, 8), range(10, 20), templates):
        passing, _ = fresh(size, seed, template)
        gold = minimal(passing)
        for budget, policy in product(("full", 40), ("production", "dual")):
            cap = (1 << size) - 1 if budget == "full" else budget
            trace, repairs, complete, _ = trajectory(
                list(range(size)), policy, cap, passing, None
            )
            exact = repairs == gold
            writer.writerow([size, seed, template, budget, policy,
                             len(trace), int(exact), int(complete and exact)])


if __name__ == "__main__":
    main()
