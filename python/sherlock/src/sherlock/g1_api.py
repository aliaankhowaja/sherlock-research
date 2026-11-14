"""G1 API scorer: one hosted-LLM call per candidate node card (metrics spec §4, experiments E1/E2).

Backend id `api` in `g1.rank`. Where the local `laya` checkpoint scores a card in-process, this backend
sends the same card to a hosted model and asks one question: must this node be restored for the run to
pass its check? The reply is JSON `{"needs_restore": "yes"|"no", "confidence": 0-100}`; the score is
P(restore) = confidence/100 for "yes" and 1 - confidence/100 for "no". A graded score in a single call,
so an ordering has the same granularity as laya's probabilities; the pre-registered >= 5 passes
(metrics spec §6.7) measure across-call agreement, not vote share.

Providers (D10): `vertex` (Vertex AI generateContent, Application Default Credentials — no key in the
repo), `gemini_api` (Generative Language API with an API key), `openai_compat` (any /chat/completions
endpoint: OpenAI, ollama, Groq, ...). Configuration comes from the environment / `.env` (see
.env-example); the same SYSTEM prompt and reply format are used for every provider and both card
variants, so the only thing that changes between experiments E1 (small cards) and E2 (big cards) is
the card text.

Cost and failure bookkeeping (§4/§10): every call records prompt/completion tokens, wall ms, whether
the card did not fit the model's context (`truncated` — the mechanism under test) and any error. USD
needs the published per-million-token prices supplied in the environment, with their date. Truncated
cards get no score, exactly as for laya. A dead endpoint is reported as `unavailable` and the eval
scripts exit loudly; it is never a silent fall-back to G0 ordering in an experiment.
"""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from sherlock import __version__

PROMPT_VERSION = "g1_api_prompt_v1"
# The same system prompt for every provider and both card variants (D4). The card itself is the user
# message; no tools are ever offered.
SYSTEM = (
    "You audit one node of a failed multi-step pipeline run. You are given a card: what this node wrote "
    "in the failed run, what it wrote in a run that passed the same check when such a run exists, the "
    "check itself, and the node's input. Decide whether this node must be restored to the behaviour that "
    "makes the run pass the check.\n"
    "Rules: judge only this node's own behaviour. A difference the node merely inherited from upstream is "
    "not its fault. Base the answer only on the card's contents.\n"
    'Reply with one JSON object and nothing else: {"needs_restore": "yes" or "no", "confidence": integer '
    "0-100} where confidence is how certain you are about your answer (100 = certain)."
)
SAMPLE_CALL_RETRIES = 2        # transient failures (429 / 5xx / network) are retried; parse failures are not
TOKEN_CHARS = 3                # the CARD_CHARS rule: 3 characters ≈ 1 token, when the API gives no usage
ENV_DEFAULTS = {
    "SHERLOCK_G1_PROVIDER": None, "SHERLOCK_G1_MODEL": None, "GOOGLE_CLOUD_PROJECT": None,
    "GOOGLE_CLOUD_LOCATION": "us-central1", "SHERLOCK_G1_BASE_URL": None, "SHERLOCK_G1_API_KEY": None,
    "SHERLOCK_G1_TEMPERATURE": "0", "SHERLOCK_G1_MAX_OUTPUT_TOKENS": "256",
    # 0 = deterministic answer, no thought tokens eating maxOutputTokens (blank value in .env = omit the
    # field entirely, for models where thinkingConfig is not supported)
    "SHERLOCK_G1_THINKING_BUDGET": "0", "SHERLOCK_G1_TIMEOUT_S": "120",
    "SHERLOCK_G1_MAX_INPUT_TOKENS": "", "SHERLOCK_G1_PASSES": "5", "SHERLOCK_G1_CONCURRENCY": "16",
    "SHERLOCK_G1_PRICE_IN": "", "SHERLOCK_G1_PRICE_OUT": "", "SHERLOCK_G1_PRICE_SOURCE": "",
}
PROVIDERS = ("vertex", "gemini_api", "openai_compat")
_token_lock = threading.Lock()
_token_cache: dict = {}


