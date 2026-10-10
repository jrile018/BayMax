"""Atomic commitments and actual aid outcomes, shared with authoritative trip movement."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from math import isfinite, isclose
from threading import RLock
from .models import Assignment, LedgerError
from .checkpoint import json_copy,make_checkpoint,restore_checkpoint

def _id(value, name):
    if not isinstance(value, str) or not value:
        raise LedgerError(name + " must be a nonempty string")
    return value

def _seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise LedgerError(name + " must be finite and nonnegative")
    return float(value)

def _count(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise LedgerError(name + " must be an integer quantity")
    return value

def _quantities(values, positive=True):
    if not isinstance(values, dict):
        raise LedgerError("goods must be a dictionary of named units")
    return {_id(k,"good"): _count(v,"quantity",positive) for k,v in values.items()}

def _people(values):
    if not isinstance(values, (tuple, list)):
        raise LedgerError("person IDs must be a tuple or list")
    result=tuple(_id(p,"person_id") for p in values)
    if len(result)!=len(set(result)):
        raise LedgerError("person IDs must be unique")
    return result

class Ledger:
    def __init__(self, vehicles, requests, destinations, stocks):
        vehicles=tuple(vehicles); requests=tuple(requests); destinations=tuple(destinations)
        stocks=deepcopy(stocks)
        self._lock=RLock()
        self.vehicles={}
        self.requests={}
        self.destinations={}
        self.assignments={}
        self._fingerprints={}
        self.people={}
        self.outcomes={}
        self.events=[]
        self.delivered={}
        self.stocks={}
        for v in vehicles:
            _id(v.vehicle_id,"vehicle_id"); _id(v.node_id,"vehicle node")
            if v.vehicle_id in self.vehicles or v.kind not in ("bus","ambulance","truck"):
                raise LedgerError("duplicate vehicle or unsupported vehicle kind")
            _count(v.seats,"seats"); _count(v.cargo_capacity,"cargo capacity")
            self.vehicles[v.vehicle_id]=dict(asdict(v),commitment=None,available_s=0)
        for r in requests:
            _id(r.request_id,"request_id"); _id(r.origin_node,"origin"); _id(r.destination_node,"destination")
            if r.request_id in self.requests or r.kind not in ("evacuation","medical","supply"):
                raise LedgerError("duplicate request or unsupported request kind")
            persons=_people(r.person_ids); goods=_quantities(r.goods)
            if r.deadline_s is not None:
                _seconds(r.deadline_s,"deadline")
            if r.kind=="supply":
                if persons or not goods:
                    raise LedgerError("supply requests require goods and no people")
            elif goods or not persons:
                raise LedgerError("person requests require people and no goods")
            for p in persons:
                if p in self.people:
                    raise LedgerError("a person may belong to only one request")
                self.people[p]=dict(location="origin",node_id=r.origin_node,dispatch_id=None)
            self.requests[r.request_id]=dict(asdict(r),person_ids=persons,goods=goods,
                remaining_people=list(persons),remaining_goods=dict(goods),reserved_people=[],reserved_goods={})
        for d in destinations:
            _id(d.destination_id,"destination_id"); _id(d.node_id,"destination node")
            if d.destination_id in self.destinations or d.kind not in ("shelter","medical"):
                raise LedgerError("duplicate destination or unsupported kind")
            _count(d.capacity,"destination capacity")
            self.destinations[d.destination_id]=dict(asdict(d),reserved=0,occupancy=0)
        if not isinstance(stocks,dict):
            raise LedgerError("stocks must be keyed by node and good")
        for node,goods in stocks.items():
            self.stocks[_id(node,"stock node")]=_quantities(goods,positive=False)
        self._initial_goods={}
        for goods in self.stocks.values():
            for good,qty in goods.items():
                self._initial_goods[good]=self._initial_goods.get(good,0)+qty
        self._initial_config=json_copy(dict(vehicles=[asdict(v) for v in sorted(vehicles,key=lambda v:v.vehicle_id)],
            requests=[asdict(r) for r in sorted(requests,key=lambda r:r.request_id)],
            destinations=[asdict(d) for d in sorted(destinations,key=lambda d:d.destination_id)],stocks=self.stocks))
        self.check_invariants()

    def checkpoint(self):
        return make_checkpoint(self)

    @classmethod
    def from_checkpoint(cls,payload):
        return restore_checkpoint(cls,payload)

    @contextmanager
    def transaction(self):
        """Reentrant savepoint: exceptions restore every resource, audit entry and outcome."""
        with self._lock:
            before=deepcopy({k:v for k,v in self.__dict__.items() if k!="_lock"})
            try:
                yield self
            except BaseException:
                for key in list(self.__dict__):
                    if key!="_lock":
                        del self.__dict__[key]
                self.__dict__.update(before)
                raise

    def _event(self,kind,a,now,**details):
        self.events.append(dict(event_id="ledger-"+str(len(self.events)+1),type=kind,
                                dispatch_id=a.dispatch_id,time_s=now,details=deepcopy(details)))

    def _assignment(self,dispatch_id):
        try:
            return self.assignments[dispatch_id]
        except (KeyError,TypeError):
            raise LedgerError("unknown dispatch") from None

    def _time(self,a,now):
        now=_seconds(now,"time")
        if now<a.last_event_s:
            raise LedgerError("assignment time cannot move backwards")
        return now

    def commit_dispatch(self,dispatch_id,vehicle_id,request_id,route,now_s,*,person_ids=None,cargo=None,
                        loading_s=0,service_s=0):
        with self.transaction():
            _id(dispatch_id,"dispatch_id"); _id(vehicle_id,"vehicle_id"); _id(request_id,"request_id")
            now=_seconds(now_s,"now"); loading=_seconds(loading_s,"loading"); service=_seconds(service_s,"service")
            if not isinstance(route,dict):
                raise LedgerError("route must be a validated route dictionary")
            fingerprint=json_copy((vehicle_id,request_id,route,now,loading,service,person_ids,cargo))
            if dispatch_id in self.assignments:
                if self._fingerprints[dispatch_id]!=fingerprint:
                    raise LedgerError("conflicting dispatch ID")
                return deepcopy(self.assignments[dispatch_id])
            if vehicle_id not in self.vehicles or request_id not in self.requests:
                raise LedgerError("unknown vehicle or request")
            v=self.vehicles[vehicle_id]; r=self.requests[request_id]
            expected={"evacuation":"bus","medical":"ambulance","supply":"truck"}[r["kind"]]
            if v["kind"]!=expected or v["commitment"] is not None or v["node_id"]!=r["origin_node"] or now<v["available_s"]:
                raise LedgerError("vehicle incompatible, committed, or away from request origin")
            if route.get("status")!="feasible" or route.get("safety_validated") is not True:
                raise LedgerError("dispatch requires a feasible interval-validated route")
            if route.get("source_node")!=r["origin_node"] or route.get("destination_node")!=r["destination_node"]:
                raise LedgerError("route endpoints differ from request")
            if "vehicle_kind" in route and route["vehicle_kind"]!=v["kind"]:
                raise LedgerError("route vehicle kind differs")
            departure=_seconds(route.get("departure_s"),"route departure")
            arrival=_seconds(route.get("arrival_s"),"route arrival")
            loading_end=_seconds(now+loading,"loading completion")
            completion=_seconds(arrival+service,"planned service completion")
            if not isclose(departure,loading_end,rel_tol=0,abs_tol=1e-8) or arrival<departure:
                raise LedgerError("route must depart after actual loading")
            edges=route.get("edge_ids")
            if not isinstance(edges,(list,tuple)) or any(not isinstance(x,str) or not x for x in edges):
                raise LedgerError("route must declare edge IDs")
            if not edges and r["origin_node"]!=r["destination_node"]:
                raise LedgerError("travel cannot be omitted")
            if r["deadline_s"] is not None and completion>r["deadline_s"]:
                raise LedgerError("planned service misses request deadline")
            selected=tuple(p for p in r["remaining_people"] if p not in r["reserved_people"]) if person_ids is None else _people(person_ids)
            load={k:q-r["reserved_goods"].get(k,0) for k,q in r["remaining_goods"].items()
                  if q-r["reserved_goods"].get(k,0)>0} if cargo is None else _quantities(cargo)
            destination_id=None
            if r["kind"]=="supply":
                if selected or not load or sum(load.values())>v["cargo_capacity"]:
                    raise LedgerError("supply load absent or exceeds cargo capacity")
                stock=self.stocks.get(r["origin_node"],{})
                for good,qty in load.items():
                    if qty>r["remaining_goods"].get(good,0)-r["reserved_goods"].get(good,0) or qty>stock.get(good,0):
                        raise LedgerError("load exceeds unreserved need or origin stock")
            else:
                if load or not selected or len(selected)>v["seats"]:
                    raise LedgerError("person load absent or exceeds seats")
                if any(p not in r["remaining_people"] or p in r["reserved_people"] for p in selected):
                    raise LedgerError("people unavailable or already reserved")
                dest_kind="shelter" if r["kind"]=="evacuation" else "medical"
                candidates=[d for _,d in sorted(self.destinations.items()) if d["node_id"]==r["destination_node"]
                            and d["kind"]==dest_kind and d["capacity"]-d["reserved"]-d["occupancy"]>=len(selected)]
                if not candidates:
                    raise LedgerError("compatible destination capacity unavailable")
                destination_id=candidates[0]["destination_id"]
            a=Assignment(dispatch_id,vehicle_id,request_id,selected,dict(load),loading_end,service,arrival,
                         now,destination_id=destination_id,travel_s=arrival-departure,last_event_s=now)
            self.assignments[dispatch_id]=a
            self._fingerprints[dispatch_id]=fingerprint
            v["commitment"]=dispatch_id
            r["reserved_people"].extend(selected)
            for p in selected:
                self.people[p]["dispatch_id"]=dispatch_id
            for good,qty in load.items():
                self.stocks[r["origin_node"]][good]-=qty
                r["reserved_goods"][good]=r["reserved_goods"].get(good,0)+qty
            if destination_id is not None:
                self.destinations[destination_id]["reserved"]+=len(selected)
            self._event("dispatch_committed",a,now,person_ids=selected,cargo=load)
            self.check_invariants()
            return deepcopy(a)

    def mark_departed(self,dispatch_id,now_s):
        with self.transaction():
            a=self._assignment(dispatch_id); now=self._time(a,now_s)
            if a.phase!="loading" or now<a.loading_complete_s:
                raise LedgerError("departure requires completed loading")
            a.phase="traveling"; a.actual_departure_s=now; a.last_event_s=now
            a.arrival_eta_s=_seconds(max(a.arrival_eta_s,now+a.travel_s),"departure ETA")
            self.vehicles[a.vehicle_id]["node_id"]=None
            for p in a.person_ids:
                self.people[p].update(location="in_transit",node_id=None)
            self._event("departure",a,now)
            self.check_invariants()
            return deepcopy(a)

    def update_eta(self,dispatch_id,arrival_eta_s):
        with self.transaction():
            a=self._assignment(dispatch_id); eta=_seconds(arrival_eta_s,"arrival ETA")
            baseline=a.actual_departure_s if a.actual_departure_s is not None else a.loading_complete_s
            if a.phase not in ("loading","traveling") or eta<max(baseline,a.last_event_s):
                raise LedgerError("ETA inconsistent with active assignment")
            a.arrival_eta_s=eta
            if a.phase=="loading":
                a.travel_s=eta-a.loading_complete_s
            return deepcopy(a)

    def record_arrival(self,dispatch_id,now_s,arrived_node,safe=True):
        node_id=arrived_node
        with self.transaction():
            a=self._assignment(dispatch_id); now=self._time(a,now_s); r=self.requests[a.request_id]
            if a.phase!="traveling" or node_id!=r["destination_node"] or safe is not True or (now<a.arrival_eta_s and not isclose(now,a.arrival_eta_s,rel_tol=0,abs_tol=1e-8)):
                raise LedgerError("arrival requires actual safe travel completion at destination")
            a.phase="servicing"; a.arrival_actual_s=now; a.last_event_s=now
            self.vehicles[a.vehicle_id]["node_id"]=node_id
            self._event("arrival",a,now,node_id=node_id)
            self.check_invariants()
            return deepcopy(a)

    def complete_service(self,dispatch_id,now_s,arrived_node,safe=True):
        node_id=arrived_node
        with self.transaction():
            a=self._assignment(dispatch_id); now=_seconds(now_s,"service completion"); r=self.requests[a.request_id]
            if dispatch_id in self.outcomes:
                old=self.outcomes[dispatch_id]
                if now!=old["completed_s"] or node_id!=r["destination_node"] or safe is not True:
                    raise LedgerError("conflicting service completion")
                return deepcopy(old)
            self._time(a,now)
            if a.phase!="servicing" or node_id!=r["destination_node"] or safe is not True or now<a.arrival_actual_s+a.service_s:
                raise LedgerError("service requires actual safe arrival and elapsed service duration")
            for p in a.person_ids:
                r["remaining_people"].remove(p); r["reserved_people"].remove(p)
                self.people[p].update(location="destination",node_id=node_id,dispatch_id=None)
            for good,qty in a.cargo.items():
                r["remaining_goods"][good]-=qty; r["reserved_goods"][good]-=qty
                self.delivered[good]=self.delivered.get(good,0)+qty
            if a.destination_id is not None:
                d=self.destinations[a.destination_id]
                d["reserved"]-=len(a.person_ids); d["occupancy"]+=len(a.person_ids)
            a.phase="completed"; a.last_event_s=now
            self.vehicles[a.vehicle_id]["commitment"]=None
            self.vehicles[a.vehicle_id]["available_s"]=now
            outcome=dict(dispatch_id=dispatch_id,request_id=a.request_id,kind=r["kind"],completed_s=now,
                         people=len(a.person_ids),goods=dict(a.cargo),
                         on_time=r["deadline_s"] is None or now<=r["deadline_s"])
            self.outcomes[dispatch_id]=outcome
            self._event("service_completed",a,now,outcome=outcome)
            self.check_invariants()
            return deepcopy(outcome)

    def strand(self,dispatch_id,now_s,reason):
        with self.transaction():
            a=self._assignment(dispatch_id); now=self._time(a,now_s); _id(reason,"strand reason")
            if a.phase not in ("loading","traveling","servicing"):
                raise LedgerError("only active assignments can strand")
            a.phase="stranded"; a.last_event_s=now
            self._event("stranded",a,now,reason=reason)
            self.check_invariants()
            return deepcopy(a)

    def export_state(self):
        with self._lock:
            counts={kind:sum(o["kind"]==kind for o in self.outcomes.values()) for kind in ("evacuation","medical","supply")}
            totals=dict(safe_evacuated_people=sum(o["people"] for o in self.outcomes.values() if o["kind"]=="evacuation"),
                        medical_people_served=sum(o["people"] for o in self.outcomes.values() if o["kind"]=="medical"),
                        on_time_medical_people=sum(o["people"] for o in self.outcomes.values() if o["kind"]=="medical" and o["on_time"]),
                        delivered_goods=dict(self.delivered))
            return json_copy(dict(vehicles=dict(sorted(self.vehicles.items())),requests=dict(sorted(self.requests.items())),
                destinations=dict(sorted(self.destinations.items())),stocks=dict(sorted(self.stocks.items())),
                assignments={k:asdict(v) for k,v in sorted(self.assignments.items())},person_locations=dict(sorted(self.people.items())),
                delivered=dict(self.delivered),outcomes=dict(sorted(self.outcomes.items())),outcome_counts=counts,
                outcome_totals=totals,audit_events=self.events))

    def check_invariants(self):
        with self._lock:
            def require(condition,message):
                if not condition:
                    raise LedgerError("invariant: "+message)
            goods=dict(self.delivered)
            active_people=set()
            reserved_people={r:[] for r in self.requests}
            reserved_goods={r:{} for r in self.requests}
            reserved_dest={d:0 for d in self.destinations}
            occupied_dest={d:0 for d in self.destinations}
            delivered_by_request={r:{} for r in self.requests}
            completed_people=set()
            for stock in self.stocks.values():
                for good,qty in stock.items():
                    require(isinstance(qty,int) and not isinstance(qty,bool) and qty>=0,"nonnegative stock")
                    goods[good]=goods.get(good,0)+qty
            for aid,a in self.assignments.items():
                v=self.vehicles[a.vehicle_id]; r=self.requests[a.request_id]
                require(len(a.person_ids)<=v["seats"] and sum(a.cargo.values())<=v["cargo_capacity"],"vehicle capacity")
                if a.phase!="completed":
                    require(v["commitment"]==aid,"active assignment vehicle commitment")
                    for p in a.person_ids:
                        require(p not in active_people,"one active commitment per person")
                        active_people.add(p); reserved_people[a.request_id].append(p)
                        loc=self.people[p]
                        require(loc["dispatch_id"]==aid,"person commitment")
                        require(loc["location"] in ("origin","in_transit"),"active person location")
                    for good,qty in a.cargo.items():
                        goods[good]=goods.get(good,0)+qty
                        rg=reserved_goods[a.request_id]; rg[good]=rg.get(good,0)+qty
                    if a.destination_id is not None:
                        reserved_dest[a.destination_id]+=len(a.person_ids)
                else:
                    require(aid in self.outcomes,"completed assignment has actual outcome")
                    for p in a.person_ids:
                        require(p not in completed_people,"person served once")
                        completed_people.add(p)
                        require(self.people[p]==dict(location="destination",node_id=r["destination_node"],dispatch_id=None),"served person location")
                    for good,qty in a.cargo.items():
                        dg=delivered_by_request[a.request_id]; dg[good]=dg.get(good,0)+qty
                    if a.destination_id is not None:
                        occupied_dest[a.destination_id]+=len(a.person_ids)
            require({k:v for k,v in goods.items() if v}=={k:v for k,v in self._initial_goods.items() if v},"stock + carried + delivered conservation")
            require(set(self.people)==active_people|completed_people|{p for p,x in self.people.items() if x["location"]=="origin" and x["dispatch_id"] is None},"person conservation")
            for rid,r in self.requests.items():
                require(set(r["reserved_people"])==set(reserved_people[rid]),"person reservations")
                require(set(r["remaining_people"])==set(r["person_ids"])-completed_people,"remaining people")
                require({k:v for k,v in r["reserved_goods"].items() if v}==reserved_goods[rid],"goods reservations")
                for good,qty in r["goods"].items():
                    require(r["remaining_goods"][good]==qty-delivered_by_request[rid].get(good,0)>=r["reserved_goods"].get(good,0),"remaining need")
            for did,d in self.destinations.items():
                require(d["reserved"]==reserved_dest[did] and d["occupancy"]==occupied_dest[did],"destination accounting")
                require(0<=d["reserved"]+d["occupancy"]<=d["capacity"],"destination capacity")
            for vid,v in self.vehicles.items():
                if v["commitment"] is not None:
                    require(v["commitment"] in self.assignments and self.assignments[v["commitment"]].vehicle_id==vid
                            and self.assignments[v["commitment"]].phase!="completed","vehicle unique commitment")
            return True

    audit=check_invariants
