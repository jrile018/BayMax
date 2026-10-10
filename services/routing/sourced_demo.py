"""Actual Paradise road replay with a clearly authored training closure."""
import argparse,json
from hashlib import sha256
from pathlib import Path
from .adapters import graph_from_geography,safety_from_access
from .search import candidate_routes
from .trip import TripExecutor
from services.planner.ledger import Ledger,Vehicle,Request,Destination

CORRIDOR=("1004364417/1/fwd","1004364415/0/fwd",
          "1004364417/2/fwd","1004364417/3/fwd","1004364416/0/fwd")
TRAINING_SOURCE="paradise-osm-routing-training"

def _require(condition,message):
    if not condition:
        raise ValueError("sourced replay: "+message)

def _corridor(graph):
    prefix,direct,*detour=(graph.edges[eid] for eid in CORRIDOR)
    a,b,d=prefix.source,prefix.target,direct.target
    _require(direct.source==b and detour[0].source==b and
             all(left.target==right.source for left,right in zip(detour,detour[1:]))
             and detour[-1].target==d and
             sum(e.travel_s for e in detour)>direct.travel_s,
             "source road IDs no longer form the reviewed directed alternatives")
    return a,b,d,prefix,direct,detour

def _alignment(graph):
    return dict(graph_version=graph.version,area_id=graph.area_id,metric_crs=graph.metric_crs,
        origin_lonlat=list(graph.origin_lonlat),graph_source_sha256=graph.source_sha256,
        source_kind="authored_simulated",source_id=TRAINING_SOURCE)

def _open_record(eid):
    return dict(edge_id=eid,status="forecast",issued_time_s=0,received_time_s=0,
        coverage_start_s=0,coverage_end_s=1000,closed_intervals=[],
        source_ids=[TRAINING_SOURCE],
        spatial_rule="Selected OSM edge IDs in an authored training corridor; no fire overlay.",
        reason="Assumed open solely for this routing exercise; no live road status.")

def _closed_record(eid,when):
    return dict(edge_id=eid,status="forecast",issued_time_s=when,received_time_s=when,
        coverage_start_s=0,coverage_end_s=1000,
        closed_intervals=[dict(start_s=when,end_s=1000)],
        source_ids=[TRAINING_SOURCE+"-injected-closure"],
        spatial_rule="Manual directed-edge closure; not observed or mapped from a fire grid.",
        reason="Injected training road report; direct edge unavailable.")

def _snapshot(graph,records,when,version,safe_nodes):
    return safety_from_access(records,graph,alignment=_alignment(graph),
        known_at_s=when,horizon_s=1000,version=version,safe_nodes=safe_nodes)

def _branch(graph,saved):
    return TripExecutor.from_checkpoint(graph,json.loads(json.dumps(saved)))

