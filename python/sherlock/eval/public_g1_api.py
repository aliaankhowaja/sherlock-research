"""Which hosted-LLM G1 order reaches the published culprit names sooner? (metrics spec §8; E1/E2 public leg)

    cd python/sherlock
    uv run python eval/public_g1_api.py --cases ../../docs/eval/public_traces/cases.jsonl.gz \
        --out ../../docs/eval/public_traces            # needs the .env provider (vertex/ADC in the paper runs)
    uv run python eval/public_g1_api.py --cases ... --limit 5     # a quick partial run
    uv run python eval/public_g1_api.py --cases ... --check ../../docs/eval/public_traces/public_g1_api.json

Same records, budget and scoring as the committed laya run (`public_g1.py`): the order is G0 clues
first with the G1 nominations breaking ties, scored by rank / reciprocal rank / recall@3 / ndcg@3 /
trials-to-label against the published label. Two G1 methods: `api_small` (the laya card budget) and
`api_big` (8x budget + GOOD_IN/UPSTREAM/WRITES_ALL where defined — public rows have no known-good
run, so GOOD_IN and the GOOD halves of UPSTREAM never appear here; that asymmetry is the corpus's,
not a choice). One scored pass per row, matching the committed laya protocol; a pre-registered
200-row subsample is scored 5 times for the §6.7 across-pass agreement (mean pairwise Kendall tau of
the produced order). The random-order reference is not recomputed: the committed
public_g1.json random_ref (100 seeds) is reused as-is.

Records are processed a few at a time so the hosted calls stay busy (each row's calls are already
parallel); results are reported in file order. Any failed hosted call (transport or parse) aborts
the script with a loud error — failed calls are not cached, so a run that swallowed one could never
be reproduced by --check; there is no silent fall-back to the G0 order.

Writes public_g1_api.json and public_g1_api.md (the markdown is also printed). Card text is never
written out; per-row card hashes/chars, scores, token counts, truncation flags and USD are.
"""

import argparse
import gzip
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "src"), str(HERE)]

from public_g1 import INTRO, _checks, _score_row, path_of  # noqa: E402
from sherlock.clues import history_clues, order_candidates  # noqa: E402
from sherlock.g1 import CARD_VARIANTS, node_card, rank  # noqa: E402

from sherlock import __version__, envfile, g1_api  # noqa: E402

RECORD_CONCURRENCY = 4   # rows scored at once (each row's own calls are already parallel, 16 wide)


def load_cases(path: Path) -> list[dict]:
    text = gzip.open(path, "rt", encoding="utf-8").read() if path.suffix == ".gz" \
        else path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _api_orders(record: dict, seed: int, cfg: dict, variants: tuple[str, ...]):
    """The orders for one record: random/path/g0 exactly as public_g1 builds them, plus one per
    requested API card variant. Returns (orders, per-variant g1 records, failures)."""
    history = record["history"]
    on_path = path_of(history)
    clues = history_clues(history, "final_output")
    checks = _checks(record)
    shuffled = list(on_path)
    random.Random(f"{seed}:{record['id']}").shuffle(shuffled)
    orders = {"random": shuffled, "path": list(on_path), "g0": order_candidates(on_path, clues)}
    g1s, failed = {}, []
    for v in variants:
        deck = {n: node_card(n, history, None, checks, **CARD_VARIANTS[v]) for n in on_path}
        g1 = rank({**cfg, "backend": "api", "card_variant": v, "passes": 1,
                   "cache_dir": str(Path(cfg["cache_dir"]) / v)},
                  on_path, lambda n, deck=deck: tuple(deck[n]))
        if g1["status"] == "unavailable":
            failed.append(f"{record['id']} ({v}): {g1.get('reason') or 'unavailable'}")
            continue
        if g1["status"] != "ok" or g1["calls"]["failed"]:  # a partial row is a failed call in disguise:
            failed.append(f"{record['id']} ({v}): status {g1['status']} with {g1['calls']['failed']} failed "
                          f"call(s) — failed calls are not cached, so the run could not be reproduced; aborting")
            continue
        orders[f"api_{v}"] = order_candidates(on_path, clues, [s["node"] for s in g1["scores"]])
        g1s[v] = g1
    return orders, g1s, failed


