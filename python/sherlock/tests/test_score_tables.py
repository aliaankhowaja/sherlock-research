"""§12: a unit test re-derives the committed score tables from the committed artifacts.

`eval/score.py` computes every pre-registered statistic (metrics spec §2–§8) from the committed
artifacts; this test runs that computation and requires byte-equality with the committed
`docs/eval/score.json`. Everything is deterministic: one shared seed list (§6.7), exact DP null
distributions, and a fixed execution order, so the JSON must match exactly.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
DOCS = ROOT / "docs" / "eval"
ARTIFACTS = [DOCS / "results.json", DOCS / "g1" / "g1_results.json", DOCS / "g1_gen" / "g1_results.json",
             DOCS / "public_traces" / "public_g1.json"]
SCORE = DOCS / "score.json"

pytestmark = pytest.mark.skipif(not all(p.exists() for p in ARTIFACTS),
                                reason="committed evaluation artifacts not generated yet")

spec = importlib.util.spec_from_file_location("score", ROOT / "python" / "sherlock" / "eval" / "score.py")
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)


@pytest.fixture(scope="module")
def computed():
    return score.compute(DOCS)


def test_committed_score_tables_are_what_the_artifacts_produce(computed):
    committed = json.loads(SCORE.read_text(encoding="utf-8"))
    assert committed == computed, "score.json does not match a fresh re-derivation from the artifacts"


def test_the_headline_claims_hold(computed):
    t1 = computed["table1"]
    assert t1["sherlock"]["wrong"] == 0 and t1["sherlock"]["em"] == 1.0
    for base in ("last_node", "random_node", "g0_only", "paste_and_play", "g0_g2", "plain_retry",
                 "llm_guess_stub"):
        assert t1["sherlock"]["em"] > (t1[base]["em"] or 0.0), base
        assert t1["sherlock"]["abstain_rate_ci95"] is not None
    assert computed["invariants"]["abstain_invariant_violations"] == []
    for name in ("table2_planted", "table2_generated"):
        t2 = computed[name]
        assert set(t2["methods"]) == set(score.ORDERS)
        assert all(v["exhausted_ci95"] is not None for v in t2["methods"].values())
        for m, c in t2["pass_at_curves"].items():
            assert len(c["pass_at"]) == t2["tight_budget"] and 0.0 <= c["pass_at"][-1] <= 1.0, m
    tests = computed["table3_tests"]
    for row in tests:
        assert row["p_holm"] is not None or row["p_exact"] == 1.0, row["test"]
        if "tost" in row:
            assert row["tost"]["delta"] == score.TOST_DELTA
    t5 = computed["table5_public"]
    assert t5["rows"] == 4112
    for m in score.PUBLIC_ORDERS:
        for col in score.PUBLIC_COLS:
            mean, ci = t5["methods"][m]["means"][col], t5["methods"][m]["ci95"][col]
            assert ci[0] <= mean <= ci[1], (m, col)


def test_statistics_reproduce_closed_forms():
    # Wilson CI for 84/84 must include 1 and start below it
    lo, hi = score.wilson(84, 84)
    assert lo < 1.0 and hi == 1.0
    # exact McNemar with c = 0 is 2·P(X = 0) = 2^{1-d}
    p, d = score.mcnemar(78, 0)
    assert d == 78 and abs(p - 2 ** -77) < 1e-30
    # Holm: the smallest of three p-values gets ×3
    assert score.holm([0.01, 0.02, 0.04])[0] == 0.03
    # Wilcoxon on [1, 2, 3] differences: mid-ranks ×2 are {2, 4, 6}, all positive → W2 = 12,
    # exact two-sided p = 2·P(W ≥ max) = 2·(1/8) = 0.25
    sr = score.signed_rank([1, 2, 3])
    assert sr["w2"] == 12 and score.wilcoxon_p(sr) == 0.25
    # TOST margin plumbing shifts both sides
    shifted = score.signed_rank([d + score.TOST_DELTA for d in [1, 2, 3]])
    assert score.wilcoxon_p(shifted, "ge") == 0.125