def build_replay(payload,manifest):
    graph=graph_from_geography(payload,manifest)
    source,junction,destination,prefix,direct,detour=_corridor(graph)
    authored=[_open_record(eid) for eid in CORRIDOR]
    initial=_snapshot(graph,authored,0,"training-k0",[destination])
    candidates=candidate_routes(graph,source,destination,"bus",0,initial,max_expansions=2000)
    _require(candidates.status=="feasible","no certified authored corridor route")
    route=candidates.routes[0]
    _require(route.edge_ids==(prefix.edge_id,direct.edge_id),
             "source weights no longer choose the reviewed direct route")
    ledger=Ledger([Vehicle("training-bus","bus",source,1,0)],
                  [Request("training-evac","evacuation",source,destination,("training-person",))],
                  [Destination("training-shelter",destination,"shelter",1)],{})
    original=TripExecutor(graph,ledger,scenario_id="paradise-osm-training-only",
                          run_id="sourced-road-corridor")
    original.dispatch("training-dispatch","training-bus","training-evac",route,initial,service_s=1)
    midpoint=prefix.travel_s/2
    original.advance(midpoint,initial)
    saved=json.loads(json.dumps(original.checkpoint()))
    before=original.snapshot()
    baseline=_branch(graph,saved); rerouted=_branch(graph,saved); uncertain=_branch(graph,saved)
    injected=authored+[_closed_record(direct.edge_id,midpoint)]
    changed=_snapshot(graph,injected,midpoint,"training-k1",[destination])
    result=rerouted.replan("training-dispatch",changed,"training-report","injected road closure")
    _require(result is not None and result.status=="feasible","detour not feasible")
    _require(rerouted.snapshot()["trips"][0]["remaining_path"]==
             [prefix.edge_id]+[edge.edge_id for edge in detour],"unexpected sourced detour")
    baseline.advance(route.arrival_s+1,initial)
    rerouted.advance(result.routes[0].arrival_s+1,changed)
    no_destination=_snapshot(graph,authored,midpoint,"training-unknown",[])
    uncertain.advance(result.routes[0].arrival_s+1,no_destination)
    _require(original.snapshot()==before,"original branch mutated")
    for branch in (original,baseline,rerouted,uncertain):
        branch.ledger.check_invariants()
        _require(_branch(graph,branch.checkpoint()).snapshot()==branch.snapshot(),
                 "continuation roundtrip differs")
    counts={name:branch.ledger.export_state()["outcome_totals"]["safe_evacuated_people"]
            for name,branch in (("direct",baseline),("detour",rerouted),("unknown_destination",uncertain))}
    _require(counts=={"direct":1,"detour":1,"unknown_destination":0},"actual service outcomes differ")
    source_nodes={n:dict(lonlat=list(graph.node_lonlat[n]),geometry_m=list(graph.nodes[n]))
                  for n in {source,junction,destination}|
                           {edge.source for edge in detour}|{edge.target for edge in detour}}
    source_edges={eid:dict(source=graph.edges[eid].source,target=graph.edges[eid].target,
        geometry_m=[list(p) for p in graph.edges[eid].geometry],
        length_m=graph.edges[eid].length_m,travel_s=graph.edges[eid].travel_s,
        access=list(graph.edges[eid].access),provenance=graph.edge_provenance[eid])
        for eid in CORRIDOR}
    replay=dict(schema="routing-sourced-training-v1",graph_version=graph.version,
        source_metadata=graph.source_metadata,selected_node_ids=dict(source=source,junction=junction,destination=destination),
        selected_nodes=source_nodes,selected_edges=source_edges,authored_access_records=injected,
        reported_at_s=midpoint,saved_state=saved,branch_snapshots=dict(saved=before,
            direct=baseline.snapshot(),detour=rerouted.snapshot(),
            unknown_destination=uncertain.snapshot()),
        detour_result=result.to_dict(),outcomes=counts,
        original_unchanged=original.snapshot()==before,
        assumptions=[
            "OSM sourced road geometry and IDs; road travel speeds are source-declared estimates or assumptions.",
            "Every open-road interval and safe destination in this corridor is authored for training.",
            "The injected road closure is hypothetical; no wildfire field or live road report is joined.",
            "Roads without explicit authored coverage and roads outside the acquired OSM bbox remain unknown.",
            "Vehicle access maps OSM bus, motorcar and hgv flags to bus, ambulance and truck proxies."
        ])
    return replay

