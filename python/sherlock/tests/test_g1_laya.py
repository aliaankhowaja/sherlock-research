"""G1 `laya` backend, local-only: ordering, cache, fail-safe and privacy.

No real inference: the `laya` package is faked in-process (`install_laya`); `sherlock-rec g1-check` is the live check.
"""

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_g1 import cassette, run  # noqa: F401 - `cassette` is a fixture

from sherlock import g1 as g1mod
from sherlock.g1 import DEFAULTS, QUESTIONS, LOCAL_TOTAL_TIMEOUT_MS


def answer(r):  # what G1 must never change; a set's members are listed in search order, so compare them as sets
    return [sorted(map(sorted, r[k])) for k in ("minimal_sets", "unverified_sets")] + [r["status"], r["reason_code"]]


def answers(body):
    """A well-formed System One reply: needs_restore is high for the extractor and low for every other node."""
    out = {}
    for qid, q in body["questions"].items():
        if q["type"] == "noul":
            out[qid] = {"type": "noul", "noul": (0.9 if "NODE: extractor" in body["state"] else 0.2)
                        if qid == "needs_restore" else 0.5}
        else:
            out[qid] = {"type": "choice", "probabilities": {o: 1 / len(q["criteria"]) for o in q["criteria"]}}
    return {"model": "stub-laya", "answers": out,
            "usage": {"input_tokens": 300, "state_tokens": 50, "state_tokens_dropped": 0, "truncated": False}}


def cfg(tmp_path, **kw):
    return {"backend": "laya", "cache_dir": tmp_path / "g1_cache", **kw}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("LAYA_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL", raising=False)
    g1mod._LOCAL_AGENTS.clear()
    yield
    g1mod._LOCAL_AGENTS.clear()


class FakeLocalAgent:
    """The small part of `laya.Agent` G1 uses: `system_one(state, questions) -> raw result`."""

    def __init__(self):
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        raw = answers({"state": state, "questions": questions})
        raw.pop("model", None)  # the local SDK need not name a checkpoint; G1 falls back to the requested model
        return raw


class FakeLaya:
    def __init__(self, agent):
        self.agent, self.loads = agent, []

    def load(self, model, **options):
        self.loads.append((model, options))
        return self.agent


def install_laya(monkeypatch, agent=None):
    agent = agent or FakeLocalAgent()
    module = FakeLaya(agent)
    monkeypatch.setitem(sys.modules, "laya", module)
    return agent, module


def test_laya_orders_by_needs_restore_caches_and_never_leaks(cassette, tmp_path, monkeypatch):  # noqa: F811
    base, events = run(cassette), []
    agent, _ = install_laya(monkeypatch)
    r = run(cassette, cfg(tmp_path), progress=events.append)
    calls = len(agent.calls)
    again = run(cassette, cfg(tmp_path))
    assert len(agent.calls) == calls  # the re-run is served from the cache, offline
    assert answer(r) == answer(base)
    g = r["g1"]
    assert g["status"] == "ok" and g["scores"][0]["node"] == "extractor" == r["pruning"]["candidates"][0]
    assert g["scores"][0]["answers"]["needs_restore"] == {"yes": 0.9, "no": 0.1} and g["model"] == "typed-decisions"
    assert g["mode"] == "local" and g["cache"] == {"hits": 0, "misses": calls}
    assert again["g1"]["cache"] == {"hits": calls, "misses": 0} and again["g1"]["scores"] == g["scores"]
    assert g["truncated_cards"] == [] and set(g["card_chars"]) == set(r["pruning"]["candidates"])
    assert all(0 < n <= g1mod.CARD_CHARS for n in g["card_chars"].values())
    written = json.dumps([r, again, events]) + "".join(f.read_text() for f in (tmp_path / "g1_cache").iterdir())
    assert "NODE: extractor" not in written  # the cache holds answers only, never the card text


class TruncatingAgent(FakeLocalAgent):
    """Reports model-side truncation: a card carrying the extractor line loses its questions."""

    def system_one(self, state, questions):
        raw = super().system_one(state, questions)
        if "NODE: extractor" in state:
            raw["usage"] = {**raw["usage"], "truncated": True, "state_tokens_dropped": 12}
        return raw


def test_a_truncated_card_gets_no_score(cassette, tmp_path, monkeypatch):  # noqa: F811
    install_laya(monkeypatch, TruncatingAgent())
    cards = {"extractor": ("NODE: extractor", False), "router": ("NODE: router", False)}
    g = g1mod.rank(cfg(tmp_path), ["router", "extractor"], lambda n: cards[n])
    assert g["status"] == "partial" and g["truncated_cards"] == ["extractor"]
    assert g["scores"][-1] == {"node": "extractor", "score": None, "answers": g["scores"][-1]["answers"]}
    assert g["scores"][0]["node"] == "router" and g["card_chars"] == {"extractor": 15, "router": 12}


