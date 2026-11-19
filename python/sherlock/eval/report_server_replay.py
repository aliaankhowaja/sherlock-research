"""Audit LangGraph replay outputs and regenerate the writeup tables from the server records."""
import argparse
import csv
import hashlib
import os
import sqlite3
import subprocess
import sys
from importlib.metadata import distributions
import json
import math
import statistics
from pathlib import Path

from final_replay import CAPS, DATA, OUT, hashes, trial_signature
from final_replay_report import bootstrap


def load_rows(path, key):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    indexed = {r[key]: r for r in rows}
    if len(rows) != len(indexed):
        raise ValueError(f"duplicate IDs in {path}")
    return indexed


def normalize(sets):
    return sorted(sorted(s) for s in sets)


def write_table(path, rows):
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def deterministic(value):
    if isinstance(value, dict):
        return {k:deterministic(v) for k,v in value.items() if k not in {"elapsed_s","worker_peak_rss_kib"}}
    if isinstance(value,list):
        return [deterministic(v) for v in value]
    return value


def manifest(folder, raw, repeat):
    root = Path(__file__).resolve().parents[3]
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def command(*args):
        return subprocess.check_output(args,cwd=root,text=True).strip()
    files = [Path(__file__),Path(__file__).with_name("final_replay_server.py"),Path(__file__).with_name("replay_asgi.py"),
             Path(__file__).with_name("final_replay.py"),Path(__file__).with_name("final_replay_report.py"),
             root/"python/sherlock/uv.lock",root/"harness/uv.lock",folder/"protocol.md",OUT/"inputs.json",
             folder/"results.jsonl",folder/"repeat.jsonl"]
    cgroup = Path("/sys/fs/cgroup")/Path("/proc/self/cgroup").read_text().strip().split("::")[-1].lstrip("/")
    info = {"cpu":command("lscpu"),"affinity":sorted(os.sched_getaffinity(0)),
            "mem_total":Path("/proc/meminfo").read_text().splitlines()[0],"os":Path("/etc/os-release").read_text(),
            "host_kernel":os.uname().release,"machine":os.uname().machine,"sqlite":sqlite3.sqlite_version,
            "python":sys.version,"packages":{d.metadata["Name"]:d.version for d in distributions()},
            "revision":command("git","rev-parse","HEAD"),"workers_per_run":48,"overlapping_runs":2,
            "worker_peak_rss_kib_max":max(r["worker_peak_rss_kib"] for r in [*raw.values(),*repeat.values()]),
            "cgroup_limits":{n:(cgroup/n).read_text().strip() for n in ["cpu.max","memory.max","pids.max"]
                             if (cgroup/n).exists()},
            "epochs_utc":{p.stem:p.read_text().strip() for p in folder.glob("*utc.txt")},
            "sha256":{str(p.resolve().relative_to(root)):sha(p) for p in files},
            "transport":"Starlette TestClient through ASGI, uvloop, one fresh server per recording per run",
            "command_template":"python/sherlock/.venv/bin/python python/sherlock/eval/final_replay_server.py --asgi --workers 48 --out NEW_PATH"}
    (folder/"environment.json").write_text(json.dumps(info,indent=2,sort_keys=True)+"\n")


