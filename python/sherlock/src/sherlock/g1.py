"""G1 suspicion scorer: one score per surviving candidate, used only to order G3 trials.

The scores feed `order_candidates` as the tie-breaker inside equal G0 clue scores (ordering variant A), so a clue
always outranks a score. G1 never names a cause, never adds or removes a candidate, and never fails a diagnosis.
Backends: `laya` (the open-weight Laya checkpoint run in this process, zero-shot: the score is P(needs_restore =
yes)) and `fake` (a hash of the node name, no network, for tests). Today's hosted shortlist stays in gates.py.

Local Laya is the only inference: no endpoint, no key, and no card text leaves the machine (the checkpoint itself
may be downloaded once). It must run on the GPU box for speed, but a CPU run works and is only slower. Answers are
rounded to 4 decimals and cached on disk by card, so a re-run gives the same scores offline.

Each candidate is shown to the scorer as a node card: a short, redacted, deterministic text that puts the node's
failed behaviour next to its known-good behaviour. The recording does not say which node made a tool call, so
cards carry no tool fields; nothing in a run names a node's role, so there is no role field either.
"""

import difflib
import hashlib
import json
import re
import time
from pathlib import Path

from sherlock import __version__
from sherlock.redact import redact_body
from sherlock.sources import node_outputs

CARD_CHARS = 2400  # 800 tokens at a conservative 1 token per 3 characters (spec 5, rule 3)
SNIPPET = 200
# Card variants (metrics spec, experiments E1/E2; pre-registered before the runs):
# `small` is the card above, byte for byte the card the local laya checkpoint was shown (its context
# is 1,024 tokens). `big` gives a hosted model more context: an 8x character budget, 4x snippets and
# three extra fields — GOOD_IN (the passing run's input state to the node; only exists when a
# known-good run does, so public-trace rows never have it), UPSTREAM (what every earlier superstep's
# node wrote in the failed run and, when it exists, in the passing run) and WRITES_ALL (every recorded
# run of the node with its input and output; only added when the node ran more than once, so it never
# duplicates IN_FAILED/OUT_FAILED). The schema, field order and priorities are otherwise identical, so
# the only manipulated variables are the context budget and the three fields.
CARD_VARIANTS = {"small": {"card_chars": CARD_CHARS, "snippet": SNIPPET, "extra_fields": False},
                 "big": {"card_chars": 12000, "snippet": 800, "extra_fields": True}}
LOCAL_TOTAL_TIMEOUT_MS = 600000  # slow on CPU, fast on GPU; still bounded
_LOCAL_AGENTS: dict[str, object] = {}
DEFAULTS = {"model": "typed-decisions", "total_timeout_ms": LOCAL_TOTAL_TIMEOUT_MS}
# typed-decisions: English, 1,024-token context
QUESTION_VERSION = "g1_questions_v1"
QUESTIONS = {  # the wording is part of QUESTION_VERSION: any change needs a new version. No tool_relevance (see above)
    "output_effect": {"type": "choice", "instructions": "How does the failed output differ from the good output?",
                      "criteria": {"same": "identical in meaning and content",
                                   "cosmetic": "only wording, order or formatting differs",
                                   "meaningful": "facts, values or content differ"}},
    "fault_origin": {"type": "choice", "instructions": "Where did the difference start?",
                     "criteria": {"originated_here": "this node introduced the difference",
                                  "inherited": "the node's input already differed and the node behaved correctly on it",
                                  "none": "no difference"}},
    "dropped_input": {"type": "noul", "instructions": "Did the node omit information that was in its input?"},
    "invented_output": {"type": "noul", "instructions": "Does the output contain content its input does not support?"},
    "pass_through": {"type": "noul", "instructions": "Did the node only pass its input along unchanged?"},
    "needs_restore": {"type": "noul",
                      "instructions": "Must this node be restored to its good behaviour for the run to pass the check?"},
}
SAMPLE_CARD = """NODE: extractor
CHECK: contains "ISO 27001"; contains "Data region: EU"; not contains "SOC 2"
FLAGS: output_same_as_good=no input_same_as_good=no errored=no upstream_differs=[retriever]
DIFF: removed "ISO 27001" | added "SOC 2 (current)"
OUT_FAILED: {"certs": ["SOC 2"], "region": "EU"}
OUT_GOOD: {"certs": ["ISO 27001"], "region": "EU"}
IN_FAILED: docs=[doc1: "SOC 2 certificate ... expired in 2023", doc2: "All data stored in the EU"]"""


def _redacted(value):
    return json.loads(redact_body(json.dumps(value, default=str).encode()))