def _stability_row(record: dict, cfg: dict, passes: int, variants: tuple[str, ...]) -> dict:
    """§6.7: the produced order (G0 + G1 nominations), `passes` times; mean pairwise Kendall tau."""
    history = record["history"]
    on_path = path_of(history)
    clues = history_clues(history, "final_output")
    checks = _checks(record)
    out = {"id": record["id"], "nodes": len(on_path)}
    for v in variants:
        deck = {n: node_card(n, history, None, checks, **CARD_VARIANTS[v]) for n in on_path}
        rec = {"orders": [], "mean_tau": None, "error": None}
        for p in range(passes):
            g1 = rank({**cfg, "backend": "api", "card_variant": v, "passes": 1, "pass_offset": p,
                       "cache_dir": str(Path(cfg["cache_dir"]) / v)},
                      on_path, lambda n, deck=deck: tuple(deck[n]))
            if g1["status"] != "ok" or g1["calls"]["failed"]:
                # no silent degradation to a null tau: failed calls are not cached, so a run that
                # swallowed one could never be reproduced by --check (E3 amendment: this happened —
                # a rate-limit burst nulled 8 consecutive stability rows' full passes)
                raise RuntimeError(f"stability row {record['id']} ({v}, pass {p}): status {g1['status']} "
                                   f"with {g1['calls']['failed']} failed call(s) — {g1.get('reason') or 'failed'}")
            rec["orders"].append(order_candidates(on_path, clues, [s["node"] for s in g1["scores"]]))
        taus = [g1_api._kendall_tau(rec["orders"][i], rec["orders"][j])
                for i in range(len(rec["orders"])) for j in range(i + 1, len(rec["orders"]))]
        rec["mean_tau"] = round(statistics.fmean(taus), 4) if taus else None
        out[v] = rec
    return out


def stability_summary(rows: list[dict], variants: tuple[str, ...]) -> dict:
    out = {"rows": len(rows), "passes_per_row": None, "mean_tau": {}}
    for v in variants:
        taus = [r[v]["mean_tau"] for r in rows if r.get(v, {}).get("mean_tau") is not None]
        out["mean_tau"][v] = round(statistics.fmean(taus), 4) if taus else None
        out["passes_per_row"] = max((len(r.get(v, {}).get("orders") or []) for r in rows), default=0)
    return out


def cost_summary(cost_cases: list[dict], variants: tuple[str, ...], cfg: dict) -> dict:
    """§4: per variant, nodes scored, truncation against card size, tokens, USD."""
    out = {}
    for v in variants:
        chars, truncated, tokens_in, tokens_out = [], 0, 0, 0
        statuses = {}
        for case in cost_cases:
            g1 = case.get(f"api_{v}")
            if not g1:
                continue
            statuses[g1.get("status")] = statuses.get(g1.get("status"), 0) + 1
            cut = set(g1.get("truncated_cards") or [])
            for n, size in (g1.get("card_chars") or {}).items():
                chars.append(size)
                truncated += n in cut
            tokens_in += (g1.get("cost") or {}).get("tokens_in") or 0
            tokens_out += (g1.get("cost") or {}).get("tokens_out") or 0
        usd = None
        if cfg.get("price_in") and cfg.get("price_out"):
            usd = round(tokens_in / 1e6 * float(cfg["price_in"]) + tokens_out / 1e6 * float(cfg["price_out"]), 4)
        out[v] = {"cards": len(chars),
                  "card_chars_mean": round(statistics.fmean(chars), 1) if chars else None,
                  "card_chars_max": max(chars) if chars else None, "builder_truncated": truncated,
                  "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": usd, "statuses": statuses,
                  "price_in": cfg.get("price_in"), "price_out": cfg.get("price_out"),
                  "price_source": cfg.get("price_source")}
    return out


