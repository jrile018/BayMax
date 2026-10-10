"""Versioned lossless continuation for physical trips; display snapshots are separate."""
from dataclasses import asdict,fields
from json import loads
from math import isclose
from hashlib import sha256
from services.planner.ledger import Ledger,Assignment
from services.planner.ledger.checkpoint import canonical_json,json_copy,keys,require,seal,unseal
from .models import Route,Leg,Exclusion,SearchResult,finite_nonnegative

SCHEMA="knight26.trip-executor"
VERSION=1

def graph_fingerprint(graph):
    return sha256(canonical_json(dict(version=graph.version,nodes=graph.nodes,
        edges={k:asdict(v) for k,v in sorted(graph.edges.items())},
        metric_crs=getattr(graph,"metric_crs","declared local metric x/y metres"),
        origin_lonlat=getattr(graph,"origin_lonlat",None))).encode()).hexdigest()

def route_from_dict(value):
    data=json_copy(value); keys(data,(f.name for f in fields(Route)),"route")
    require(isinstance(data["legs"],list),"route legs")
    data["legs"]=tuple(Leg(**leg) for leg in data["legs"])
    data["edge_ids"]=tuple(data["edge_ids"])
    data["geometry"]=tuple(tuple(p) for p in data["geometry"])
    return Route(**data)

def _route_valid(graph,route,departure=None):
    graph.validate_nodes(route.source_node,route.destination_node,route.vehicle_kind)
    require(route.graph_version==graph.version and route.status=="feasible"
            and route.safety_validated is True,"route graph/status")
    require(type(route.route_version) is int and route.route_version>0
            and isinstance(route.route_id,str) and bool(route.route_id),"route ID/version")
    declared=finite_nonnegative(route.departure_s,"departure")
    now=declared if departure is None else departure
    require(isclose(declared,now,rel_tol=0,abs_tol=1e-8),"actual departure")
    node=route.source_node; distance=0
    require(len(route.edge_ids)==len(route.legs),"route leg count")
    for eid,leg in zip(route.edge_ids,route.legs):
        require(eid in graph.edges,"unknown route edge"); edge=graph.edges[eid]
        require(edge.source==node and route.vehicle_kind in edge.access and leg.edge_id==eid,"route continuity/access")
        for value in (leg.entry_s,leg.exit_s,leg.length_m):
            finite_nonnegative(value,"leg value")
        require(isclose(leg.entry_s,now,rel_tol=0,abs_tol=1e-8)
                and isclose(leg.exit_s,now+edge.travel_s,rel_tol=0,abs_tol=1e-8)
                and leg.length_m==edge.length_m,"route timing/length")
        node=edge.target; now+=edge.travel_s; distance+=edge.length_m
    finite_nonnegative(route.distance_m,"route distance")
    require(node==route.destination_node and route.arrival_s is not None
            and isclose(finite_nonnegative(route.arrival_s,"arrival"),now,rel_tol=0,abs_tol=1e-8)
            and isclose(route.distance_m,distance,rel_tol=0,abs_tol=1e-8),"route destination/totals")
    expected=graph.geometry_for(route.edge_ids)
    require(route.geometry==expected or (not route.edge_ids and route.geometry==(graph.nodes[node],)),"route geometry")
    for time in (route.forecast_issued_s,route.forecast_horizon_s):
        if time is not None:
            finite_nonnegative(time,"forecast metadata")

def _result(value,graph):
    if value is None:
        return None
    keys(value,(f.name for f in fields(SearchResult)),"search result")
    result=SearchResult(value["status"],tuple(route_from_dict(r) for r in value["routes"]),
        tuple(Exclusion(**e) for e in value["exclusions"]),value["expansions"],
        value["search_limited"],value["calculation_ms"],value["search_scope"])
    require(result.status in ("feasible","search_limit","unreachable_static","no_feasible_candidate")
        and type(result.expansions) is int and result.expansions>=0
        and type(result.search_limited) is bool and bool(result.routes)==(result.status=="feasible"),"search result")
    finite_nonnegative(result.calculation_ms,"search time")
    for route in result.routes:
        _route_valid(graph,route)
    return result

def _same(left,right):
    return canonical_json(left)==canonical_json(right)

