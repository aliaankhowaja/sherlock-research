"""Offline crossed intervention study. Run from the repository root with Python 3.13."""
import argparse
import ast
import hashlib
import itertools
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python/sherlock/src"))
from sherlock.cassette import Cassette, request_key
from sherlock.checks import Checks
from sherlock.diagnose import diagnose
from sherlock.g3 import Verdict, run_g3
from sherlock.search import Budget, search

DATA = ROOT / "data/sherlock-replay-corpus"
OUT = ROOT / "docs/eval/replay_corpus/final"
TEAM = DATA / "team/bench_solver.py"
FLAGS = ["extract.drop_last", "format.prefix"]
CAPS = [1, 2, 3, 4, 5, 6, 7, 40]


def load_team():
    # Load the exact exported functions without importing its unavailable HTTP/graph server.
    tree = ast.parse(TEAM.read_text())
    kept = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and ast.unparse(statement.targets[0]) == "builder":
            break
        if isinstance(statement, ast.ImportFrom) and statement.module.startswith("langgraph"):
            continue
        if isinstance(statement, ast.Import) and statement.names[0].name == "httpx":
            continue
        kept.append(statement)
    tree.body = kept
    scope = {"__name__": __name__}
    exec(compile(tree, str(TEAM), "exec"), scope)
    return scope


class LinearReplay:
    """Checkpoint operations used by G3 on the exported team's linear, append-free state."""
    def __init__(self, path):
        self.team = load_team()
        self.nodes = self.team["NODES"]
        self.db = Cassette(path)
        self.db.mark_replay(os.getpid())
        self.records = {}
        for row in self.db.calls():
            if row["name"].endswith("/chat/completions") and row["complete"] and row["status"] == 200:
                self.name = row["name"]
                self.template = json.loads(row["request"])
                assert request_key("http", self.name, row["request"]) == row["key"]
                response = json.loads(b"".join(self.db.chunks(row["id"])))
                self.records[row["key"]] = response["choices"][0]["message"]["content"]
        self.team["ask"] = self.ask
        self.histories = {}
        self.contexts = {}

    def ask(self, content):
        body = dict(self.template, messages=[{"role": "user", "content": content}])
        key = request_key("http", self.name, json.dumps(body).encode())
        if key not in self.records:
            self.db.add_abstain("unrecorded model request")
            raise KeyError(key)
        return self.records[key]

    def snapshot(self, state, index):
        return {"values": dict(state), "next": self.nodes[index:index+1], "tasks": [],
                "metadata": {"step": index, "run_id": "run"}, "checkpoint": {"checkpoint_id": str(index)}}

    def run(self, tid, flags, question=None):
        context = {"faults": flags}
        self.contexts[tid] = context
        if question is not None:
            inp = {"question": question}
            self.histories[tid] = [dict(self.snapshot({}, -1), next=["__start__"],
                                        tasks=[{"name": "__start__", "result": inp}]), self.snapshot(inp, 0)]
        hist = self.histories[tid]
        runtime = SimpleNamespace(context=self.team["Context"](faults=flags))
        while hist[-1]["next"]:
            snap = hist[-1]
            node = snap["next"][0]
            index = self.nodes.index(node)
            try:
                update = self.team["_FNS"][index](snap["values"], runtime)
            except KeyError as exc:
                if node != "solve":
                    raise
                return {"__error__": {"error": "cassette_miss", "message": str(exc)}}
            snap["tasks"] = [{"name": node, "result": update}]
            hist.append(self.snapshot(snap["values"] | update, index + 1))
        return hist[-1]["values"]

    def request(self, method, path, body=None):
        if path == "/threads":
            state = {}
            for step in body["supersteps"]:
                for update in step["updates"]:
                    state.update(update["values"])
                    last = update["as_node"]
            index = 0 if last == "__start__" else self.nodes.index(last) + 1
            tid = "fork"  # G3 completes one isolated fork before starting the next.
            self.histories[tid] = [self.snapshot(state, index)]
            return {"thread_id": tid}
        _, _, tid, *parts = path.split("/")
        if not parts:
            return {"metadata": {"graph_id": "bench_solver"}}
        if parts == ["history"]:
            return self.histories[tid][::-1]
        if parts == ["runs", "wait"]:
            return self.run(tid, body["context"]["faults"])
        run = {"kwargs": {"context": self.contexts[tid]}}
        if parts == ["runs"]:
            return [run]
        if parts == ["runs", "run"]:
            return run
        raise ValueError(path)