def truncation_by_card_size(cost_cases: list[dict], variants: tuple[str, ...]) -> dict:
    out = {}
    for v in variants:
        buckets = {}
        for case in cost_cases:
            g1 = case.get(f"api_{v}")
            if not g1:
                continue
            built = set(g1.get("truncated_cards") or [])
            api_cut = set(g1.get("api_truncated") or [])
            for n, size in (g1.get("card_chars") or {}).items():
                b = "<1200" if size < 1200 else ">=2400" if size >= 2400 else "1200-2399"
                agg = buckets.setdefault(b, [0, 0, 0])
                agg[0] += 1
                agg[1] += n in built
                agg[2] += n in api_cut
        out[v] = {b: {"cards": a[0], "builder_cut": a[1], "api_cut": a[2]} for b, a in sorted(buckets.items())}
    return out


def evaluate(records: list[dict], seed: int, cfg: dict, variants: tuple[str, ...],
             stability_rows: int, stability_passes: int, concurrency: int = RECORD_CONCURRENCY) -> dict:
    """Score every headline record with both card variants, then the stability subsample."""
    methods_all = ("random", "path", "g0", *(f"api_{v}" for v in variants))
    rows = [None] * len(records)
    costs = [None] * len(records)

    def work(i):
        record = records[i]
        orders, g1s, failed = _api_orders(record, seed, cfg, variants)
        if failed:  # a dead endpoint fails the run loudly and immediately; no G0 fallback
            raise RuntimeError("The G1 API was unavailable: " + "; ".join(failed))
        cost = {f"api_{v}": {"card_chars": g1s[v].get("card_chars", {}),
                             "truncated_cards": g1s[v]["truncated_cards"],
                             "api_truncated": sorted(n for n, rec in (g1s[v].get("per_node") or {}).items()
                                                     if any(rec["truncated"])),
                             "cost": g1s[v].get("cost"),
                             "calls": g1s[v].get("calls"), "status": g1s[v]["status"]}
                for v in variants}
        return i, _score_row(record, orders), cost

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, row, cost in pool.map(work, range(len(records))):
            rows[i], costs[i] = row, {**{"id": records[i]["id"]}, **cost}
    got = [r for r in rows if r is not None]
    assert len(got) == len(records), "some rows did not score"
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)

    # the pre-registered stability subsample: a seeded sample of headline rows, `stability_passes` passes
    stability = {}
    if stability_rows:
        rng = random.Random(f"{cfg['seed_tag']}:{stability_rows}")
        picked = sorted(rng.sample(range(len(records)), min(stability_rows, len(records))))
        sub = [_stability_row(records[i], cfg, stability_passes, variants) for i in picked]
        stability = {"rows": len(sub), "selection": f"random.Random('{cfg['seed_tag']}:{stability_rows}')"
                                                     f".sample over headline rows, reported in file order",
                     "passes_per_row": stability_passes,
                     "rows_detail": [{"id": r["id"], **{v: r[v]["mean_tau"] for v in variants}} for r in sub],
                     "summary": stability_summary(sub, variants)}
    return {
        "intro": INTRO, "backend": "api", "seed": seed,
        "methods": summarize(rows, methods_all),
        "by_source": {source: summarize(group, methods_all) for source, group in sorted(by_source.items())},
        "stability": stability, "rows": rows, "cost": {"cases": costs},
    }


def summarize(rows: list[dict], methods: tuple[str, ...]) -> dict:
    out = {}
    for method in methods:
        cells = [row["methods"][method] for row in rows]
        trials = [cell["trials_to_label"] for cell in cells if cell["trials_to_label"] is not None]
        out[method] = {
            "rows": len(cells),
            "rank": _mean([cell["rank"] for cell in cells if cell["rank"] is not None]),
            "reciprocal rank": _mean([cell["reciprocal rank"] for cell in cells]),
            "recall@3": _mean([cell["recall@3"] for cell in cells]),
            "ndcg@3": _mean([cell["ndcg@3"] for cell in cells]),
            "trials_to_label": _mean(trials),
            "no_trial": len(cells) - len(trials),
        }
    return out


def _mean(values):
    return round(statistics.mean(values), 3) if values else None


