"""Score primary and independent repeat directories into a results directory."""
from collections import defaultdict
import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import platform
import random
from pathlib import Path
from statistics import fmean
import sys

ROOT = Path(__file__).resolve().parents[3]
primary, repeat, output = map(Path,sys.argv[1:])
output.mkdir(exist_ok=True,parents=True)


def write_json(name, obj):
    (output/name).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")


def table(name,rows):
    with (output/name).open("w") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def contrast(label, groups):
    values=[x for group in groups.values() for x in group]
    win=sum(x>0 for x in values)
    loss=sum(x<0 for x in values)
    n=win+loss
    p=min(1,2*sum(math.comb(n,i) for i in range(min(win,loss)+1))/2**n)
    rng=random.Random(185)
    boot=sorted(sum(sum(rng.choices(group,k=len(group))) for group in groups.values())/len(values)
                for _ in range(10000))
    return dict(contrast=label,mean=fmean(values),low=boot[249],high=boot[9749],
                win=win,tie=len(values)-n,loss=loss,p=p)


def normalize(sets):
    return {frozenset(s) for s in sets}


archive=json.loads((ROOT/"docs/eval/results.json").read_text())["cases"]
planted=[]
for i in range(89):
    data=(primary/f"{i}.json").read_bytes()
    assert data==(repeat/f"{i}.json").read_bytes(),i
    planted.append(json.loads(data))
(output/"planted.jsonl").write_text("".join(json.dumps(r,separators=(",",":"))+"\n" for r in planted))
assert all(r["control"]=="already_passes" for r in planted[86:])
gates=defaultdict(list)
verification=[]
g2_gain=defaultdict(list)
wrong_gain=defaultdict(list)
for row, ref in zip(planted,archive):
    assert row["id"]==ref["id"]
    gold=normalize(row["gold"])
    slices=["all",row["team"]]
    slices.append("singleton" if all(len(s)==1 for s in gold) else "joint")
    if "silent_decoy" in row["tags"]: slices.append("decoy")
    if ref["expect_abstain"]: slices.append("missing")
    proposal=normalize([[row["proposal"]]])
    wrong=proposal!=gold
    verified=row["verification"]=="pass"
    wrong_gain[row["team"]].append(int(wrong and not verified))
    for group in slices:
        verification.append(dict(group=group,raw_exact=int(not wrong),raw_wrong=int(wrong),
                                 verified_exact=int(verified and not wrong),verified_wrong=int(verified and wrong),
                                 abstain=int(not verified)))
    values={}
    for r in row["runs"]:
        sets=normalize(r["sets"])
        exact=int(bool(sets) and sets==gold)
        complete=int(exact and r["complete"])
        if (r["g0"],r["g2"],r["cap"])==(1,1,40):
            assert r["reason"]==ref["sherlock"]["reason_code"] and len(r["trials"])==ref["sherlock"]["trials_used"]
            assert sets==normalize(ref["methods"]["sherlock"]["prediction"].get("sets",[]))
        if r["g0"] and r["cap"]==10: values[r["g2"]]=complete
        for group in slices:
            gates[group,r["g0"],r["g2"],r["cap"]].append(dict(exact=exact,wrong=int(bool(sets) and not exact),
                abstain=int(not sets),complete_exact=complete,queries=len(r["trials"]),
                retains_gold=int(all(s<=set(r["order"]) for s in gold))))
    g2_gain[row["team"]].append(values[1]-values[0])
table("gates.csv",[dict(group=k[0],g0=k[1],g2=k[2],cap=k[3],n=len(v),
                        **{m:sum(r[m] for r in v) for m in v[0]}) for k,v in gates.items()])
table("verification.csv",[dict(group=g,n=len(v),**{m:sum(r[m] for r in v) for m in v[0] if m!="group"})
    for g in dict.fromkeys(r["group"] for r in verification) for v in [[r for r in verification if r["group"]==g]]])
table("team_sensitivity.csv",[dict(team=t,contrast=label,within=fmean(groups[t]),
    omit_team=fmean(x for other,v in groups.items() if other!=t for x in v))
    for label,groups in [("G2",g2_gain),("verification",wrong_gain)] for t in groups])