def subsets(nodes):
    return (s for k in range(1, len(nodes)+1) for s in itertools.combinations(nodes, k))


def minimal(table):
    return [sorted(s) for s, t in table.items() if t["verdict"] == "pass" and
            all(u["verdict"] == "fail" for k, u in table.items() if k < s)]


def trial_signature(trials):
    return [(sorted(t["restored"]), t["verdict"], t["cassette_miss"]) for t in trials]


def evaluate_case(record, path):
    client = LinearReplay(path)
    q, answer = record["question"], record["answer"]
    clean = client.run("good", [], q)
    checks = Checks([{"type": "equals", "value": answer}], "final_output", path.parent, path)
    issues = []
    def check(ok, label):
        if not ok:
            issues.append(label)

    dedicated = "preregistered" not in record
    check(clean["final_output"] == answer == record["clean_final_output"], "clean output")
    if not dedicated:
        check(clean["reply"] == record["reply"], "clean reply")
    controls = {"clean": clean["final_output"], "bias_only": client.run("bias", ["bias.flag"], q)["final_output"]}
    check(controls["bias_only"] == answer, "bias only")
    tapes, client.records = client.records, {}
    controls["withheld"] = client.run("withheld", [], q).get("__error__", {}).get("error")
    client.records = tapes
    controls["restored"] = client.run("restored", [], q)["final_output"]
    check(controls["withheld"] == "cassette_miss" and controls["restored"] == answer, "withholding")
    conditions = []
    designs = [record["faults"]] if dedicated else [
        list(active) + decoy for active in subsets(FLAGS) for decoy in ([], ["bias.flag"])]
    for flags in designs:
        expected = sorted(f.split(".")[0] for f in flags if f != "bias.flag")
        bad = client.run("bad", flags, q)
        started = time.perf_counter()
        art = diagnose(client, "bad", None, checks, path, good_runs=["good"])
        latency = time.perf_counter() - started
        patches = art["known_good_source"]["context_diff"]
        candidates = art["pruning"]["candidates"]
        table = {frozenset(): {"restored": [], "output": bad["final_output"], "verdict":
                               "pass" if bad["final_output"] == answer else "fail", "cassette_miss": False}}
        for subset in subsets([n for n in client.nodes if n in patches]):
            v = run_g3(client, "bad", list(subset), patches, checks, path, {"faults": flags})
            table[frozenset(subset)] = {"restored": sorted(subset), "verdict": v.verdict,
                "output": client.histories["fork"][-1]["values"].get("final_output"),
                "cassette_miss": bool(v.evidence.get("cassette_miss"))}
        gold = minimal(table)
        original = set(flags) == set(record["faults"])
        actual = sorted(sorted(s) for s in art["minimal_sets"])
        if original:
            check(bad["final_output"] == record["failed_final_output"], "export failed output")
            saved = record["sherlock"]
            check(all(art[k] == saved[k] for k in ("status", "reason_code", "minimal_sets", "unverified_sets"))
                  and trial_signature(art["trials"]) == trial_signature(saved["trials"]), "export diagnosis")
            if not dedicated:
                check(sorted(trial_signature(list(table.values())[1:])) == sorted(trial_signature(record["forks"]))
                      and gold == record["gold"] and expected == record["preregistered"], "export enumeration")
        check(all(t["verdict"] == table[frozenset(t["restored"])]["verdict"] for t in art["trials"]), "fork parity")
        if dedicated:
            check(art["reason_code"] == "unrecorded_call" and actual == gold == [] and
                  art["unverified_sets"] == [expected] and table[frozenset(expected)]["verdict"] == "pass"
                  and all(table[frozenset([n])]["cassette_miss"] for n in expected), "dedicated abstention")
        else:
            check(gold == [expected] and all(t["verdict"] != "abstain" for t in table.values()), "enumerated gold")
        def oracle(s):
            t = table[frozenset(s)]
            return Verdict(t["verdict"], "", evidence={"cassette_miss": t["cassette_miss"]})
        budgets = {}
        for cap in CAPS:
            result = search(candidates, oracle, 0, Budget(max_trials=cap))
            budgets[cap] = {"sets": result.minimal_sets, "complete": result.complete,
                            "forks": len(result.trials), "status": result.status}
        check(budgets[40]["sets"] == art["minimal_sets"] and budgets[40]["forks"] == len(art["trials"]), "policy parity")
        changed = art["known_good_source"]["differing_nodes"]
        conditions.append({"faults": flags, "expected": expected, "original": original, "candidates": candidates,
            "all_changed": [sorted(changed)], "singleton": [sorted(k) for k,v in table.items()
                if len(k)==1 and v["verdict"]=="pass"], "exhaustive": gold, "sherlock": actual,
            "status": art["reason_code"], "unverified": art["unverified_sets"], "forks": list(table.values()),
            "trials": trial_signature(art["trials"]), "budgets": budgets, "latency_s": latency})
    return {"id": record["case_id"], "source": record["source_dataset"], "benchmark": record["benchmark"],
        "cluster": hashlib.sha256(" ".join(q.casefold().split()).encode()).hexdigest(), "controls": controls,
        "conditions": conditions, "issues": issues}