class ConfigError(RuntimeError):
    """The environment does not name a usable provider/model; the caller must stop, not fall back."""


def env_config(extra: dict | None = None) -> dict:
    """The scorer config from the environment (.env already loaded); ENV_DEFAULTS fill what is unset.
    Missing essentials raise ConfigError."""
    missing = {k: v for k, v in ENV_DEFAULTS.items() if v is not None and not os.environ.get(k)}
    for key, value in missing.items():
        os.environ.setdefault(key, value)
    cfg = {k: os.environ.get(k) for k in ENV_DEFAULTS}
    cfg["provider"] = cfg.pop("SHERLOCK_G1_PROVIDER")
    cfg["model"] = cfg.pop("SHERLOCK_G1_MODEL")
    cfg["base_url"] = cfg.pop("SHERLOCK_G1_BASE_URL")
    cfg["api_key"] = cfg.pop("SHERLOCK_G1_API_KEY")
    cfg["project"] = cfg.pop("GOOGLE_CLOUD_PROJECT")
    cfg["location"] = cfg.pop("GOOGLE_CLOUD_LOCATION")
    cfg["temperature"] = float(cfg.pop("SHERLOCK_G1_TEMPERATURE"))
    cfg["max_output_tokens"] = int(cfg.pop("SHERLOCK_G1_MAX_OUTPUT_TOKENS"))
    tb = cfg.pop("SHERLOCK_G1_THINKING_BUDGET")
    cfg["thinking_budget"] = int(tb) if tb not in (None, "") else None
    cfg["timeout_s"] = float(cfg.pop("SHERLOCK_G1_TIMEOUT_S"))
    mit = cfg.pop("SHERLOCK_G1_MAX_INPUT_TOKENS")
    cfg["max_input_tokens"] = int(mit) if mit not in (None, "") else None
    cfg["passes"] = max(1, int(cfg.pop("SHERLOCK_G1_PASSES")))
    cfg["max_workers"] = max(1, int(cfg.pop("SHERLOCK_G1_CONCURRENCY")))
    cfg["price_in"] = cfg.pop("SHERLOCK_G1_PRICE_IN") or None
    cfg["price_out"] = cfg.pop("SHERLOCK_G1_PRICE_OUT") or None
    cfg["price_source"] = cfg.pop("SHERLOCK_G1_PRICE_SOURCE") or None
    if cfg["provider"] not in PROVIDERS:
        raise ConfigError(f"SHERLOCK_G1_PROVIDER must be one of {', '.join(PROVIDERS)}")
    if not cfg["model"]:
        raise ConfigError("SHERLOCK_G1_MODEL is not set")
    if cfg["provider"] in ("vertex", "gemini_api") and not cfg["project"] and cfg["provider"] == "vertex":
        raise ConfigError("SHERLOCK_G1_PROVIDER=vertex needs GOOGLE_CLOUD_PROJECT (or use gemini_api/openai_compat)")
    if cfg["provider"] == "gemini_api" and not cfg["api_key"]:
        raise ConfigError("SHERLOCK_G1_PROVIDER=gemini_api needs SHERLOCK_G1_API_KEY")
    if cfg["provider"] == "openai_compat" and not cfg["base_url"]:
        raise ConfigError("SHERLOCK_G1_PROVIDER=openai_compat needs SHERLOCK_G1_BASE_URL (e.g. http://127.0.0.1:11434/v1)")
    return {**cfg, **(extra or {})}