hosted=json.loads((ROOT/"docs/eval/pipeline_g1/pipeline_g1.json").read_text())
lookup={r["id"]:r for r in planted}
g1=[]
for case in hosted["cases"]:
    order=case["candidate_list"]
    current=lookup[case["id"]]
    assert order==current["runs"][0]["order"]
    off=case["variants"]["off"]["passes"][0]
    for name in ("small","big","full"):
        v=case["variants"][name]
        scores=v["g1"]["per_pass_scores"]
        changed=missing=0
        for batch in scores:
            if len(order)<2: continue
            missing+=sum(batch.get(n) is None for n in order)
            effective=sorted(order,key=lambda n:(-current["weights"][n],batch.get(n) is None,-(batch.get(n) or 0),n))
            changed+=effective!=order
        g1.append(dict(id=case["id"],variant=name,eligible=int(len(order)>=2),passes=len(scores),
                       changed=changed,missing_scores=missing,delta_queries=fmean(p["trials_used"] for p in v["passes"])-off["trials_used"],
                       delta_exact=fmean(p["outcome"]=="exact" for p in v["passes"])-(off["outcome"]=="exact")))
table("hosted.csv",g1)

data=gzip.decompress((primary/"matrix.gz").read_bytes())
assert data==gzip.decompress((repeat/"matrix.gz").read_bytes())
(output/"search.jsonl.gz").write_bytes(gzip.compress(data,mtime=0))
cost=defaultdict(dict)
summary=defaultdict(list)
failures=[]
for line in data.splitlines():
    r=json.loads(line)
    family=r["id"].split(":")[0]
    if family=="g1gen" and r["cap"]=="full":
        cost[r["id"],r["perm"]][r["method"]]=len(r["trace"])
    if r["perm"]!=-1: continue
    gap=r["sets"]!=r["gold"]
    if r["false_complete"] or r["unsupported"] or (r["cap"]=="full" and gap):
        failures.append({k:r[k] for k in ("id","method","missing","cap","sets","gold","complete","false_complete","unsupported")})
    for size in ("all",str(r["n"])):
        key=family,size,r["missing"] is not None,r["method"],r["cap"]
        summary[key].append(dict(queries=len(r["trace"]),complete_exact=int(r["complete"] and not gap),
            exact=int(not gap),false_complete=int(r["false_complete"]),unsupported=int(bool(r["unsupported"])),
            first=r["first"]))
table("search.csv",[dict(family=k[0],size=k[1],withheld=k[2],method=k[3],cap=k[4],n=len(v),
     mean_queries=fmean(r["queries"] for r in v),first_verified=sum(r["first"] is not None for r in v),
     mean_first_given_verified=fmean(r["first"] for r in v if r["first"] is not None) if any(r["first"] for r in v) else "",
     **{m:sum(r[m] for r in v) for m in ("exact","complete_exact","false_complete","unsupported")}) for k,v in summary.items()])
by_id=defaultdict(list)
for (cid,perm),v in cost.items(): by_id[cid].append(v["enum"]-v["dual"])
assert len(by_id)==100 and all(len(v)==11 for v in by_id.values())
diff={k:fmean(v) for k,v in by_id.items()}
sizes={r["id"]:len(r["candidates"]) for r in map(json.loads,(ROOT/"docs/eval/search_efficiency/cases.jsonl").read_text().splitlines())}
cs=[contrast("G2 complete exact",g2_gain),contrast("wrong proposals prevented",wrong_gain),
    contrast("enumeration minus duality queries",{"workflows":list(diff.values())})]
previous=0
for i,r in enumerate(sorted(cs,key=lambda r:r["p"])):
    previous=max(previous,min(1,(3-i)*r["p"]))
    r["holm_p"]=previous
table("primary.csv",cs)
table("size_effect.csv",[contrast(group,{"workflows":[d for k,d in diff.items() if (sizes[k]>6)==large]})
                         for group,large in [("1-6",False),("7+",True)]])
write_json("failures.json",failures)
files=["docs/eval/results.json","docs/eval/pipeline_g1/pipeline_g1.json","docs/eval/search_efficiency/cases.jsonl",
       "docs/eval/g1_gen/g1_results.json","docs/eval/final_ablations/protocol.md",
       "python/sherlock/uv.lock","harness/uv.lock"]
for folder in ("python/sherlock/eval","python/sherlock/src/sherlock","harness/sherlock_harness"):
    files.extend(str(p.relative_to(ROOT)) for p in sorted((ROOT/folder).rglob("*.py")))
write_json("manifest.json",dict(python=sys.version,platform=platform.platform(),
    packages={k:importlib.metadata.version(k) for k in ("langgraph","langgraph-api","httpx","starlette")},
    input_hashes={p:digest((ROOT/p).read_bytes()) for p in files},
    repeated_planted_records=len(planted),repeated_search_rows=len(data.splitlines()),
    search_sha256=digest(data),planted_sha256=digest((output/"planted.jsonl").read_bytes())))
