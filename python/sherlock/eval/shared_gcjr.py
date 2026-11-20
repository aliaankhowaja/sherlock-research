"""Matched deterministic message/configuration interventions for GCJR and Sherlock."""
import csv
from itertools import combinations
import sys

from evidence_search import direct_search
from sherlock.g3 import Verdict
from sherlock.search import Budget, search

AGENTS = ("a", "b", "c")
FULL = 7


def messages(ordered, config=0, replacements=0, clean=()):
    """Distinct agents emit to a common join; in the ordered graph b also reads a."""
    emitted = []
    for index in range(len(AGENTS)):
        bit = 1 << index
        if config & bit:
            value = 1
        elif ordered and index == 1:
            value = 2 * emitted[0]
        else:
            value = 0
        emitted.append(clean[index] if replacements & bit else value)
    return tuple(emitted)


def gcjr(oracle, pairs):
    """Li et al., Sec. II: test singles, then admissible pairs lacking a passing child."""
    singles = [1, 2, 4]
    found = [mask for mask in singles if oracle(mask)]
    tested = singles.copy()
    for pair in pairs:
        if any(mask & pair == mask for mask in found):
            continue
        tested.append(pair)
        if oracle(pair):
            found.append(pair)
    return found, tested


def rows():
    for ordered in (False, True):
        clean = messages(ordered, config=FULL)
        states = [messages(ordered, config=m) for m in range(8)]
        assert len(set(states)) == 8
        assert all(messages(ordered, replacements=m, clean=clean) == states[m] for m in range(8))
        # All three events lie in the output slice, have distinct agents, and share its join.
        # The only possible path between candidates is a -> b in the second graph.
        pairs = [a | b for a, b in combinations((1, 2, 4), 2) if not (ordered and (a, b) == (1, 2))]
        domain = {1, 2, 4, *pairs}
        for bits in range(64):
            # Fix failed and passing references. Enumerate outcomes on the six other inputs.
            allowed = {states[FULL]} | {states[m] for m in range(1, 7) if bits & (1 << (m - 1))}
            def config_pass(mask):
                return messages(ordered, config=mask) in allowed

            def message_pass(mask):
                return messages(ordered, replacements=mask, clean=clean) in allowed

            passes = [m for m in range(1, 8) if config_pass(m)]
            gold = {m for m in passes if all(s == m or s & m != s for s in passes)}
            reported, gcjr_trace = gcjr(message_pass, pairs)
            direct, complete, direct_trace = direct_search(3, lambda m: "pass" if config_pass(m) else "fail", 7)
            def mask(nodes):
                return sum(1 << AGENTS.index(n) for n in nodes)

            def fork(nodes):
                return Verdict("pass" if config_pass(mask(nodes)) else "fail", "")

            production = search(list(AGENTS), fork, None, Budget(max_trials=7))
            assert complete and set(direct) == gold
            assert set(reported) == gold.intersection(domain)
            results = [("gcjr_rule", reported, gcjr_trace),
                       ("production", list(map(mask, production.minimal_sets)),
                        [mask(t["restored"]) for t in production.trials]),
                       ("direct", direct, direct_trace)]
            for policy, found, trace in results:
                yield ["ordered_edge" if ordered else "parallel", bits, int(gold <= domain),
                       policy, " ".join(map(str, sorted(gold))), " ".join(map(str, sorted(found))),
                       int(set(found) == gold), len(trace), " ".join(map(str, trace))]


if __name__ == "__main__":
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["graph", "predicate", "in_gcjr_domain", "policy", "gold_masks",
                     "returned_masks", "full_family_exact", "queries", "query_masks"])
    writer.writerows(rows())