def config_hash(cfg: dict) -> str:
    """A fingerprint of the scored configuration: everything except secrets, hashed (§10)."""
    fields = {k: cfg.get(k) for k in ("provider", "model", "project", "location", "base_url", "temperature",
                                      "max_output_tokens", "thinking_budget", "max_input_tokens", "passes",
                                      "max_workers", "price_in", "price_out", "price_source")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def endpoint_of(cfg: dict) -> str:
    """scheme + host only: never the key, never a path with secrets (as gates.G1Result.endpoint)."""
    if cfg["provider"] == "vertex":
        return f"https://{cfg['location']}-aiplatform.googleapis.com"
    if cfg["provider"] == "gemini_api":
        return "https://generativelanguage.googleapis.com"
    parts = urlsplit(cfg["base_url"] or "")
    return f"{parts.scheme}://{parts.netloc}"


# --- the reply --------------------------------------------------------------------------------------------

def parse_reply(text: str) -> float:
    """P(needs_restore = yes) from the reply, or ValueError. Fenced JSON and leading prose are tolerated."""
    t = text.strip()
    for candidate in (t, re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()):
        try:
            data = json.loads(candidate)
        except ValueError:
            start, end = t.find("{"), t.rfind("}")
            if start < 0 or end <= start:
                continue
            try:
                data = json.loads(t[start:end + 1])
            except ValueError:
                continue
        if isinstance(data, dict):
            answer = data.get("needs_restore") or data.get("answer") or data.get("restore")
            conf = data.get("confidence")
            if answer not in ("yes", "no") or not isinstance(conf, int | float) or not 0 <= conf <= 100:
                raise ValueError(f"reply is not a needs_restore/confidence object: {text[:120]!r}")
            p = conf / 100.0
            return round(p if answer == "yes" else 1.0 - p, 4)
    raise ValueError(f"reply holds no JSON object: {text[:120]!r}")


# --- providers ----------------------------------------------------------------------------------------------

def _adc_token() -> str:
    """An access token from Application Default Credentials. `google.auth` when installed, else `gcloud`."""
    with _token_lock:
        if _token_cache.get("token") and _token_cache.get("expires", 0) > time.time() + 120:
            return _token_cache["token"]
        token = expires = None
        try:
            import google.auth  # noqa: PLC0415 - optional; the gcloud fallback needs no package
            from google.auth.transport.requests import Request  # noqa: PLC0415
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            if not creds.valid:
                creds.refresh(Request())
            token, expires = creds.token, (creds.expiry.timestamp() if creds.expiry else 0)
        except ImportError:
            out = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"],  # noqa: S603
                                 capture_output=True, text=True, timeout=60, check=True)
            token = out.stdout.strip().splitlines()[-1].strip()
            expires = time.time() + 45 * 60
        _token_cache.update(token=token, expires=expires)
        return token


def _request(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the user's own configured endpoint
        return json.loads(resp.read())


def _call_vertex(cfg: dict, card: str) -> tuple[str, dict]:
    url = (f"{endpoint_of(cfg)}/v1/projects/{cfg['project']}/locations/{cfg['location']}"
           f"/publishers/google/models/{cfg['model']}:generateContent")
    gen = {"temperature": cfg["temperature"], "maxOutputTokens": cfg["max_output_tokens"],
           "responseMimeType": "application/json"}
    if cfg["thinking_budget"] is not None:
        gen["thinkingConfig"] = {"thinkingBudget": cfg["thinking_budget"]}
    data = _request(url, {"contents": [{"role": "user", "parts": [{"text": card}]}],
                          "systemInstruction": {"parts": [{"text": SYSTEM}]}, "generationConfig": gen},
                    {"Authorization": f"Bearer {_adc_token()}"}, cfg["timeout_s"])
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []))
    usage = data.get("usageMetadata") or {}
    return text, {"prompt_tokens": usage.get("promptTokenCount"), "completion_tokens": usage.get("candidatesTokenCount"),
                  "finish": cand.get("finishReason"), "model": data.get("modelVersion")}


def _call_gemini_api(cfg: dict, card: str) -> tuple[str, dict]:
    url = f"{endpoint_of(cfg)}/v1beta/models/{cfg['model']}:generateContent"
    gen = {"temperature": cfg["temperature"], "maxOutputTokens": cfg["max_output_tokens"],
           "responseMimeType": "application/json"}
    if cfg["thinking_budget"] is not None:
        gen["thinkingConfig"] = {"thinkingBudget": cfg["thinking_budget"]}
    data = _request(url, {"contents": [{"role": "user", "parts": [{"text": card}]}],
                          "systemInstruction": {"parts": [{"text": SYSTEM}]}, "generationConfig": gen},
                    {"x-goog-api-key": cfg["api_key"]}, cfg["timeout_s"])
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in ((cand.get("content") or {}).get("parts") or []))
    usage = data.get("usageMetadata") or {}
    return text, {"prompt_tokens": usage.get("promptTokenCount"), "completion_tokens": usage.get("candidatesTokenCount"),
                  "finish": cand.get("finishReason"), "model": data.get("modelVersion")}