def _first_diff(want, got, path="$"):
    """First path where two canonical artifacts disagree, so a failed --check says where."""
    if type(want) is not type(got):
        return f"{path}: type {type(want).__name__} vs {type(got).__name__}"
    if isinstance(want, dict):
        for k in sorted(set(want) | set(got)):
            if k not in want:
                return f"{path}.{k}: only in the fresh run ({str(got[k])[:120]})"
            if k not in got:
                return f"{path}.{k}: only in the committed artifact ({str(want[k])[:120]})"
            found = _first_diff(want[k], got[k], f"{path}.{k}")
            if found:
                return found
        return None
    if isinstance(want, list):
        if len(want) != len(got):
            return f"{path}: list length {len(want)} vs {len(got)}"
        for i, (w, g) in enumerate(zip(want, got)):
            found = _first_diff(w, g, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if want == got else f"{path}: {str(want)[:120]!r} vs {str(got)[:120]!r}"


def canonical(res):
    """The artifact minus wall-clock fields; everything scored stays."""
    out = json.loads(json.dumps(res))

    def strip(v):
        if isinstance(v, dict):
            for k in ("ms", "created", "cache", "wall_s"):
                v.pop(k, None)
            for c in v.values():
                strip(c)
        elif isinstance(v, list):
            for c in v:
                strip(c)

    strip(out)
    return out


def _cell(value) -> str:
    return "-" if value is None else str(value)


def _table(head, body) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in body]
    return "\n".join(lines)


def _method_table(summary: dict) -> str:
    cols = ["rank", "reciprocal rank", "recall@3", "ndcg@3", "trials_to_label"]
    body = [[method, summary[method]["rows"], *[_cell(summary[method][col]) for col in cols],
             summary[method]["no_trial"]] for method in summary]
    return _table(["method", "rows", *cols, "no trial"], body)


