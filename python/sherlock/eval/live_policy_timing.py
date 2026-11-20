"""Paired serial search latency on recorded solver questions; write CSV to stdout."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from evidence_search import direct_search
from final_replay import DATA, OUT, TEAM
from replay_corpus import Budget, Cassette, Checks, Client, Server, _new_lab, _run, diagnose, run_g3
from sherlock.search import search


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def measure(record, reference, work, transport, writer):
    _new_lab(work)
    shutil.copyfile(TEAM, work / "bench_solver.py")
    tape_path = work / ".sherlock/cassette.db"
    tape_path.parent.mkdir(exist_ok=True)
    shutil.copyfile(DATA / record["recording"], tape_path)
    tape = Cassette(tape_path)
    call = next(c for c in tape.calls() if c["complete"] and c["name"].endswith("/chat/completions"))
    base = call["name"].removeprefix("POST ").removesuffix("/chat/completions")
    request = json.loads(call["request"])
    os.environ.update(BENCH_URL=base, BENCH_MODEL=request["model"], BENCH_EXTRA=json.dumps(
        {k: v for k, v in request.items() if k not in ("model", "messages")}))
    checks = Checks([{"type": "equals", "value": record["answer"]}], "final_output", work, tape_path)
    if transport == "asgi":
        from replay_asgi import ReplayAPI
        client = server = ReplayAPI(work, tape)
    else:
        server = Server(work, replay=True, cassette=tape_path, stub_port=urlsplit(base).port, log=work/"server.log")
        client = Client(server.url)
    try:
        tape.start_trial()
        good, values = _run(client, record["question"], [], False)
        assert values["final_output"] == record["answer"]
        for i, cell in enumerate(reference["conditions"]):
            flags = cell["faults"]
            tape.start_trial()
            failed, values = _run(client, record["question"], flags, False)
            assert values["final_output"] == cell["forks"][0]["output"] != record["answer"]
            # Untimed warm-up supplies the actual production candidate order and clean patches.
            warm = diagnose(client, failed, None, checks, tape_path, Budget(), good_runs=[good])
            order = warm["pruning"]["candidates"]
            patches = warm["known_good_source"]["context_diff"]
            expected = set(cell["expected"])
            assert warm["complete"] and warm["minimal_sets"] == [sorted(expected, key=order.index)]
            for repeat in range(2):
                policies = ["production", "direct"]
                if (int(record["case_id"]) + i + repeat) % 2:
                    policies.reverse()
                for position, policy in enumerate(policies):
                    def fork(nodes):
                        result = run_g3(client, failed, nodes, patches, checks, tape_path, {"faults": flags})
                        assert result.verdict in ("pass", "fail") and result.fork_thread
                        return result

                    started = time.perf_counter_ns()
                    if policy == "production":
                        result = search(order, fork, None, Budget(max_trials=40))
                        found, complete, count = result.minimal_sets, result.complete, len(result.trials)
                    else:
                        def verdict(mask):
                            return fork([node for j, node in enumerate(order) if mask & (1 << j)]).verdict
                        masks, complete, trace = direct_search(len(order), verdict, 40)
                        found = [[node for j, node in enumerate(order) if mask & (1 << j)] for mask in masks]
                        count = len(trace)
                    elapsed = time.perf_counter_ns() - started
                    assert complete and len(found) == 1 and set(found[0]) == expected
                    writer.writerow([record["case_id"], record["source_dataset"], record["benchmark"],
                                     "+".join(flags), repeat, position, transport, policy, count, elapsed])
        assert not (work / "net_attempts.txt").exists() and not tape.abstains()
    finally:
        server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["asgi", "tcp"], default="asgi")
    parser.add_argument("--case", help=argparse.SUPPRESS)
    args = parser.parse_args()
    corpus = records(DATA / "data/cases.jsonl")
    writer = csv.writer(sys.stdout, lineterminator="\n")
    if args.case:
        record = next(r for r in corpus if r["case_id"] == args.case)
        reference = next(r for r in records(OUT / "results.jsonl") if r["id"] == args.case)
        with tempfile.TemporaryDirectory() as tmp:
            measure(record, reference, Path(tmp)/"lab", args.transport, writer)
        return
    writer.writerow(["question", "source", "benchmark", "faults", "repeat", "position",
                     "transport", "policy", "forks", "elapsed_ns"])
    sys.stdout.flush()
    strata = sorted({(r["source_dataset"], r["benchmark"]) for r in corpus})
    for source, benchmark in strata:
        rows = sorted((r for r in corpus if (r["source_dataset"], r["benchmark"]) == (source, benchmark)),
                      key=lambda r: r["case_id"])
        for record in rows[:2]:
            subprocess.run([sys.executable, __file__, "--transport", args.transport, "--case", record["case_id"]],
                           check=True)


if __name__ == "__main__":
    main()
