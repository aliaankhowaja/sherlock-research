"""Run the locked LangGraph dev server against isolated copies of the final replay corpus."""
import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import json
import os
import resource
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from final_replay import CAPS, DATA, OUT, TEAM, hashes, subsets, trial_signature
from replay_corpus import Client, Checks, Budget, Cassette, Server, _new_lab, _run, diagnose, run_g3


def run_record(record, reference, work, asgi=False):
    _new_lab(work)
    shutil.copyfile(TEAM, work / "bench_solver.py")
    path = work / ".sherlock/cassette.db"
    path.parent.mkdir(exist_ok=True)
    shutil.copyfile(DATA / record["recording"], path)
    tape = Cassette(path)
    calls = [c for c in tape.calls() if c["complete"] and c["name"].endswith("/chat/completions")]
    name = calls[0]["name"]
    base = name.removeprefix("POST ").removesuffix("/chat/completions")
    request = json.loads(calls[0]["request"])
    os.environ.update(BENCH_URL=base, BENCH_MODEL=request["model"],
                      BENCH_EXTRA=json.dumps({k:v for k,v in request.items() if k not in ("model","messages")}))
    checks = Checks([{"type":"equals","value":record["answer"]}],"final_output",work,path)
    if asgi:
        from replay_asgi import ReplayAPI
        client = server = ReplayAPI(work, tape)
    else:
        server = Server(work,replay=True,cassette=path,stub_port=urlsplit(base).port,log=work/"server.log")
        client = Client(server.url)
    errors = []
    def check(ok, label):
        if not ok:
            errors.append(label)
    def replay(flags):
        tape.start_trial()
        return _run(client, record["question"], flags, live=False)
    try:
        good, clean = replay([])
        check(clean.get("final_output")==record["clean_final_output"]==record["answer"], "clean output")
        if "preregistered" in record:
            check(clean.get("reply")==record["reply"], "clean reply")
        bias_output = replay(["bias.flag"])[1].get("final_output")
        check(bias_output==record["answer"], "bias control")
        # Disable just the recorded model requests, then restore the working DB before diagnosis.
        ids = [(c["id"],) for c in calls]
        with sqlite3.connect(path) as db:
            db.executemany("update calls set complete=0 where id=?",ids)
        before = len(tape.abstains())
        try:
            _, withheld = replay([])
            withheld_misses = len(tape.abstains()) - before
            check("final_output" not in withheld and withheld_misses==1,"withheld request")
        finally:
            with sqlite3.connect(path) as db:
                db.executemany("update calls set complete=1 where id=?",ids)
        restored_output = replay([])[1].get("final_output")
        check(restored_output==record["answer"],"restored tape")
        conditions = []
        for ref in reference["conditions"]:
            flags = ref["faults"]
            bad, values = replay(flags)
            check(values.get("final_output")==ref["forks"][0]["output"],f"{flags} failed output")
            budgets = {}
            for cap in CAPS:
                started = time.perf_counter()
                art = diagnose(client,bad,None,checks,path,Budget(max_trials=cap),good_runs=[good])
                elapsed = time.perf_counter()-started
                result = dict(sets=art["minimal_sets"],complete=art["complete"],status=art["status"],
                              forks=len(art["trials"]))
                check(result==ref["budgets"][str(cap)],f"{flags} budget {cap}")
                budgets[cap] = dict(result,elapsed_s=elapsed, trials=trial_signature(art["trials"]))
            check(trial_signature(art["trials"])==[tuple(t) for t in ref["trials"]],f"{flags} default trials")
            check(art["reason_code"]==ref["status"] and art["unverified_sets"]==ref["unverified"],f"{flags} verdict")
            changed_nodes = sorted(art["known_good_source"]["differing_nodes"])
            check([changed_nodes]==ref["all_changed"],f"{flags} changed writes")
            patches = art["known_good_source"]["context_diff"]
            measured = {}
            for subset in subsets(list(patches)):
                verdict = run_g3(client,bad,list(subset),patches,checks,path,{"faults":flags})
                output = None
                if verdict.verdict in ("pass","fail"):
                    hist = client.request("POST",f"/threads/{verdict.fork_thread}/history",{"limit":1})
                    output = hist[0]["values"].get("final_output")
                key = tuple(sorted(subset))
                measured[key] = (verdict.verdict,output,bool(verdict.evidence.get("cassette_miss")))
            check(measured=={tuple(t["restored"]):(t["verdict"],t["output"],t["cassette_miss"])
                             for t in ref["forks"] if t["restored"]}, f"{flags} exhaustive forks")
            conditions.append(dict(faults=flags,budgets=budgets, changed_nodes=changed_nodes, failed_output=values.get("final_output"),
                                   reason_code=art["reason_code"], unverified=art["unverified_sets"], forks=[(k,v) for k,v in measured.items()]))
        check(not (work/"net_attempts.txt").exists(),"socket trap")
        result = dict(id=record["case_id"], conditions=conditions, errors=errors,
                      controls=dict(clean=clean["final_output"],bias_only=bias_output,
                                    withheld_misses=withheld_misses,restored=restored_output))
        if asgi:
            result["replay_hits"] = server.runtime.hits
            result["replay_misses"] = server.runtime.lookups - server.runtime.hits
            result["worker_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            check(result["replay_misses"] == withheld_misses + sum(
                t[2] for c in conditions for b in c["budgets"].values() for t in b["trials"]
            ) + sum(v[2] for c in conditions for k,v in c["forks"]), "unexpected tape misses")
        return result
    finally:
        server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True,help="new JSONL output path")
    parser.add_argument("--smoke",action="store_true")
    parser.add_argument("--asgi",action="store_true",help="use installed server application without a TCP listener")
    parser.add_argument("--workers",type=int,default=1)
    parser.add_argument("--case",help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.out = args.out.resolve()
    inputs = hashes()
    assert inputs==json.loads((OUT/"inputs.json").read_text())
    refs = {r["id"]:r for r in map(json.loads,(OUT/"results.jsonl").read_text().splitlines())}
    rows = [json.loads(line) for f in ("cases","abstain") for line in (DATA/f"data/{f}.jsonl").read_text().splitlines()]
    if args.case:
        rows = [r for r in rows if r["case_id"]==args.case]
        assert len(rows)==1
    if args.smoke:
        rows = [rows[0], rows[-1]]
    args.out.parent.mkdir(parents=True,exist_ok=True)
    issues = 0
    if args.asgi and not args.case:
        def worker(r):
            out_file = args.out.parent / (args.out.name+"."+r["case_id"]+".part")
            cmd = [sys.executable, __file__, "--asgi","--case",r["case_id"],"--out",str(out_file)]
            with tempfile.TemporaryFile() as log:
                process = subprocess.run(cmd,stdout=log,stderr=log)
                if out_file.is_file():
                    data = json.loads(out_file.read_text())
                    out_file.unlink()
                    return data
                log.seek(0,2)
                log.seek(max(0,log.tell()-3000))
                return dict(id=r["case_id"],errors=[f"worker exit {process.returncode}",log.read().decode(errors="replace")])
        with args.out.open("x") as out, ThreadPoolExecutor(max_workers=args.workers) as pool:
            for result in pool.map(worker,rows):
                issues += bool(result["errors"])
                out.write(json.dumps(result)+"\n")
                out.flush()
        assert hashes()==inputs
        raise SystemExit(int(issues>0))
    with args.out.open("x") as out:
        for r in rows:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)/"lab"
                try:
                    result = run_record(r, refs[r["case_id"]], work,args.asgi)
                except Exception as e:
                    log = work/"server.log"
                    result = dict(id=r["case_id"],errors=[repr(e)],server_log=log.read_text()[-4000:] if log.exists() else "")
                issues += bool(result["errors"])
                out.write(json.dumps(result)+"\n")
                out.flush()
            if args.smoke and issues:
                break
    assert hashes()==inputs
    raise SystemExit(int(issues>0))

if __name__=="__main__":
    main()
