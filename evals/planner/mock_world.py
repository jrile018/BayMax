"""Synthetic bounded progression adapter, explicitly MOCK routing/ledger.

Routes are declared hand-authored edge catalogs, not computed graph paths. No
repositioning, pickup legs, return-to-base or turnaround is modeled. Idle vehicles
must already be at a request origin. Use the routing worker's production adapter
for product claims. This fixture enforces its supported commitments/conservation.
"""
from __future__ import annotations
import copy
import math
from services.planner.futures.conditional import visible_observations
from services.planner.policies.dispatch import Candidate, PolicyView

class MockWorld:
    label="SYNTHETIC MOCK routing/ledger adapter; declared routes only"
    def __init__(self,snapshot,future):
        self.state=copy.deepcopy(snapshot)
        self.future=copy.deepcopy(future)
        self.time=float(snapshot["time_s"])
        self.start=self.time
        self.roads={e["edge_id"]:e for e in self.state["roads"]}
        self.requests={r["request_id"]:r for r in self.state["requests"]}
        self.vehicles={v["vehicle_id"]:v for v in self.state["vehicles"]}
        self.ledger=self.state["ledger"]
        self.events=[]
        self.personal_observations=[]
        self.arrivals=[]
        self.metrics={k:0 for k in ("safe_arrivals","medical_on_time","medical_completed",
            "supplies_delivered","unmet_goods","unmet_urgent_people","route_failures",
            "constraint_violations","travel_s","stranded_vehicle_s")}
        self.last={v:self.time for v in self.vehicles}
        self.service_end={}
        self.stranded_at={}
        self.route_faults=set()
        self._validate_resources()
        self.initial_urgent_remaining=sum(r["remaining"] for r in self.requests.values() if r["kind"] in ("evacuation","medical"))
        multiplier=self.future["latent"]["travel_delay_multiplier"]
        if not math.isfinite(multiplier) or multiplier<=0:
            raise ValueError("invalid travel multiplier")
        for edge in self.roads.values():
            if not math.isfinite(edge["length_m"]) or edge["length_m"]<=0 or not math.isfinite(edge["travel_time_s"]) or edge["travel_time_s"]<=0:
                raise ValueError("mock edge length and time must be finite positive")
        seen_routes=set()
        for route in self.state["route_catalog"]:
            if not route["edge_ids"] or route["route_id"] in seen_routes:
                raise ValueError("mock routes must have edges and unique IDs")
            seen_routes.add(route["route_id"])
            node=route["start_node"]
            for edge_id in route["edge_ids"]:
                edge=self.roads[edge_id]
                if edge["source"]!=node:
                    raise ValueError("discontinuous declared mock route")
                node=edge["target"]
            if node!=route["destination"]:
                raise ValueError("wrong route destination")
        for vehicle in self.vehicles.values():
            if vehicle["phase"]=="traveling":
                edge=self.roads[vehicle["current_edge_id"]]
                if not 0<=vehicle["progress_m"]<edge["length_m"]:
                    raise ValueError("invalid preserved edge progress")


    def _validate_resources(self):
        def quantity(value,label):
            if isinstance(value,bool) or not isinstance(value,int) or value<0:
                raise ValueError(label+" must be a nonnegative integer")
        if len(self.roads)!=len(self.state["roads"]) or len(self.requests)!=len(self.state["requests"]) or len(self.vehicles)!=len(self.state["vehicles"]):
            raise ValueError("duplicate IDs in known snapshot")
        quantity(self.ledger["stock"],"stock")
        for r in self.requests.values():
            if r["kind"] not in ("evacuation","medical","supply"):
                raise ValueError("unsupported request kind")
            quantity(r["quantity"],"request quantity")
            quantity(r["remaining"],"request remaining")
            if r["remaining"]>r["quantity"]:
                raise ValueError("remaining demand exceeds original demand")
            if not math.isfinite(r["service_s"]) or r["service_s"]<0:
                raise ValueError("invalid service duration")
            if r["deadline_s"] is not None and (not math.isfinite(r["deadline_s"]) or r["deadline_s"]<0):
                raise ValueError("invalid deadline")
        for rid,n in self.ledger["reservations"].items():
            quantity(n,"reservation")
            if rid not in self.requests or n!=self.requests[rid]["remaining"]:
                raise ValueError("reservation must match a remaining request")
        for dest,capacity in self.ledger["destination_capacity"].items():
            quantity(capacity,"destination capacity")
            occupied=self.ledger["occupancy"].get(dest,0)
            quantity(occupied,"destination occupancy")
            reserved=sum(n for rid,n in self.ledger["reservations"].items() if self.requests[rid]["destination"]==dest)
            if occupied+reserved>capacity:
                raise ValueError("destination is overreserved")
        assigned=set()
        for v in self.vehicles.values():
            quantity(v["capacity"],"vehicle capacity")
            for n in v["load"].values(): quantity(n,"vehicle load")
            if sum(v["load"].values())>v["capacity"]:
                raise ValueError("vehicle load exceeds capacity")
            if v["request_id"] is not None:
                rid=v["request_id"]
                if rid in assigned or rid not in self.requests:
                    raise ValueError("invalid or duplicate vehicle commitment")
                assigned.add(rid)
                if self.ledger["reservations"].get(rid)!=sum(v["load"].values()):
                    raise ValueError("committed load does not match reservation")
            elif sum(v["load"].values()):
                raise ValueError("unassigned vehicle carries aid")
        if assigned!=set(self.ledger["reservations"]):
            raise ValueError("reservation has no committed vehicle")

    def _observations(self):
        return sorted(visible_observations(self.future,self.time)+
                      copy.deepcopy(self.personal_observations),
                      key=lambda o:(o["received_at_s"],o["event_id"]))

    def _known_closed(self):
        closed=set()
        for o in self._observations():
            if o["kind"]=="road_closed":
                closed.add(o["edge_id"])
            elif o["kind"]=="road_open":
                closed.discard(o["edge_id"])
        return closed

    def policy_view(self):
        closed=self._known_closed()
        forecasts={}
        observations=self._observations()
        for o in observations:
            if o["kind"]=="forecast" and "closes_at_s" in o:
                forecasts[o["edge_id"]]=o["closes_at_s"]
        candidates=[]
        for v in self.vehicles.values():
            if v["phase"] not in ("idle","waiting"):
                continue
            for r in self.requests.values():
                underway=v["phase"]=="waiting"
                if underway and v["request_id"]!=r["request_id"]:
                    continue
                if r["remaining"]<=0 or (not underway and v["node_id"]!=r["origin"]):
                    continue
                if not underway and r["request_id"] in self.ledger["reservations"]:
                    continue
                if {"evacuation":"bus","medical":"ambulance","supply":"truck"}[r["kind"]]!=v["type"]:
                    continue
                qty=r["remaining"]
                if qty>v["capacity"]:
                    continue
                if not underway and r["kind"]=="supply" and qty>self.ledger["stock"]:
                    continue
                reserved=sum(n for rid,n in self.ledger["reservations"].items()
                             if self.requests[rid]["destination"]==r["destination"])
                free=self.ledger["destination_capacity"][r["destination"]]-self.ledger["occupancy"][r["destination"]]-reserved
                if not underway and qty>free:
                    continue
                for route in self.state["route_catalog"]:
                    if route["start_node"]!=v["node_id"] or route["destination"]!=r["destination"]:
                        continue
                    t=self.time
                    margins=[]
                    for eid in route["edge_ids"]:
                        if eid in closed:
                            break
                        t+=self.roads[eid]["travel_time_s"]
                        if eid in forecasts:
                            margins.append(forecasts[eid]-t-1.0)
                    else:
                        margin=min(margins) if margins else None
                        if margin is not None and margin<0:
                            continue
                        candidates.append(Candidate(
                            action_id=f'{v["vehicle_id"]}:{r["request_id"]}:{route["route_id"]}:{self.time:g}',
                            vehicle_id=v["vehicle_id"],request_id=r["request_id"],kind=r["kind"],
                            quantity=qty,arrival_time_s=t+r["service_s"],deadline_s=r["deadline_s"],
                            travel_s=t-self.time,route_id=route["route_id"],forecast_margin_s=margin))
        return PolicyView(time_s=self.time,observations=tuple(observations),candidates=tuple(candidates))

    def commit(self,candidate):
        if candidate not in self.policy_view().candidates:
            raise ValueError("stale or infeasible mock dispatch")
        v=self.vehicles[candidate.vehicle_id]; r=self.requests[candidate.request_id]
        route=next(p for p in self.state["route_catalog"] if p["route_id"]==candidate.route_id)
        person_ids=[]
        if v["phase"]=="idle" and r["kind"]=="evacuation":
            person_ids=r.get("person_ids",[])
            if len(person_ids)!=candidate.quantity or len(set(person_ids))!=len(person_ids) or any(
                self.ledger["person_locations"].get(person)!=f'origin:{r["origin"]}' for person in person_ids):
                raise ValueError("evacuees must be uniquely present at their origin")
        if v["phase"]=="idle":
            self.ledger["reservations"][r["request_id"]]=candidate.quantity
            key={"evacuation":"people","medical":"patients","supply":"supplies"}[r["kind"]]
            if r["kind"]=="supply":
                self.ledger["stock"]-=candidate.quantity
            v["load"][key]=candidate.quantity
            v["request_id"]=r["request_id"]
            for person in person_ids:
                self.ledger["person_locations"][person]=f'vehicle:{v["vehicle_id"]}'
        v["phase"]="traveling"
        v["current_edge_id"]=route["edge_ids"][0]
        v["remaining_path"]=list(route["edge_ids"][1:])
        v["progress_m"]=0
        v["node_id"]=None
        v["route_id"]=route["route_id"]
        self.events.append({"kind":"dispatch","time_s":self.time,"vehicle_id":v["vehicle_id"],
                            "request_id":r["request_id"],"route_id":route["route_id"]})

    def _closure_time(self,edge_id,entry,exit):
        # Initial known access is authoritative. Future physical changes are
        # evaluator-only; a physical encounter produces a driver observation.
        closed=False
        for o in sorted(self.future["initial_snapshot"]["observations"],key=lambda o:(o["received_at_s"],o["event_id"])):
            if o.get("edge_id")==edge_id:
                if o["kind"]=="road_closed": closed=True
                if o["kind"]=="road_open": closed=False
        for ev in sorted(self.future["truth_events"],key=lambda e:(e["time_s"],e["event_id"])):
            if ev["edge_id"]!=edge_id:
                continue
            if ev["time_s"]<=entry:
                closed=ev["kind"]=="road_closed"
            elif ev["time_s"]<=exit and ev["kind"]=="road_closed":
                return entry if closed else ev["time_s"]
        return entry if closed else None

    def _fault(self,v,time_s,edge_id,in_edge):
        fault=(v["vehicle_id"],edge_id)
        if fault not in self.route_faults:
            self.route_faults.add(fault)
            self.metrics["route_failures"]+=1
            event_id=f'physical:{v["vehicle_id"]}:{edge_id}:{time_s:g}'
            self.personal_observations.append({"event_id":event_id,"kind":"road_closed",
                "edge_id":edge_id,"issued_at_s":time_s,"received_at_s":time_s,
                "source":"mock physical driver encounter"})
            self.events.append({"kind":"stranded" if in_edge else "blocked_at_node",
                "time_s":time_s,"vehicle_id":v["vehicle_id"],"edge_id":edge_id,
                "progress_m":v["progress_m"],"load":copy.deepcopy(v["load"])})
        if in_edge:
            v["phase"]="stranded"
            self.stranded_at[v["vehicle_id"]]=time_s
        else:
            v["phase"]="waiting"
            v["node_id"]=self.roads[edge_id]["source"]
            v["current_edge_id"]=None
            v["progress_m"]=0

    def _complete(self,v,time_s):
        r=self.requests[v["request_id"]]
        if r["request_id"] in self.ledger["delivered"]:
            raise ValueError("duplicate service")
        qty=self.ledger["reservations"].pop(r["request_id"])
        self.ledger["delivered"][r["request_id"]]=qty
        self.ledger["occupancy"][r["destination"]]+=qty
        r["remaining"]-=qty
        if r["kind"]=="evacuation":
            self.metrics["safe_arrivals"]+=qty
            for person,location in self.ledger["person_locations"].items():
                if location==f'vehicle:{v["vehicle_id"]}':
                    self.ledger["person_locations"][person]=f'destination:{r["destination"]}'
        elif r["kind"]=="medical":
            self.metrics["medical_completed"]+=qty
            if r["deadline_s"] is None or time_s<=r["deadline_s"]:
                self.metrics["medical_on_time"]+=qty
        else:
            self.metrics["supplies_delivered"]+=qty
        self.arrivals.append(time_s)
        self.events.append({"kind":"service_completed","time_s":time_s,
                            "vehicle_id":v["vehicle_id"],"request_id":r["request_id"],"quantity":qty})
        v["load"]={"people":0,"patients":0,"supplies":0}
        v["phase"]="idle"
        v["request_id"]=None

    def _advance_vehicle(self,v,target):
        now=self.last[v["vehicle_id"]]
        while now<target:
            if v["phase"]=="servicing":
                end=self.service_end[v["vehicle_id"]]
                if end>target:
                    break
                self._complete(v,end)
                now=end
                continue
            if v["phase"]!="traveling":
                break
            eid=v["current_edge_id"]; edge=self.roads[eid]
            duration=edge["travel_time_s"]*self.future["latent"]["travel_delay_multiplier"]
            speed=edge["length_m"]/duration
            exit=now+(edge["length_m"]-v["progress_m"])/speed
            closure=self._closure_time(eid,now,min(exit,target))
            if closure is not None:
                elapsed=max(0,closure-now)
                v["progress_m"]+=elapsed*speed
                self.metrics["travel_s"]+=elapsed
                self._fault(v,closure,eid,v["progress_m"]>0)
                now=closure
                break
            until=min(exit,target)
            self.metrics["travel_s"]+=until-now
            v["progress_m"]+=speed*(until-now)
            now=until
            if exit>target:
                break
            v.setdefault("completed_trail",[]).append({"edge_id":eid,"exit_time_s":exit})
            v["node_id"]=edge["target"]
            v["current_edge_id"]=None
            v["progress_m"]=0
            if v["remaining_path"]:
                nex=v["remaining_path"].pop(0)
                if self.roads[nex]["source"]!=v["node_id"]:
                    raise ValueError("continuation does not preserve reached node")
                v["current_edge_id"]=nex
                v["node_id"]=None
            else:
                v["phase"]="servicing"
                r=self.requests[v["request_id"]]
                end=now+r["service_s"]
                self.service_end[v["vehicle_id"]]=end
                if end<=target:
                    self._complete(v,end)
                    now=end
        self.last[v["vehicle_id"]]=target

    def advance_to(self,time_s):
        if not math.isfinite(time_s) or time_s<self.time:
            raise ValueError("clock must advance monotonically")
        for v in self.vehicles.values():
            self._advance_vehicle(v,time_s)
        self.time=time_s
        self.state["time_s"]=time_s

    def outcome(self):
        metrics=copy.deepcopy(self.metrics)
        metrics["unmet_goods"]=sum(r["remaining"] for r in self.requests.values() if r["kind"]=="supply")
        metrics["unmet_urgent_people"]=self.initial_urgent_remaining-metrics["safe_arrivals"]-metrics["medical_on_time"]
        metrics["stranded_vehicle_s"]=sum(self.time-t for t in self.stranded_at.values())
        return {"metrics":metrics,"arrival_times_s":list(self.arrivals),
                "events":copy.deepcopy(self.events),"final_state":copy.deepcopy(self.state)}
