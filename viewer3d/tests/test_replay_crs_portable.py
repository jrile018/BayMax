"""Portable regression for the Maps CRS declaration and AMD scene projection."""
from dataclasses import replace
import hashlib

import pytest

import viewer3d.replay_adapter as replay
from viewer3d.scene import SourceMetadata


def _minimal_replay():
    raw = b"<osm version='0.6'/>"
    raw_sha = hashlib.sha256(raw).hexdigest()
    origin = [-121.607, 39.754]
    bbox = [-121.61, 39.75, -121.60, 39.76]
    note = "tiny declared source area"
    manifest = {
        "source": "OpenStreetMap",
        "license": "ODbL 1.0",
        "attribution": "© OpenStreetMap contributors",
        "license_url": "https://www.openstreetmap.org/copyright",
        "attribution_url": "https://www.openstreetmap.org/copyright",
        "endpoint": "https://overpass-api.de/api/interpreter",
        "raw_sha256": raw_sha,
        "decompressed_sha256": raw_sha,
        "coverage_bbox_lonlat": bbox,
        "source_geometry_bbox_lonlat": bbox,
        "geometry_coverage_note": note,
    }
    area = {
        "area_id": "tiny-training-area",
        "origin_lonlat": origin,
        "metric_crs": replay.METRIC_CRS,
        "bbox_lonlat": bbox,
        "coverage_bbox_lonlat": bbox,
        "source_geometry_bbox_lonlat": bbox,
        "geometry_coverage_note": note,
        "coverage": [
            {"layer": layer, "status": "unavailable"}
            for layer in ("terrain", "fuels", "current_fire", "roads", "buildings", "landuse")
        ],
        "roads": [], "buildings": [], "landuse": [],
        "source_manifest": manifest,
    }
    bootstrap = {
        "area": area,
        "replay": {
            "run_id": "tiny-run",
            "scenario_id": "constructed-training",
            "frame_times_s": [0],
            "frame_count": 1,
        },
        "mode": "mock-replay",
        "label": "constructed training replay",
    }
    graph = {
        "nodes": [], "edges": [],
        "source_sha256": raw_sha,
        "origin_lonlat": origin,
        "metric_crs": replay.METRIC_CRS,
        "area_id": area["area_id"],
        "coverage_bbox_lonlat": bbox,
        "source_geometry_bbox_lonlat": bbox,
        "geometry_coverage_note": note,
    }
    frame = {
        "run_id": "tiny-run",
        "scenario_id": "constructed-training",
        "index": 0,
        "time_s": 0,
        "snapshot_version": 1,
        "mode": "mock-replay",
        "geometry_status": "constructed mock geometry",
        "vehicles": [], "hazards": [], "closures": [], "needs": [], "stocks": [],
    }
    frame["snapshot_hash"] = replay.canonical_content_hash(frame)
    binding = replay.DashboardFrameBinding(
        "tiny-run", "constructed-training", 0, 0, frame["snapshot_hash"],
        replay.canonical_content_hash(bootstrap), replay.canonical_content_hash(graph), raw_sha,
    )
    source = SourceMetadata(
        "project-authored-training", "project-authored training display",
        "project-authorized-training-display", "fixture://tiny-replay", True,
        ("Constructed mock overlays only",),
    )
    return bootstrap, frame, graph, binding, raw, source


def test_maps_crs_is_normalized_to_metres_with_exact_origin_retained():
    bootstrap, frame, graph, binding, raw, source = _minimal_replay()
    view = replay.adapt_dashboard_replay(
        bootstrap, frame, graph, binding=binding,
        raw_source_bytes=raw, overlay_source=source,
    )
    assert "WGS84" in replay.METRIC_CRS
    assert view.scene.metric_crs == replay.NORMALIZED_CRS
    assert view.scene.horizontal_units == "metres"
    assert view.scene.metric_origin == "WGS84 origin_lonlat=[-121.607,39.754]; R=6371008.8 m"
    assert view.metadata["metric_crs"] == replay.NORMALIZED_CRS
    assert view.metadata["source_metric_crs"] == replay.METRIC_CRS
    assert view.metadata["origin_lonlat"] == [-121.607, 39.754]
    assert view.metadata["mode"] == "mock-replay"
    assert view.metadata["mission_bridge"] == "not connected"


def test_unexpected_producer_crs_is_rejected():
    bootstrap, frame, graph, binding, raw, source = _minimal_replay()
    graph["metric_crs"] = "EPSG:4326"
    binding = replace(binding, graph_hash=replay.canonical_content_hash(graph))
    with pytest.raises(ValueError, match="exact local equirectangular"):
        replay.adapt_dashboard_replay(
            bootstrap, frame, graph, binding=binding,
            raw_source_bytes=raw, overlay_source=source,
        )