def _call_openai(cfg: dict, card: str) -> tuple[str, dict]:
    body = {"model": cfg["model"], "temperature": cfg["temperature"], "max_tokens": cfg["max_output_tokens"],
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": card}]}
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
    data = _request(cfg["base_url"].rstrip("/") + "/chat/completions", body, headers, cfg["timeout_s"])
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    usage = data.get("usage") or {}
    return text, {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                  "finish": choice.get("finish_reason"), "model": data.get("model")}


_CALLERS = {"vertex": _call_vertex, "gemini_api": _call_gemini_api, "openai_compat": _call_openai}


# --- one call, its record, the cache -----------------------------------------------------------------------

def card_truncated(card: str, usage: dict, cfg: dict) -> bool:
    """Did the card not fit the model's context (the mechanism under test)? Usage first, the 3-chars/1-token
    rule as the fallback; `max_input_tokens` unset means no model limit is configured and nothing is flagged."""
    limit = cfg.get("max_input_tokens")
    if limit is None:
        return False
    prompt = usage.get("prompt_tokens")
    tokens = prompt if isinstance(prompt, int) else len(card) / TOKEN_CHARS
    return bool(tokens > limit)


def call_card(cfg: dict, card: str, pass_index: int = 0) -> dict:
    """One scored call. {score, usage, model, error} — usage without wall ms (that varies, and is recorded
    by the caller). `score` is None on any failure; the failure is in `error`."""
    started = time.monotonic()
    usage = {"prompt_tokens": None, "completion_tokens": None, "finish": None, "model": None, "latency_ms": None}
    try:
        text, raw_usage = _CALLERS[cfg["provider"]](cfg, card)
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors="replace") if exc.code not in (429,) else "rate limited"
        return {"score": None, "error": f"HTTP {exc.code}: {detail}", "usage": {**usage, "latency_ms": _ms(started)}}
    except Exception as exc:  # noqa: BLE001 - any transport failure is a failed call, never a crash of the run
        return {"score": None, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "usage": {**usage, "latency_ms": _ms(started)}}
    usage.update(raw_usage, latency_ms=_ms(started))
    try:
        score = parse_reply(text)
    except ValueError as exc:
        return {"score": None, "error": str(exc), "usage": usage}
    return {"score": score, "error": None, "usage": usage}


def _ms(started: float) -> int:
    return round(1000 * (time.monotonic() - started))


def _cache_path(cfg: dict, card: str, pass_index: int) -> Path | None:
    if not cfg.get("cache_dir"):
        return None
    key = json.dumps([cfg["provider"], cfg["model"], PROMPT_VERSION, SYSTEM, card, pass_index,
                      cfg["temperature"], cfg["max_output_tokens"], cfg["thinking_budget"]])
    return Path(cfg["cache_dir"]) / f"{hashlib.sha256(key.encode()).hexdigest()}.json"


def _stable_call(cfg: dict, card: str, pass_index: int, retries: int = SAMPLE_CALL_RETRIES) -> dict:
    """The call with transient retries (429/5xx/network) and the on-disk cache. The cache entry keeps the
    answer and the token usage but never the card, the key, or the wall time."""
    path = _cache_path(cfg, card, pass_index)
    if path and path.is_file():
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["cached"] = True
        return entry
    last = {"score": None, "error": "no attempt", "usage": {}}
    for attempt in range(retries + 1):
        last = call_card(cfg, card)
        usage = last.get("usage") or {}
        if last["score"] is not None or not str(last.get("error", "")).startswith(("HTTP 429", "HTTP 5")):
            break
        time.sleep(min(30.0, 2.0 * 2 ** attempt))
    entry = {"score": last["score"], "error": last["error"],
             "usage": {k: (usage or {}).get(k) for k in ("prompt_tokens", "completion_tokens", "finish")},
             "model": (usage or {}).get("model")}
    if path and entry["score"] is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, sort_keys=True), encoding="utf-8")
    entry["cached"] = False
    return entry


