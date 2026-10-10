"""Reproducible fictional C1 checkpoint using the real graph, executor and aid ledger."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import median
import subprocess
from time import perf_counter
from .models import Edge, Graph
from .safety import Closure, SafetySnapshot
from .search import candidate_routes, static_reference
from .trip import TripExecutor
from services.planner.ledger import Ledger, Vehicle, Request, Destination

FIXTURE=Path(__file__).resolve().parents[2]/"fixtures/routing/tiny_graph.json"

def exercise_graph():
    data=json.loads(FIXTURE.read_text())
    return Graph(data["nodes"],[Edge(**e,weight_source=data["source"]) for e in data["edges"]],
                 version=data["graph_version"])

def known(graph,version="k0",when=0,closures=()):
    return SafetySnapshot(version,when,when,1000,tuple(closures),
                          provenance="Fictional exercise observations; safe nodes explicitly declared.",
                          safe_nodes=frozenset(graph.nodes))

def evacuation(run_id):
    graph=exercise_graph(); safety=known(graph)
    ledger=Ledger([Vehicle("bus","bus","A",2,0)],
                  [Request("evac","evacuation","A","D",("p1","p2"))],
                  [Destination("shelter","D","shelter",2)],{})
    engine=TripExecutor(graph,ledger,run_id=run_id)
    route=candidate_routes(graph,"A","D","bus",0,safety).routes[0]
    engine.dispatch("dispatch","bus","evac",route,safety,service_s=2)
    return graph,safety,ledger,engine

def frame(label,engine):
    engine.ledger.check_invariants()
    return dict(label=label,snapshot=engine.snapshot())

def conservation(snapshot):
    ledger=snapshot["ledger"]
    people={k:sum(p["location"]==k for p in ledger["person_locations"].values())
            for k in ("origin","in_transit","destination")}
    people["total"]=len(ledger["person_locations"])
    goods={}
    for stock in ledger["stocks"].values():
        for good,qty in stock.items():
            goods.setdefault(good,dict(stock=0,carried=0,delivered=0,total=0))["stock"]+=qty
    for assignment in ledger["assignments"].values():
        if assignment["phase"]!="completed":
            for good,qty in assignment["cargo"].items():
                goods.setdefault(good,dict(stock=0,carried=0,delivered=0,total=0))["carried"]+=qty
    for good,qty in ledger["delivered"].items():
        goods.setdefault(good,dict(stock=0,carried=0,delivered=0,total=0))["delivered"]+=qty
    for entry in goods.values():
        entry["total"]=entry["stock"]+entry["carried"]+entry["delivered"]
    return dict(people=people,goods=goods,invariants_checked=True)

def build_replays():
    graph,safety,ledger,engine=evacuation("c1-reroute")
    frames=[frame("dispatched",engine)]
    engine.advance(5,safety); frames.append(frame("midpoint",engine))
    newer=known(graph,"k1",5,[Closure("bd",5,100,5,5,"B-D closure received",
                                    "fictional road report")])
    result=engine.replan("dispatch",newer,"report-bd","B-D is closed")
    frames.append(frame("rerouted",engine))
    for when,label in ((10,"junction"),(15,"detour_midpoint"),(35,"arrived"),(37,"served")):
        engine.advance(when,newer); frames.append(frame(label,engine))
    # Repeated completion timestamp is an actual no-op.
    engine.advance(37,newer)
    reroute=dict(frames=frames,status=result.status,
                 explanation="At 5s, continue the safe remaining A-B edge for 5s, then take B-C-D. Arrival35s, service37s.",
                 conservation=conservation(engine.snapshot()))

    graph,safety,ledger,engine=evacuation("c1-stranded")
    failed=[frame("dispatched",engine)]
    engine.advance(5,safety); failed.append(frame("midpoint",engine))
    newer=known(graph,"k1",5,[Closure("ab",5,100,5,5,"Current edge closed","fictional road report")])
    engine.replan("dispatch",newer,"report-ab","Cannot safely finish current edge")
    failed.append(frame("stranded",engine))
    engine.advance(25,newer); failed.append(frame("exposed",engine))
    stranded=dict(frames=failed,explanation="Current edge becomes unsafe at the actual midpoint. People remain on the bus; no aid counted.",
                  conservation=conservation(engine.snapshot()))

    graph=exercise_graph(); safety=known(graph)
    ledger=Ledger([Vehicle("bus","bus","A",2,0),Vehicle("ambulance","ambulance","A",1,0),
                   Vehicle("truck","truck","A",0,5)],
      [Request("evac","evacuation","A","D",("p1","p2")),
       Request("medical","medical","A","D",("p3",),deadline_s=30),
       Request("supply","supply","A","D",goods={"water":8})],
      [Destination("shelter","D","shelter",2),Destination("medical","D","medical",1)],
      {"A":{"water":10}})
    engine=TripExecutor(graph,ledger,run_id="c1-actual-aid")
    for vehicle_id,request_id,kind,loading,service,cargo in (
        ("bus","evac","bus",0,2,None),("ambulance","medical","ambulance",1,2,None),
        ("truck","supply","truck",0,3,{"water":5})):
        route=candidate_routes(graph,"A","D",kind,loading,safety).routes[0]
        engine.dispatch("dispatch-"+vehicle_id,vehicle_id,request_id,route,safety,
                        loading_s=loading,service_s=service,cargo=cargo)
    aid_frames=[frame("committed",engine)]
    for when,label in ((1,"departed"),(5,"in_transit"),(20,"bus_arrived"),(21,"medical_arrived"),
                       (22,"evacuation_served"),(23,"medical_served"),(30,"truck_arrived"),
                       (33,"supply_served"),(40,"later_no_double_count")):
        engine.advance(when,safety); aid_frames.append(frame(label,engine))
    aid=dict(frames=aid_frames,explanation="2 evacuated, 1 medical person served on time, 5 water delivered; remaining supply need3, stock5.",
             conservation=conservation(engine.snapshot()))
    return dict(reroute=reroute,stranded=stranded,aid=aid)

def measure_operations(sample_count=100):
    if isinstance(sample_count,bool) or not isinstance(sample_count,int) or sample_count<1:
        raise ValueError("sample_count must be a positive integer")
    graph=exercise_graph(); safety=known(graph)
    samples=dict(route_search=[],mid_edge_replan=[])
    candidate_routes(graph,"A","D","bus",0,safety) # warmup, outside samples
    for index in range(sample_count):
        began=perf_counter()
        candidate_routes(graph,"A","D","bus",0,safety)
        samples["route_search"].append((perf_counter()-began)*1000)
        graph,safety,ledger,engine=evacuation("timing-"+str(index))
        engine.advance(5,safety)
        newer=known(graph,"k1",5,[Closure("bd",5,100,5,5,"closure")])
        began=perf_counter()
        engine.replan("dispatch",newer,"report","closure")
        samples["mid_edge_replan"].append((perf_counter()-began)*1000)
    return {kind:dict(sample_count=sample_count,p50_ms=median(values),
                      p95_ms=sorted(values)[ceil(.95*sample_count)-1],
                      samples_ms=values,units="milliseconds")
            for kind,values in samples.items()}

def write_checkpoint(output_dir,sample_count=100):
    output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    data=json.loads(FIXTURE.read_text())
    replays=build_replays()
    graph=exercise_graph(); safety=known(graph)
    reference=static_reference(graph,"A","D","bus",0,safety)
    candidates=candidate_routes(graph,"A","D","bus",0,safety)
    replay=dict(schema="routing-c1-evidence-v1",scenario_id="fictional-tiny",
                source=data["source"],metric_crs="fictional local x/y metres",
                input_graph=data,replays=replays,
                limitations=["Hand-authored fictional graph/hazard intervals; no sourced mission integration.",
                             "Bounded simple paths; no waiting, retreat, or arbitrary time-dependent optimality claim.",
                             "TripExecutor is simulated authority; no live GPS or real vehicle telemetry."],
                reference=reference.to_dict(),candidate_status=candidates.status,
                candidate_routes=[r.to_dict() for r in candidates.routes])
    (output/"c1-replay.json").write_text(json.dumps(replay,indent=2,sort_keys=True)+"\n")
    timing=measure_operations(sample_count)
    (output/"c1-timing.json").write_text(json.dumps(timing,indent=2,sort_keys=True)+"\n")
    summary=dict(source=data["source"],replay_file="c1-replay.json",timing_file="c1-timing.json",
                 graph_sha256=sha256(FIXTURE.read_bytes()).hexdigest(),
                 actual_outcomes={k:case["frames"][-1]["snapshot"]["ledger"]["outcome_totals"] for k,case in replays.items()},
                 conservation={k:case["conservation"] for k,case in replays.items()},
                 timing={k:{x:y for x,y in stats.items() if x!="samples_ms"} for k,stats in timing.items()},
                 generated_utc=datetime.now(timezone.utc).isoformat(),
                 git_head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=FIXTURE.parents[2],text=True).strip())
    (output/"c1-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    return summary

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--samples",type=int,default=100)
    args=parser.parse_args()
    print(json.dumps(write_checkpoint(args.output_dir,args.samples),indent=2))
