"""CPU projection of the root public mission contract, preserving routing authority.

Requires the separately maintained ``contracts.mission`` package on PYTHONPATH.
This module does not interpolate progress, compute routes, evaluate safety, or
infer outcomes. Expected hashes and display permissions are caller assertions.
"""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math

from .scene import (FrameIdentity, MetricPoint, PolylineRecord, PreparedScene,
                    RouteRecord, SceneBounds, SceneInput, SceneLimits,
                    SourceMetadata, UnitRecord, build_scene)

MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_JSON_NODES = 1000000
ELEVATION_ASSUMPTION = "z=0 flat ground visual assumption; terrain and measured elevations unavailable"
NORMALIZED_CRS = "LOCAL_EQUIRECTANGULAR_METRES:R6371008.8"


@dataclass(frozen=True)
class AdaptedMission:
    scene: PreparedScene
    metadata: dict


def _json_bytes(value, *, allow_tuples=False):
    # Bound the traversal before serialization and before calling the external
    # validator. Shared/cyclic Python structures are not public JSON input.
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > MAX_JSON_NODES or depth > 64:
            raise ValueError("mission JSON node/depth budget exceeded")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("mission JSON keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list or (allow_tuples and type(item) is tuple):
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("mission requires plain JSON values")
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ValueError("mission JSON must be finite and serializable") from error
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("mission JSON byte budget exceeded")
    return payload


def _hash(value):
    return hashlib.sha256(_json_bytes(value, allow_tuples=True)).hexdigest()


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} requires nonempty text")
    return value


def _number(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} requires a finite number")
    return value


def _version(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} requires a nonnegative integer")
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("trusted expected mission hash must be a lowercase SHA256")
    return value


def _permission(source):
    if not isinstance(source, SourceMetadata):
        raise ValueError("explicit SourceMetadata display permission required")
    for name in ("source_id", "provider", "license_id", "reference"):
        _text(getattr(source, name), f"source {name}")
    if source.license_id.strip().casefold() in {"unknown", "unlicensed", "none", "unavailable", "not licensed"}:
        raise ValueError("source display license unavailable")
    if source.independently_sourced is not True or type(source.assumptions) is not tuple:
        raise ValueError("source must explicitly declare independent geometry and immutable assumptions")
    for assumption in source.assumptions:
        _text(assumption, "source assumption")
    if "google" in " ".join((source.source_id, source.provider, source.license_id,
                               source.reference, *source.assumptions)).casefold():
        raise ValueError("Google-derived source rejected")
    assumptions = source.assumptions
    if ELEVATION_ASSUMPTION not in assumptions:
        assumptions += (ELEVATION_ASSUMPTION,)
    return replace(source, assumptions=assumptions)


class _Geometry:
    def __init__(self, limits):
        self.points = []
        self.limits = limits

    def point(self, pair, label):
        if type(pair) is not list or len(pair) != 2:
            raise ValueError(f"{label} requires a source x/y pair")
        point = MetricPoint(_number(pair[0], label), _number(pair[1], label), 0)
        self.points.append(point)
        if len(self.points) > self.limits.max_points:
            raise ValueError("source geometry point budget exceeded")
        return point

    def path(self, pairs, label):
        if type(pairs) is not list:
            raise ValueError(f"{label} requires an array")
        return tuple(self.point(pair, label) for pair in pairs)


def _route_points(route, graph, geometry, label):
    points = geometry.path(route.get("geometry"), label)
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    expected = []
    for edge_id in route["edge_ids"]:
        supplied = edges[edge_id]["geometry"]
        expected.extend(supplied if not expected or expected[-1] != supplied[0] else supplied[1:])
    if not expected:
        node = graph["nodes"][route["source_node"]]
        if route["geometry"] not in ([], [node]):
            raise ValueError("zero-edge route geometry differs from supplied source node")
    elif route["geometry"] != expected:
        raise ValueError("route geometry differs from exact directed graph geometry")
    return points