# --- scoring a whole shortlist -------------------------------------------------------------------------------

def _kendall_tau(a: list[str], b: list[str]) -> float:
    """Mean pairwise Kendall tau between two orders (ties by name; n small)."""
    n = len(a)
    if n < 2:
        return 1.0
    pos = {n_: i for i, n_ in enumerate(b)}
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            x, y = (pos[a[i]] < pos[a[j]]), (pos[b[i]] < pos[b[j]])  # a is already in rank order
            concordant += x == y
            discordant += x != y
    return round((concordant - discordant) / (concordant + discordant), 4)


def score_cards(cfg: dict, cards: dict[str, str], passes: int | None = None) -> dict:
    """Score every card `passes` times (concurrently) and pool.

    Returns {scores, per_node, tokens_in, tokens_out, usd, tau, calls_failed, calls_ok}. `scores` maps
    node -> pooled P(restore) (mean over the passes that answered, None when none did); `per_node` keeps
    the per-pass detail (§10): each pass's score, tokens, wall ms, truncated flag and error.
    """
    started = time.monotonic()
    passes = passes or cfg.get("passes") or 1
    offset = int(cfg.get("pass_offset") or 0)
    jobs = [(n, offset + p) for n in sorted(cards) for p in range(passes)]
    workers = min(cfg.get("max_workers") or 1, len(jobs)) or 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda j: (j, _stable_call(cfg, cards[j[0]], j[1])), jobs))
    per_node = {n: {"scores": [], "tokens_in": [], "tokens_out": [], "ms": [], "truncated": [], "errors": [],
                    "cached": 0, "calls": 0} for n in sorted(cards)}
    for (n, p), entry in results:
        rec = per_node[n]
        rec["calls"] += 1
        rec["cached"] += bool(entry.get("cached"))
        usage = entry.get("usage") or {}
        rec["tokens_in"].append(usage.get("prompt_tokens"))
        rec["tokens_out"].append(usage.get("completion_tokens"))
        rec["ms"].append(usage.get("latency_ms"))
        cut = card_truncated(cards[n], usage, cfg)
        rec["truncated"].append(cut)
        if entry["score"] is None:
            rec["errors"].append(entry.get("error") or "unknown error")
            rec["scores"].append(None)
        elif cut:  # a card the model's context cut gets no score, as for laya (spec rule 4)
            rec["scores"].append(None)
        else:
            rec["scores"].append(entry["score"])
    scores = {}
    for n, rec in per_node.items():
        got = [s for s in rec["scores"] if s is not None]
        scores[n] = round(sum(got) / len(got), 4) if got else None
    orders = []
    for p in range(passes):
        order = sorted(cards, key=lambda n: (per_node[n]["scores"][p] is None,
                                             -(per_node[n]["scores"][p] or 0.0), n))
        orders.append(order)
    taus = [_kendall_tau(orders[0], o) for o in orders[1:]] if passes > 1 else []
    tokens_in = sum(t for rec in per_node.values() for t in rec["tokens_in"] if t is not None)
    tokens_out = sum(t for rec in per_node.values() for t in rec["tokens_out"] if t is not None)
    usd = None
    if cfg.get("price_in") and cfg.get("price_out"):
        usd = round(tokens_in / 1e6 * float(cfg["price_in"]) + tokens_out / 1e6 * float(cfg["price_out"]), 4)
    return {"scores": scores, "per_node": per_node, "orders": orders,
            "tau": round(sum(taus) / len(taus), 4) if taus else None,
            "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd,
            "calls_ok": sum(len([s for s in r["scores"] if s is not None]) for r in per_node.values()),
            "calls_failed": sum(len(r["errors"]) for r in per_node.values()),
            "ms": round(1000 * (time.monotonic() - started))}
