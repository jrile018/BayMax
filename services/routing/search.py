"""Nonnegative Dijkstra reference plus explicitly bounded safe candidate search."""
import heapq
from hashlib import sha256
from time import perf_counter
from .models import Route, Leg, Exclusion, SearchResult, finite_nonnegative

def _record(graph,start,end,kind,departure,edge_ids,safety,version,validated,algorithm,status="feasible"):
    clock=departure
    legs=[]
    for eid in edge_ids:
        edge=graph.edges[eid]
        exit_s=finite_nonnegative(clock+edge.travel_s,"accumulated arrival_s")
        legs.append(Leg(eid,clock,exit_s,edge.length_m))
        clock=exit_s
    token=f"{graph.version}|{safety.version if safety else 'none'}|{kind}|{start}|{end}|{departure}|{edge_ids}|{version}"
    return Route("route-"+sha256(token.encode()).hexdigest()[:16],version,status,start,end,kind,departure,
                 clock if status=="feasible" else None,tuple(edge_ids),tuple(legs),graph.geometry_for(edge_ids),
                 finite_nonnegative(sum(graph.edges[eid].length_m for eid in edge_ids),"route distance"),graph.version,
                 safety.version if safety else "none",validated,algorithm,
                 safety.issued_s if safety else None,safety.horizon_s if safety else None)

def static_reference(graph,start,end,vehicle_kind,departure_s,safety=None,route_version=1):
    graph.validate_nodes(start,end,vehicle_kind)
    departure=finite_nonnegative(departure_s,"departure_s")
    if safety and departure<safety.known_at_s:
        raise ValueError("departure precedes available snapshot")
    if safety and not safety.operational_enabled:
        return _record(graph,start,end,vehicle_kind,departure,(),safety,route_version,False,
                       "static_dijkstra","no_feasible_candidate")
    queue=[(0.0,(),start)]
    best={start:(0.0,())}
    while queue:
        cost,path,node=heapq.heappop(queue)
        if best.get(node)!=(cost,path):
            continue
        if node==end:
            return _record(graph,start,end,vehicle_kind,departure,path,safety,route_version,False,"static_dijkstra")
        for edge in graph.outgoing[node]:
            if vehicle_kind not in edge.access or (safety and not safety.open_now(edge.edge_id,departure)):
                continue
            item=(finite_nonnegative(cost+edge.travel_s,"accumulated cost"),path+(edge.edge_id,))
            # Never accept equal-cost cyclic revisits (zero-cost cycles included).
            old=best.get(edge.target)
            if old is None or item[0]<old[0]:
                best[edge.target]=item
                heapq.heappush(queue,(*item,edge.target))
    return _record(graph,start,end,vehicle_kind,departure,(),safety,route_version,False,
                   "static_dijkstra","unreachable_static")

def candidate_routes(graph,start,end,vehicle_kind,departure_s,safety,*,max_expansions=1000,max_candidates=3,route_version=1):
    graph.validate_nodes(start,end,vehicle_kind)
    departure=finite_nonnegative(departure_s,"departure_s")
    if departure<safety.known_at_s:
        raise ValueError("departure precedes available snapshot")
    if isinstance(max_expansions,bool) or not isinstance(max_expansions,int) or max_expansions<1:
        raise ValueError("max_expansions must be positive integer")
    if isinstance(max_candidates,bool) or not isinstance(max_candidates,int) or max_candidates<1:
        raise ValueError("max_candidates must be positive integer")
    began=perf_counter()
    if not safety.operational_enabled:
        return SearchResult("no_feasible_candidate",(),(),0,False,(perf_counter()-began)*1000)
    # Structural disconnection is the only proof of static unreachability here.
    reference=static_reference(graph,start,end,vehicle_kind,departure)
    if reference.status=="unreachable_static":
        return SearchResult("unreachable_static",(),(),0,False,(perf_counter()-began)*1000)
    queue=[(departure,(),start,(start,))]
    routes=[]
    exclusions=[]
    expansions=0
    while queue and expansions<max_expansions and len(routes)<max_candidates:
        clock,path,node,visited=heapq.heappop(queue)
        expansions+=1
        if node==end:
            routes.append(_record(graph,start,end,vehicle_kind,departure,path,safety,route_version,True,
                                  "bounded_interval_safe_candidates"))
            continue
        for edge in graph.outgoing[node]:
            if vehicle_kind not in edge.access:
                exclusions.append(Exclusion(edge.edge_id,clock,clock+edge.travel_s,"vehicle_access",edge.weight_source))
                continue
            if edge.target in visited:
                continue
            exit_s=finite_nonnegative(clock+edge.travel_s,"accumulated arrival_s")
            safe,reason,evidence=safety.traversal(edge.edge_id,clock,exit_s)
            if not safe:
                exclusions.append(Exclusion(edge.edge_id,clock,exit_s,reason,evidence))
                continue
            heapq.heappush(queue,(exit_s,path+(edge.edge_id,),edge.target,visited+(edge.target,)))
    limited=bool(queue)
    status="feasible" if routes else ("search_limit" if limited else "no_feasible_candidate")
    return SearchResult(status,tuple(routes),tuple(exclusions),expansions,limited,(perf_counter()-began)*1000)
