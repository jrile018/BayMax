"""Synthetic practice physics and a separate, recipient-specific knowledge view.

Training assumptions are editable; this adapter is not the production hazard/router.
"""
from __future__ import annotations
import copy
import hashlib
import heapq
import json
import math
from collections import defaultdict


class TrainingWorld:
    def __init__(self, situation, future):
        self.situation = copy.deepcopy(situation)
        self.future = copy.deepcopy(future)
        self.time_s = float(situation.get("time_s", 0))
        self.horizon_end_s = float(future["horizon_end_s"])
        self.command_id = situation.get("command_id", "command")
        if future.get("start_time_s", self.time_s) != self.time_s:
            raise ValueError("future start disagrees with situation")
        if "initial_snapshot" in future and future["initial_snapshot"] != situation:
            raise ValueError("future does not preserve initial situation")
        if not math.isfinite(self.horizon_end_s) or self.horizon_end_s < self.time_s:
            raise ValueError("invalid horizon")
        if future.get("scenario_id") != situation.get("scenario_id"):
            raise ValueError("future belongs to a different situation")
        self.roads = {r["id"]: copy.deepcopy(r) for r in situation["roads"]}
        self.vehicles = {v["id"]: dict(copy.deepcopy(v), status="idle", load=0, edge_id=None, edge_progress=0) for v in situation["vehicles"]}
        self.facilities = {f["id"]: dict(copy.deepcopy(f), failed=False, occupied=0, reserved=0) for f in situation["facilities"]}
        self.requests = {r["id"]: dict(copy.deepcopy(r), delivered=0, reserved=0) for r in situation["requests"]}
        self.stock = situation.get("stocks", {}).get("supplies", 100)
        self.travel_multiplier = float(future.get("travel_multiplier", 1))
        if not math.isfinite(self.travel_multiplier) or self.travel_multiplier <= 0:
            raise ValueError("invalid travel multiplier")
        nodes = {n["id"] for n in situation["nodes"]}
        for rows, name in [(situation["roads"],"roads"),(situation["vehicles"],"vehicles"),(situation["facilities"],"facilities"),(situation["requests"],"requests")]:
            if len(rows) != len({r["id"] for r in rows}):
                raise ValueError("duplicate " + name)
        for road in self.roads.values():
            if road["source"] not in nodes or road["target"] not in nodes or not math.isfinite(road["travel_s"]) or road["travel_s"] <= 0:
                raise ValueError("invalid road")
        for resource in list(self.vehicles.values()) + list(self.facilities.values()):
            if resource["node_id"] not in nodes or not isinstance(resource["capacity"],int) or isinstance(resource["capacity"],bool) or resource["capacity"] <= 0:
                raise ValueError("invalid resource")
        for request in self.requests.values():
            self._validate_request(request, nodes)
        self.truth_events = sorted(copy.deepcopy(future.get("truth_events", [])), key=lambda e:(e["time_s"],e["id"]))
        for event in self.truth_events:
            if not math.isfinite(event["time_s"]) or event["time_s"] < self.time_s or event["time_s"] > self.horizon_end_s:
                raise ValueError("invalid physical event time")
            if event["kind"] == "road_closed" and event["edge_id"] not in self.roads:
                raise ValueError("unknown physical road")
            if event["kind"] == "facility_failed" and event["facility_id"] not in self.facilities:
                raise ValueError("unknown physical facility")
            if event["kind"] == "request_created":
                self._validate_request(event["request"], nodes)
        self.observation_events = copy.deepcopy(future.get("observation_events", []))
        self._validate_observations(self.observation_events)
        self._truth_index = 0
        self.closed = set()
        self.trips = {}
        self.commands = []
        self.events = []
        self.arrival_times_s = []
        self.metrics = {k:0 for k in ["safe_arrivals","medical_on_time","medical_completed","supplies_delivered","route_failures","constraint_violations","travel_s","stranded_vehicle_s"]}
        self._apply_truth()

    def _validate_request(self, request, nodes):
        if request["node_id"] not in nodes or request["destination_id"] not in self.facilities or request["kind"] not in {"medical","evacuation","supply"} or isinstance(request["quantity"],bool) or not isinstance(request["quantity"],int) or request["quantity"] <= 0:
            raise ValueError("invalid request")
        deadline = request.get("deadline_s")
        if deadline is not None and (not math.isfinite(deadline) or deadline < 0):
            raise ValueError("invalid request deadline")

    @staticmethod
    def _validate_observations(observations):
        for obs in observations:
            issued = obs.get("issued_at_s", obs.get("time_s", 0))
            received = obs["received_at_s"]
            happened = obs.get("time_s", issued)
            if not math.isfinite(happened) or happened < 0 or happened > issued or not math.isfinite(issued) or not math.isfinite(received) or issued < 0 or received < issued or not obs.get("recipient_id"):
                raise ValueError("invalid observation timing/recipient")

    def _received(self, recipient):
        rows = []
        for raw in self.observation_events:
            if raw["recipient_id"] == recipient and raw["received_at_s"] <= self.time_s:
                row = copy.deepcopy(raw)
                row = dict(row.get("payload", {}), **row)
                row.pop("payload", None)
                rows.append(row)
        return sorted(rows, key=lambda e:(e["received_at_s"],e.get("id","")))

    def knowledge(self, recipient_id=None):
        recipient = recipient_id or self.command_id
        obs = self._received(recipient)
        informed = set(self.situation.get("communications", {}).get("initially_informed", []))
        known = {r["id"]: dict(copy.deepcopy(r),delivered=0,reserved=0) for r in self.situation["requests"] if recipient == r.get("source_id") or recipient in r.get("initial_received_by", []) or (recipient == self.command_id and r.get("source_id") in informed)}
        resources = {v["id"]: dict(copy.deepcopy(v),status="idle") for v in self.situation["vehicles"]}
        facilities = {f["id"]: dict(copy.deepcopy(f),failed=False,occupied=0,reserved=0) for f in self.situation["facilities"]}
        stock = self.situation.get("stocks", {}).get("supplies",100)
        # A dispatch is command's own knowledge. Completion/failure needs a report.
        completed = set()
        for row in obs:
            if row["kind"] == "request_created" and "request" in row:
                request = row["request"]
                known.setdefault(request["id"],dict(copy.deepcopy(request),delivered=0,reserved=0))
            if row["kind"] == "facility_failed":
                facilities[row["facility_id"]]["failed"] = True
            if row["kind"] == "service_completed":
                completed.add(row["action_id"])
        if recipient == self.command_id:
            for cmd in self.commands:
                a = cmd["action"]
                resources[a["vehicle_id"]]["status"] = "busy"
                if a["kind"] == "dispatch":
                    if a["request_id"] in known:
                        known[a["request_id"]]["reserved"] += a["quantity"]
                    facilities[a["destination_id"]]["reserved"] += a["quantity"]
                    if a["request_kind"] == "supply": stock -= a["quantity"]
                for row in obs:
                    if row.get("action_id") != a["id"]: continue
                    if row["kind"] in {"service_completed","reposition_completed"}:
                        resources[a["vehicle_id"]].update(status="idle",node_id=row["node_id"])
                        if a["kind"] == "dispatch":
                            request = known[a["request_id"]]
                            request["reserved"] -= a["quantity"]
                            request["delivered"] += a["quantity"]
                            facilities[a["destination_id"]]["reserved"] -= a["quantity"]
                            facilities[a["destination_id"]]["occupied"] += a["quantity"]
                    elif row["kind"] == "trip_failed":
                        resources[a["vehicle_id"]].update(status="stranded",node_id=row["node_id"])
                        if a["kind"]=="dispatch" and row.get("loaded") is False:
                            known[a["request_id"]]["reserved"]-=a["quantity"]
                            facilities[a["destination_id"]]["reserved"]-=a["quantity"]
                            if a["request_kind"]=="supply": stock+=a["quantity"]
        for request in known.values():
            request["remaining"] = max(0,request["quantity"]-request["delivered"]-request["reserved"])
        return copy.deepcopy({"time_s":self.time_s,"recipient_id":recipient,"severity":self.situation["severity"],"assumptions":self.situation.get("assumptions",{}),"goals":self.situation.get("goals",{}),"nodes":self.situation["nodes"],"roads":list(self.roads.values()),"resources":list(resources.values()),"facilities":list(facilities.values()),"requests":list(known.values()),"observations":obs,"stocks":{"supplies":stock},"coverage_by_vehicle":{v["id"]:self._covered(v,{o["edge_id"] for o in obs if o["kind"]=="road_closed"}) for v in resources.values()}})

    def _path(self, start, end, closed):
        queue = [(0,start,())]; best = {start:0}
        graph = defaultdict(list)
        for edge in self.roads.values():
            if edge["id"] not in closed: graph[edge["source"]].append(edge)
        while queue:
            distance,node,path = heapq.heappop(queue)
            if distance > best[node]: continue
            if node == end: return list(path),distance
            for edge in sorted(graph[node],key=lambda e:e["id"]):
                d = distance+edge["travel_s"]
                if d < best.get(edge["target"],math.inf):
                    best[edge["target"]]=d; heapq.heappush(queue,(d,edge["target"],path+(edge["id"],)))
        return None

    def _covered(self, vehicle, closed):
        threshold=self.situation.get("goals",{}).get("coverage_threshold_s",self.situation.get("assumptions",{}).get("coverage_threshold_s",60))
        if vehicle["status"] != "idle": return []
        return [n["id"] for n in self.situation["nodes"] if n["kind"]=="camp" and (p:=self._path(vehicle["node_id"],n["id"],closed)) is not None and p[1]<=threshold]

    def _coverage(self, resources, closed):
        threshold = self.situation.get("goals",{}).get("coverage_threshold_s",self.situation.get("assumptions",{}).get("coverage_threshold_s",60))
        camps = [n["id"] for n in self.situation["nodes"] if n["kind"] == "camp"]
        return sum(any(v["status"] == "idle" and (p:=self._path(v["node_id"],camp,closed)) is not None and p[1] <= threshold for v in resources) for camp in camps)

    def _action(self, **data):
        identity = json.dumps(dict(data,at=self.time_s),sort_keys=True,separators=(",",":"))
        data["id"] = hashlib.sha256(identity.encode()).hexdigest()[:16]
        data["feasible"] = True
        return data

    def actions(self):
        wait = {"id":"wait","kind":"wait","vehicle_id":None,"request_id":None,"quantity":0,"route":[],"destination_id":None,"travel_s":0,"expected_urgent":0,"expected_supply":0,"coverage_delta":0,"protection_delta":0,"feasible":True,"explanation":"Wait for information or keep response capacity available."}
        if self.time_s >= self.horizon_end_s: return [wait]
        view = self.knowledge()
        closed = {o["edge_id"] for o in view["observations"] if o["kind"]=="road_closed"}
        before = self._coverage(view["resources"],closed)
        p_fail = view["assumptions"].get("road_failure_probability",0.15)
        options = []
        allowed = {"ambulance":{"medical"},"bus":{"evacuation"},"truck":{"supply"}}
        for vehicle in view["resources"]:
            if vehicle["status"] != "idle": continue
            after = copy.deepcopy(view["resources"])
            next(v for v in after if v["id"]==vehicle["id"])["status"] = "busy"
            coverage_delta = self._coverage(after,closed)-before
            for request in view["requests"]:
                if request["remaining"] <= 0 or request["kind"] not in allowed.get(vehicle["kind"],set()): continue
                pickup = self._path(vehicle["node_id"],request["node_id"],closed)
                if pickup is None: continue
                for facility in view["facilities"]:
                    matches = facility["kind"] in {request["kind"],{"medical":"clinic","evacuation":"shelter","supply":"depot"}[request["kind"]]}
                    if not matches or facility["failed"]: continue
                    free = facility["capacity"]-facility["occupied"]-facility["reserved"]
                    quantity = min(vehicle["capacity"],request["remaining"],free)
                    if request["kind"]=="supply": quantity=min(quantity,view["stocks"]["supplies"])
                    if quantity <= 0: continue
                    delivery = self._path(request["node_id"],facility["node_id"],closed)
                    if delivery is None: continue
                    routes = [delivery]
                    for eid in delivery[0]:
                        alternative = self._path(request["node_id"],facility["node_id"],closed|{eid})
                        if alternative is not None and alternative[0] not in [r[0] for r in routes]: routes.append(alternative)
                        if len(routes)>=2: break
                    for route,duration in routes:
                        full = pickup[0]+route
                        travel = pickup[1]+duration
                        multiplier_range = view["assumptions"].get("travel_multiplier_range",[1,1])
                        expected_arrival=self.time_s+travel*sum(multiplier_range)/2+2
                        on_time = request.get("deadline_s") is None or expected_arrival<=request["deadline_s"]
                        probability = (1-p_fail)**len({self.roads[e].get("physical_id",e) for e in full})
                        urgent = quantity*probability if request["kind"] in {"medical","evacuation"} else 0
                        options.append(self._action(kind="dispatch",vehicle_id=vehicle["id"],request_id=request["id"],request_kind=request["kind"],quantity=quantity,route=full,pickup_index=len(pickup[0]),destination_id=facility["id"],destination_node=facility["node_id"],travel_s=travel,deadline_s=request.get("deadline_s"),expected_on_time=quantity*probability*on_time,expected_urgent=urgent,expected_supply=quantity*probability if request["kind"]=="supply" else 0,coverage_delta=coverage_delta,covered_camps_after=[],protection_delta=-(1-probability)*quantity,explanation=f"Serve {quantity} {request['kind']} need(s); leave {before+coverage_delta} camps covered; route success assumption {probability:.2f}; estimated service {expected_arrival:.1f}s, deadline {request.get("deadline_s")}, expected on-time {on_time}."))
            for node in view["nodes"]:
                if node["id"]==vehicle["node_id"]: continue
                path = self._path(vehicle["node_id"],node["id"],closed)
                if path is None: continue
                repositioned=copy.deepcopy(view["resources"])
                next(v for v in repositioned if v["id"]==vehicle["id"])["node_id"]=node["id"]
                delta=self._coverage(repositioned,closed)-before
                if delta<=0: continue
                options.append(self._action(kind="reposition",vehicle_id=vehicle["id"],request_id=None,quantity=0,route=path[0],pickup_index=0,destination_id=node["id"],destination_node=node["id"],travel_s=path[1],expected_urgent=0,expected_supply=0,coverage_delta=delta,covered_camps_after=self._covered(next(v for v in repositioned if v["id"]==vehicle["id"]),closed),protection_delta=-(1-(1-p_fail)**len(path[0])),explanation=f"Position at {node['id']} to cover {delta} additional camps after arrival."))
        return sorted(options,key=lambda a:a["id"])+[wait]

    def commit(self, action_id):
        action = next((a for a in self.actions() if a["id"]==action_id),None)
        if action is None: raise ValueError("stale or unavailable action")
        if action["kind"]=="wait": return
        vehicle=self.vehicles[action["vehicle_id"]]
        if vehicle["status"]!="idle": raise ValueError("vehicle unavailable")
        if action["kind"]=="dispatch":
            request=self.requests[action["request_id"]]
            facility=self.facilities[action["destination_id"]]
            if request["quantity"]-request["delivered"]-request["reserved"]<action["quantity"] or facility["capacity"]-facility["occupied"]-facility["reserved"]<action["quantity"]:
                raise ValueError("insufficient resource")
            if action["request_kind"]=="supply" and self.stock<action["quantity"]: raise ValueError("insufficient stock")
            request["reserved"]+=action["quantity"]; facility["reserved"]+=action["quantity"]
            if action["request_kind"]=="supply": self.stock-=action["quantity"]
        vehicle["status"]="busy"
        trip={"action":copy.deepcopy(action),"index":0,"edge_remaining_s":None,"service_until_s":None,"loaded":False,"failed_at_s":None}
        self.trips[vehicle["id"]]=trip
        self.commands.append({"time_s":self.time_s,"action":copy.deepcopy(action)})
        self.events.append({"kind":"action_committed","time_s":self.time_s,"action":copy.deepcopy(action)})
        self._start_leg(vehicle,trip)

    def _fact(self, kind, vehicle, trip, **payload):
        from services.planner.futures.information import diffuse_information
        action=trip["action"]
        fact=dict(payload,id=f"{action['id']}-{kind}",kind=kind,time_s=self.time_s,issued_at_s=self.time_s,source_id=vehicle["id"],action_id=action["id"],vehicle_id=vehicle["id"],node_id=vehicle["node_id"])
        source_event=dict(fact,payload=copy.deepcopy(fact))
        rows=diffuse_information([source_event],self.situation["communications"],self.horizon_end_s,0)
        self.observation_events.extend(rows)
        self.events.append(fact)

    def _fail(self, vehicle,trip,reason):
        if vehicle["status"]=="stranded": return
        vehicle["status"]="stranded"; trip["failed_at_s"]=self.time_s
        self.metrics["route_failures"]+=1
        action=trip["action"]
        if action["kind"]=="dispatch" and not trip["loaded"]:
            self.requests[action["request_id"]]["reserved"]-=action["quantity"]
            self.facilities[action["destination_id"]]["reserved"]-=action["quantity"]
            if action["request_kind"]=="supply": self.stock+=action["quantity"]
        self._fact("trip_failed",vehicle,trip,reason=reason,loaded=trip["loaded"])
        if reason=="road_closed": self._fact("road_closed",vehicle,trip,edge_id=vehicle["edge_id"])

    def _start_leg(self,vehicle,trip):
        action=trip["action"]
        if action["kind"]=="dispatch" and not trip["loaded"] and trip["index"]>=action["pickup_index"]:
            trip["loaded"]=True; vehicle["load"]=action["quantity"]
        if trip["index"]==len(action["route"]):
            vehicle["edge_id"]=None; vehicle["edge_progress"]=0
            if action["kind"]=="reposition": self._complete(vehicle,trip)
            elif self.facilities[action["destination_id"]]["failed"]: self._fail(vehicle,trip,"facility_failed")
            else: trip["service_until_s"]=self.time_s+2
            return
        edge=self.roads[action["route"][trip["index"]]]
        vehicle["edge_id"]=edge["id"]; vehicle["edge_progress"]=0
        if edge["id"] in self.closed: self._fail(vehicle,trip,"road_closed"); return
        if vehicle["node_id"]!=edge["source"]: raise ValueError("disconnected physical route")
        trip["edge_remaining_s"]=edge["travel_s"]*self.travel_multiplier
        trip["edge_exit_at_s"]=self.time_s+trip["edge_remaining_s"]

    def _complete(self,vehicle,trip):
        action=trip["action"]
        if action["kind"]=="dispatch":
            facility=self.facilities[action["destination_id"]]
            if facility["failed"]: self._fail(vehicle,trip,"facility_failed"); return
            request=self.requests[action["request_id"]]; quantity=action["quantity"]
            request["reserved"]-=quantity; request["delivered"]+=quantity
            facility["reserved"]-=quantity; facility["occupied"]+=quantity
            if request["kind"]=="medical":
                self.metrics["medical_completed"]+=quantity
                if request.get("deadline_s") is None or self.time_s<=request["deadline_s"]: self.metrics["medical_on_time"]+=quantity
            elif request["kind"]=="evacuation": self.metrics["safe_arrivals"]+=quantity
            else: self.metrics["supplies_delivered"]+=quantity
            self.arrival_times_s.append(self.time_s)
            kind="service_completed"
        else: kind="reposition_completed"
        vehicle.update(status="idle",load=0,edge_id=None,edge_progress=0)
        self._fact(kind,vehicle,trip)
        self.trips.pop(vehicle["id"],None)

    def _apply_truth(self):
        while self._truth_index<len(self.truth_events) and self.truth_events[self._truth_index]["time_s"]<=self.time_s:
            event=self.truth_events[self._truth_index]; self._truth_index+=1
            kind=event["kind"]
            if kind=="road_closed":
                self.closed.add(event["edge_id"])
                for vehicle in self.vehicles.values():
                    if vehicle["status"]=="busy" and vehicle["edge_id"]==event["edge_id"]: self._fail(vehicle,self.trips[vehicle["id"]],"road_closed")
            elif kind=="facility_failed": self.facilities[event["facility_id"]]["failed"]=True
            elif kind=="request_created":
                request=event["request"]
                if request["id"] in self.requests: raise ValueError("duplicate incident")
                self.requests[request["id"]]=dict(copy.deepcopy(request),delivered=0,reserved=0)
            else: raise ValueError("unsupported physical event")
            self.events.append(copy.deepcopy(event))

    def advance_to(self,time_s):
        if not isinstance(time_s,(int,float)) or not math.isfinite(time_s) or time_s<self.time_s or time_s>self.horizon_end_s:
            raise ValueError("invalid advance time")
        while self.time_s<time_s:
            next_time=time_s
            if self._truth_index<len(self.truth_events): next_time=min(next_time,self.truth_events[self._truth_index]["time_s"])
            for vehicle_id,trip in self.trips.items():
                if self.vehicles[vehicle_id]["status"]!="busy": continue
                if trip["service_until_s"] is not None: next_time=min(next_time,trip["service_until_s"])
                elif trip["edge_remaining_s"] is not None: next_time=min(next_time,trip["edge_exit_at_s"])
            delta=next_time-self.time_s
            for vehicle_id,trip in list(self.trips.items()):
                vehicle=self.vehicles[vehicle_id]
                if vehicle["status"]=="stranded": self.metrics["stranded_vehicle_s"]+=delta
                elif trip["service_until_s"] is None and trip["edge_remaining_s"] is not None:
                    trip["edge_remaining_s"]=max(0,trip["edge_exit_at_s"]-next_time)
                    duration=self.roads[vehicle["edge_id"]]["travel_s"]*self.travel_multiplier
                    vehicle["edge_progress"]=1-trip["edge_remaining_s"]/duration
                    self.metrics["travel_s"]+=delta
            self.time_s=next_time
            # Traversal occupies [entry, exit); leave before closures at exact exit.
            exited=set()
            for vehicle_id,trip in list(self.trips.items()):
                vehicle=self.vehicles[vehicle_id]
                if vehicle["status"]=="busy" and trip["service_until_s"] is None and trip["edge_remaining_s"] is not None and trip["edge_remaining_s"]<=0:
                    edge=self.roads[vehicle["edge_id"]];vehicle["node_id"]=edge["target"]
                    vehicle.update(edge_id=None,edge_progress=0)
                    trip["index"]+=1;trip["edge_remaining_s"]=None
                    exited.add(vehicle_id)
            # Failures precede new edge entry and service at the same instant.
            self._apply_truth()
            for vehicle_id,trip in list(self.trips.items()):
                vehicle=self.vehicles[vehicle_id]
                if vehicle["status"]!="busy": continue
                if trip["service_until_s"] is not None and trip["service_until_s"]<=self.time_s:
                    self._complete(vehicle,trip)
                elif vehicle_id in exited:
                    self._start_leg(vehicle,trip)
        return self.knowledge()

    def step(self,action_id):
        self.commit(action_id)
        self.advance_to(min(self.horizon_end_s,self.time_s+15))
        return {"knowledge":self.knowledge(),"actions":self.actions()}

    def outcome(self):
        metrics=dict(self.metrics)
        metrics["unmet_urgent_people"]=sum(r["quantity"]-r["delivered"] for r in self.requests.values() if r["kind"] in {"medical","evacuation"})
        metrics["unmet_goods"]=sum(r["quantity"]-r["delivered"] for r in self.requests.values() if r["kind"]=="supply")
        return copy.deepcopy({"metrics":metrics,"arrival_times_s":self.arrival_times_s,"events":self.events,"final_state":{"time_s":self.time_s,"vehicles":list(self.vehicles.values()),"requests":list(self.requests.values()),"facilities":list(self.facilities.values()),"closed_roads":sorted(self.closed),"stocks":{"supplies":self.stock}}})