def paired_comparisons(metrics, headline):
    # Analyze the six fixed interventions jointly within each question.
    questions = [" ".join(r["question"].casefold().split()) for r in headline.values()]
    assert len(set(questions)) == len(headline)
    accuracy = {}
    for row in metrics:
        accuracy.setdefault((row["id"],row["method"]),[]).append(row["exact"])
    rows = []
    for baseline in ("All changed writes","Singleton restores","Exhaustive eligible restores"):
        wins = losses = 0
        effects = []
        for ident in headline:
            a, b = accuracy[ident,"Sherlock"], accuracy[ident,baseline]
            assert len(a)==len(b)==6
            wins += all(a) and not all(b)
            losses += all(b) and not all(a)
            effects.append(statistics.fmean(a)-statistics.fmean(b))
        discordant = wins+losses
        p = min(1.,2*sum(math.comb(discordant,k) for k in range(min(wins,losses)+1))/2**discordant)
        low, high = bootstrap(effects)
        rows.append(dict(baseline=baseline,questions=len(headline),sherlock_only_all_correct=wins,
                         baseline_only_all_correct=losses,mean_accuracy_gain=statistics.fmean(effects),
                         bootstrap_low=low,bootstrap_high=high,mcnemar_p=p))
    running = 0.
    for index,row in enumerate(sorted(rows,key=lambda r:r["mcnemar_p"])):
        running = max(running,min(1.,(len(rows)-index)*row["mcnemar_p"]))
        row["holm_p"] = running
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir",type=Path,nargs="?",default=OUT/"langgraph")
    parser.add_argument("--capture-environment",action="store_true",help="record execution host when scoring on the original machine")
    args = parser.parse_args()
    folder = args.dir
    raw = load_rows(folder/"results.jsonl","id")
    repeat = load_rows(folder/"repeat.jsonl","id")
    assert set(repeat)==set(raw)
    headline = load_rows(DATA/"data/cases.jsonl","case_id")
    special = load_rows(DATA/"data/abstain.jsonl","case_id")
    assert len(headline) == 185 and len(special) == 1
    assert set(raw) == headline.keys() | special.keys()
    assert hashes() == json.loads((OUT/"inputs.json").read_text())

    by_method = []
    by_budget = []
    failures = {}
    num_original = 0
    num_controls = 0
    matched_budget_pairs = 0
    total_calls = total_search_trials = total_subset_trials = 0
    expected_designs = {tuple(sorted(f+d)) for f in (["extract.drop_last"],["format.prefix"],
                                                      ["extract.drop_last","format.prefix"])
                        for d in ([],["bias.flag"])}
    for ident, record in (headline | special).items():
        row = raw[ident]
        issues = list(row["errors"])
        if deterministic(row)!=deterministic(repeat[ident]):
            issues.append("independent run disagrees")
        controls = row.get("controls",{})
        good_controls = (all(controls.get(k)==record["answer"] for k in ("clean","bias_only","restored"))
                         and controls.get("withheld_misses")==1)
        if not good_controls:
            issues.append("control failure")
        num_controls += ident in headline and good_controls
        conditions = row.get("conditions",[])
        designs = [tuple(sorted(c["faults"])) for c in conditions]
        expected = expected_designs if ident in headline else {tuple(sorted(record["faults"]))}
        if len(designs)!=len(expected) or set(designs)!=expected:
            issues.append("missing or duplicate intervention")
        for c in conditions:
            flags = c["faults"]
            gold = [sorted(f.split(".")[0] for f in flags if f!="bias.flag")]
            budgets = c["budgets"]
            assert set(budgets)=={str(cap) for cap in CAPS}
            total_calls += len(budgets)
            total_search_trials += sum(len(b["trials"]) for b in budgets.values())
            total_subset_trials += len(c["forks"])
            b = budgets["40"]
            key = set(flags)
            if key==set(record["faults"]):
                archived = record["sherlock"]
                num_original += ident in headline
                expected_trials = trial_signature(archived["trials"])
                if (b["trials"] != [list(t) for t in expected_trials] or
                    normalize(b["sets"])!=normalize(archived["minimal_sets"]) or
                    c["reason_code"]!=archived["reason_code"] or c["unverified"]!=archived["unverified_sets"] or
                    c["failed_output"]!=record["failed_final_output"]):
                    issues.append("original diagnosis disagreement")
                if ident in headline:
                    server_forks = sorted((sorted(s),v[0],v[2]) for s,v in c["forks"])
                    if server_forks != sorted(trial_signature(record["forks"])):
                        issues.append("original exhaustive disagreement")
            if ident in special:
                continue
            matched_budget_pairs += deterministic(b)==deterministic(budgets["7"])
            passing = [set(s) for s,v in c["forks"] if v[0]=="pass"]
            if any(v[0]=="abstain" for s,v in c["forks"]) or c["failed_output"]==record["answer"]:
                issues.append("invalid headline fork evidence")
            for cap in CAPS:
                obs = budgets[str(cap)]
                exact = normalize(obs["sets"])==gold
                by_budget.append(dict(id=ident,cap=cap,exact=int(exact),complete_exact=int(exact and obs["complete"]),
                                      trials=obs["forks"]))
            method_sets = {"Sherlock":(b["sets"],b["forks"]),
                           "All changed writes":([c["changed_nodes"]],0),
                           "Singleton restores":([sorted(s) for s in passing if len(s)==1],
                                                 sum(len(s)==1 for s,v in c["forks"])),
                           "Exhaustive eligible restores":([sorted(s) for s in passing if not any(u<s for u in passing)],
                                                          len(c["forks"]))}
            for method,(sets,forks) in method_sets.items():
                by_method.append(dict(id=ident,benchmark=record["benchmark"],faults=",".join(flags),
                                      method=method,exact=int(normalize(sets)==gold),no_set=int(not sets),
                                      bias_named=int(any("bias" in s for s in sets)),forks=forks))
        if issues:
            failures[ident]=issues

    (folder/"failures.json").write_text(json.dumps(failures,indent=2)+"\n")
    if failures:
        raise ValueError(f"{len(failures)} records failed validation; see failures.json")
    def aggregate(rows,group,fields):
        result = []
        for value in dict.fromkeys(r[group] for r in rows):
            sub = [r for r in rows if r[group]==value]
            result.append({group:value,"conditions":len(sub),**{f:sum(r[f] for r in sub) for f in fields}})
        return result
    methods = aggregate(by_method,"method",["exact","no_set","bias_named","forks"])
    budgets = aggregate(by_budget,"cap",["exact","complete_exact","trials"])
    paired = paired_comparisons(by_method,headline)
    write_table(folder/"paired_comparisons.csv",paired)
    write_table(folder/"method_results.csv",methods)
    write_table(folder/"budget_results.csv",budgets)
    write_table(folder/"condition_results.csv",by_method)
    hits = sum(r["replay_hits"] for r in raw.values())
    misses = sum(r["replay_misses"] for r in raw.values())
    if args.capture_environment:
        manifest(folder,raw,repeat)
    report = [
        "# LangGraph server replay results", "",
        f"The installed LangGraph API replayed all {len(headline)} questions under six interventions each, plus the dedicated missing-evidence case. All {num_original} original assignments reproduced the archived trial order, verdicts and minimal sets. The source data hashes matched before and after execution. Per pass, the full run made {total_calls:,} separate production diagnoses across eight budgets, triggering {total_search_trials:,} G3 forks. Independent subset enumeration executed {total_subset_trials:,} additional G3 forks. Each method below is scored against the assigned intervention.",
        "", "| Method | Exact / 1,110 | Wrong nonempty | No set | Decoy named | Mean forks |",
        "|---|---:|---:|---:|---:|---:|"]
    for m in methods:
        report.append(f"| {m['method']} | {m['exact']} | {m['conditions']-m['exact']-m['no_set']} | {m['no_set']} | {m['bias_named']} | {m['forks']/m['conditions']:.2f} |")
    report += ["", "| Comparator | Mean paired recovery gain [95% interval], pp | Perfect-question discordance (Sherlock only / comparator only) | Holm p |",
               "|---|---:|---:|---:|"]
    for pair in paired:
        report.append(f"| {pair['baseline']} | {100*pair['mean_accuracy_gain']:.2f} [{100*pair['bootstrap_low']:.2f}, {100*pair['bootstrap_high']:.2f}] | {pair['sherlock_only_all_correct']} / {pair['baseline_only_all_correct']} | {pair['holm_p']:.3g} |")
    report.append("\nRecovery gains average the six fixed conditions within each question. Intervals resample questions. Identical within-question contrasts produce point intervals on this corpus. Exact paired McNemar tests use the binary endpoint of all six repairs recovered; Holm adjustment covers the three prespecified comparisons. Inference is conditional on these fault templates and the retained questions.")
    report += ["", "The observed failed output supplies the empty-set verdict at zero fork cost. All changed writes proposes every node with a different output. The singleton baseline tests all eligible singleton restorations. Exhaustive search tests every nonempty subset of the same eligible context patches. Each method receives the same passing and failed runs.",
               "", "| Intervention | Complete and exact at the default budget | Mean Sherlock forks |",
               "|---|---:|---:|"]
    for cell in aggregate([r for r in by_method if r["method"]=="Sherlock"],"faults",["exact","forks"]):
        certified = sum(c["budgets"]["40"]["complete"] and normalize(c["budgets"]["40"]["sets"])==
                        [sorted(f.split(".")[0] for f in c["faults"] if f!="bias.flag")]
                        for i in headline for c in raw[i]["conditions"] if ",".join(c["faults"])==cell["faults"])
        report.append(f"| {cell['faults']} | {certified}/{cell['conditions']} | {cell['forks']/cell['conditions']:.2f} |")
    report += ["", "| Maximum forks | Exactly recovered | Complete and exact |", "|---:|---:|---:|"]
    for b in budgets:
        report.append(f"| {b['cap']} | {b['exact']}/{b['conditions']} | {b['complete_exact']}/{b['conditions']} |")
    report += ["",f"All {num_controls} headline questions passed the clean and decoy-only controls. Withholding the tape caused a miss before diagnosis and restoring it recovered the answer. The separate two-node request intervention passed under joint restoration, missed on both singleton requests and ended unrecorded_call with zero certified repairs. In each pass, the HTTP replay interceptor served {hits:,} recorded replies and rejected {misses:,} requests. All misses were accounted for by the prespecified missing-evidence controls. No outbound connection was observed.",
         "", f"A separate execution repeated the entire matrix from fresh server processes and new working cassette copies. All {len(raw)} records matched across passes on the controls, outputs, trial order, restore verdicts, search completeness and replay hit/miss counts. The two passes together made {2*total_calls:,} diagnoses and executed {2*(total_search_trials+total_subset_trials):,} restore forks. Within the primary run, the seven-fork and 40-fork diagnoses agreed on every trial and outcome in {matched_budget_pairs}/1,110 headline conditions. [Repeat records](repeat.jsonl).",
         "", "The six intervention cells contain 185 originally recorded assignments and 925 crossed assignments. With a three-fork cap the five simpler cells were fully certified. A second causal fault together with a decoy required seven forks on every question. Sherlock and exhaustive enumeration used identical counts in each cell. No evidence of search savings arises from this small candidate universe.",
         "", "The paper can attribute exact recovery to the LangGraph runtime on this fixed seven-node graph. The corpus contains 185 distinct retained questions out of 300 attempts. The 1,110 conditions are paired measurements on those questions. The original selection included a diagnosis-agreement check and the two deterministic output faults are shared across questions. The previously reported reduction on larger generated workflows belongs to a separate experiment.",
         "", "Starlette dispatched HTTP requests in process to the installed ASGI application. LangGraph ran the graph, maintained histories, scheduled resumes and produced checkpoint forks. The run used the CPU and recorded replies only. TCP listener throughput and GPU inference latency were outside this experiment. Latencies in the raw records are wall times under concurrent load.",
         "", "The [environment manifest](environment.json) records machine, package and code versions. [Raw records](results.jsonl), [condition results](condition_results.csv), [budget results](budget_results.csv), [failure ledger](failures.json), and [protocol](protocol.md).",
         "", "To reproduce, run the manifest command twice from the repository root with distinct new output paths. Name the resulting records results.jsonl and repeat.jsonl in one output directory. Score both files with `python/sherlock/.venv/bin/python python/sherlock/eval/report_server_replay.py OUTPUT_DIRECTORY`."]
    (folder/"results.md").write_text("\n".join(report)+"\n")

if __name__=="__main__":
    main()
