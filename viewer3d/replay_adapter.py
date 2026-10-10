"""CPU-only adapter for existing dashboard exports, not a shared mission bridge."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from .scene import (BuildingRecord, FrameIdentity, MetricPoint, PolygonRecord,
    PolylineRecord, PreparedScene, RouteRecord, SceneBounds, SceneInput,
    SceneLimits, SourceMetadata, UnitRecord, build_scene)

R = 6371008.8
METRIC_CRS = "local equirectangular metres; origin_lonlat is WGS84 longitude,latitude"
NORMALIZED_CRS = "LOCAL_EQUIRECTANGULAR_METRES:R6371008.8"
ELEVATION_ASSUMPTION = "z=0 flat ground visual assumption; terrain and measured elevations unavailable"
MAX_JSON_BYTES = 32*1024*1024
MAX_RAW_BYTES = 8*1024*1024

@dataclass(frozen=True)
class DashboardFrameBinding:
    run_id: str
    scenario_id: str
    index: int
    time_s: float
    snapshot_hash: str
    bootstrap_hash: str
    graph_hash: str
    raw_source_sha256: str

@dataclass(frozen=True)
class AdaptedReplay:
    scene: PreparedScene
    metadata: dict

def _json_bytes(value):
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",",":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("JSON content must be finite and serializable") from error
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("JSON input budget exceeded")
    return payload

def canonical_content_hash(value):
    """Canonical exported mapping digest; not original file-byte SHA256."""
    return hashlib.sha256(_json_bytes(value)).hexdigest()

def _object(value, label):
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return value

def _array(value, label):
    if type(value) is not list:
        raise ValueError(f"{label} must be a JSON array")
    return value

def _text(value, label):
    if not isinstance(value,str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value

def _number(value, label):
    if type(value) not in (int,float):
        raise ValueError(f"{label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite")
    return value

def _count(value,label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value

def _sha(value,label):
    if not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA256")
    return value

def _lonlat(value,label):
    _array(value,label)
    if len(value)!=2:
        raise ValueError(f"{label} requires WGS84 longitude,latitude")
    lon,lat=(_number(v,label) for v in value)
    if not -180<=lon<=180 or not -90<=lat<=90:
        raise ValueError(f"{label} outside WGS84 bounds")
    return lon,lat

def _bbox(value,label):
    _array(value,label)
    if len(value)!=4:
        raise ValueError(f"{label} requires west,south,east,north")
    west,south=_lonlat(value[:2],label)
    east,north=_lonlat(value[2:],label)
    if west>=east or south>=north:
        raise ValueError(f"{label} must be ordered and nondegenerate")
    return west,south,east,north

def _source_permission(source):
    if not isinstance(source,SourceMetadata):
        raise ValueError("explicit overlay source/display permission required")
    for name in ("source_id","provider","license_id","reference"):
        _text(getattr(source,name),f"overlay source {name}")
    if source.license_id.strip().casefold() in {"unknown","unlicensed","none","unavailable","not licensed"}:
        raise ValueError("overlay source license/display permission unavailable")
    if source.independently_sourced is not True:
        raise ValueError("overlay source must declare independent project-authored geometry")
    if type(source.assumptions) is not tuple:
        raise ValueError("overlay source assumptions must be a tuple")
    for assumption in source.assumptions:
        _text(assumption,"overlay source assumption")
    if "google" in " ".join((source.source_id,source.provider,source.reference,source.license_id,*source.assumptions)).casefold():
        raise ValueError("Google-derived overlay source rejected")

class _Budget:
    def __init__(self,limits):
        self.limits,self.points=limits,0
    def consume(self,count):
        self.points+=count
        if self.points>self.limits.max_points:
            raise ValueError("source geometry point budget exceeded")

def adapt_dashboard_replay(bootstrap,frame,graph,*,binding:DashboardFrameBinding,
                          raw_source_bytes:bytes,overlay_source:SourceMetadata,
                          limits=SceneLimits())->AdaptedReplay:
    """Bind exact exports/source bytes and project explicitly mock overlays.

    Expected digests must come from a trusted producer/captured input manifest,
    not be calculated by the consumer from untrusted received mappings. Hashes
    establish caller-bound artifact consistency, not audited OSM derivation or
    actual mission outcomes. Metadata retains the unmodified original frame.
    """
    try:
        return _adapt(bootstrap,frame,graph,binding,raw_source_bytes,overlay_source,limits)
    except (KeyError,IndexError,TypeError) as error:
        raise ValueError(f"malformed replay adapter field: {error}") from error

def _adapt(bootstrap,frame,graph,binding,raw,overlay_source,limits):
    _object(bootstrap,"bootstrap");_object(frame,"frame");_object(graph,"graph")
    if not isinstance(binding,DashboardFrameBinding):
        raise ValueError("trusted DashboardFrameBinding required")
    if not isinstance(limits,SceneLimits):
        raise ValueError("SceneLimits required")
    for name in ("max_primitives","max_points","max_triangles","max_polygon_points"):
        _count(getattr(limits,name),"scene limit")
    if _number(limits.max_extent_m,"extent limit")<=0:
        raise ValueError("extent limit must be positive")
    _source_permission(overlay_source)
    for name in ("snapshot_hash","bootstrap_hash","graph_hash","raw_source_sha256"):
        _sha(getattr(binding,name),f"binding {name}")
    _text(binding.run_id,"binding run");_text(binding.scenario_id,"binding scenario")
    _count(binding.index,"binding index")
    if _number(binding.time_s,"binding time")<0:
        raise ValueError("binding time must be nonnegative")
    if type(raw) is not bytes or len(raw)>MAX_RAW_BYTES:
        raise ValueError("raw source bytes required within 8 MiB budget")
    if hashlib.sha256(raw).hexdigest()!=binding.raw_source_sha256:
        raise ValueError("raw source hash binding mismatch")
    area=_object(bootstrap.get("area"),"bootstrap area")
    replay=_object(bootstrap.get("replay"),"bootstrap replay")
    nodes,edges=_array(graph.get("nodes"),"graph nodes"),_array(graph.get("edges"),"graph edges")
    if len(nodes)+len(edges)>limits.max_primitives:
        raise ValueError("graph record budget exceeded")
    groups={key:_array(area.get(key),f"area {key}") for key in ("roads","buildings","landuse")}
    vehicles=_array(frame.get("vehicles"),"frame vehicles")
    hazards=_array(frame.get("hazards"),"frame hazards")
    closures=_array(frame.get("closures"),"frame closures")
    if sum(map(len,groups.values()))+4*len(vehicles)+len(hazards)+len(closures)>limits.max_primitives:
        raise ValueError("scene record budget exceeded")
    if canonical_content_hash(bootstrap)!=binding.bootstrap_hash:
        raise ValueError("bootstrap hash binding mismatch")
    if canonical_content_hash(graph)!=binding.graph_hash:
        raise ValueError("graph hash binding mismatch")
    if "google" in _json_bytes(frame).decode().casefold():
        raise ValueError("Google-derived replay overlay source marker rejected")
    actual_hash=canonical_content_hash({k:v for k,v in frame.items() if k!="snapshot_hash"})
    if frame.get("snapshot_hash")!=actual_hash or actual_hash!=binding.snapshot_hash:
        raise ValueError("original frame snapshot hash binding mismatch")
    for name in ("run_id","scenario_id","index","time_s"):
        if frame.get(name)!=getattr(binding,name):
            raise ValueError(f"frame identity binding mismatch: {name}")
    _count(frame["index"],"frame index");_count(frame.get("snapshot_version"),"frame snapshot version")
    if _number(frame["time_s"],"frame time")<0:
        raise ValueError("frame time must be nonnegative")
    if replay.get("run_id")!=binding.run_id or replay.get("scenario_id")!=binding.scenario_id:
        raise ValueError("bootstrap replay identity mismatch")
    times=_array(replay.get("frame_times_s"),"replay frame times")
    if _count(replay.get("frame_count"),"replay frame count")!=len(times) or not times:
        raise ValueError("replay index/time binding invalid")
    for i,time in enumerate(times):
        if _number(time,"replay time")<0 or (i and time<=times[i-1]):
            raise ValueError("replay times must be strictly increasing")
    if not binding.index<len(times) or times[binding.index]!=binding.time_s:
        raise ValueError("replay index/time binding mismatch")
    if bootstrap.get("mode")!="mock-replay" or frame.get("mode")!="mock-replay":
        raise ValueError("only explicitly mock dashboard replay supported; mission bridge absent")
    label=_text(bootstrap.get("label"),"mock replay label")
    geometry_status=_text(frame.get("geometry_status"),"mock geometry status")
    if not any(t in geometry_status.casefold() for t in ("mock","constructed","illustration")):
        raise ValueError("mock geometry status must remain explicit")
    manifest=_object(area.get("source_manifest"),"resolved source manifest")
    if manifest.get("source")!="OpenStreetMap" or manifest.get("license")!="ODbL 1.0":
        raise ValueError("source manifest must declare OpenStreetMap ODbL license")
    attribution=_text(manifest.get("attribution"),"source attribution")
    if "OpenStreetMap contributors" not in attribution:
        raise ValueError("OpenStreetMap source attribution required")
    for field in ("license_url","attribution_url"):
        if manifest.get(field)!="https://www.openstreetmap.org/copyright":
            raise ValueError("source manifest license/attribution reference required")
    endpoint=_text(manifest.get("endpoint"),"source manifest endpoint")
    if not endpoint.startswith("https://") or "google" in _json_bytes(manifest).decode().casefold():
        raise ValueError("source manifest reference invalid or Google-derived")
    if _sha(manifest.get("raw_sha256"),"source manifest raw SHA256")!=binding.raw_source_sha256:
        raise ValueError("source manifest raw hash mismatch")
    if manifest.get("decompressed_sha256")!=binding.raw_source_sha256:
        raise ValueError("adapter requires verified uncompressed OSM source bytes")
    if graph.get("source_sha256")!=binding.raw_source_sha256:
        raise ValueError("graph source hash mismatch")
    origin=_lonlat(area.get("origin_lonlat"),"projection origin")
    if not -90<origin[1]<90 or abs(math.cos(math.radians(origin[1])))<1e-12:
        raise ValueError("invalid WGS84 projection origin")
    if graph.get("origin_lonlat")!=area["origin_lonlat"]:
        raise ValueError("graph projection origin mismatch")
    if area.get("metric_crs")!=METRIC_CRS or graph.get("metric_crs")!=METRIC_CRS:
        raise ValueError("exact local equirectangular metric CRS declaration required")
    if graph.get("area_id")!=area.get("area_id") or not isinstance(area.get("area_id"),str):
        raise ValueError("geography area identity mismatch")
    viewport=_bbox(area.get("bbox_lonlat"),"geometry viewport bounds")
    for name in ("coverage_bbox_lonlat","source_geometry_bbox_lonlat"):
        b=_bbox(area.get(name),f"source {name}")
        if graph.get(name)!=area[name] or manifest.get(name)!=area[name]:
            raise ValueError(f"source coverage/geometry bounds mismatch: {name}")
        if not (viewport[0]<=b[0]<=b[2]<=viewport[2] and viewport[1]<=b[1]<=b[3]<=viewport[3]):
            raise ValueError("coverage/source geometry outside viewport extent")
    coverage=_array(area.get("coverage"),"source coverage")
    layer_status={}
    for row in coverage:
        _object(row,"coverage row")
        layer=_text(row.get("layer"),"coverage layer")
        if layer in layer_status or row.get("status") not in {"available","unavailable","unknown"}:
            raise ValueError("invalid source coverage")
        layer_status[layer]=row["status"]
    for layer in ("terrain","fuels","current_fire"):
        if layer_status.get(layer)!="unavailable":
            raise ValueError(f"unsupported source coverage layer: {layer}")
    for layer in ("roads","buildings","landuse"):
        if layer_status.get(layer)!=("available" if groups[layer] else "unavailable"):
            raise ValueError("geometry layer source coverage mismatch")
    coverage_note=_text(area.get("geometry_coverage_note"),"source geometry coverage note")
    if graph.get("geometry_coverage_note")!=coverage_note or manifest.get("geometry_coverage_note")!=coverage_note:
        raise ValueError("geometry coverage note mismatch")
    budget=_Budget(limits)
    def project(point):
        lon,lat=_lonlat(point,"geometry longitude/latitude")
        if not (viewport[0]<=lon<=viewport[2] and viewport[1]<=lat<=viewport[3]):
            raise ValueError("geometry outside source viewport extent")
        return MetricPoint(math.radians(lon-origin[0])*R*math.cos(math.radians(origin[1])),
                           math.radians(lat-origin[1])*R,0)
    def path(lonlat,metric=None):
        coords=_array(lonlat,"geometry coordinate array")
        budget.consume(len(coords))
        expected=tuple(project(p) for p in coords)
        if metric is None:
            return expected
        supplied=_array(metric,"supplied metric geometry")
        if len(supplied)!=len(expected):
            raise ValueError("metric/lonlat geometry vertex count mismatch")
        result=[]
        for pair,point in zip(supplied,expected):
            _array(pair,"supplied metric point")
            if len(pair)!=2 or any(_number(v,"metric geometry")!=ref for v,ref in zip(pair,(point.x_m,point.y_m))):
                raise ValueError("supplied metric geometry differs from exact source projection")
            result.append(MetricPoint(pair[0],pair[1],0))
        return tuple(result)
    def ring(points):
        return points[:-1] if len(points)>1 and points[0]==points[-1] else points
    identity=FrameIdentity(binding.run_id,binding.scenario_id,binding.time_s,binding.snapshot_hash)
    corners=(project([viewport[0],viewport[1]]),project([viewport[2],viewport[3]]))
    bounds=SceneBounds(*corners)
    if max(corners[1].x_m-corners[0].x_m,corners[1].y_m-corners[0].y_m)>limits.max_extent_m:
        raise ValueError("scene extent limit exceeded")
    osm_source=SourceMetadata("osm:"+binding.raw_source_sha256,"OpenStreetMap","ODbL 1.0",endpoint,True,
        (ELEVATION_ASSUMPTION,coverage_note,"terrain/fuels/current_fire unavailable"))
    mock_source=replace(overlay_source,assumptions=overlay_source.assumptions+(
        ELEVATION_ASSUMPTION,"mock-replay: project-authored constructed overlays, not actual mission state",label,geometry_status))
    roads,buildings,road_geometry=[],[],{}
    for row in groups["roads"]:
        _object(row,"road");ident=_text(row.get("id"),"road ID")
        if ident in road_geometry:
            raise ValueError("duplicate road geometry ID")
        points=path(row.get("geometry_lonlat"),_array(row.get("geometry_m"),"required source metric geometry"))
        road_geometry[ident]=points
        roads.append(PolylineRecord(ident,identity,osm_source,points))
    for row in groups["buildings"]:
        _object(row,"building")
        if any(row.get(k) is not None for k in ("height","height_m","elevation_m")):
            raise ValueError("building height/elevation outside supported area schema")
        points=ring(path(row.get("geometry_lonlat"),_array(row.get("geometry_m"),"required source metric geometry")))
        buildings.append(BuildingRecord(_text(row.get("id"),"building ID"),identity,osm_source,points))
    for row in groups["landuse"]:
        _object(row,"landuse");path(row.get("geometry_lonlat"))
    graph_nodes={}
    for node in nodes:
        _object(node,"graph node");ident=_text(node.get("id"),"graph node ID")
        if ident in graph_nodes:
            raise ValueError("duplicate graph node geometry ID")
        graph_nodes[ident]=path([node.get("lonlat")],[node.get("geometry_m")])[0]
    seen_edges=set()
    for edge in edges:
        _object(edge,"graph edge");ident=_text(edge.get("id"),"graph edge ID")
        if ident in seen_edges:
            raise ValueError("duplicate graph edge ID")
        seen_edges.add(ident)
        way=_text(edge.get("way_id"),"graph edge way ID")
        index=_count(edge.get("segment_index"),"graph edge segment index")
        points=road_geometry.get(way)
        if points is None or not index+1<len(points):
            raise ValueError("graph edge source road geometry binding invalid")
        if ident==f"{way}/{index}/fwd":
            expected=(points[index],points[index+1])
        elif ident==f"{way}/{index}/rev":
            expected=(points[index+1],points[index])
        else:
            raise ValueError("graph edge source segment/direction identity invalid")
        supplied=_array(edge.get("geometry_m"),"graph edge metric geometry")
        budget.consume(len(supplied))
        for pair in supplied:
            _array(pair,"graph edge metric point")
            if len(pair)!=2:
                raise ValueError("graph edge metric point requires two coordinates")
            for value in pair:
                _number(value,"graph edge metric geometry")
        if supplied!=[[p.x_m,p.y_m] for p in expected]:
            raise ValueError("graph edge metric geometry binding mismatch")
        if graph_nodes.get(edge.get("from_node"))!=expected[0] or graph_nodes.get(edge.get("to_node"))!=expected[1]:
            raise ValueError("graph edge node geometry binding mismatch")
    units,routes,trails,fires,undrawn,mappings=[],[],[],[],[],[]
    for i,vehicle in enumerate(vehicles):
        _object(vehicle,"mock vehicle")
        vehicle_id=_text(vehicle.get("vehicle_id"),"vehicle ID")
        position=path([vehicle.get("position_lonlat")])[0]
        kind=vehicle.get("kind");kind="supply_truck" if kind=="truck" else kind
        units.append(UnitRecord(vehicle_id,identity,mock_source,kind,position))
        mappings.append({"record_id":vehicle_id,"source_field":f"vehicles[{i}].position_lonlat"})
        version=_count(vehicle.get("route_version"),"route version")
        for field in ("route_geometry_lonlat","remaining_path_lonlat","completed_trail_lonlat","old_route_geometry_lonlat"):
            geometry=path(vehicle.get(field,[]))
            if field=="old_route_geometry_lonlat":
                if geometry:
                    undrawn.append({"category":"previous_route","vehicle_id":vehicle_id,
                        "reason":"no explicit previous route version; original geometry retained in source_frame"})
                continue
            if field in ("remaining_path_lonlat","completed_trail_lonlat") and geometry:
                endpoint=geometry[0] if field=="remaining_path_lonlat" else geometry[-1]
                if endpoint!=position:
                    raise ValueError("mock path endpoint does not bind to exact vehicle position")
            if not geometry:
                continue
            if len(geometry)==1:
                undrawn.append({"category":"singleton_path","vehicle_id":vehicle_id,"source_field":field,
                    "reason":"one supplied point retained; no line geometry invented"})
                continue
            if field=="completed_trail_lonlat":
                record_id=vehicle_id+":completed-trail"
                trails.append(PolylineRecord(record_id,identity,mock_source,geometry))
            else:
                route_id=_text(vehicle.get("route_id"),"current route ID")
                role="full" if field=="route_geometry_lonlat" else "remaining"
                record_id=f"{vehicle_id}:{route_id}:v{version}:{role}"
                routes.append(RouteRecord(record_id,identity,mock_source,geometry,version,"committed"))
            mappings.append({"record_id":record_id,"source_field":f"vehicles[{i}].{field}"})
    for hazard in hazards:
        _object(hazard,"mock hazard")
        status=_text(hazard.get("source_status"),"hazard source status")
        if hazard.get("kind")!="fire" or "mock" not in status.casefold():
            raise ValueError("only explicitly mock fire illustration overlays supported")
        fires.append(PolygonRecord(_text(hazard.get("id"),"mock hazard ID"),identity,mock_source,
                                   ring(path(hazard.get("geometry_lonlat")))))
    for closure in closures:
        _object(closure,"mock closure")
        if "mock" not in _text(closure.get("source_status"),"closure source status").casefold():
            raise ValueError("closure source must remain explicitly mock")
        path(closure.get("geometry_lonlat"))
        observed=_number(closure.get("observed_at_s"),"closure observed time")
        if not 0<=observed<=binding.time_s:
            raise ValueError("closure observation outside recorded frame time")
    for category in ("closures","needs","stocks","landuse"):
        records=groups[category] if category=="landuse" else frame.get(category,[])
        _array(records,category)
        if records:
            reason=("no supported closure glyph" if category=="closures" else
                "no supplied geographic position; no aid/depot position invented" if category in {"needs","stocks"} else
                "renderer has no landuse primitive; original records retained")
            undrawn.append({"category":category,"reason":reason,"count":len(records)})
    scene=build_scene(SceneInput(identity,NORMALIZED_CRS,
        "WGS84 origin_lonlat="+json.dumps(list(origin),separators=(",",":"))+"; R=6371008.8 m",
        bounds,"metres",roads=tuple(roads),buildings=tuple(buildings),fires=tuple(fires),
        routes=tuple(routes),trails=tuple(trails),units=tuple(units)),limits=limits)
    metadata={
        "identity":dict(asdict(identity),index=binding.index,snapshot_version=frame["snapshot_version"]),
        "mode":"mock-replay","mission_bridge":"not connected","label":label,
        "description":replay.get("description",""),"geometry_status":geometry_status,
        "source_frame":json.loads(_json_bytes(frame)),"source_manifest":json.loads(_json_bytes(manifest)),
        "license":manifest["license"],"attribution":attribution,"coverage":json.loads(_json_bytes(coverage)),
        "coverage_bbox_lonlat":area["coverage_bbox_lonlat"],"source_geometry_bbox_lonlat":area["source_geometry_bbox_lonlat"],
        "geometry_coverage_note":coverage_note,"elevation_assumption":ELEVATION_ASSUMPTION,
        "origin_lonlat":list(origin),"metric_crs":NORMALIZED_CRS,"source_metric_crs":METRIC_CRS,"horizontal_units":"metres",
        "input_hashes":{name:getattr(binding,name) for name in ("bootstrap_hash","graph_hash","raw_source_sha256")},
        "view_hash":canonical_content_hash(asdict(scene)),
        "hash_semantics":"snapshot_hash verifies original source frame; view_hash identifies normalized view only",
        "source_binding":"caller-bound artifact integrity checked; OSM derivation and actual mission outcomes not audited",
        "overlay_source":asdict(mock_source),"undrawn":undrawn,"record_mapping":mappings,"unrendered_landuse":groups["landuse"],
    }
    return AdaptedReplay(scene,json.loads(_json_bytes(metadata)))