def _history_valid(engine):
    """Validate committed paths and trigger receipts against the ordered trip audit."""
    receipts={}
    by_trip={aid:[] for aid in engine.trips}
    for event in engine.events:
        by_trip[event["dispatch_id"]].append(event)
        if event["type"] in ("reroute","replan_failed"):
            details=event["details"]; key=(event["dispatch_id"],details["trigger_event_id"])
            require(key not in receipts and key in engine._triggers,"reroute receipt identity")
            version,reason,result=engine._triggers[key]
            require(version==details["known_version"] and reason==details["reason"],"reroute receipt metadata")
            if event["type"]=="reroute":
                require(result is not None and result.status=="feasible" and bool(result.routes),"successful reroute receipt")
            elif details["status"]=="unsafe_current_edge":
                require(result is None,"unsafe-current-edge receipt")
            else:
                require(result is not None and not result.routes and result.status==details["status"],"failed reroute receipt")
            receipts[key]=result
    require(set(receipts)==set(engine._triggers),"missing or extra reroute receipts")
    for aid,t in engine.trips.items():
        audit=by_trip[aid]
        require(bool(audit) and audit[0]["type"]=="dispatch","initial dispatch event")
        signature=loads(t.signature)
        original=route_from_dict(signature[2])
        route=original; pending=list(route.edge_ids); completed=[]; current=None
        failure=None; phase="loading"; entry=None; distance=0
        trail=[list(engine.graph.nodes[original.source_node])]; previous_time=t.started_s
        for index,event in enumerate(audit):
            kind=event["type"]; details=event["details"]; when=event["time_s"]
            require(when>=previous_time,"trip audit time regressed"); previous_time=when
            if kind=="dispatch":
                require(index==0 and _same(details["route"],original.to_dict())
                    and details["loading_s"]==signature[3]
                    and details["service_s"]==t.assignment.service_s,"dispatch audit")
            elif kind=="departure":
                require(phase=="loading" and event["time_s"]==t.departed_s,"departure audit")
                phase="traveling"
            elif kind=="edge_enter":
                require(phase=="traveling" and current is None and bool(pending)
                    and pending[0]==details["edge_id"],"committed edge entry")
                current=pending.pop(0); entry=when; distance=0
            elif kind=="movement":
                require(phase=="traveling" and current==details["edge_id"],"movement edge")
                edge=engine.graph.edges[current]; moved=finite_nonnegative(details["distance_m"],"movement distance")
                require(edge.travel_s>0 and entry<=when<=entry+edge.travel_s and distance<moved<=edge.length_m
                    and isclose(moved,edge.length_m*(when-entry)/edge.travel_s,rel_tol=0,abs_tol=1e-6),
                    "movement timing/distance")
                require(_same(details["position_m"],list(engine.graph.position(current,moved))),"movement position")
                trail.extend([list(point) for point in engine.graph.segment(current,distance,moved)[1:]])
                distance=moved
            elif kind=="edge_exit":
                require(phase=="traveling" and current==details["edge_id"],"committed edge exit")
                edge=engine.graph.edges[current]
                require(isclose(when,entry+edge.travel_s,rel_tol=0,abs_tol=1e-8)
                    and isclose(distance,edge.length_m,rel_tol=0,abs_tol=1e-6)
                    and details["reached_node"]==edge.target,"edge exit timing/position")
                completed.append(current); current=None; entry=None; distance=0
            elif kind=="reroute":
                require(phase in ("loading","traveling"),"reroute phase")
                result=receipts[(aid,details["trigger_event_id"])]; new=result.routes[0]
                require(details["previous_path"]==([current] if current else [])+pending
                    and details["current_edge_id"]==current
                    and details["new_path"]==([current] if current else [])+list(new.edge_ids)
                    and details["route_id"]==new.route_id and details["route_version"]==new.route_version
                    and new.route_version==route.route_version+1
                    and details["new_eta_s"]==new.arrival_s
                    and details["decision_node"]==new.source_node
                    and details["decision_time_s"]==new.departure_s,"reroute committed path")
                decision=engine.graph.edges[current].target if current else (
                    engine.graph.edges[completed[-1]].target if completed else original.source_node)
                require(new.source_node==decision,"reroute junction")
                route=new; pending=list(new.edge_ids); failure=None
            elif kind=="replan_failed":
                # Unsafe-current-edge failure follows the stranding event.
                require(phase in ("loading","traveling","stranded")
                    and details["previous_path"]==([current] if current else [])+pending,"failed replan path")
                if details["status"]!="unsafe_current_edge":
                    require(phase in ("loading","traveling"),"failed suffix phase")
                    pending=[]; failure=details["status"]
            elif kind=="stranded":
                require(phase in ("loading","traveling","servicing")
                    and when==engine.ledger.assignments[aid].last_event_s,"stranding phase/time")
                phase="stranded"
            elif kind=="arrival":
                require(phase=="traveling" and current is None and not pending
                    and event["time_s"]==t.arrival_actual_s,"arrival audit")
                phase="servicing"
            elif kind=="service_completed":
                require(phase=="servicing" and when==engine.ledger.outcomes[aid]["completed_s"],
                    "service audit phase/time"); phase="completed"
            else:
                require(False,"unknown executor event")
        require(completed==t.completed_edge_ids and current==t.current_edge_id
            and pending==t.pending and entry==t.edge_entry_s,"remaining path differs from committed audit")
        require(_same(route.to_dict(),t.route.to_dict()) and failure==t.pending_failure
            and phase==t.phase,"active route/phase differs from audit")
        require(_same(trail,t.trail),"completed trail differs from movement audit")