def test_every_card_truncated_stays_partial_and_not_unavailable(cassette, tmp_path, monkeypatch):  # noqa: F811
    install_laya(monkeypatch, TruncatingAgent())
    cards = {"extractor": ("NODE: extractor", False), "router": ("NODE: extractor cut", False)}
    g = g1mod.rank(cfg(tmp_path), ["router", "extractor"], lambda n: cards[n])
    assert g["status"] == "partial" and "reason" not in g
    assert g["scores"] and all(s["score"] is None for s in g["scores"])
    assert set(g["truncated_cards"]) == {s["node"] for s in g["scores"]}


class BatchAgent(FakeLocalAgent):
    """Scores every uncached card in one predict_batch, which is what GPU batching wants."""

    def __init__(self):
        super().__init__()
        self.batches = []

    def predict_batch(self, states, questions):
        self.batches.append(list(states))
        out = []
        for state in states:
            raw = answers({"state": state, "questions": questions})
            raw.pop("model", None)
            out.append(raw)
        return out


def test_local_scoring_uses_one_batch_for_uncached_cards(cassette, tmp_path, monkeypatch):  # noqa: F811
    agent, module = install_laya(monkeypatch, BatchAgent())
    r = run(cassette, cfg(tmp_path))
    g = r["g1"]
    assert g["status"] == "ok" and g["scores"][0]["node"] == "extractor"
    assert agent.calls == [] and len(agent.batches) == 1 and len(agent.batches[0]) > 1
    assert module.loads == [("typed-decisions", {})]


def test_local_inference_needs_no_key_or_network(cassette, tmp_path, monkeypatch):  # noqa: F811
    base = run(cassette)
    agent, module = install_laya(monkeypatch)
    tried = []
    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", lambda self, addr: tried.append(addr) or real(self, addr))
    r = run(cassette, cfg(tmp_path))
    calls = len(agent.calls)
    again = run(cassette, cfg(tmp_path))
    assert answer(r) == answer(base)
    assert set(r["pruning"]["candidates"]) == set(base["pruning"]["candidates"])
    g = r["g1"]
    assert g["status"] == "ok" and g["mode"] == "local"
    assert g["scores"][0]["node"] == "extractor" == r["pruning"]["candidates"][0]
    assert g["model"] == "typed-decisions"  # the local result does not name one
    assert module.loads == [("typed-decisions", {})]  # one resident agent, not one per card
    assert g["cache"] == {"hits": 0, "misses": calls} and again["g1"]["cache"] == {"hits": calls, "misses": 0}
    assert len(agent.calls) == calls and again["g1"]["scores"] == g["scores"]  # re-run is offline from the cache
    assert tried == []  # in-process inference opens no connection


def test_a_missing_or_unloadable_local_model_leaves_the_result_as_if_g1_were_off(cassette, tmp_path, monkeypatch):  # noqa: F811
    base = run(cassette)
    monkeypatch.setitem(sys.modules, "laya", None)  # `import laya` fails
    missing = run(cassette, cfg(tmp_path))
    assert answer(missing) == answer(base) and missing["g1"]["status"] == "unavailable"
    assert "pip install laya" in missing["g1"]["reason"]

    class Broken:
        def load(self, model, **options):
            raise OSError("checkpoint missing")

    monkeypatch.setitem(sys.modules, "laya", Broken())
    broken = run(cassette, cfg(tmp_path))
    assert answer(broken) == answer(base) and broken["g1"]["status"] == "unavailable"
    assert "could not be loaded" in broken["g1"]["reason"] and "typed-decisions" in broken["g1"]["reason"]


def test_rank_echoes_the_applied_total_timeout(cassette, tmp_path, monkeypatch):  # noqa: F811
    install_laya(monkeypatch)
    cards = {"a": ("NODE: a", False), "b": ("NODE: b", False)}
    g = g1mod.rank(cfg(tmp_path), ["a", "b"], lambda n: cards[n])
    assert g["total_timeout_ms"] == LOCAL_TOTAL_TIMEOUT_MS == DEFAULTS["total_timeout_ms"]
    g = g1mod.rank({**cfg(tmp_path), "total_timeout_ms": 1234}, ["a", "b"], lambda n: cards[n])
    assert g["total_timeout_ms"] == 1234
