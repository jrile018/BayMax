"""Authoritative simulated movement. Views consume snapshots, never recalculate travel."""
from dataclasses import dataclass, field
from copy import deepcopy
from hashlib import sha256
from json import dumps, loads
from math import isclose
from threading import RLock
from contextlib import contextmanager
from .models import finite_nonnegative
from .search import candidate_routes

@dataclass
class Trip:
    dispatch_id: str
    vehicle_id: str
    request_id: str
    route: object
    assignment: object
    signature: str
    started_s: float
    time_s: float
    current_node: str | None
    pending: list
    phase: str = "loading"
    current_edge_id: str | None = None
    edge_entry_s: float | None = None
    distance_m: float = 0
    departed_s: float | None = None
    arrival_actual_s: float | None = None
    completed_edge_ids: list = field(default_factory=list)
    trail: list = field(default_factory=list)
    eta_arrival_s: float | None = None
    exposure_s: float = 0
    pending_failure: str | None = None

class TripExecutor:
    def __init__(self,graph,ledger,scenario_id="fictional-tiny",run_id="demo",start_s=0):
        self.graph=graph
        self.ledger=ledger
        self.scenario_id=scenario_id
        self.run_id=run_id
        self.now_s=finite_nonnegative(start_s,"start_s")
        self.trips={}
        self.events=[]
        self.snapshot_version=0
        self._known_at_s=-1
        self._triggers={}
        self._lock=RLock()

    def checkpoint(self):
        from .checkpoint import make_checkpoint
        return make_checkpoint(self)

    @classmethod
    def from_checkpoint(cls,graph,payload):
        from .checkpoint import restore_checkpoint
        return restore_checkpoint(cls,graph,payload)

    @contextmanager
    def _atomic(self):
        # Shared ledger transaction and executor rollback define one authoritative action.
        with self._lock:
            before=deepcopy((self.trips,self.events,self.now_s,self.snapshot_version,self._known_at_s,self._triggers))
            try:
                with self.ledger.transaction():
                    yield
            except BaseException:
                (self.trips,self.events,self.now_s,self.snapshot_version,self._known_at_s,self._triggers)=before
                raise

    def _accept_safety(self,safety):
        if safety.known_at_s>self.now_s:
            raise ValueError("advance to report time before using its information")
        if safety.known_at_s<self._known_at_s:
            raise ValueError("cannot replace known history with an earlier snapshot")

    def _event(self,trip,event_type,when,**details):
        self.events.append(dict(event_id=f"{self.run_id}-event-{len(self.events)+1}",
                                type=event_type,time_s=when,dispatch_id=trip.dispatch_id,details=details))

    def _position(self,t):
        if t.current_edge_id:
            return list(self.graph.position(t.current_edge_id,t.distance_m))
        return list(self.graph.nodes[t.current_node])

    def _remaining(self,t):
        return ([t.current_edge_id] if t.current_edge_id else [])+list(t.pending)

    def dispatch(self,dispatch_id,vehicle_id,request_id,route,safety,*,loading_s=0,service_s=0,person_ids=None,cargo=None):
        with self._atomic():
            self._accept_safety(safety)
            loading=finite_nonnegative(loading_s,"loading_s")
            service=finite_nonnegative(service_s,"service_s")
            signature=dumps([vehicle_id,request_id,route.to_dict(),loading,service,person_ids,cargo],sort_keys=True)
            if dispatch_id in self.trips:
                old=self.trips[dispatch_id]
                if old.signature!=signature:
                    raise ValueError("conflicting dispatch ID")
                return self._trip_dict(old)
            if not safety.operational_enabled:
                raise ValueError("dispatch requires operationally enabled safety")
            if route.status!="feasible" or not route.safety_validated:
                raise ValueError("dispatch requires interval-validated feasible route")
            if route.graph_version!=self.graph.version or route.known_version!=safety.version:
                raise ValueError("route information/graph version is stale")
            if not isclose(route.departure_s,self.now_s+loading,rel_tol=0,abs_tol=1e-8):
                raise ValueError("route departure must follow actual loading")
            self.graph.validate_nodes(route.source_node,route.destination_node,route.vehicle_kind)
            clock=self.now_s+loading
            node=route.source_node
            if len(route.edge_ids)!=len(route.legs):
                raise ValueError("route legs must match edge IDs")
            for eid,leg in zip(route.edge_ids,route.legs):
                edge=self.graph.edges.get(eid)
                if edge is None or edge.source!=node or route.vehicle_kind not in edge.access:
                    raise ValueError("route is not a contiguous compatible directed path")
                if leg.edge_id!=eid or not isclose(leg.entry_s,clock,rel_tol=0,abs_tol=1e-8) or not isclose(leg.exit_s,clock+edge.travel_s,rel_tol=0,abs_tol=1e-8):
                    raise ValueError("route timing must derive from declared edge weights")
                safe,reason,_=safety.traversal(eid,clock,clock+edge.travel_s)
                if not safe:
                    raise ValueError(f"route is unsafe: {reason}")
                clock+=edge.travel_s
                node=edge.target
            if node!=route.destination_node or route.arrival_s is None or not isclose(clock,route.arrival_s,rel_tol=0,abs_tol=1e-8):
                raise ValueError("route destination/arrival inconsistent")
            assignment=self.ledger.commit_dispatch(dispatch_id,vehicle_id,request_id,route.to_dict(),self.now_s,
                                                   person_ids=person_ids,cargo=cargo,loading_s=loading,service_s=service)
            t=Trip(dispatch_id,vehicle_id,request_id,route,assignment,signature,self.now_s,self.now_s,
                   route.source_node,list(route.edge_ids),trail=[list(self.graph.nodes[route.source_node])],
                   eta_arrival_s=route.arrival_s)
            self.trips[dispatch_id]=t
            self._event(t,"dispatch",self.now_s,route=route.to_dict(),loading_s=loading,service_s=service)
            self._known_at_s=safety.known_at_s
            self.snapshot_version+=1
            return self._trip_dict(t)

    def _strand(self,t,when,reason):
        if t.phase=="stranded":
            return
        self.ledger.strand(t.dispatch_id,when,reason)
        t.phase="stranded"
        t.eta_arrival_s=None
        self._event(t,"stranded",when,reason=reason,position_m=self._position(t),remaining_path=self._remaining(t))

    def _arrival(self,t,safety):
        if t.current_node!=t.route.destination_node:
            self._strand(t,t.time_s,t.pending_failure or "no_feasible_continuation")
            return
        if not safety.destination_safe(t.current_node,t.time_s):
            self._strand(t,t.time_s,"destination_safety_unknown_or_closed")
            return
        self.ledger.record_arrival(t.dispatch_id,t.time_s,t.current_node,safe=True)
        t.phase="servicing"
        t.arrival_actual_s=t.time_s
        self._event(t,"arrival",t.time_s,arrived_node=t.current_node,position_m=self._position(t))

    def _advance_trip(self,t,target,safety):
        while True:
            if t.phase in ("completed","stranded"):
                if t.phase=="stranded":
                    t.exposure_s+=target-t.time_s
                t.time_s=target
                return
            if t.phase=="loading":
                loading_end=t.assignment.loading_complete_s
                if target<loading_end:
                    t.time_s=target
                    return
                t.time_s=loading_end
                self.ledger.mark_departed(t.dispatch_id,t.time_s)
                t.departed_s=t.time_s
                t.phase="traveling"
                self._event(t,"departure",t.time_s,passengers=list(t.assignment.person_ids),cargo=dict(t.assignment.cargo))
            if t.phase=="servicing":
                finish=t.arrival_actual_s+t.assignment.service_s
                # Certify every observed service segment before consuming its time.
                # Later restoration cannot erase an unsafe or uncovered segment.
                if not safety.destination_safe(t.current_node,t.time_s) or not safety.destination_safe(t.current_node,min(target,finish)):
                    self._strand(t,t.time_s,"destination_unsafe_or_unknown_during_service")
                    continue
                if target<finish:
                    t.time_s=target
                    return
                if not safety.destination_safe(t.current_node,finish):
                    self._strand(t,max(t.time_s,safety.known_at_s),"destination_unsafe_during_service")
                    continue
                t.time_s=finish
                outcome=self.ledger.complete_service(t.dispatch_id,finish,t.current_node,safe=True)
                t.phase="completed"
                self._event(t,"service_completed",finish,outcome=outcome)
                continue
            if t.current_edge_id is None:
                if not t.pending:
                    self._arrival(t,safety)
                    continue
                eid=t.pending.pop(0)
                edge=self.graph.edges[eid]
                safe,reason,evidence=safety.traversal(eid,t.time_s,t.time_s+edge.travel_s)
                if not safe:
                    t.pending.insert(0,eid)
                    self._strand(t,t.time_s,reason+": "+evidence)
                    continue
                if edge.source!=t.current_node:
                    raise RuntimeError("committed path lost directed continuity")
                t.current_edge_id=eid
                t.edge_entry_s=t.time_s
                t.current_node=None
                t.distance_m=0
                self._event(t,"edge_enter",t.time_s,edge_id=eid)
            edge=self.graph.edges[t.current_edge_id]
            remaining_s=max(0.0,t.edge_entry_s+edge.travel_s-t.time_s)
            safe,reason,evidence=safety.traversal(edge.edge_id,t.time_s,t.time_s+remaining_s)
            if not safe:
                self._strand(t,t.time_s,reason+": "+evidence)
                continue
            dt=min(target-t.time_s,remaining_s)
            if dt<0:
                raise RuntimeError("trip time exceeded target")
            before=t.distance_m
            t.distance_m=edge.length_m if remaining_s==0 else min(edge.length_m,t.distance_m+edge.length_m*dt/edge.travel_s)
            t.time_s+=dt
            if t.distance_m>before:
                t.trail.extend([list(p) for p in self.graph.segment(edge.edge_id,before,t.distance_m)[1:]])
                self._event(t,"movement",t.time_s,edge_id=edge.edge_id,distance_m=t.distance_m,position_m=self._position(t))
            if remaining_s<=dt+1e-9:
                t.completed_edge_ids.append(edge.edge_id)
                t.current_node=edge.target
                t.current_edge_id=None
                t.distance_m=0
                t.edge_entry_s=None
                self._event(t,"edge_exit",t.time_s,edge_id=edge.edge_id,reached_node=edge.target)
                # Process arrival/zero-time transitions even when target is exactly the junction time.
                continue
            return

    def advance(self,to_s,safety):
        with self._atomic():
            target=finite_nonnegative(to_s,"to_s")
            if target<self.now_s:
                raise ValueError("cannot move simulation time backwards")
            self._accept_safety(safety)
            if target==self.now_s:
                return self.snapshot()
            for t in self.trips.values():
                self._advance_trip(t,target,safety)
            self.now_s=target
            self._known_at_s=safety.known_at_s
            self.snapshot_version+=1
            return self.snapshot()

    def replan(self,dispatch_id,safety,trigger_event_id,reason,*,max_expansions=1000):
        with self._atomic():
            self._accept_safety(safety)
            if not trigger_event_id or not reason:
                raise ValueError("reroute requires trigger and reason")
            key=(dispatch_id,trigger_event_id)
            if key in self._triggers:
                version,old_reason,result=self._triggers[key]
                if version!=safety.version or old_reason!=reason:
                    raise ValueError("conflicting trigger ID")
                return result
            t=self.trips[dispatch_id]
            if t.phase not in ("loading","traveling"):
                raise ValueError("only active loading/traveling trips may replan")
            before=self._position(t)
            old_remaining=self._remaining(t)
            old_eta=t.eta_arrival_s
            if t.current_edge_id:
                edge=self.graph.edges[t.current_edge_id]
                remaining_s=max(0.0,t.edge_entry_s+edge.travel_s-t.time_s)
                decision_s=self.now_s+remaining_s
                safe,why,evidence=safety.traversal(edge.edge_id,self.now_s,decision_s)
                if not safe:
                    self._strand(t,self.now_s,why+": "+evidence)
                    self._event(t,"replan_failed",self.now_s,trigger_event_id=trigger_event_id,reason=reason,
                                status="unsafe_current_edge",known_version=safety.version,previous_path=old_remaining,
                                position_before=before,position_after=self._position(t))
                    self._triggers[key]=(safety.version,reason,None)
                    self._known_at_s=safety.known_at_s
                    self.snapshot_version+=1
                    return None
                decision_node=edge.target
            else:
                decision_node=t.current_node
                decision_s=max(self.now_s,t.assignment.loading_complete_s) if t.phase=="loading" else self.now_s
            result=candidate_routes(self.graph,decision_node,t.route.destination_node,t.route.vehicle_kind,
                                    decision_s,safety,max_expansions=max_expansions,route_version=t.route.route_version+1)
            if result.routes:
                self.ledger.update_eta(t.dispatch_id,result.routes[0].arrival_s)
                t.route=result.routes[0]
                t.pending=list(t.route.edge_ids)
                t.eta_arrival_s=t.route.arrival_s
                t.pending_failure=None
                self._event(t,"reroute",self.now_s,trigger_event_id=trigger_event_id,reason=reason,
                            previous_path=old_remaining,new_path=self._remaining(t),previous_eta_s=old_eta,
                            new_eta_s=t.eta_arrival_s,position_before=before,position_after=self._position(t),
                            current_edge_id=t.current_edge_id,known_version=safety.version,
                            route_id=t.route.route_id,route_version=t.route.route_version,status=result.status,
                            decision_node=decision_node,decision_time_s=decision_s)
            else:
                t.pending=[]
                t.pending_failure=result.status
                t.eta_arrival_s=None
                self._event(t,"replan_failed",self.now_s,trigger_event_id=trigger_event_id,reason=reason,
                            previous_path=old_remaining,status=result.status,known_version=safety.version,
                            position_before=before,position_after=self._position(t))
                if t.current_edge_id is None:
                    self._strand(t,self.now_s,result.status)
            self._triggers[key]=(safety.version,reason,result)
            self._known_at_s=safety.known_at_s
            self.snapshot_version+=1
            return result

    def _trip_dict(self,t):
        carried=t.departed_s is not None and t.phase!="completed"
        remaining=self._remaining(t)
        geometry=[]
        if t.current_edge_id:
            geometry=list(self.graph.segment(t.current_edge_id,t.distance_m,self.graph.edges[t.current_edge_id].length_m))
        for eid in t.pending:
            poly=self.graph.edges[eid].geometry
            geometry.extend(poly if not geometry else poly[1:])
        if not geometry:
            geometry=[tuple(self._position(t))]
        return dict(dispatch_id=t.dispatch_id,vehicle_id=t.vehicle_id,request_id=t.request_id,phase=t.phase,
                    route=t.route.to_dict(),route_version=t.route.route_version,current_node=t.current_node,
                    current_edge=None if not t.current_edge_id else dict(edge_id=t.current_edge_id,distance_m=t.distance_m,
                        direction=f"{self.graph.edges[t.current_edge_id].source}->{self.graph.edges[t.current_edge_id].target}"),
                    position_m=self._position(t),time_s=t.time_s,elapsed_s=t.time_s-t.started_s,
                    passengers=list(t.assignment.person_ids) if carried else [],cargo=dict(t.assignment.cargo) if carried else {},
                    committed_passengers=list(t.assignment.person_ids) if t.phase!="completed" else [],
                    completed_edge_ids=list(t.completed_edge_ids),completed_trail=deepcopy(t.trail),
                    remaining_path=remaining,remaining_geometry=geometry,eta_arrival_s=t.eta_arrival_s,
                    eta_service_complete_s=None if t.eta_arrival_s is None else t.eta_arrival_s+t.assignment.service_s,
                    exposure_s=t.exposure_s)

    def snapshot(self):
        with self._lock:
            state=dict(scenario_id=self.scenario_id,run_id=self.run_id,snapshot_version=self.snapshot_version,
                       time_s=self.now_s,graph_version=self.graph.version,metric_crs=getattr(self.graph,"metric_crs","declared local metric x/y metres"),
                       trips=[self._trip_dict(t) for _,t in sorted(self.trips.items())],
                       ledger=self.ledger.export_state(),events=deepcopy(self.events))
            if hasattr(self.graph,"source_metadata"):
                state["origin_lonlat"]=list(self.graph.origin_lonlat)
                state["source_metadata"]=deepcopy(self.graph.source_metadata)
            state=loads(dumps(state,sort_keys=True))
            state["snapshot_hash"]=sha256(dumps(state,sort_keys=True,separators=(",",":")).encode()).hexdigest()
            return state