def _remaining_points(trip, graph):
    """Check supplied remaining coordinates against the trip producer's edge order.

    This only compares the received points. In particular it never constructs a
    replacement progress position or asks the graph to interpolate one.
    """
    nodes = graph["nodes"]
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    position = trip["position_m"]
    current = trip["current_edge"]
    remaining = trip["remaining_path"]
    if current is None:
        node = trip["current_node"]
        if node is None or position != nodes[node]:
            raise ValueError("current node position differs from supplied graph node")
        expected = []
        pending = remaining
    else:
        # The public envelope may retain an entry-node identity while the
        # vehicle is in flight. Progress/position binds to the directed edge,
        # so the node-only coordinate check above must not run here.
        edge = edges[current["edge_id"]]
        if not remaining or remaining[0] != edge["edge_id"]:
            raise ValueError("current edge must start remaining path")
        poly = edge["geometry"]
        lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(poly, poly[1:])]
        total = sum(lengths)
        length = edge["length_m"]
        distance = current["distance_m"]
        if length == 0:
            if position != poly[-1]:
                raise ValueError("current edge position differs from supplied zero-length edge")
            expected = [position]
        else:
            if total <= 0:
                raise ValueError("current edge geometry cannot validate progress")
            # Measure the received point along the directed polyline. This is
            # an inverse consistency check, not a new display coordinate.
            passed = 0.0
            located = False
            for a, b, segment in zip(poly, poly[1:], lengths):
                if segment:
                    dx, dy = b[0]-a[0], b[1]-a[1]
                    along = ((position[0]-a[0])*dx + (position[1]-a[1])*dy) / segment
                    offset = ((position[0]-a[0])*dy - (position[1]-a[1])*dx) / segment
                    progress = (passed + along) / total * length
                    if (-1e-6 <= along <= segment + 1e-6 and abs(offset) <= 1e-6
                            and math.isclose(progress, distance, rel_tol=1e-9, abs_tol=1e-6)):
                        located = True
                        break
                passed += segment
            if not located:
                raise ValueError("current edge position differs from supplied progress distance")
            expected = [position]
            passed = 0.0
            for vertex, segment in zip(poly[1:-1], lengths):
                passed += segment
                if distance < passed / total * length < length:
                    expected.append(vertex)
            if expected[-1] != poly[-1]:
                expected.append(poly[-1])
        pending = remaining[1:]
    for edge_id in pending:
        poly = edges[edge_id]["geometry"]
        expected.extend(poly if not expected else poly[1:])
    if not expected:
        expected = [position]
    if trip["remaining_geometry"] != expected:
        raise ValueError("remaining geometry differs from supplied current/pending edge geometry")