def _flat(value) -> str:
    return " ".join(json.dumps(_redacted(value), sort_keys=True, ensure_ascii=False).split())


def _words(value) -> list[str]:
    if isinstance(value, dict):
        return [w for k in sorted(value) for w in _words(value[k])]
    if isinstance(value, list):
        return [w for v in value for w in _words(v)]
    return str(value).split()


def _cut(text: str, keep: int) -> str:
    if len(text) <= keep:
        return text
    head = keep // 2
    return f"{text[:head]}[...{len(text) - keep} chars cut...]{text[len(text) - (keep - head):]}"


def _diff(failed, good) -> str:
    """Word-level over the values: what the good output has that the failed one lacks (removed), and the reverse."""
    a, b = _words(_redacted(good)), _words(_redacted(failed))
    removed, added = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            removed += [" ".join(a[i1:i2])] if i2 > i1 else []
            added += [" ".join(b[j1:j2])] if j2 > j1 else []
    if not removed + added:
        return "none"
    side = lambda parts: json.dumps(_cut(" ... ".join(parts), SNIPPET), ensure_ascii=False)  # noqa: E731
    return f"removed {side(removed)} | added {side(added)}"


def _first_runs(history: list[dict]) -> tuple[dict, dict, dict]:
    """node -> superstep of its first run, the state it started from, its first error. Oldest first."""
    step, before, error = {}, {}, {}
    for i, snap in enumerate(reversed(history)):
        for t in snap.get("tasks") or []:
            if not t["name"].startswith("__"):
                step.setdefault(t["name"], i)
                before.setdefault(t["name"], snap.get("values"))
                if t.get("error"):
                    error.setdefault(t["name"], str(t["error"]))
    return step, before, error


def node_card(node: str, history: list[dict], good_history: list[dict] | None, checks, mask: bool = False,
              card_chars: int = CARD_CHARS, snippet: int = SNIPPET, extra_fields: bool = False):
    """(card text, truncated). A pure function of its inputs: the same run gives the same card, byte for byte.
    `card_chars`/`snippet`/`extra_fields` are the card variant (CARD_VARIANTS); the defaults are the small
    card the laya checkpoint was scored on, so every committed artifact is unaffected."""
    step, before, error = _first_runs(history)
    out = node_outputs(history)
    good_out = node_outputs(good_history) if good_history else {}
    _good_step, good_before, _good_error = _first_runs(good_history) if good_history else ({}, {}, {})
    runs = [{"in": snap.get("values"), "out": t.get("result")} for snap in reversed(history)
            for t in snap.get("tasks") or [] if t["name"] == node]
    one = lambda writes: writes[0] if len(writes) == 1 else writes  # noqa: E731
    yn = lambda same: "unknown" if same is None else "yes" if same else "no"  # noqa: E731
    same_out = out.get(node) == good_out[node] if node in good_out else None
    same_in = before.get(node) == good_before[node] if node in good_before else None
    upstream = (f"[{', '.join(n for n in out if step[n] < step[node] and out[n] != good_out.get(n))}]"
                if good_history else "unknown")
    fields = [  # (priority, line): P0 is never cut, the highest number is cut first (spec 5)
        (0, f"NODE: {node}"),
        (0, f"FLAGS: output_same_as_good={yn(same_out)} input_same_as_good={yn(same_in)} "
            f"errored={yn(node in error)} upstream_differs={upstream}"),
        (1, "CHECK: " + "; ".join(f"{a.get('type')} {_flat(a.get('value'))}" for a in checks.assertions)),
        *([(1, "DIFF: " + _diff(one(out[node]), one(good_out[node])))] if node in good_out else []),
        *([(1, f"ERROR: {error[node]}")] if node in error else []),
        (2, f"OUT_FAILED: {_flat(one(out.get(node, [])))}"),
        *([(2, f"OUT_GOOD: {_flat(one(good_out[node]))}")] if node in good_out else []),
        *([(2, "UPSTREAM: " + "; ".join(
            f"{n}: {_flat(one(out[n]))}" + (f" | GOOD: {_flat(one(good_out[n]))}" if n in good_out else "")
            for n in sorted((n for n in out if step[n] < step.get(node, -1)), key=lambda n: (step[n], n))))]
          if extra_fields else []),
        (3, f"IN_FAILED: {_flat(before.get(node))}"),
        *([(3, f"GOOD_IN: {_flat(good_before.get(node))}")] if extra_fields and node in good_before else []),
        *([(4, "WRITES_ALL: " + " | ".join(f"#{k} IN={_flat(r['in'])} OUT={_flat(r['out'])}" for k, r in
                                           enumerate(runs)))] if extra_fields and len(runs) > 1 else []),
    ]
    fields = [(p, redact_body(line.encode()).decode()) for p, line in fields]
    if mask:  # shortcut control (spec 9): the same card with every node name replaced by a stable ID
        for n in sorted(out, key=len, reverse=True):
            alias = "node_" + hashlib.sha256(n.encode()).hexdigest()[:6]
            fields = [(p, re.sub(rf"(?<![\w-]){re.escape(n)}(?![\w-])", alias, line)) for p, line in fields]
    over = sum(len(line) + 1 for _, line in fields) - card_chars
    truncated = over > 0
    for prio in (4, 3, 2, 1):
        for i in reversed(range(len(fields))):
            p, line = fields[i]
            if over > 0 and p == prio and len(line) > 40:
                fields[i] = (p, _cut(line, max(40, len(line) - over - 30)))  # 30: room for the cut marker
                over -= len(line) - len(fields[i][1])
    return "\n".join(line for _, line in fields), truncated


