"""Strict adapter for sourced metric roads and declared edge-access evidence."""
from hashlib import sha256
from json import dumps
from math import cos,degrees,hypot,isclose,isfinite,radians
from .models import Edge,Graph,finite_nonnegative
from .safety import Closure,SafetySnapshot

MAP_CRS="local equirectangular metres; origin_lonlat is WGS84 longitude,latitude"
EARTH_RADIUS_M=6371008.8
ACCESS_PROXY={"bus":"bus","ambulance":"motorcar","truck":"hgv"}
SOURCE_KINDS=frozenset(("observed","forecast","modeled_forecast","authored_simulated"))

def _require(ok,message):
    if not ok:
        raise ValueError("sourced routing: "+message)

def _name(value,label):
    _require(isinstance(value,str) and bool(value.strip()),label+" must be a nonempty string")
    return value

def _point(value,label,geographic=False):
    _require(isinstance(value,(list,tuple)) and len(value)==2,label+" needs two coordinates")
    _require(all(isinstance(x,(int,float)) and not isinstance(x,bool) and isfinite(x) for x in value),
             label+" needs finite numeric coordinates")
    if geographic:
        _require(-180<=value[0]<=180 and -90<=value[1]<=90,label+" is not longitude/latitude")
    return tuple(value)

def _bbox(value,label):
    _require(isinstance(value,(list,tuple)) and len(value)==4,label+" requires four coordinates")
    west,south=_point(value[:2],label,True)
    east,north=_point(value[2:],label,True)
    _require(west<east and south<north,label+" bounds must increase")
    return (west,south,east,north)

def _inside(lonlat,bbox):
    return bbox[0]<=lonlat[0]<=bbox[2] and bbox[1]<=lonlat[1]<=bbox[3]

def _project(lonlat,origin):
    scale=cos(radians(origin[1]))
    _require(abs(scale)>1e-12,"metric projection origin too close to pole")
    return (radians(lonlat[0]-origin[0])*EARTH_RADIUS_M*scale,
            radians(lonlat[1]-origin[1])*EARTH_RADIUS_M)

def _unproject(point,origin):
    scale=cos(radians(origin[1]))
    _require(abs(scale)>1e-12,"metric projection origin too close to pole")
    return (origin[0]+degrees(point[0]/(EARTH_RADIUS_M*scale)),
            origin[1]+degrees(point[1]/EARTH_RADIUS_M))

def _json(value):
    return dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)