def run_one(record):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tape.db"
        shutil.copyfile(DATA / record["recording"], path)
        return evaluate_case(record, path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes():
    return {str(p.relative_to(DATA)): digest(p) for p in sorted(DATA.rglob("*")) if p.is_file()
            and not p.name.endswith(("-wal","-shm"))}


def deny_network(event, args):
    if event in ("socket.connect", "socket.getaddrinfo"):
        raise RuntimeError("unexpected network access: " + event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    sys.addaudithook(deny_network)
    started = time.monotonic()
    inputs = hashes()
    rows = [json.loads(line) for f in ["cases", "abstain"] for line in
            (DATA / f"data/{f}.jsonl").read_text().splitlines()]
    assert len(rows) == 186 and len({r["recording"] for r in rows}) == 186
    if args.smoke:
        for r in [rows[0], rows[-1]]:
            out = run_one(r)
            print(out["id"], out["issues"])
            assert not out["issues"]
        return
    results = [run_one(r) for r in rows]
    def deterministic(row):
        return row | {"conditions": [{k:v for k,v in c.items() if k != "latency_s"} for c in row["conditions"]]}
    with ProcessPoolExecutor(max_workers=6) as pool:
        for first, second in zip(results, pool.map(run_one, rows), strict=True):
            if deterministic(first) != deterministic(second):
                first["issues"].append("second pass disagrees")
    assert inputs == hashes()
    (OUT/"inputs.json").write_text(json.dumps(inputs, indent=2)+"\n")
    (OUT/"results.jsonl").write_text("".join(json.dumps(r, separators=(",",":"))+"\n" for r in results))
    issues = {r["id"]:r["issues"] for r in results if r["issues"]}
    (OUT/"failures.json").write_text(json.dumps(issues, indent=2)+"\n")
    def command(*args):
        return subprocess.check_output(args, cwd=ROOT, text=True).strip()
    cg = Path("/sys/fs/cgroup") / Path("/proc/self/cgroup").read_text().strip().split("::")[-1].lstrip("/")
    manifest = {"cgroup_limits": {name:(cg/name).read_text().strip() for name in ("cpu.max","memory.max","cpuset.cpus.effective") if (cg/name).exists()},
        "max_child_peak_rss_KiB": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,"python": sys.version, "sqlite": sqlite3.sqlite_version, "kernel": os.uname().release,
        "os": Path("/etc/os-release").read_text(), "lscpu": command("lscpu"), "affinity": sorted(os.sched_getaffinity(0)),
        "mem_total": Path("/proc/meminfo").read_text().splitlines()[0], "workers": [1,6],
        "total_wall_s": time.monotonic()-started, "serial_driver_peak_rss_KiB": resource.getrusage(0).ru_maxrss,
        "revision": command("git","rev-parse","HEAD"), "tracked_diff": command("git","diff","HEAD"),
        "script_sha256": digest(Path(__file__)), "protocol_sha256": digest(OUT/"protocol.md"),
        "dep_versions": command(sys.executable,"-m","pip","freeze"), "limits":Path("/proc/self/limits").read_text(),
        "command":"python3 python/sherlock/eval/final_replay.py", "network":"Python audit hook denies socket.connect and DNS"}
    (OUT/"environment.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print("Completed", len(results), "records. Discrepancies:", issues)
    if issues:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
