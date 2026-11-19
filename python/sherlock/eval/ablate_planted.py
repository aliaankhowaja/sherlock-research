"""Run paired gate interventions on fresh LangGraph ASGI threads."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx
from run_eval import TEAMS, Checks, Budget, diagnose, ROOT, HARMLESS, Case, HARNESS
from replay_asgi import ReplayAPI
from sherlock.cassette import Cassette
from sherlock.g3 import apply_restore, run_g3

engine = importlib.import_module("sherlock.diagnose")
ARCHIVE = json.loads((ROOT / "docs/eval/results.json").read_text())["cases"]
CASES = [Case(**{k:r[k] for k in ("team","faults","split","gold","tags","expect_abstain")}) for r in ARCHIVE] + [Case(t, f, "probe") for t, f in HARMLESS]


def echo(_transport, request):
    assert str(request.url) == "http://stub/v1/chat/completions"
    message = json.loads(request.content)["messages"][-1]["content"]
    body = json.dumps({"choices": [{"message": {"content": f"echo: {message}"}}]}).encode()
    return httpx.Response(200, stream=httpx.ByteStream(body), headers={"content-type":"application/json"})


def experiment(case, work):
    os.environ["STUB_URL"] = "http://stub"
    team = TEAMS[case.team]
    path = work / "cassette.db"
    tape = Cassette(path)
    graph = HARNESS / "sherlock_harness/teams" / (case.team + ".py")
    httpx.HTTPTransport.handle_request = echo
    server = ReplayAPI(work, tape, {case.team: str(graph) + ":graph"})
    server.runtime.mode = "record"

    def run(flags):
        tid = server.request("POST", "/threads", {"metadata": {"assistant_id": case.team}})["thread_id"]
        output = server.request("POST", f"/threads/{tid}/runs/wait", dict(
            assistant_id=case.team, input=team.input, context={"faults": flags}, durability="sync"))
        assert "final_output" in output or (flags and "__error__" in output), output
        return tid

    good, bad = run([]), run(case.faults)
    server.runtime.mode = "replay"
    checks = Checks(team.check, "final_output", work, path)
    cache = {}
    def fork(client, thread, restore, *args, **kw):
        key = tuple(sorted(restore))
        if key not in cache:
            cache[key] = run_g3(client, thread, restore, *args, **kw)
        return cache[key]

    normal = engine.plan_candidates
    def eligible(history, kg, context, output_key, same, widen):
        result = normal(history, kg, context, output_key, same, widen)
        result.candidates = [n for n in result.on_path if n in kg and apply_restore(context, kg, [n]) != context]
        result.pruned = {n: r for n, r in result.pruned.items() if n not in result.candidates}
        return result

    row = dict(id=case.id, team=case.team, tags=case.tags, gold=case.gold, runs=[])
    for g0, g2 in [(1,1),(0,1),(1,0),(0,0)]:
        with patch.object(engine, "run_g3", fork), patch.object(engine, "plan_candidates", normal if g2 else eligible), patch.object(
            engine, "order_candidates", engine.order_candidates if g0 else lambda nodes,*args: list(nodes)):
            for cap in (40,3,10):
                art = diagnose(server,bad,None,checks,path,Budget(max_trials=cap),good_runs=[good],node_map=team.node_map)
                if case.split == "probe":
                    assert art["reason_code"] == "already_passes"
                    return dict(id=case.id, control=art["reason_code"])
                order = art["pruning"]["candidates"]
                trials = [(t["restored"],t["verdict"]) for t in art["trials"]]
                row["runs"].append(dict(g0=g0,g2=g2,cap=cap,order=order,trials=trials,sets=art["minimal_sets"],
                                        complete=art["complete"],reason=art["reason_code"]))
                if "proposal" not in row and order:
                    node = order[0]
                    row["weights"] = {n: sum(c["weight"] for c in art["clues"] if c["node"] == n) for n in order}
                    verdict = fork(server,bad,[node],art["known_good_source"]["context_diff"],checks,path,art["context"])
                    row.update(proposal=node,verification=verdict.verdict)
    assert not (work/"net_attempts.txt").exists()
    return row


if __name__ == "__main__":
    output = Path(sys.argv[2]).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        result = experiment(CASES[int(sys.argv[1])], Path(tmp))
        output.write_text(json.dumps(result,sort_keys=True)+"\n")
        os.chdir("/")