def render(res: dict) -> str:
    methods_all = ("random", "path", "g0", *(f"api_{v}" for v in res["variants"]))
    cost = res["cost_summary"]
    parts = [f"# Public-trace ordering with the hosted-LLM G1 ({res['config']['provider']} / "
             f"{res['config']['model']})", "", res["intro"], "",
             "mathchat rows tagged `two_role` are not in these means. The random-order reference is the "
             "committed `public_g1.json` one (100 seeds); no new shuffle was run. `api_small` = the laya "
             "card budget; `api_big` = 8x budget + GOOD_IN/UPSTREAM/WRITES_ALL where a known-good run "
             "exists (on this corpus it never does, so those fields are absent).",
             *(["`api_full` = no card budget at all: every field in full, no per-field DIFF cap; the only "
               "truncation left is the model's own context window (§14 amendment: E3).",] if "full" in res["variants"] else []),
             "",
             "## Methods", "", _method_table(res["methods"]), ""]
    for source, summary in res["by_source"].items():
        parts += [f"## {source}", "", _method_table(summary), ""]
    parts += ["## Cost (§4)", "",
              _table(["variant", "cards", "mean chars", "max chars", "builder-cut", "tokens in", "tokens out",
                      "USD", "statuses"],
                     [[v, cost[v]["cards"], cost[v]["card_chars_mean"], cost[v]["card_chars_max"],
                       cost[v]["builder_truncated"], cost[v]["tokens_in"], cost[v]["tokens_out"],
                       cost[v]["usd"], cost[v]["statuses"]] for v in res["variants"]]),
              "", "### Truncation by card size", "",
              _table(["variant", "bucket", "cards", "builder-cut", "api-context-cut"],
                     [[v, b, a["cards"], a["builder_cut"], a["api_cut"]]
                      for v in res["variants"] for b, a in res["truncation_by_card_size"][v].items()])]
    st = res["stability"]
    if st:
        parts += ["", "## Stability (§6.7): across-pass agreement of the produced order", "",
                  f"{st['rows']} pre-registered rows, {st['passes_per_row']} passes each "
                  f"(selection: {st['selection']}).", "",
                  _table(["variant", "mean pairwise Kendall tau"],
                         [[v, st["summary"]["mean_tau"][v]] for v in res["variants"]])]
    parts += ["", f"Generated by eval/public_g1_api.py; prompt version {res['prompt_version']}; "
                  f"config hash {res['config']['config_hash']}."]
    return "\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_cases = None
    for name in ("cases.jsonl.gz", "cases.jsonl"):
        p = HERE.parents[2] / "docs" / "eval" / "public_traces" / name
        if p.is_file():
            default_cases = p
            break
    ap.add_argument("--cases", type=Path, default=default_cases,
                    help="the records convert_public_traces.py wrote (default: the committed file)")
    ap.add_argument("--out", type=Path, help="write public_g1_api.json/.md here")
    ap.add_argument("--check", type=Path, help="re-run from the cache and compare with this artifact")
    ap.add_argument("--seed", type=int, default=1, help="the shared shuffle seed (public_g1 used 1)")
    ap.add_argument("--stability", type=int, default=200,
                    help="headline rows scored 5 times for the §6.7 agreement (0 disables)")
    ap.add_argument("--stability-passes", type=int, default=5)
    ap.add_argument("--limit", type=int, help="score only the first N rows (a quick partial run)")
    ap.add_argument("--variants", default="small,big",
                    help="comma-separated card variants to score (default small,big; E3 adds full)")
    args = ap.parse_args()
    if not args.cases:
        sys.exit("public_g1_api: no --cases file given and none found")
    envfile.load()
    try:
        cfg = g1_api.env_config({"cache_dir": str(HERE / ".g1" / "public_api_cache"),
                                 "seed_tag": f"{args.seed}:stability"})
    except g1_api.ConfigError as exc:
        print(f"public_g1_api: {exc}", file=sys.stderr)
        return 2
    records = load_cases(args.cases)
    headline = [r for r in records if "two_role" not in r.get("tags", [])]
    if args.limit:
        headline = headline[:args.limit]
    variants = tuple(v.strip() for v in args.variants.split(","))
    unknown = [v for v in variants if v not in CARD_VARIANTS]
    if unknown:
        sys.exit(f"public_g1_api: unknown card variant(s): {', '.join(unknown)}; known: {', '.join(CARD_VARIANTS)}")
    res = evaluate(headline, args.seed, cfg, variants, args.stability, args.stability_passes)
    res["variants"] = list(variants)
    res["created"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    res["config"] = {**{k: cfg[k] for k in ("provider", "model", "temperature", "max_output_tokens",
                                            "thinking_budget", "max_input_tokens", "max_workers",
                                            "price_in", "price_out", "price_source")},
                     "endpoint": g1_api.endpoint_of(cfg), "config_hash": g1_api.config_hash(cfg),
                     "client_version": __version__}
    res["prompt"] = g1_api.SYSTEM
    res["prompt_version"] = g1_api.PROMPT_VERSION
    res["card_variants"] = CARD_VARIANTS
    res["cost_summary"] = cost_summary(res["cost"]["cases"], variants, cfg)
    res["truncation_by_card_size"] = truncation_by_card_size(res["cost"]["cases"], variants)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "public_g1_api.json").write_text(json.dumps(res, indent=2, sort_keys=True) + "\n",
                                                     encoding="utf-8", newline="\n")
        (args.out / "public_g1_api.md").write_text(render(res), encoding="utf-8", newline="\n")
    if args.check:
        want = canonical(json.loads(Path(args.check).read_text(encoding="utf-8")))
        got = canonical(res)
        if json.dumps(want, indent=2, sort_keys=True) + "\n" != json.dumps(got, indent=2, sort_keys=True) + "\n":
            diff = _first_diff(want, got) or "(values differ somewhere the walk could not localize)"
            print("public_g1_api: results differ from", args.check, "(not reproducible, or the code changed)",
                  file=sys.stderr)
            print(f"public_g1_api: first difference: {diff}", file=sys.stderr)
            dump = HERE / ".g1" / "fresh_public_check.json"
            dump.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            print(f"public_g1_api: the fresh canonical projection was written to {dump} for diffing", file=sys.stderr)
            return 1
        print("public_g1_api: results identical to", args.check)
    print(render(res), end="")
    s = res["methods"]
    return 0


if __name__ == "__main__":
    sys.exit(main())