class LocalUnavailable(RuntimeError):
    """Local Laya cannot run here (missing package or checkpoint); G1 falls back to the G0 order (C8)."""


def _local_agent(cfg: dict):
    """The resident `laya` agent for this checkpoint, loaded once and reused across cards."""
    model = cfg.get("model") or DEFAULTS["model"]
    if model in _LOCAL_AGENTS:
        return _LOCAL_AGENTS[model]
    try:
        import laya
    except Exception as exc:  # noqa: BLE001 - any import failure is a clear install hint
        raise LocalUnavailable(
            "local Laya needs the `laya` package: run `pip install laya` (or `uv pip install laya`)") from exc
    options = {"device": cfg["device"]} if cfg.get("device") else {}
    try:
        agent = laya.load(model, **options)
    except Exception as exc:  # noqa: BLE001 - weights missing, bad path, unsupported device
        raise LocalUnavailable(
            f"local Laya model {model!r} could not be loaded: {type(exc).__name__}: {exc}") from exc
    _LOCAL_AGENTS[model] = agent
    return agent


def _ask_local(cfg: dict, card: str) -> dict:
    try:
        raw = _local_agent(cfg).system_one(card, QUESTIONS)
    except LocalUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - one bad card is a null score, as with HTTP
        raise RuntimeError(f"local Laya inference failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("local Laya returned no result mapping")
    return raw


def ask(cfg: dict, card: str, timeout_s: float) -> dict:
    """Score one card with the local checkpoint; the raw response. `timeout_s` is unused today
    (the total budget bounds the whole pass), kept so callers stay stable for future backends."""
    return _ask_local(cfg, card)


def parse(raw: dict) -> tuple[dict, bool]:
    """(answers as option -> probability, rounded to 4 decimals; truncated). ValueError if anything is malformed."""
    answers = {}
    try:
        for qid, q in QUESTIONS.items():
            a = raw["answers"][qid]
            probs = ({"yes": a["noul"], "no": 1 - a["noul"]} if q["type"] == "noul"
                     else {o: a["probabilities"][o] for o in q["criteria"]})
            ok = all(isinstance(p, int | float) and 0 <= p <= 1 for p in probs.values())
            if not ok or abs(sum(probs.values()) - 1) > 0.02:
                raise ValueError(f"answer {qid} is not a probability distribution")
            answers[qid] = {o: round(p, 4) for o, p in probs.items()}
        usage = raw.get("usage") or {}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed response: missing {exc}") from exc
    # input_tokens counts the card once per question, so it says nothing about truncation; these fields do
    return answers, bool(usage.get("truncated") or usage.get("state_tokens_dropped") or usage.get("truncated_questions"))


def _cache_path(cfg: dict, card: str) -> Path | None:
    if not cfg.get("cache_dir"):
        return None
    key = json.dumps(["local", cfg.get("model"), QUESTION_VERSION, card])
    return Path(cfg["cache_dir"]) / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def _entry_from(cfg: dict, raw: dict) -> dict:
    answers, truncated = parse(raw)
    return {"answers": answers, "truncated": truncated, "model": raw.get("model") or cfg.get("model")}


def _write_entry(path: Path | None, entry: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")


def cached_answers(cfg: dict, card: str, timeout_s: float) -> tuple[dict, bool]:
    """({answers, truncated, model}, cache hit). The cache holds answers only: never the card, never the key."""
    path = _cache_path(cfg, card)
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), True
    entry = _entry_from(cfg, ask(cfg, card, timeout_s))
    _write_entry(path, entry)
    return entry, False


def fake_score(node: str) -> float:
    return round(int(hashlib.sha256(node.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF, 4)


def _rank_api(cfg: dict, candidates: list[str], card_of) -> dict:
    """The `api` backend: one hosted-LLM call per card per pass (g1_api). Same contract as the laya path:
    never raises, scores may be null, a null-scoring shortlist is `partial` or `unavailable` (C8) — and the
    eval scripts stop the run on `unavailable`, so a dead endpoint is never a silent G0 fallback."""
    from sherlock import g1_api  # imported here: the module is only needed when the backend is used

    start = time.monotonic()
    out = {"backend": "api", "provider": cfg.get("provider"), "model": cfg.get("model"), "status": "skipped",
           "order_variant": "A", "scores": [], "truncated_cards": [], "card_hashes": {}, "card_chars": {},
           "question_version": g1_api.PROMPT_VERSION, "mode": "api", "endpoint": None,
           "temperature": cfg.get("temperature"), "passes": cfg.get("passes") or 1,
           "client_version": __version__, "config_hash": None,
           "cache": {"hits": 0, "misses": 0} if cfg.get("cache_dir") else "disabled"}
    try:
        out["endpoint"] = g1_api.endpoint_of(cfg)
        out["config_hash"] = g1_api.config_hash(cfg)
    except Exception as exc:  # noqa: BLE001 - a malformed config is reported, not raised (C8)
        return {**out, "status": "unavailable", "reason": f"bad G1 API config: {type(exc).__name__}: {exc}",
                "ms": 0}
    if len(candidates) < 2:
        return {**out, "ms": 0}
    cards, built = {}, []
    for n in candidates:
        try:
            card, truncated = card_of(n)
        except Exception:  # noqa: BLE001 - C8: a card that cannot be built gets no score, the pass continues
            built.append(n)
            continue
        cards[n] = card
        out["card_hashes"][n] = hashlib.sha256(card.encode()).hexdigest()[:16]
        out["card_chars"][n] = len(card)
        if truncated:
            out["truncated_cards"] += [n]
    if not cards:
        return {**out, "status": "partial",
                "scores": [{"node": n, "score": None} for n in sorted(built)],
                "reason": "no candidate card could be built", "ms": round(1000 * (time.monotonic() - start))}
    scored = g1_api.score_cards(cfg, cards, cfg.get("passes") or 1)
    per_node = scored["per_node"]
    if isinstance(out["cache"], dict):
        for rec in per_node.values():
            out["cache"]["hits"] += rec["cached"]
            out["cache"]["misses"] += rec["calls"] - rec["cached"]
    scores = dict(scored["scores"])
    for n in built:
        scores[n] = None
    api_cut = sorted(n for n, rec in per_node.items() if any(rec["truncated"]))
    for n in api_cut:
        if n not in out["truncated_cards"]:
            out["truncated_cards"] += [n]
    order = sorted(candidates, key=lambda n: (scores[n] is None, -(scores[n] or 0.0), n))
    errors = [e for rec in per_node.values() for e in rec["errors"]]
    partial = any(scores[n] is None for n in candidates)
    if scored["calls_ok"] == 0 and errors:
        out.update(status="unavailable", reason=errors[0])
    else:
        out.update(status="partial" if partial else "ok")
    out.update(scores=[{"node": n, "score": scores[n]} for n in order],
               per_pass={"orders": scored["orders"], "tau": scored["tau"]},
               per_node=per_node,
               cost={"tokens_in": scored["tokens_in"], "tokens_out": scored["tokens_out"], "usd": scored["usd"]},
               calls={"ok": scored["calls_ok"], "failed": scored["calls_failed"]},
               ms=round(1000 * (time.monotonic() - start)))
    return out


def rank(cfg: dict, candidates: list[str], card_of) -> dict:
    """The artifact's `g1` object. `scores` is in rank order: score high to low, then name; null scores last.
    `card_of(node)` gives (card, truncated); a card that cannot be built gives a null score (C8), never an error."""
    start = time.monotonic()
    cfg = {**DEFAULTS, **cfg}
    if cfg["backend"] == "api":
        return _rank_api(cfg, candidates, card_of)
    laya = cfg["backend"] == "laya"
    out = {"backend": cfg["backend"], "status": "skipped", "order_variant": "A", "scores": [], "truncated_cards": [],
           "card_hashes": {}, "card_chars": {}}
    if laya:
        out.update(question_version=QUESTION_VERSION, mode="local", model=cfg.get("model"),
                   client_version=__version__, total_timeout_ms=cfg["total_timeout_ms"],
                   cache={"hits": 0, "misses": 0} if cfg.get("cache_dir") else "disabled")
    if len(candidates) < 2:
        return {**out, "ms": 0}
    problem = None
    scores, answers, called = {}, {}, False
    misses: list[tuple[str, str]] = []

    def _accept(n: str, entry: dict, hit: bool) -> None:
        nonlocal called
        called = True
        if out["cache"] != "disabled":
            out["cache"]["hits" if hit else "misses"] += 1
        out["model"] = entry["model"]
        answers[n] = entry["answers"]
        if entry["truncated"] and n not in out["truncated_cards"]:
            out["truncated_cards"].append(n)
        # a card the model cut may have lost its end or the questions, so it gets no score
        scores[n] = None if entry["truncated"] else entry["answers"]["needs_restore"]["yes"]

    def _score_one(n: str, card: str) -> bool:
        """Score one card. False means stop: time ran out or the checkpoint could not be loaded."""
        nonlocal problem
        left = cfg["total_timeout_ms"] / 1000 - (time.monotonic() - start)
        if left <= 0:
            problem = f"the G1 time limit of {cfg['total_timeout_ms']} ms was reached"
            return False
        try:
            entry, hit = cached_answers(cfg, card, left)
        except LocalUnavailable as exc:  # C8: no local package or checkpoint means G1 is off, not a failed run
            problem = str(exc)
            return False
        except Exception:  # noqa: BLE001 - C8: one bad card is a null score and the pass continues
            scores[n] = None
            return True
        _accept(n, entry, hit)
        return True

    for n in candidates if not problem else ():
        try:
            card, truncated = card_of(n)
        except Exception:  # noqa: BLE001 - C8: G1 must never fail the diagnosis
            scores[n] = None
            continue
        out["card_hashes"][n] = hashlib.sha256(card.encode()).hexdigest()[:16]
        out["card_chars"][n] = len(card)
        out["truncated_cards"] += [n] if truncated else []
        if not laya:
            scores[n] = fake_score(n)
            continue
        path = _cache_path(cfg, card)
        if path and path.is_file():
            _accept(n, json.loads(path.read_text(encoding="utf-8")), True)
        else:
            misses.append((n, card))
    if misses and not problem:
        # One forward for every uncached card. On Metal, system_one scores a single card and
        # leaves the batch axis idle; predict_batch packs them. Checked against system_one on
        # this checkpoint: the rounded probabilities match, so the cache stays interchangeable.
        # sort_by_length is left off because that packing can change the floats.
        left = cfg["total_timeout_ms"] / 1000 - (time.monotonic() - start)
        raws = None
        if left <= 0:
            problem = f"the G1 time limit of {cfg['total_timeout_ms']} ms was reached"
        else:
            try:
                agent = _local_agent(cfg)
                if len(misses) > 1 and hasattr(agent, "predict_batch"):
                    raws = agent.predict_batch([card for _, card in misses], QUESTIONS)
                    if len(raws) != len(misses):
                        raws = None
            except LocalUnavailable as exc:
                problem = str(exc)
            except Exception:  # noqa: BLE001 - fall back to one card at a time
                raws = None
        if not problem and raws is not None:
            for (n, card), raw in zip(misses, raws):
                try:
                    entry = _entry_from(cfg, raw)
                except Exception:  # noqa: BLE001 - one bad card is a null score
                    scores[n] = None
                    continue
                _write_entry(_cache_path(cfg, card), entry)
                _accept(n, entry, False)
        elif not problem:
            for n, card in misses:
                if not _score_one(n, card):
                    break
    # A card the model cut gets a null score and the run continues (spec rule 4). That is
    # `partial`, including when every card was cut. `unavailable` is a missing checkpoint or a
    # time limit: treating "all truncated" as that made the evaluation stop and blame the model.
    every_card_cut = set(scores) <= set(out["truncated_cards"])
    if not problem and all(v is None for v in scores.values()) and not every_card_cut:
        problem = "no card got a score"
    if problem:  # C8: the run goes on exactly as if G1 were off
        out.update(status="unavailable", reason=problem)
    else:
        order = sorted(candidates, key=lambda n: (scores[n] is None, -(scores[n] or 0.0), n))
        partial = not scores or any(v is None for v in scores.values())
        out.update(status="partial" if partial else "ok",
                   scores=[{"node": n, "score": scores[n], **({"answers": answers[n]} if n in answers else {})}
                           for n in order])
    out["ms"] = round(1000 * (time.monotonic() - start))
    return out
