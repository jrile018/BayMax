#!/usr/bin/env python3
"""CPU-only validator for saved probe JSONL, not a GPU runner or ML classifier."""
import argparse
import json
from pathlib import Path

def validate(path, mode):
    events=[]
    for index,line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():
            continue
        value=json.loads(line)
        if not isinstance(value,dict) or not isinstance(value.get("event"),str):
            raise ValueError(f"line {index}: object/event required")
        if value.get("ml_dispatch_verified") is True:
            raise ValueError(f"line {index}: probe must not self-certify ML")
        events.append(value)
    results=[v for v in events if v["event"]=="result"]
    if len(results)!=1 or events[-1] is not results[0]:
        raise ValueError("one final result event required")
    result=results[0]
    if result.get("context_provider_verified") is not True:
        raise ValueError("context identity not verified")
    if result.get("dispatch_readback_completed") is not (mode=="dispatch"):
        raise ValueError("result mode/dispatch mismatch")
    providers={v["id"]:v["name_bytes"] for v in events if v["event"]=="provider"}
    context=[v for v in events if v["event"]=="context_provider"]
    if len(context)!=1 or not context[0].get("selected_id_matches") or context[0]["id"] not in providers:
        raise ValueError("context provider was not enumerated and retained")
    dispatches=[v for v in events if v["event"]=="api" and v.get("api")=="ffxDispatch synthetic upscale"]
    readbacks=[v for v in events if v["event"]=="dispatch_readback"]
    if mode=="query-only" and (dispatches or readbacks):
        raise ValueError("query-only contains dispatch evidence")
    if mode=="dispatch":
        if not 1<=len(dispatches)<=8 or len(dispatches)!=len(readbacks):
            raise ValueError("bounded complete dispatch/readback pairs required")
        if any(v.get("ffx_code")!=0 for v in dispatches):
            raise ValueError("failed dispatch")
        for index,value in enumerate(readbacks):
            if value["frame"]!=index or value["changed_components"]!=96*96*4 or value["finite_components"]!=96*96*4:
                raise ValueError("incomplete or nonfinite readback")
    return {"context_provider_verified":True,"dispatch_frames":len(readbacks),"ml_dispatch_verified":False}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--mode",required=True,choices=["query-only","dispatch"])
    args=parser.parse_args()
    print(json.dumps(validate(args.path,args.mode),sort_keys=True))