def graph_from_geography(payload,source_manifest):
    """Map the published Paradise OSM graph shape; preserve its explicit source limits."""
    _require(isinstance(payload,dict) and isinstance(source_manifest,dict),"graph and manifest objects required")
    area=_name(payload.get("area_id"),"area_id")
    _require(payload.get("metric_crs")==MAP_CRS,"unsupported or missing metric CRS")
    origin=_point(payload.get("origin_lonlat"),"origin_lonlat",True)
    coverage=_bbox(payload.get("coverage_bbox_lonlat"),"coverage bbox")
    geometry_bbox=_bbox(payload.get("source_geometry_bbox_lonlat"),"source geometry bbox")
    _require(_inside(origin,coverage),"metric origin outside acquired coverage")
    _require(_bbox(source_manifest.get("coverage_bbox_lonlat"),"manifest coverage bbox")==coverage
             and _bbox(source_manifest.get("source_geometry_bbox_lonlat"),"manifest geometry bbox")==geometry_bbox,
             "manifest coverage differs from graph")
    rawsha=_name(source_manifest.get("raw_sha256"),"raw source SHA256")
    _require(len(rawsha)==64 and all(c in "0123456789abcdef" for c in rawsha)
             and payload.get("source_sha256")==rawsha,"source hash differs from manifest")
    _require(source_manifest.get("source")=="OpenStreetMap","unrecognized road source")
    license_name=_name(source_manifest.get("license"),"license")
    attribution=_name(source_manifest.get("attribution"),"attribution")
    downloaded=_name(source_manifest.get("downloaded_at_utc"),"download time")
    note=_name(payload.get("geometry_coverage_note"),"geometry coverage note")
    nodes_raw=payload.get("nodes"); edges_raw=payload.get("edges")
    _require(isinstance(nodes_raw,list) and isinstance(edges_raw,list),"nodes and edges must be arrays")
    nodes={}; geographic={}
    for item in nodes_raw:
        _require(isinstance(item,dict),"node must be an object")
        nid=_name(item.get("id"),"node ID")
        _require(nid not in nodes,"duplicate node ID")
        lonlat=_point(item.get("lonlat"),"node lonlat",True)
        _require(_inside(lonlat,geometry_bbox),"node outside declared source geometry bbox")
        metric=_point(item.get("geometry_m"),"node metric point")
        _require(hypot(metric[0]-_project(lonlat,origin)[0],
                       metric[1]-_project(lonlat,origin)[1])<=0.25,
                 "node metric projection disagrees with declared WGS84 origin")
        nodes[nid]=metric
        geographic[nid]=lonlat
    seen=set(); edges=[]; provenance={}; excluded=[]
    for item in edges_raw:
        _require(isinstance(item,dict),"edge must be an object")
        eid=_name(item.get("id"),"edge ID")
        _require(eid not in seen,"duplicate edge ID"); seen.add(eid)
        way=_name(item.get("way_id"),"way ID")
        segment=item.get("segment_index")
        _require(type(segment) is int and segment>=0 and
                 eid in (f"{way}/{segment}/fwd",f"{way}/{segment}/rev"),"unstable directed edge identity")
        source=_name(item.get("from_node"),"from_node")
        target=_name(item.get("to_node"),"to_node")
        _require(source in nodes and target in nodes,"unknown edge endpoint")
        poly_raw=item.get("geometry_m")
        _require(isinstance(poly_raw,list) and len(poly_raw)>=2,"edge metric geometry")
        poly=tuple(_point(point,"edge metric point") for point in poly_raw)
        _require(poly[0]==nodes[source] and poly[-1]==nodes[target],"edge geometry endpoint mismatch")
        length=finite_nonnegative(item.get("length_m"),"length_m")
        duration=finite_nonnegative(item.get("travel_time_s"),"travel_time_s")
        speed=finite_nonnegative(item.get("speed_mps"),"speed_mps")
        _require(speed>0 and length>0 and duration>0,"positive sourced road length, speed and time required")
        measured=sum(hypot(b[0]-a[0],b[1]-a[1]) for a,b in zip(poly,poly[1:]))
        _require(isclose(length,measured,rel_tol=1e-9,abs_tol=1e-7)
                 and isclose(duration,length/speed,rel_tol=1e-9,abs_tol=1e-7),
                 "road geometry, length, speed and travel time disagree")
        assumption=_name(item.get("speed_assumption"),"speed assumption")
        raw_access=item.get("vehicle_access")
        _require(isinstance(raw_access,dict) and
                 all(type(raw_access.get(kind)) is bool for kind in ("motor_vehicle","motorcar","bus","hgv")),
                 "explicit Boolean source vehicle access required")
        kinds=tuple(kind for kind,raw in ACCESS_PROXY.items()
                    if raw_access["motor_vehicle"] and raw_access[raw])
        if not kinds:
            excluded.append(eid)
            continue
        edges.append(Edge(eid,source,target,length,duration,kinds,poly,
            f"{attribution}; {assumption}; way={way}"))
        provenance[eid]=dict(way_id=way,segment_index=segment,speed_mps=speed,
            speed_assumption=assumption,vehicle_access=dict(raw_access),
            source_observed_at=source_manifest.get("source_observed_at"))
    graphsha=sha256(_json(payload).encode()).hexdigest()
    graph=Graph(nodes,edges,version=f"osm-{area}-{graphsha[:16]}")
    graph.area_id=area
    graph.metric_crs=MAP_CRS
    graph.origin_lonlat=origin
    graph.coverage_bbox_lonlat=coverage
    graph.source_geometry_bbox_lonlat=geometry_bbox
    graph.node_lonlat=geographic
    graph.edge_provenance=provenance
    graph.source_sha256=rawsha
    graph.source_metadata=dict(area_id=area,source="OpenStreetMap",license=license_name,
        attribution=attribution,downloaded_at_utc=downloaded,raw_sha256=rawsha,
        graph_sha256=graphsha,coverage_bbox_lonlat=list(coverage),
        source_geometry_bbox_lonlat=list(geometry_bbox),geometry_coverage_note=note,
        excluded_no_access_edge_ids=excluded,
        vehicle_access_proxy={"bus":"OSM bus","ambulance":"OSM motorcar proxy",
                              "truck":"OSM hgv proxy"})
    return graph

