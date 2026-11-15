"""G1 API scorer (g1_api.py, g1.rank backend `api`): a loopback stub only — no provider, no key, no network.

Covers the reply parser, the config validation, the card variants (small byte-identical to the golden
cards, big with GOOD_IN/UPSTREAM/WRITES_ALL), the truncation rule, the pass pooling and the Kendall
agreement, the cache, and the AC-G1-1 invariant through `diagnose`: an API-backed G1 may reorder
trials, never change the answer.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from api_stub import ChatStub
from test_diagnose_unit import KG, DiagServer
from test_g3_unit import CHECKS, HISTORY
from test_sources import good_history

from sherlock import envfile, g1_api
from sherlock.diagnose import diagnose
from sherlock.g1 import CARD_CHARS, CARD_VARIANTS, node_card, rank
from sherlock.search import Budget

NODES = ["router", "retriever", "extractor", "writer", "reviewer"]
CARD = lambda n: (n, False)  # noqa: E731


def api_cfg(stub_url, **kw):
    cfg = {"backend": "api", "provider": "openai_compat", "model": "stub", "base_url": stub_url, "api_key": "k-123",
           "temperature": 0.0, "max_output_tokens": 64, "thinking_budget": None, "timeout_s": 30.0,
           "max_input_tokens": None, "passes": 2, "max_workers": 4, "price_in": None, "price_out": None,
           "price_source": None, "cache_dir": None}
    return {**cfg, **kw}


# --- envfile -------------------------------------------------------------------------------------------------------

def test_envfile_parse_and_load(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('# comment\nexport A="1"\nB=2 # not a comment\n  C = spaced  \n', encoding="utf-8")
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    monkeypatch.setenv("C", "shell-wins")
    assert envfile.parse((tmp_path / ".env").read_text()) == {"A": "1", "B": "2", "C": "spaced"}
    envfile.load(tmp_path)
    import os
    assert os.environ["A"] == "1" and os.environ["B"] == "2" and os.environ["C"] == "shell-wins"


# --- the reply -----------------------------------------------------------------------------------------------------

def test_parse_reply_accepts_plain_fenced_and_prose_wrapped_json():
    assert g1_api.parse_reply('{"needs_restore": "yes", "confidence": 80}') == 0.8
    assert g1_api.parse_reply('```json\n{"needs_restore": "no", "confidence": 30}\n```') == 0.7
    assert g1_api.parse_reply('Sure: {"needs_restore": "yes", "confidence": 100}. Done') == 1.0
    assert g1_api.parse_reply('{"answer": "no", "confidence": 0}') == 1.0


def test_parse_reply_rejects_malformed_answers():
    for bad in ('{"needs_restore": "maybe", "confidence": 50}', '{"needs_restore": "yes"}',
                '{"needs_restore": "yes", "confidence": 180}', '{"needs_restore": "yes", "confidence": "high"}',
                "no idea", '{"other": 1}'):
        with pytest.raises(ValueError):
            g1_api.parse_reply(bad)


# --- config --------------------------------------------------------------------------------------------------------

def test_env_config_defaults_and_errors(monkeypatch):
    monkeypatch.delenv("SHERLOCK_G1_PROVIDER", raising=False)
    monkeypatch.delenv("SHERLOCK_G1_MODEL", raising=False)
    with pytest.raises(g1_api.ConfigError):
        g1_api.env_config()
    monkeypatch.setenv("SHERLOCK_G1_PROVIDER", "bogus")
    with pytest.raises(g1_api.ConfigError):
        g1_api.env_config()
    monkeypatch.setenv("SHERLOCK_G1_PROVIDER", "openai_compat")
    monkeypatch.setenv("SHERLOCK_G1_MODEL", "m")
    monkeypatch.delenv("SHERLOCK_G1_BASE_URL", raising=False)
    with pytest.raises(g1_api.ConfigError):
        g1_api.env_config()
    monkeypatch.setenv("SHERLOCK_G1_BASE_URL", "http://127.0.0.1:11434/v1")
    cfg = g1_api.env_config()
    assert cfg["provider"] == "openai_compat" and cfg["temperature"] == 0.0 and cfg["passes"] >= 1
    assert cfg["thinking_budget"] == 0  # the paper default: no thought tokens
    monkeypatch.setenv("SHERLOCK_G1_PROVIDER", "vertex")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(g1_api.ConfigError):
        g1_api.env_config()


def test_endpoint_records_scheme_and_host_only():
    cfg = {"provider": "openai_compat", "base_url": "http://127.0.0.1:9/v1/secret/path", "location": None}
    assert g1_api.endpoint_of(cfg) == "http://127.0.0.1:9"
    assert g1_api.endpoint_of({"provider": "vertex", "location": "us-central1"}) == \
        "https://us-central1-aiplatform.googleapis.com"
    assert g1_api.endpoint_of({"provider": "gemini_api"}) == "https://generativelanguage.googleapis.com"


# --- the card variants ---------------------------------------------------------------------------------------------

def test_small_card_is_the_golden_card_and_big_card_carries_the_extra_fields():
    small, cut = node_card("extractor", HISTORY, good_history(), CHECKS, **CARD_VARIANTS["small"])
    assert small == (Path(__file__).parent / "golden" / "g1_cards" / "extractor.txt").read_text(encoding="utf-8")
    assert not cut and len(small) <= CARD_CHARS
    big, _ = node_card("extractor", HISTORY, good_history(), CHECKS, **CARD_VARIANTS["big"])
    assert len(big) > len(small)
    assert "GOOD_IN: " in big and "UPSTREAM: router: " in big and "; retriever: " in big
    assert "WRITES_ALL" not in big  # the node ran once: WRITES_ALL would only repeat OUT_FAILED
    lines = [ln.split(":")[0] for ln in big.splitlines()]
    assert lines.index("FLAGS") < lines.index("CHECK") < lines.index("UPSTREAM") < lines.index("IN_FAILED")


def test_big_card_cuts_the_lowest_priority_fields_first():
    long_tail = "y" * 9000
    history = [dict(s, tasks=[dict(t, result={**(t.get("result") or {}), "note": long_tail})
                              for t in s.get("tasks") or []]) for s in HISTORY]
    big, truncated = node_card("extractor", history, good_history(), CHECKS, **CARD_VARIANTS["big"])
    assert truncated and len(big) <= CARD_VARIANTS["big"]["card_chars"]
    assert "WRITES_ALL" not in big  # the node ran once: nothing multi-run to add
    small, small_truncated = node_card("extractor", history, good_history(), CHECKS, **CARD_VARIANTS["small"])
    assert small_truncated and len(small) <= CARD_CHARS and "UPSTREAM" not in small and "WRITES_ALL" not in small
    assert small.splitlines()[1].startswith("FLAGS: ")  # P0 flags are never cut


def test_full_card_cuts_nothing():
    long_tail = "y" * 9000
    history = [dict(s, tasks=[dict(t, result={**(t.get("result") or {}), "note": long_tail})
                              for t in s.get("tasks") or []]) for s in HISTORY]
    full, truncated = node_card("extractor", history, good_history(), CHECKS, **CARD_VARIANTS["full"])
    big, big_truncated = node_card("extractor", history, good_history(), CHECKS, **CARD_VARIANTS["big"])
    assert big_truncated and not truncated  # the budget that cuts big does not exist for full
    assert len(full) > len(big)             # full carries what big had to cut
    assert "chars cut" not in full          # no snippet cap on the DIFF field either
    assert "WRITES_ALL" not in full  # still only for multi-run nodes (variant change, not schema change)
    for line in big.splitlines():  # full contains everything big shows, uncut
        assert line.split(":")[0] in {ln.split(":")[0] for ln in full.splitlines()}


# --- scoring through the stub ---------------------------------------------------------------------------------------

def test_rank_api_scores_orders_pools_and_agrees_over_passes():
    with ChatStub(['{"needs_restore": "yes", "confidence": 80}', '{"needs_restore": "yes", "confidence": 80}']) as stub:
        r = rank(api_cfg(stub.url, price_in="0.30", price_out="2.50"), list(reversed(NODES)), CARD)
    assert r["status"] == "ok" and r["backend"] == "api" and r["endpoint"].startswith("http://127.0.0.1")
    scores = [s["score"] for s in r["scores"]]
    assert scores == [0.8] * len(NODES) and scores == sorted(scores, reverse=True)
    assert [s["node"] for s in r["scores"]] == sorted(NODES)  # equal scores: name order (the recorded tie-break)
    assert r["per_pass"]["tau"] == 1.0 and len(r["per_pass"]["orders"]) == 2
    assert r["calls"] == {"ok": len(NODES) * 2, "failed": 0}
    assert r["cost"]["tokens_in"] == 10 * len(NODES) * 2 and r["cost"]["usd"] is not None
    assert r["ms"] >= 0 and r["question_version"] == g1_api.PROMPT_VERSION
    body = stub.hits[0]
    assert "tools" not in body and "functions" not in body
    assert body["_auth"] == "Bearer k-123" and body["temperature"] == 0
    assert body["messages"][0]["role"] == "system" and body["messages"][1]["role"] == "user"


def test_rank_api_is_cached_and_reports_hits(tmp_path):
    with ChatStub(usage=(111, 7)) as stub:
        first = rank(api_cfg(stub.url, cache_dir=tmp_path / "c"), NODES, CARD)
        assert first["cache"] == {"hits": 0, "misses": len(NODES) * 2}
        second = rank(api_cfg(stub.url, cache_dir=tmp_path / "c"), NODES, CARD)
        assert second["cache"] == {"hits": len(NODES) * 2, "misses": 0}
    assert [s["score"] for s in first["scores"]] == [s["score"] for s in second["scores"]]


def test_rank_api_flags_context_truncated_cards_and_gives_them_no_score():
    with ChatStub() as stub:
        r = rank(api_cfg(stub.url, max_input_tokens=5), NODES, CARD)  # every card over 5 tokens: cut
    assert r["status"] == "partial" and sorted(r["truncated_cards"]) == sorted(NODES)
    assert all(s["score"] is None for s in r["scores"])
    assert r["calls"] == {"ok": 0, "failed": 0}  # a truncated card is recorded as truncated, not failed


def test_rank_api_reports_a_dead_endpoint_as_unavailable_with_the_reason():
    with ChatStub(status=500) as stub:
        r = rank(api_cfg(stub.url), NODES, CARD)
    assert r["status"] == "unavailable" and "HTTP 500" in r["reason"]


def test_rank_api_partials_when_calls_fail_and_names_are_forgiven():
    # max_workers=1 makes arrival order deterministic (the stub hands out replies in arrival order,
    # so a concurrent run would be a thread-scheduling lottery). Three good replies: extractor scores
    # on both passes, retriever on one (pooled 0.5, not null), the rest fail every pass.
    replies = ['{"needs_restore": "yes", "confidence": 50}'] * 3 + ["not json at all"]
    with ChatStub(replies=replies) as stub:
        r = rank(api_cfg(stub.url, max_workers=1), NODES, CARD)
    assert r["status"] == "partial" and any(s["score"] is None for s in r["scores"])
    assert r["calls"]["failed"] == 7 and r["calls"]["ok"] == 3  # 3 good replies cover 3 of 10 calls
    assert [s["node"] for s in r["scores"] if s["score"] is None] == ["reviewer", "router", "writer"]  # nulls last, name order
    assert next(s["score"] for s in r["scores"] if s["node"] == "retriever") == 0.5  # one pass, pooled
    assert next(s["score"] for s in r["scores"] if s["node"] == "extractor") == 0.5  # both passes, pooled


def test_rank_api_skips_single_candidate_and_unbuildable_cards():
    assert rank(api_cfg("http://127.0.0.1:9/v1"), ["writer"], CARD)["status"] == "skipped"
    boom = lambda n: (_ for _ in ()).throw(RuntimeError("no card"))  # noqa: E731
    with ChatStub() as stub:
        r = rank(api_cfg(stub.url), NODES, boom)
    assert r["status"] == "partial" and all(s["score"] is None for s in r["scores"])


def test_kendall_tau_orders():
    assert g1_api._kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert g1_api._kendall_tau(["a", "b", "c"], ["c", "b", "a"]) == -1.0
    assert g1_api._kendall_tau(["a", "b", "c"], ["a", "c", "b"]) == pytest.approx(1 / 3, abs=1e-3)
    assert g1_api._kendall_tau(["a"], ["b"]) == 1.0


# --- through diagnose: G1 may reorder, never change the answer (AC-G1-1) --------------------------------------------

@pytest.fixture
def cassette(tmp_path):
    from sherlock.cassette import Cassette
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def run(cassette, g1_cfg=None, **kw):
    server = DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"])
    return diagnose(server, "T", KG, CHECKS, cassette, Budget(), g1=g1_cfg, **kw)


def test_api_g1_changes_order_never_the_answer(cassette):
    base = run(cassette)
    with ChatStub(['{"needs_restore": "yes", "confidence": 90}']) as stub:
        with_g1 = run(cassette, api_cfg(stub.url, passes=1))
    assert [sorted(x) for x in with_g1["minimal_sets"]] == [sorted(x) for x in base["minimal_sets"]]
    assert with_g1["status"] == base["status"] and with_g1["reason_code"] == base["reason_code"]
    g1 = with_g1["g1"]
    assert g1["backend"] == "api" and g1["status"] == "ok" and len(g1["scores"]) == g1["calls"]["ok"]
    assert sorted(with_g1["pruning"]["candidates"]) == sorted(base["pruning"]["candidates"])  # nothing excluded or added
    assert with_g1["pruning"]["candidates"][0] == g1["scores"][0]["node"]  # the G1 order is the search order
    assert [s["node"] for s in g1["scores"]] == [s["node"] for s in sorted(g1["scores"], key=lambda s: -s["score"])]
    assert with_g1["gate_summary"]["g1_nominated"] == len(g1["scores"])
    body = stub.hits[0]
    assert "UPSTREAM: " in body["messages"][1]["content"] or body["messages"][1]["content"].startswith("NODE: ")


def test_api_g1_dead_endpoint_cannot_change_the_answer(cassette):
    dead = run(cassette, api_cfg("http://127.0.0.1:9/v1"))
    assert [sorted(x) for x in dead["minimal_sets"]] == [["extractor", "retriever"]]
    assert dead["g1"]["status"] == "unavailable"  # the engine goes on (C8); the eval script stops loudly


def test_api_g1_big_cards_flow_through_diagnose(cassette):
    with ChatStub() as stub:
        r = run(cassette, api_cfg(stub.url, passes=1, card_variant="big"))
    assert r["g1"]["status"] == "ok"
    assert all(v <= CARD_VARIANTS["big"]["card_chars"] for v in r["g1"]["card_chars"].values())
    assert all(v >= 0 for v in r["g1"]["card_chars"].values())
