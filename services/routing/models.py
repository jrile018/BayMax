"""Directed metric roads and immutable route records (route-trip-v1 proposal)."""
from dataclasses import dataclass, asdict
from math import isfinite, hypot
from typing import Mapping

VEHICLE_KINDS = ("bus", "ambulance", "truck")

def finite_nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)

@dataclass(frozen=True)
class Edge:
    edge_id: str
    source: str
    target: str
    length_m: float
    travel_s: float
    access: tuple[str,...] = VEHICLE_KINDS
    geometry: tuple[tuple[float,float],...] = ()
    weight_source: str = "declared fictional fixture"

class Graph:
    def __init__(self, nodes: Mapping, edges, version="graph-v1"):
        self.version = str(version)
        self.nodes = {str(k):tuple(v) for k,v in nodes.items()}
        if not self.nodes:
            raise ValueError("graph requires mapped nodes")
        for xy in self.nodes.values():
            if len(xy)!=2 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and isfinite(x) for x in xy):
                raise ValueError("nodes require finite metric x,y")
        self.edges = {}
        self.outgoing = {n:[] for n in self.nodes}
        for e in edges:
            if not e.edge_id or e.edge_id in self.edges:
                raise ValueError("edge IDs must be unique and nonempty")
            if e.source not in self.nodes or e.target not in self.nodes:
                raise ValueError("edge endpoints must be mapped nodes")
            length = finite_nonnegative(e.length_m,"length_m")
            duration = finite_nonnegative(e.travel_s,"travel_s")
            if length>0 and duration==0:
                raise ValueError("positive length cannot take zero travel time")
            if not e.weight_source:
                raise ValueError("travel weight requires provenance")
            if not e.access or any(x not in VEHICLE_KINDS for x in e.access):
                raise ValueError("access must declare known vehicle kinds")
            poly = tuple(tuple(p) for p in (e.geometry or (self.nodes[e.source],self.nodes[e.target])))
            if len(poly)<2 or any(len(p)!=2 or not all(isinstance(x,(int,float)) and isfinite(x) for x in p) for p in poly):
                raise ValueError("edge requires finite metric polyline")
            if poly[0]!=self.nodes[e.source] or poly[-1]!=self.nodes[e.target]:
                raise ValueError("polyline endpoints must match directed road nodes")
            geometric_length=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(poly,poly[1:]))
            finite_nonnegative(geometric_length,"polyline length")
            if length==0 and geometric_length>0:
                raise ValueError("zero length cannot connect distinct metric positions")
            if length>0 and geometric_length==0:
                raise ValueError("positive length requires noncollapsed geometry")
            normalized = Edge(e.edge_id,e.source,e.target,length,duration,tuple(e.access),poly,e.weight_source)
            self.edges[e.edge_id]=normalized
            self.outgoing[e.source].append(normalized)
        for edges_at_node in self.outgoing.values():
            edges_at_node.sort(key=lambda x:x.edge_id)

    def validate_nodes(self, start, end, vehicle_kind):
        if start not in self.nodes or end not in self.nodes:
            raise ValueError("start/destination must resolve to mapped nodes")
        if vehicle_kind not in VEHICLE_KINDS:
            raise ValueError("unsupported vehicle kind")

    def geometry_for(self, edge_ids):
        points=[]
        for eid in edge_ids:
            poly=self.edges[eid].geometry
            points.extend(poly if not points else poly[1:])
        return tuple(points)

    def segment(self, edge_id, from_m, to_m):
        e=self.edges[edge_id]
        if from_m<0 or to_m<from_m or to_m>e.length_m+1e-8:
            raise ValueError("invalid actual segment")
        points=[self.position(edge_id,from_m)]
        if e.length_m>0:
            lengths=[hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(e.geometry,e.geometry[1:])]
            total=sum(lengths)
            passed=0
            for p,n in zip(e.geometry[1:-1],lengths):
                passed+=n
                metric=passed/total*e.length_m
                if from_m<metric<to_m:
                    points.append(p)
        final=self.position(edge_id,to_m)
        if final!=points[-1]:
            points.append(final)
        return tuple(points)

    def position(self, edge_id, distance_m):
        e=self.edges[edge_id]
        distance=finite_nonnegative(distance_m,"distance_m")
        if distance>e.length_m+1e-9:
            raise ValueError("progress exceeds edge length")
        if e.length_m==0:
            return e.geometry[-1]
        segments=[hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(e.geometry,e.geometry[1:])]
        along=min(1,distance/e.length_m)*sum(segments)
        for a,b,segment in zip(e.geometry,e.geometry[1:],segments):
            if along<=segment and segment>0:
                ratio=along/segment
                return (a[0]+ratio*(b[0]-a[0]),a[1]+ratio*(b[1]-a[1]))
            along-=segment
        return e.geometry[-1]

@dataclass(frozen=True)
class Leg:
    edge_id: str
    entry_s: float
    exit_s: float
    length_m: float

@dataclass(frozen=True)
class Route:
    route_id: str
    route_version: int
    status: str
    source_node: str
    destination_node: str
    vehicle_kind: str
    departure_s: float
    arrival_s: float | None
    edge_ids: tuple[str,...]
    legs: tuple[Leg,...]
    geometry: tuple[tuple[float,float],...]
    distance_m: float
    graph_version: str
    known_version: str
    safety_validated: bool
    algorithm: str
    forecast_issued_s: float | None
    forecast_horizon_s: float | None

    def to_dict(self):
        return asdict(self)

@dataclass(frozen=True)
class Exclusion:
    edge_id: str
    entry_s: float
    exit_s: float
    reason: str
    evidence: str

@dataclass(frozen=True)
class SearchResult:
    status: str
    routes: tuple[Route,...]
    exclusions: tuple[Exclusion,...]
    expansions: int
    search_limited: bool
    calculation_ms: float
    search_scope: str = "bounded simple directed paths; no waiting or retreat; not globally optimal arbitrary time-dependent routing"

    def to_dict(self):
        return asdict(self)