def make_checkpoint(engine):
    with engine._lock:
        return seal(dict(schema=SCHEMA,version=VERSION,graph_fingerprint=graph_fingerprint(engine.graph),
            scenario_id=engine.scenario_id,run_id=engine.run_id,now_s=engine.now_s,
            snapshot_version=engine.snapshot_version,known_at_s=engine._known_at_s,
            ledger=engine.ledger.checkpoint(),trips={k:asdict(t) for k,t in sorted(engine.trips.items())},
            events=engine.events,triggers=[dict(dispatch_id=k[0],trigger_event_id=k[1],known_version=v[0],
                reason=v[1],result=None if v[2] is None else v[2].to_dict())
                for k,v in sorted(engine._triggers.items())]))

def restore_checkpoint(engine_type,graph,payload):
    from .trip import Trip
    try:
        data=unseal(payload,SCHEMA,VERSION)
        keys(data,("schema","version","graph_fingerprint","scenario_id","run_id","now_s","snapshot_version",
                   "known_at_s","ledger","trips","events","triggers"),"executor")
        require(data["graph_fingerprint"]==graph_fingerprint(graph),"graph content/version differs")
        now=finite_nonnegative(data["now_s"],"now")
        require(type(data["snapshot_version"]) is int and data["snapshot_version"]>=0,"snapshot version")
        require(data["known_at_s"]==-1 or 0<=finite_nonnegative(data["known_at_s"],"known history")<=now,"known history")
        require(all(isinstance(data[k],str) and data[k] for k in ("scenario_id","run_id")),"run identifiers")
        ledger=Ledger.from_checkpoint(data["ledger"])
        engine=engine_type(graph,ledger,data["scenario_id"],data["run_id"],now)
        engine.snapshot_version=data["snapshot_version"]; engine._known_at_s=data["known_at_s"]
        require(isinstance(data["trips"],dict) and set(data["trips"])==set(ledger.assignments),"trip identities")
        for aid,value in data["trips"].items():
            record=json_copy(value); keys(record,(f.name for f in fields(Trip)),"trip")
            record["route"]=route_from_dict(record["route"]); _route_valid(graph,record["route"])
            record["assignment"]=Assignment(**record["assignment"])
            record["assignment"].person_ids=tuple(record["assignment"].person_ids)
            t=Trip(**record); a=ledger.assignments[aid]; request=ledger.requests[a.request_id]
            require(t.dispatch_id==aid and t.vehicle_id==a.vehicle_id and t.request_id==a.request_id
                    and t.phase==a.phase,"trip resource/phase")
            for name in ("dispatch_id","vehicle_id","request_id","person_ids","cargo","loading_complete_s","service_s","created_s"):
                require(_same(getattr(t.assignment,name),getattr(a,name)),"trip original load/timing")
            finite_nonnegative(t.started_s,"started"); finite_nonnegative(t.time_s,"trip time")
            require(t.started_s==a.created_s and t.time_s==now and t.started_s<=now,"trip clock")
            require(t.departed_s==a.actual_departure_s and t.arrival_actual_s==a.arrival_actual_s,"actual phase times")
            finite_nonnegative(t.distance_m,"distance"); finite_nonnegative(t.exposure_s,"exposure")
            require(isinstance(t.pending,list) and isinstance(t.completed_edge_ids,list)
                    and isinstance(t.trail,list) and bool(t.trail),"path/trail arrays")
            node=request["origin_node"]
            for eid in t.completed_edge_ids:
                require(eid in graph.edges and graph.edges[eid].source==node,"completed directed path")
                node=graph.edges[eid].target
            if t.current_edge_id is not None:
                require(t.current_edge_id in graph.edges and t.current_node is None,"current edge")
                edge=graph.edges[t.current_edge_id]
                require(edge.source==node and edge.travel_s>0 and t.edge_entry_s is not None,"edge continuity/timing")
                entry=finite_nonnegative(t.edge_entry_s,"edge entry")
                progress_time=a.last_event_s if t.phase=="stranded" else now
                require(t.departed_s is not None and t.departed_s<=entry<=progress_time<=now
                    and progress_time<=entry+edge.travel_s
                    and isclose(t.distance_m,edge.length_m*(progress_time-entry)/edge.travel_s,
                                rel_tol=0,abs_tol=1e-6),"actual edge progress")
                node=edge.target
            else:
                require(t.current_node==node and t.edge_entry_s is None and t.distance_m==0,"current node/progress")
            for eid in t.pending:
                require(eid in graph.edges and graph.edges[eid].source==node
                        and t.route.vehicle_kind in graph.edges[eid].access,"pending continuity/access")
                node=graph.edges[eid].target
            if t.pending_failure is None and t.phase!="stranded":
                require(node==request["destination_node"],"remaining destination")
            require(t.phase!="completed" or (t.current_node==request["destination_node"] and not t.pending),"completed destination")
            require(t.eta_arrival_s is None if t.phase=="stranded" or t.pending_failure is not None
                    else t.eta_arrival_s==a.arrival_eta_s,"trip ETA")
            require(t.pending_failure is None or (t.pending_failure in
                ("search_limit","unreachable_static","no_feasible_candidate") and not t.pending
                and (t.phase=="stranded" or (t.phase=="traveling" and t.current_edge_id is not None))),
                "pending failure state")
            require(isclose(t.exposure_s,now-a.last_event_s,rel_tol=0,abs_tol=1e-8) if t.phase=="stranded" else t.exposure_s==0,"exposure")
            signature=loads(t.signature); fp=ledger._fingerprints[aid]
            require(isinstance(signature,list) and len(signature)==7 and _same(signature[:3],fp[:3])
                    and _same(signature[3:],fp[4:]),"dispatch signature")
            _route_valid(graph,route_from_dict(signature[2]),a.loading_complete_s)
            for point in t.trail:
                require(isinstance(point,list) and len(point)==2
                    and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in point),"trail point")
                canonical_json(point)
            position=graph.position(t.current_edge_id,t.distance_m) if t.current_edge_id else graph.nodes[t.current_node]
            require(all(isclose(x,y,rel_tol=0,abs_tol=1e-6) for x,y in zip(t.trail[-1],position)),"trail endpoint")
            engine.trips[aid]=t
        require(isinstance(data["events"],list),"events array")
        completed_events=[]
        for index,event in enumerate(data["events"],1):
            keys(event,("event_id","type","time_s","dispatch_id","details"),"executor event")
            when=finite_nonnegative(event["time_s"],"event time")
            require(event["event_id"]==engine.run_id+"-event-"+str(index) and event["dispatch_id"] in engine.trips
                and when<=now and isinstance(event["details"],dict),"event identity/time")
            if event["type"]=="service_completed":
                completed_events.append(event["dispatch_id"])
                require(_same(event["details"].get("outcome"),ledger.outcomes.get(event["dispatch_id"])),"service event outcome")
        require(len(completed_events)==len(set(completed_events)) and set(completed_events)==set(ledger.outcomes),"service event counts")
        engine.events=data["events"]; require(isinstance(data["triggers"],list),"triggers array")
        for item in data["triggers"]:
            keys(item,("dispatch_id","trigger_event_id","known_version","reason","result"),"trigger")
            key=(item["dispatch_id"],item["trigger_event_id"])
            require(key[0] in engine.trips and all(isinstance(item[n],str) and item[n]
                for n in ("trigger_event_id","known_version","reason")) and key not in engine._triggers,"trigger identity")
            engine._triggers[key]=(item["known_version"],item["reason"],_result(item["result"],graph))
        _history_valid(engine)
        ledger.check_invariants()
        return engine
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError,AttributeError) as error:
        raise ValueError("invalid executor checkpoint: "+str(error)) from error