def adapt_mission(envelope, *, expected_mission_hash, source_bindings,
                  graph_source_id, snapshot_source_id, limits=SceneLimits()) -> AdaptedMission:
    """Project one caller-bound knight26-mission-v1 envelope without changing it.

    ``expected_mission_hash`` must come from a trusted producer/export manifest,
    rather than being calculated from an untrusted received object. Every source
    declared by the envelope needs an explicit display binding; graph and snapshot
    source selection is the caller's declaration, not inferred OSM provenance.
    """
    if type(envelope) is not dict:
        raise ValueError("mission envelope must be a JSON object")
    _sha(expected_mission_hash)
    if not isinstance(limits, SceneLimits):
        raise ValueError("SceneLimits required")
    for name in ("max_primitives", "max_points", "max_triangles", "max_polygon_points"):
        _version(getattr(limits, name), "scene limit")
    if _number(limits.max_extent_m, "extent limit") <= 0:
        raise ValueError("extent limit must be positive")
    _json_bytes(envelope)
    if envelope.get("mission_hash") != expected_mission_hash:
        raise ValueError("trusted mission hash binding mismatch")
    # Import the canonical public validator, never a vendored schema substitute.
    from contracts.mission import validate_mission
    try:
        mission = validate_mission(envelope)
        return _project(mission, source_bindings, graph_source_id, snapshot_source_id, limits)
    except (KeyError, IndexError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError(f"malformed mission field: {error}") from error


def _project(mission, source_bindings, graph_source_id, snapshot_source_id, limits):
    declared = {source["source_id"] for source in mission["sources"]}
    if type(source_bindings) is not dict or set(source_bindings) != declared:
        raise ValueError("every declared source requires its own explicit display binding")
    selected = {}
    for source_id, binding in source_bindings.items():
        selected[source_id] = _permission(binding)
        if binding.source_id != source_id:
            raise ValueError("display source ID differs from declared envelope source")
    for source_id in (graph_source_id, snapshot_source_id):
        if _text(source_id, "selected source ID") not in declared:
            raise ValueError("selected source must be declared by the envelope")
    if "google" in _json_bytes(mission["sources"]).decode().casefold():
        raise ValueError("Google-derived envelope source rejected")
    metric, snapshot, graph = mission["metric"], mission["snapshot"], mission["graph"]
    origin = metric["origin_lonlat"]
    if abs(math.cos(math.radians(origin[1]))) < 1e-12:
        raise ValueError("equirectangular origin degenerates at the poles")
    identity = FrameIdentity(mission["run_id"], mission["scenario_id"], mission["time_s"], mission["snapshot_hash"])
    roads, units, routes, trails, mapping, undrawn = [], [], [], [], [], []
    geo = _Geometry(limits)
    if len(graph["nodes"]) + len(graph["edges"]) + 4 * len(snapshot["trips"]) + len(snapshot["events"]) > limits.max_primitives:
        raise ValueError("mission record budget exceeded")
    for node_id, point in graph["nodes"].items():
        geo.point(point, f"graph node {node_id}")
    for i, edge in enumerate(graph["edges"]):
        record_id = "road:" + edge["edge_id"]
        roads.append(PolylineRecord(record_id, identity, selected[graph_source_id],
                                    geo.path(edge["geometry"], "graph edge geometry")))
        mapping.append({"record_id": record_id, "source_field": f"graph.edges[{i}].geometry"})
    trips = {}
    vehicles = set()
    for i, trip in enumerate(snapshot["trips"]):
        dispatch = _text(trip.get("dispatch_id"), "dispatch ID")
        vehicle = _text(trip.get("vehicle_id"), "vehicle ID")
        if dispatch in trips or vehicle in vehicles:
            raise ValueError("duplicate dispatch or vehicle identity; authoritative current binding unavailable")
        trips[dispatch] = trip
        vehicles.add(vehicle)
        time = _number(trip.get("time_s"), "trip time")
        if time != identity.time_s:
            raise ValueError("trip time differs from source frame time")
        route = trip["route"]
        version = _version(trip.get("route_version"), "trip route version")
        if _version(route.get("route_version"), "current route version") != version:
            raise ValueError("trip and route versions differ")
        _text(route.get("route_id"), "route ID")
        position = geo.point(trip.get("position_m"), "trip position")
        kind = route["vehicle_kind"]
        kind = "supply_truck" if kind == "truck" else kind
        record_id = "unit:" + vehicle
        units.append(UnitRecord(record_id, identity, selected[snapshot_source_id], kind, position))
        mapping.append({"record_id": record_id, "source_field": f"snapshot.trips[{i}].position_m"})
        full = _route_points(route, graph, geo, "current route geometry")
        completed = geo.path(trip.get("completed_trail"), "completed trail")
        remaining = geo.path(trip.get("remaining_geometry"), "remaining geometry")
        if completed and completed[-1] != position:
            raise ValueError("completed trail endpoint differs from exact source position")
        if remaining and remaining[0] != position:
            raise ValueError("remaining geometry endpoint differs from exact source position")
        _remaining_points(trip, graph)
        for field, points in (("route.geometry", full), ("remaining_geometry", remaining), ("completed_trail", completed)):
            if len(points) < 2:
                if points:
                    undrawn.append({"category": "singleton_path", "dispatch_id": dispatch, "source_field": field,
                                    "reason": "single supplied point; no line geometry invented"})
                continue
            record_id = f"trip:{dispatch}:v{version}:{field}"
            if field == "completed_trail":
                trails.append(PolylineRecord(record_id, identity, selected[snapshot_source_id], points))
            else:
                routes.append(RouteRecord(record_id, identity, selected[snapshot_source_id], points, version, "committed"))
            mapping.append({"record_id": record_id, "source_field": f"snapshot.trips[{i}].{field}"})
    _previous_routes(snapshot, graph, identity, selected[snapshot_source_id], trips, geo, routes, mapping, undrawn)
    points = geo.points
    bounds = SceneBounds(MetricPoint(min(p.x_m for p in points), min(p.y_m for p in points), 0),
                         MetricPoint(max(p.x_m for p in points), max(p.y_m for p in points), 0))
    scene = build_scene(SceneInput(identity, NORMALIZED_CRS,
        "WGS84 origin_lonlat=" + json.dumps(origin, separators=(",", ":")) + "; R=6371008.8 m",
        bounds, "metres", roads=tuple(roads), routes=tuple(routes), trails=tuple(trails), units=tuple(units)), limits=limits)
    undrawn.extend([
        {"category": "ledger", "reason": "ledger/outcomes retained unchanged; no aid or depot coordinates invented"},
        {"category": "safety", "reason": "supplied safety and closure evidence retained; no hazard polygon or safety result computed"},
        {"category": "terrain_buildings_elevations", "reason": "no source geometry/elevations in this envelope"},
    ])
    metadata = {
        "identity": dict(asdict(identity), snapshot_version=mission["snapshot_version"], graph_version=mission["graph_version"]),
        "schema_version": mission["schema_version"], "mission_hash": mission["mission_hash"],
        "source_snapshot": snapshot, "source_mission": mission, "fidelity": mission["fidelity"],
        "source_bindings": {key: asdict(value) for key, value in selected.items()},
        "graph_source_id": graph_source_id, "snapshot_source_id": snapshot_source_id,
        "elevation_assumption": ELEVATION_ASSUMPTION, "view_hash": _hash(asdict(scene)),
        "hash_semantics": "snapshot_hash retains original routing authority; mission_hash binds wrapper; view_hash identifies display projection only",
        "source_binding": "caller-bound declared source/display permissions; source derivation and actual outcomes not independently audited",
        "undrawn": undrawn, "record_mapping": mapping,
    }
    return AdaptedMission(scene, json.loads(_json_bytes(metadata, allow_tuples=True)))


def _previous_routes(snapshot, graph, identity, source, trips, geo, routes, mapping, undrawn):
    seen_events, previous = set(), {}
    for i, event in enumerate(snapshot["events"]):
        event_id = _text(event.get("event_id"), "event ID")
        if event_id in seen_events:
            raise ValueError("duplicate event identity")
        seen_events.add(event_id)
        time = _number(event.get("time_s"), "event time")
        if not 0 <= time <= identity.time_s:
            raise ValueError("event time outside recorded snapshot")
        details = event.get("details")
        if type(details) is not dict:
            raise ValueError("event details must be a JSON object")
        if "previous_path" in details:
            undrawn.append({"category": "previous_path", "event_id": event_id,
                            "reason": "edge IDs lack explicit previous geometry/version; retained without interpolation"})
        route = details.get("route")
        if route is None:
            continue
        if type(route) is not dict:
            raise ValueError("event route must be an object")
        dispatch = _text(event.get("dispatch_id"), "event route dispatch ID")
        trip = trips.get(dispatch)
        if trip is None:
            undrawn.append({"category": "previous_route", "event_id": event_id,
                            "reason": "no current trip identity to bind historical route"})
            continue
        points = _route_points(route, graph, geo, "event route geometry")
        if "route_version" not in route:
            undrawn.append({"category": "previous_route", "event_id": event_id,
                            "reason": "no explicit previous route version; original route retained"})
            continue
        version = _version(route["route_version"], "event route version")
        route_id = _text(route.get("route_id"), "event route ID")
        if route["vehicle_kind"] != trip["route"]["vehicle_kind"] or version > trip["route_version"]:
            raise ValueError("event route differs from trip vehicle/version identity")
        if version == trip["route_version"]:
            if route_id != trip["route"]["route_id"] or route["geometry"] != trip["route"]["geometry"]:
                raise ValueError("same route version has conflicting identity/geometry")
            continue
        key = (dispatch, version)
        authority = (route_id, route["geometry"])
        if key in previous:
            if previous[key] != authority:
                raise ValueError("previous route version has conflicting identity/geometry")
            continue
        previous[key] = authority
        if len(points) < 2:
            undrawn.append({"category": "singleton_path", "event_id": event_id,
                            "reason": "historical route has no line geometry"})
            continue
        record_id = f"previous:{dispatch}:{route_id}:v{version}"
        routes.append(RouteRecord(record_id, identity, source, points, version, "previous"))
        mapping.append({"record_id": record_id, "source_field": f"snapshot.events[{i}].details.route.geometry"})