def safety_from_access(records,graph,*,alignment,known_at_s,horizon_s,version,
                       safe_nodes,default_received_s=None,safety_buffer_s=0):
    """Use only received, spatially aligned, fully covered edge intervals."""
    _require(hasattr(graph,"source_metadata") and hasattr(graph,"node_lonlat"),
             "sourced graph metadata required")
    _require(isinstance(alignment,dict),"explicit alignment metadata required")
    for name,expected in (("graph_version",graph.version),("area_id",graph.area_id),
                          ("metric_crs",graph.metric_crs),
                          ("origin_lonlat",list(graph.origin_lonlat)),
                          ("graph_source_sha256",graph.source_sha256)):
        _require(type(alignment.get(name)) is type(expected) and alignment[name]==expected,
                 "edge access coordinate/source identity differs: "+name)
    source_kind=_name(alignment.get("source_kind"),"source_kind")
    _require(source_kind in SOURCE_KINDS,"unsupported source_kind")
    source_id=_name(alignment.get("source_id"),"source_id")
    known=finite_nonnegative(known_at_s,"known_at_s")
    horizon=finite_nonnegative(horizon_s,"horizon_s")
    buffer=finite_nonnegative(safety_buffer_s,"safety_buffer_s")
    _require(horizon>=known,"horizon must include known time")
    _name(version,"snapshot version")
    _require(isinstance(records,(list,tuple)),"edge access records must be an array")
    _require(isinstance(safe_nodes,(list,tuple,set,frozenset)),"safe destination nodes must be explicit")
    safe=frozenset(safe_nodes)
    for node in safe:
        _require(node in graph.node_lonlat and _inside(graph.node_lonlat[node],graph.coverage_bbox_lonlat),
                 "safe destination outside acquired road coverage")
    if default_received_s is not None:
        default_received_s=finite_nonnegative(default_received_s,"default_received_s")
    grouped={}
    for row in records:
        _require(isinstance(row,dict),"access record must be an object")
        eid=_name(row.get("edge_id"),"access edge_id")
        _require(eid in graph.edges,"access record has unknown or mismatched edge ID")
        status=row.get("status")
        _require(status in ("forecast","observed","unknown"),"access status must be explicit")
        issued=finite_nonnegative(row.get("issued_time_s"),"issued_time_s")
        received=finite_nonnegative(row.get("received_time_s",default_received_s),"received_time_s")
        _require(received>=issued,"access cannot be received before issue")
        start=finite_nonnegative(row.get("coverage_start_s"),"coverage_start_s")
        end=finite_nonnegative(row.get("coverage_end_s"),"coverage_end_s")
        _require(start<=end and issued<=end,"invalid access coverage interval")
        reason=_name(row.get("reason"),"access reason")
        spatial=_name(row.get("spatial_rule"),"spatial_rule")
        ids=row.get("source_ids")
        _require(isinstance(ids,list) and bool(ids),"access source_ids required")
        for sid in ids: _name(sid,"access source ID")
        intervals=row.get("closed_intervals")
        _require(isinstance(intervals,list),"closed_intervals must be an array")
        spans=[]
        for item in intervals:
            _require(isinstance(item,dict),"closed interval must be an object")
            left=finite_nonnegative(item.get("start_s"),"closed start")
            right=finite_nonnegative(item.get("end_s"),"closed end")
            _require(start<=left<right<=end,"closed interval outside access coverage")
            spans.append((left,right))
        if issued<=known and received<=known:
            grouped.setdefault(eid,[]).append((issued,received,status,start,end,reason,spatial,tuple(ids),spans))
    covered=set(); closures=[]; latest_issues=[]
    for eid,entries in grouped.items():
        latest=max(entry[0] for entry in entries)
        current=[entry for entry in entries if entry[0]==latest]
        if any(entry[2]=="unknown" or entry[3]>known or entry[4]<horizon
               or (entry[2]=="observed" and horizon>known) for entry in current):
            continue
        edge=graph.edges[eid]
        if not all(_inside(_unproject(point,graph.origin_lonlat),graph.coverage_bbox_lonlat)
                   for point in edge.geometry):
            continue
        covered.add(eid)
        latest_issues.append(latest)
        for issued,received,status,start,end,reason,spatial,ids,spans in current:
            for left,right in spans:
                closures.append(Closure(eid,left,right,issued,received,reason,
                    f"{source_kind}:{source_id}; sources={','.join(ids)}; rule={spatial}"))
    return SafetySnapshot(str(version),known,max(latest_issues,default=0),horizon,
        tuple(closures),buffer,frozenset(covered),
        provenance=f"{source_kind}:{source_id}; graph={graph.version}; acquired coverage only",
        safe_nodes=safe)
