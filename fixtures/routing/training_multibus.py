"""Deterministic public-graph TRAINING positions; no telemetry or dispatch."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRAPH_PATH = Path("/workspace/knight26/worktrees/maps/fixtures/geography/paradise/graph.json")
MANIFEST_PATH = Path("/workspace/knight26/worktrees/maps/fixtures/geography/paradise/source_manifest.json")
ARTIFACT_DIR = Path("/workspace/knight26/artifacts/routing")
GRAPH_SHA256 = "a83e326e42aafd581f2e110fa7ca069b17709a6abef2bba86a90acbaaaee550d"
MANIFEST_SHA256 = "e58dbf698d3a50bba58bd23ddc806eeb5458094f19b99a053e697ef8604f0f5e"
RAW_SHA256 = "b73334f6280cc756fee13ab9687ccbd7d47368785f0703fea9dafd97c6035897"
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
EPOCH_TEXT = "2026-01-01T00:00:00Z"
LABEL = "TRAINING — simulated multi-bus positions"
METRIC_CRS = "local equirectangular metres; origin_lonlat is WGS84 longitude,latitude"
ROOT_KEYS = {"schema_version", "training_only", "label", "gps_feed", "real_dispatch",
             "real_eta", "local_hazard_binding", "simulation_epoch_utc",
             "mock_duration_s", "graph_identity", "coordinate_frame", "buses"}
BUS_KEYS = {"bus_id", "route_id", "trail_id", "route", "positions"}
ROUTE_KEYS = {"source_node", "destination_node", "edge_ids", "geometry_m",
              "geometry_lonlat"}
POSITION_KEYS = {"sequence", "elapsed_s", "timestamp_utc", "edge_id",
                 "offset_m", "route_distance_m", "position_m",
                 "position_lonlat", "status"}
IDENTITY_KEYS = {"graph_sha256", "manifest_sha256", "raw_source_sha256"}
FRAME_KEYS = {"metric_crs", "origin_lonlat", "world_crs", "world_axes",
              "acquired_bbox_lonlat"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value):
    _require(type(value) in (float, int) and math.isfinite(value),
             "coordinate or distance must be a finite number")
    return float(value)


def _point(value):
    _require(type(value) is list and len(value) == 2, "expected pair")
    return [_number(x) for x in value]


def _bbox(value):
    _require(type(value) is list and len(value) == 4, "expected bbox")
    bounds = [_number(x) for x in value]
    _require(bounds[0] < bounds[2] and bounds[1] < bounds[3], "invalid bbox")
    return bounds


def _keys(value, keys):
    _require(type(value) is dict and set(value) == keys, "invalid object fields")


def _parse(data, digest):
    _require(type(data) is bytes, "expected raw bytes")
    _require(type(digest) is str and len(digest) == 64
             and all(c in "0123456789abcdef" for c in digest), "invalid expected hash")
    _require(hashlib.sha256(data).hexdigest() == digest, "input byte hash mismatch")
    try:
        result = json.loads(data, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    _require(type(result) is dict, "JSON root must be object")
    return result


def _distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polyline(value):
    _require(type(value) is list and len(value) >= 2, "invalid polyline")
    points = [_point(p) for p in value]
    length = sum(_distance(a, b) for a, b in zip(points, points[1:]))
    _require(length > 0 and math.isfinite(length), "zero or invalid polyline")
    return points, length


def _near(a, b, tolerance=1e-6):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def _context(graph_bytes, manifest_bytes, graph_hash, manifest_hash):
    graph = _parse(graph_bytes, graph_hash)
    manifest = _parse(manifest_bytes, manifest_hash)
    _require(graph.get("area_id") == "paradise-ca", "unsupported area")
    _require(graph.get("metric_crs") == METRIC_CRS, "unsupported frame")
    origin = _point(graph.get("origin_lonlat"))
    bbox = _bbox(graph.get("coverage_bbox_lonlat"))
    _require(manifest.get("coverage_bbox_lonlat") == graph.get("coverage_bbox_lonlat"),
             "incoherent acquired bbox")
    raw = graph.get("source_sha256")
    _require(type(raw) is str and len(raw) == 64
             and all(c in "0123456789abcdef" for c in raw), "invalid raw source identity")
    _require(manifest.get("raw_sha256") == raw
             and manifest.get("decompressed_sha256") == raw,
             "contradictory raw source identity")
    nodes_raw = graph.get("nodes")
    edges_raw = graph.get("edges")
    _require(type(nodes_raw) is list and type(edges_raw) is list,
             "missing graph topology")
    nodes = {}
    for item in nodes_raw:
        _require(type(item) is dict, "invalid node")
        node_id = item.get("id")
        _require(type(node_id) is str and node_id and node_id not in nodes,
                 "duplicate or invalid node id")
        nodes[node_id] = (_point(item.get("geometry_m")), _point(item.get("lonlat")))
    _require(len(nodes) >= 3, "insufficient nodes")
    # Use exact existing node anchors to calibrate the documented separable affine frame.
    anchor_x = max(nodes.values(), key=lambda pair: abs(pair[1][0] - origin[0]))
    anchor_y = max(nodes.values(), key=lambda pair: abs(pair[1][1] - origin[1]))
    dx = anchor_x[1][0] - origin[0]
    dy = anchor_y[1][1] - origin[1]
    _require(abs(dx) > 1e-12 and abs(dy) > 1e-12, "uncalibrated frame")
    x_scale = anchor_x[0][0] / dx
    y_scale = anchor_y[0][1] / dy
    _require(math.isfinite(x_scale) and math.isfinite(y_scale)
             and x_scale > 0 and y_scale > 0, "invalid affine calibration")
    for metric, lonlat in nodes.values():
        _require(abs(metric[0] - (lonlat[0] - origin[0]) * x_scale) <= 1e-5
                 and abs(metric[1] - (lonlat[1] - origin[1]) * y_scale) <= 1e-5,
                 "incoherent node frame")
    def world(metric):
        return [origin[0] + metric[0] / x_scale,
                origin[1] + metric[1] / y_scale]
    edges = {}
    outgoing = defaultdict(list)
    for item in edges_raw:
        _require(type(item) is dict, "invalid edge")
        edge_id = item.get("id")
        source, target = item.get("from_node"), item.get("to_node")
        _require(type(edge_id) is str and edge_id and edge_id not in edges,
                 "duplicate or invalid edge id")
        _require(type(source) is str and type(target) is str
                 and source in nodes and target in nodes and source != target,
                 "invalid directed edge")
        points, length = _polyline(item.get("geometry_m"))
        _require(_near(points[0], nodes[source][0])
                 and _near(points[-1], nodes[target][0]),
                 "edge endpoints disagree with nodes")
        stated_length = _number(item.get("length_m"))
        _require(abs(stated_length - length) <= max(1e-4, length * 1e-6),
                 "edge length disagrees with geometry")
        edges[edge_id] = (source, target, points, length)
        outgoing[source].append(edge_id)
    for ids in outgoing.values():
        ids.sort()
    return graph, origin, bbox, raw, nodes, edges, outgoing, world


def _inside(points, world, bbox):
    return all(bbox[0] <= ll[0] <= bbox[2] and bbox[1] <= ll[1] <= bbox[3]
               for ll in map(world, points))


def _walks(edges, outgoing, world, bbox):
    candidates = []
    for first_id in sorted(edges):
        source, middle, points, _ = edges[first_id]
        if not _inside(points, world, bbox):
            continue
        for second_id in outgoing[middle]:
            _, target, other_points, _ = edges[second_id]
            if target in (source, middle) or not _inside(other_points, world, bbox):
                continue
            candidates.append((first_id, second_id))
    walks = []
    used = set()
    for walk in candidates:
        nodes = {edges[walk[0]][0], edges[walk[0]][1], edges[walk[1]][1]}
        if nodes & used:
            continue
        walks.append(walk)
        used.update(nodes)
        if len(walks) == 3:
            break
    _require(len(walks) == 3, "fewer than three disjoint directed walks")
    return walks


def _geometry(walk, edges):
    first, second = (edges[edge_id] for edge_id in walk)
    return first[2] + second[2][1:]


def _sample(walk, edges, progress):
    lengths = [edges[edge_id][3] for edge_id in walk]
    total = sum(lengths)
    target = total * progress
    traversed = 0.0
    for index, edge_id in enumerate(walk):
        points = edges[edge_id][2]
        edge_length = lengths[index]
        if target <= traversed + edge_length or index == len(walk) - 1:
            offset = min(edge_length, max(0.0, target - traversed))
            along = 0.0
            for segment, (a, b) in enumerate(zip(points, points[1:])):
                size = _distance(a, b)
                if offset <= along + size or segment == len(points) - 2:
                    fraction = min(1.0, max(0.0, (offset - along) / size)) if size else 0.0
                    point = [a[0] + (b[0] - a[0]) * fraction,
                             a[1] + (b[1] - a[1]) * fraction]
                    return edge_id, offset, target, point
                along += size
        traversed += edge_length
    raise ValueError("unreachable route sample")


def _time(seconds):
    return (EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_training_fixture(graph_bytes, manifest_bytes, *,
                           expected_graph_sha256, expected_manifest_sha256):
    _, origin, bbox, raw, _, edges, outgoing, world = _context(
        graph_bytes, manifest_bytes, expected_graph_sha256, expected_manifest_sha256)
    buses = []
    for ordinal, walk in enumerate(_walks(edges, outgoing, world, bbox), 1):
        geometry = _geometry(walk, edges)
        positions = []
        for sequence in range(13):
            elapsed = sequence * 10
            edge_id, offset, distance, metric = _sample(walk, edges, elapsed / 120)
            positions.append({
                "sequence": sequence, "elapsed_s": elapsed, "timestamp_utc": _time(elapsed),
                "edge_id": edge_id, "offset_m": offset, "route_distance_m": distance,
                "position_m": metric, "position_lonlat": world(metric),
                "status": "TRAINING_COMPLETE" if sequence == 12 else "TRAINING_MOVING",
            })
        buses.append({
            "bus_id": f"TRAINING-BUS-{ordinal:03d}",
            "route_id": f"TRAINING-ROUTE-{ordinal:03d}",
            "trail_id": f"TRAINING-TRAIL-{ordinal:03d}",
            "route": {"source_node": edges[walk[0]][0],
                      "destination_node": edges[walk[-1]][1],
                      "edge_ids": list(walk), "geometry_m": geometry,
                      "geometry_lonlat": [world(point) for point in geometry]},
            "positions": positions,
        })
    payload = {
        "schema_version": "1.0", "training_only": True, "label": LABEL,
        "gps_feed": False, "real_dispatch": False, "real_eta": False,
        "local_hazard_binding": None, "simulation_epoch_utc": EPOCH_TEXT,
        "mock_duration_s": 120,
        "graph_identity": {"graph_sha256": expected_graph_sha256,
                           "manifest_sha256": expected_manifest_sha256,
                           "raw_source_sha256": raw},
        "coordinate_frame": {"metric_crs": METRIC_CRS, "origin_lonlat": origin,
                             "world_crs": "WGS84", "world_axes": ["longitude", "latitude"],
                             "acquired_bbox_lonlat": bbox},
        "buses": buses,
    }
    validate_training_fixture(payload, graph_bytes, manifest_bytes,
                              expected_graph_sha256=expected_graph_sha256,
                              expected_manifest_sha256=expected_manifest_sha256)
    return payload


def validate_training_fixture(payload, graph_bytes, manifest_bytes, *,
                              expected_graph_sha256, expected_manifest_sha256):
    _, origin, bbox, raw, _, edges, outgoing, world = _context(
        graph_bytes, manifest_bytes, expected_graph_sha256, expected_manifest_sha256)
    _keys(payload, ROOT_KEYS)
    _require(payload["schema_version"] == "1.0"
             and payload["training_only"] is True and payload["label"] == LABEL
             and payload["gps_feed"] is False and payload["real_dispatch"] is False
             and payload["real_eta"] is False
             and payload["local_hazard_binding"] is None
             and payload["simulation_epoch_utc"] == EPOCH_TEXT
             and type(payload["mock_duration_s"]) is int
             and payload["mock_duration_s"] == 120, "not a bounded TRAINING fixture")
    _keys(payload["graph_identity"], IDENTITY_KEYS)
    _require(payload["graph_identity"] == {
        "graph_sha256": expected_graph_sha256,
        "manifest_sha256": expected_manifest_sha256,
        "raw_source_sha256": raw}, "graph identity mismatch")
    _keys(payload["coordinate_frame"], FRAME_KEYS)
    frame = payload["coordinate_frame"]
    _require(frame["metric_crs"] == METRIC_CRS
             and frame["world_crs"] == "WGS84"
             and frame["world_axes"] == ["longitude", "latitude"]
             and _point(frame["origin_lonlat"]) == origin
             and _bbox(frame["acquired_bbox_lonlat"]) == bbox,
             "coordinate frame mismatch")
    expected_walks = _walks(edges, outgoing, world, bbox)
    buses = payload["buses"]
    _require(type(buses) is list and len(buses) == 3, "expected three buses")
    seen_buses, seen_routes, seen_trails = set(), set(), set()
    for ordinal, (bus, expected_walk) in enumerate(zip(buses, expected_walks), 1):
        _keys(bus, BUS_KEYS)
        ids = [(bus["bus_id"], seen_buses, f"TRAINING-BUS-{ordinal:03d}"),
               (bus["route_id"], seen_routes, f"TRAINING-ROUTE-{ordinal:03d}"),
               (bus["trail_id"], seen_trails, f"TRAINING-TRAIL-{ordinal:03d}")]
        for value, seen, expected in ids:
            _require(type(value) is str and value == expected and value not in seen,
                     "ambiguous TRAINING identity")
            seen.add(value)
        route = bus["route"]
        _keys(route, ROUTE_KEYS)
        walk = route["edge_ids"]
        _require(type(walk) is list and walk == list(expected_walk), "foreign or changed walk")
        _require(route["source_node"] == edges[walk[0]][0]
                 and route["destination_node"] == edges[walk[-1]][1],
                 "route endpoints mismatch")
        geometry = _geometry(walk, edges)
        _require(type(route["geometry_m"]) is list
                 and len(route["geometry_m"]) == len(geometry), "route geometry size mismatch")
        _require(type(route["geometry_lonlat"]) is list
                 and len(route["geometry_lonlat"]) == len(geometry), "world geometry size mismatch")
        for claimed_m, claimed_ll, actual in zip(route["geometry_m"],
                                                  route["geometry_lonlat"], geometry):
            _require(_near(_point(claimed_m), actual)
                     and _near(_point(claimed_ll), world(actual), 1e-9),
                     "route geometry mismatch")
        positions = bus["positions"]
        _require(type(positions) is list and len(positions) == 13, "invalid timeline")
        for sequence, position in enumerate(positions):
            _keys(position, POSITION_KEYS)
            elapsed = sequence * 10
            _require(type(position["sequence"]) is int
                     and position["sequence"] == sequence
                     and type(position["elapsed_s"]) is int
                     and position["elapsed_s"] == elapsed
                     and position["timestamp_utc"] == _time(elapsed)
                     and position["status"] ==
                     ("TRAINING_COMPLETE" if sequence == 12 else "TRAINING_MOVING"),
                     "incoherent TRAINING timestamp or status")
            edge_id, offset, distance, metric = _sample(walk, edges, elapsed / 120)
            _require(position["edge_id"] == edge_id
                     and abs(_number(position["offset_m"]) - offset) <= 1e-6
                     and abs(_number(position["route_distance_m"]) - distance) <= 1e-6
                     and _near(_point(position["position_m"]), metric)
                     and _near(_point(position["position_lonlat"]), world(metric), 1e-9),
                     "position disagrees with directed route progress")
    return None


def contract_schema():
    def obj(properties, required=None):
        return {"type": "object", "additionalProperties": False,
                "required": list(required or properties), "properties": properties}
    number = {"type": "number"}
    pair = {"type": "array", "items": number, "minItems": 2, "maxItems": 2}
    bbox = {"type": "array", "items": number, "minItems": 4, "maxItems": 4}
    polyline = {"type": "array", "items": pair, "minItems": 2}
    position = obj({
        "sequence": {"type": "integer", "minimum": 0, "maximum": 12},
        "elapsed_s": {"type": "integer", "minimum": 0, "maximum": 120},
        "timestamp_utc": {"type": "string", "format": "date-time"},
        "edge_id": {"type": "string", "minLength": 1},
        "offset_m": {"type": "number", "minimum": 0},
        "route_distance_m": {"type": "number", "minimum": 0},
        "position_m": pair, "position_lonlat": pair,
        "status": {"enum": ["TRAINING_MOVING", "TRAINING_COMPLETE"]},
    })
    route = obj({"source_node": {"type": "string"}, "destination_node": {"type": "string"},
                 "edge_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                 "geometry_m": polyline, "geometry_lonlat": polyline})
    bus = obj({"bus_id": {"type": "string", "pattern": "^TRAINING-BUS-00[1-3]$"},
               "route_id": {"type": "string", "pattern": "^TRAINING-ROUTE-00[1-3]$"},
               "trail_id": {"type": "string", "pattern": "^TRAINING-TRAIL-00[1-3]$"},
               "route": route, "positions": {"type": "array", "items": position,
                                             "minItems": 13, "maxItems": 13}})
    schema = obj({
        "schema_version": {"const": "1.0"}, "training_only": {"const": True},
        "label": {"const": LABEL}, "gps_feed": {"const": False},
        "real_dispatch": {"const": False}, "real_eta": {"const": False},
        "local_hazard_binding": {"type": "null"},
        "simulation_epoch_utc": {"const": EPOCH_TEXT},
        "mock_duration_s": {"const": 120},
        "graph_identity": obj({name: {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                               for name in sorted(IDENTITY_KEYS)}),
        "coordinate_frame": obj({
            "metric_crs": {"const": METRIC_CRS}, "origin_lonlat": pair,
            "world_crs": {"const": "WGS84"},
            "world_axes": {"const": ["longitude", "latitude"]},
            "acquired_bbox_lonlat": bbox}),
        "buses": {"type": "array", "items": bus, "minItems": 3, "maxItems": 3},
    })
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Paradise static multi-bus TRAINING fixture"
    schema["description"] = ("Authored positions over an existing public road graph. "
        "No GPS, current restrictions, safety, vehicle eligibility, dispatch, aid or ETA.")
    return schema


def _read_fixed(path, maximum):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum,
                 "public input must be bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        _require(len(data) <= maximum, "public input exceeded limit")
        return data
    finally:
        os.close(fd)


def _write_exclusive(path, document):
    data = (json.dumps(document, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def main():
    graph = _read_fixed(GRAPH_PATH, 64 * 1024 * 1024)
    manifest = _read_fixed(MANIFEST_PATH, 5 * 1024 * 1024)
    fixture = build_training_fixture(
        graph, manifest, expected_graph_sha256=GRAPH_SHA256,
        expected_manifest_sha256=MANIFEST_SHA256)
    _require(fixture["graph_identity"]["raw_source_sha256"] == RAW_SHA256,
             "unexpected raw public source")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _write_exclusive(ARTIFACT_DIR / "training-multibus-fixture.json", fixture)
    _write_exclusive(ARTIFACT_DIR / "training-multibus-contract.json", contract_schema())
    print("TRAINING fixture: 3 buses, 3 routes, 3 trails, 39 positions")


if __name__ == "__main__":
    main()
