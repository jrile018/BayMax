"""Actual independent continuations from one saved mixed-resource state."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from .demo import exercise_graph,known,conservation
from .search import candidate_routes
from .trip import TripExecutor
from services.planner.ledger import Ledger,Vehicle,Request,Destination

def build_evidence():
    graph=exercise_graph(); safety=known(graph)
    ledger=Ledger([Vehicle("bus","bus","A",2,0),Vehicle("ambulance","ambulance","A",1,0),
                   Vehicle("truck","truck","A",0,5)],
        [Request("evac","evacuation","A","D",("p1","p2")),
         Request("medical","medical","A","D",("p3",),deadline_s=30),
         Request("supply","supply","A","D",goods={"water":8})],
        [Destination("shelter","D","shelter",2),Destination("medical","D","medical",1)],
        {"A":{"water":10}})
    original=TripExecutor(graph,ledger,run_id="checkpoint-mixed-aid")
    for vid,rid,kind,loading,service,cargo in (
        ("bus","evac","bus",0,2,None),("ambulance","medical","ambulance",1,2,None),
        ("truck","supply","truck",0,3,{"water":5})):
        route=candidate_routes(graph,"A","D",kind,loading,safety).routes[0]
        original.dispatch("dispatch-"+vid,vid,rid,route,safety,
                          loading_s=loading,service_s=service,cargo=cargo)
    original.advance(21.5,safety)
    saved=json.loads(json.dumps(original.checkpoint()))
    before=original.snapshot()
    served=TripExecutor.from_checkpoint(graph,saved)
    uncertain=TripExecutor.from_checkpoint(graph,saved)
    assert served.snapshot()==before==uncertain.snapshot()
    served.advance(33,safety)
    finished=served.snapshot()
    served.advance(40,safety)
    assert served.ledger.export_state()["outcome_totals"]==finished["ledger"]["outcome_totals"]
    unknown=known(graph,"k1",21.5)
    from dataclasses import replace
    unknown=replace(unknown,safe_nodes=frozenset())
    uncertain.advance(40,unknown)
    assert original.snapshot()==before
    assert served.snapshot()["ledger"]["outcome_totals"]==finished["ledger"]["outcome_totals"]
    for engine in (original,served,uncertain):
        assert engine.ledger.check_invariants()
        again=TripExecutor.from_checkpoint(graph,json.loads(json.dumps(engine.checkpoint())))
        assert again.snapshot()==engine.snapshot()
    evidence=dict(schema="routing-checkpoint-evidence-v1",scenario_id="fictional-tiny",
        saved_time_s=21.5,saved_snapshot=before,served_snapshot=served.snapshot(),
        unknown_destination_snapshot=uncertain.snapshot(),
        original_unchanged=original.snapshot()==before,independent_continuations=True,
        conservation={name:conservation(engine.snapshot())
            for name,engine in (("saved",original),("served",served),("unknown_destination",uncertain))},
        limitations=["Fictional tiny roads and explicit training safety declarations.",
                     "Demonstrates actual continuation and resource conservation; no Monte Carlo risk estimate.",
                     "Restore requires the exact graph content and version; safety is supplied to later actions."])
    return saved,evidence

def write_evidence(output_dir):
    output=Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    saved,evidence=build_evidence()
    evidence["git_head"]=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    evidence["generated_utc"]=datetime.now(timezone.utc).isoformat()
    files={"checkpoint-mixed-state.json":saved,"checkpoint-mixed-replay.json":evidence}
    for name,value in files.items():
        (output/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
    return dict(git_head=evidence["git_head"],
        files={name:sha256((output/name).read_bytes()).hexdigest() for name in files},
        original_unchanged=evidence["original_unchanged"],
        outcomes={name:evidence[name+"_snapshot"]["ledger"]["outcome_totals"]
                  for name in ("served","unknown_destination")},
        conservation=evidence["conservation"])

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args()
    print(json.dumps(write_evidence(args.output_dir),indent=2,sort_keys=True))