def _fire_mismatch(graph_payload,manifest,fire_hazard_path,fire_access_path):
    hazard_bytes=Path(fire_hazard_path).read_bytes()
    access_bytes=Path(fire_access_path).read_bytes()
    hazard=json.loads(hazard_bytes); records=json.loads(access_bytes)
    graph=graph_from_geography(graph_payload,manifest)
    source,junction,destination,*_= _corridor(graph)
    grid=hazard["grid"]
    context=_alignment(graph)
    context["metric_crs"]=grid["crs"]
    context["origin_lonlat"]=grid.get("origin_lonlat",grid.get("origin_m"))
    try:
        safety_from_access(records,graph,alignment=context,known_at_s=0,
            horizon_s=100,version="reject-fire-crs",safe_nodes=[destination],
            default_received_s=0)
    except ValueError as error:
        crs_rejection=str(error)
    else:
        raise ValueError("synthetic fire CRS unexpectedly joined to Paradise roads")
    _require("metric_crs" in crs_rejection,"fire CRS rejection was not explicit")
    try:
        safety_from_access(records,graph,alignment=_alignment(graph),known_at_s=0,
            horizon_s=100,version="reject-fire-ids",safe_nodes=[destination],
            default_received_s=0)
    except ValueError as error:
        id_rejection=str(error)
    else:
        raise ValueError("synthetic fire edge IDs unexpectedly joined to Paradise roads")
    _require("edge ID" in id_rejection,"fire edge ID rejection was not explicit")
    return dict(hazard_sha256=sha256(hazard_bytes).hexdigest(),
        access_sha256=sha256(access_bytes).hexdigest(),fire_crs=grid["crs"],
        fire_origin_m=grid.get("origin_m"),map_crs=graph.metric_crs,
        map_origin_lonlat=list(graph.origin_lonlat),fire_edge_count=len(records),
        crs_rejection=crs_rejection,edge_id_rejection=id_rejection,
        joined=False)

def write_replay(graph_path,manifest_path,output_dir,fire_hazard_path=None,fire_access_path=None):
    graph_path=Path(graph_path);manifest_path=Path(manifest_path);out=Path(output_dir)
    out.mkdir(parents=True,exist_ok=True)
    raw_graph=graph_path.read_bytes();raw_manifest=manifest_path.read_bytes()
    graph_payload=json.loads(raw_graph);manifest=json.loads(raw_manifest)
    replay=build_replay(graph_payload,manifest)
    if fire_hazard_path is not None or fire_access_path is not None:
        _require(fire_hazard_path is not None and fire_access_path is not None,
                 "both fire hazard and access paths are required for mismatch proof")
        replay["rejected_fire_join"]=_fire_mismatch(graph_payload,manifest,fire_hazard_path,fire_access_path)
    replay["input_files"]=dict(graph_sha256=sha256(raw_graph).hexdigest(),
        manifest_sha256=sha256(raw_manifest).hexdigest(),
        graph_path=str(graph_path),manifest_path=str(manifest_path))
    output=out/"c2-sourced-replay.json"
    output.write_text(json.dumps(replay,indent=2,sort_keys=True)+"\n")
    summary=dict(schema=replay["schema"],graph_version=replay["graph_version"],
        input_files=replay["input_files"],source_metadata=replay["source_metadata"],
        selected_node_ids=replay["selected_node_ids"],selected_edge_ids=list(CORRIDOR),
        selected_edge_count=len(CORRIDOR),
        distance_m={name:sum(replay["selected_edges"][eid]["length_m"]
                            for eid in snapshot["trips"][0]["completed_edge_ids"])
                    for name,snapshot in replay["branch_snapshots"].items() if name in ("direct","detour")},
        arrival_s={name:snapshot["ledger"]["assignments"]["training-dispatch"]["arrival_actual_s"]
                   for name,snapshot in replay["branch_snapshots"].items() if name in ("direct","detour")},
        outcomes=replay["outcomes"],original_unchanged=replay["original_unchanged"],
        rejected_fire_join=replay.get("rejected_fire_join"),
        replay_sha256=sha256(output.read_bytes()).hexdigest(),assumptions=replay["assumptions"])
    (out/"c2-sourced-summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    return summary

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--graph",required=True)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--fire-hazard")
    parser.add_argument("--fire-access")
    args=parser.parse_args()
    print(json.dumps(write_replay(args.graph,args.manifest,args.output_dir,
        args.fire_hazard,args.fire_access),indent=2,sort_keys=True))
