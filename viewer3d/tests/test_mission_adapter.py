"""Fictional schema fixtures only; these do not prove an integrated OSM mission."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json

import pytest
mission_contract = pytest.importorskip(
    "contracts.mission", reason="optional mission contract is maintained separately"
)
build_mission = mission_contract.build_mission
canonical_hash = mission_contract.canonical_hash
from viewer3d.mission_adapter import adapt_mission
from viewer3d.scene import SourceMetadata, SceneLimits


def fixture():
    graph = {"version": "fictional-v1", "nodes": {"A": [0, 0], "B": [100, 0], "C": [200, 0]},
             "edges": [{"edge_id": eid, "source": a, "target": b, "geometry": geometry,
                "length_m": 100, "travel_s": 10, "access": ["bus", "ambulance", "truck"],
                "weight_source": "fictional fixture", "source_way_id": eid,
                "raw_vehicle_access": {}, "access_policy": "declared fixture"}
                for eid, a, b, geometry in [("ab", "A", "B", [[0, 0], [100, 0]]),
                                            ("bc", "B", "C", [[100, 0], [200, 0]])]]}
    route = {"route_id": "route1", "route_version": 2, "graph_version": "fictional-v1",
             "source_node": "A", "destination_node": "C", "vehicle_kind": "bus",
             "edge_ids": ["ab", "bc"], "legs": [{"edge_id": "ab", "entry_s": 0, "exit_s": 10},
                {"edge_id": "bc", "entry_s": 10, "exit_s": 20}],
             "geometry": [[0, 0], [100, 0], [200, 0]], "status": "feasible",
             "safety_validated": True, "known_version": "k0", "departure_s": 0, "arrival_s": 20}
    trip = {"dispatch_id": "dispatch1", "vehicle_id": "bus1", "request_id": "request1",
        "phase": "traveling", "route": route, "route_version": 2, "time_s": 5.0,
        "current_node": None, "current_edge": {"edge_id": "ab", "direction": "A->B", "distance_m": 50},
        "position_m": [50, 0], "completed_trail": [[0, 0], [50, 0]],
        "remaining_geometry": [[50, 0], [100, 0], [200, 0]], "remaining_path": ["ab", "bc"],
        "completed_edge_ids": [], "passengers": ["fictional-person"], "cargo": {},
        "eta_arrival_s": 20, "exposure_s": 0}
    old = deepcopy(route); old["route_version"] = 1
    snapshot = {"run_id": "fictional-run", "scenario_id": "fictional-schema-test", "time_s": 5.0,
                "snapshot_version": 2, "graph_version": "fictional-v1",
                "metric_crs": "declared local metric x/y metres", "trips": [trip],
                "events": [{"event_id": "e1", "type": "dispatch", "dispatch_id": "dispatch1", "time_s": 0,
                    "details": {"route": old}}, {"event_id": "e2", "type": "reroute", "dispatch_id": "dispatch1",
                    "time_s": 4, "details": {"previous_path": ["ab", "bc"], "route_version": 2}}],
                "ledger": {"stocks": {"unlocated": {"water": 10}}, "outcomes": {}, "outcome_counts": {"supply": 0}}}
    snapshot["snapshot_hash"] = canonical_hash(snapshot)
    metric = {"crs": "local-equirectangular", "origin_lonlat": [-121.607, 39.754],
              "horizontal_units": "metres", "axis_order": ["east", "north"], "radius_m": 6371008.8}
    sources = [{"source_id": sid, "kind": "fictional fixture", "sha256": digest * 64,
                "available_at_s": 0, "retrieved_at_utc": "2026-10-10T00:00:00Z"}
               for sid, digest in [("fictional-graph", "a"), ("fictional-trip", "b")]]
    safety = {"version": "k0", "known_at_s": 5, "issued_s": 0, "horizon_s": 1000,
              "safety_buffer_s": 0, "covered_edges": ["ab", "bc"], "safe_nodes": ["A", "B", "C"],
              "closures": [{"edge_id": "ab", "start_s": 10, "end_s": 20, "issued_s": 0,
                            "received_s": 5, "reason": "fictional exercise", "evidence": "fixture"}]}
    fidelity = {"geography": "fictional_fixture", "mission": "computed_training",
                "hazard": "training_closure_inject", "model": "not_run", "physical_engine": "not_proved", "fsr4": "not_proved"}
    return build_mission(snapshot, graph, metric, sources, safety, fidelity=fidelity)


def bindings():
    return {sid: SourceMetadata(sid, "project-authored fictional fixture", "MIT", "fictional schema test", True)
            for sid in ("fictional-graph", "fictional-trip")}


def adapt(value, **kw):
    args = dict(expected_mission_hash=value["mission_hash"], source_bindings=bindings(),
                graph_source_id="fictional-graph", snapshot_source_id="fictional-trip")
    args.update(kw)
    return adapt_mission(value, **args)


def resign(value):
    value["snapshot"]["snapshot_hash"] = canonical_hash(value["snapshot"], omit_key="snapshot_hash")
    value["snapshot_hash"] = value["snapshot"]["snapshot_hash"]
    value["mission_hash"] = canonical_hash(value, omit_key="mission_hash")
    return value


def xy(primitive):
    return [[p.x_m, p.y_m] for p in primitive.points]


def test_exact_source_geometry_identity_and_three_hashes():
    value = fixture(); before = deepcopy(value)
    adapted = adapt(value)
    scene, meta = adapted.scene, adapted.metadata
    assert value == before
    assert scene.frame.snapshot_hash == value["snapshot_hash"]
    assert meta["identity"]["snapshot_hash"] == value["snapshot_hash"]
    assert meta["source_snapshot"] == value["snapshot"]
    assert meta["source_mission"] == value
    assert meta["mission_hash"] == value["mission_hash"]
    assert meta["view_hash"] == canonical_hash(asdict(scene))
    assert meta["fidelity"] == value["fidelity"]
    assert meta["source_mission"]["safety"] == value["safety"]
    primitives = scene.primitives
    assert xy(next(p for p in primitives if p.kind == "unit")) == [[50, 0]]
    assert xy(next(p for p in primitives if p.kind == "trail")) == [[0, 0], [50, 0]]
    assert [xy(p) for p in primitives if p.kind == "route" and p.role == "committed"] == [
        [[0, 0], [100, 0], [200, 0]], [[50, 0], [100, 0], [200, 0]]]
    assert [p.route_version for p in primitives if p.role == "previous"] == [1]
    assert all(p.z_m == 0 for primitive in primitives for p in primitive.points)
    assert "visual assumption" in meta["elevation_assumption"]
    assert not any(p.kind in {"terrain", "building", "fire", "aid"} for p in primitives)
    assert any(row["category"] == "previous_path" for row in meta["undrawn"])
    assert any(row["category"] == "ledger" for row in meta["undrawn"])
    assert "not independently audited" in meta["source_binding"]
    value["snapshot"]["ledger"]["outcomes"]["changed"] = 1
    assert "changed" not in meta["source_snapshot"]["ledger"]["outcomes"]


def test_trusted_mission_hash_required_and_original_tamper_rejected():
    value = fixture()
    with pytest.raises(ValueError, match="mission hash"):
        adapt(value, expected_mission_hash="c" * 64)
    value["snapshot"]["trips"][0]["position_m"][0] += 1
    value["mission_hash"] = canonical_hash(value, omit_key="mission_hash")
    with pytest.raises(ValueError, match="snapshot_hash"):
        adapt(value)


@pytest.mark.parametrize("mutation", [
    lambda v: v.__setitem__("time_s", True),
    lambda v: v["metric"].__setitem__("radius_m", float("nan")),
    lambda v: v["metric"].__setitem__("axis_order", ["north", "east"]),
    lambda v: v["metric"].__setitem__("origin_lonlat", [0, 90]),
    lambda v: v["safety"]["closures"][0].__setitem__("received_s", 6),
    lambda v: v["sources"][0].__setitem__("available_at_s", 6),
    lambda v: v["sources"][0].__setitem__("kind", "Google-derived map"),
])
def test_invalid_root_evidence_fails_closed(mutation):
    value = fixture(); mutation(value)
    try: resign(value)
    except ValueError: pass
    with pytest.raises(ValueError): adapt(value)


@pytest.mark.parametrize("field,value", [
    ("position_m", [True, 0]), ("position_m", [0, 0, 0]),
    ("completed_trail", [[0, 0], [True, 0]]), ("remaining_geometry", [[50, 0], [float("inf"), 0]]),
    ("route_version", True), ("route_version", 3), ("time_s", True), ("time_s", 6),
    ("vehicle_id", ""), ("dispatch_id", ""), ("position_m", None),
    ("completed_trail", [[0, 0], [49, 0]]), ("remaining_geometry", [[49, 0], [100, 0]]),
])
def test_malformed_trip_display_fields_rejected(field, value):
    envelope = fixture(); envelope["snapshot"]["trips"][0][field] = value
    try: resign(envelope)
    except ValueError: pass
    with pytest.raises(ValueError): adapt(envelope)


@pytest.mark.parametrize("mutation", [
    lambda r: r.__setitem__("route_version", True),
    lambda r: r.__setitem__("geometry", [[True, 0], [100, 0], [200, 0]]),
    lambda r: r.__setitem__("geometry", [[0, 0], [90, 0], [200, 0]]),
])
def test_route_geometry_must_bind_to_directed_graph(mutation):
    value = fixture(); mutation(value["snapshot"]["trips"][0]["route"]); resign(value)
    with pytest.raises(ValueError): adapt(value)


def test_singleton_trails_and_unknown_previous_versions_stay_metadata():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["completed_trail"] = [[50, 0]]
    value["snapshot"]["events"][0]["details"]["route"].pop("route_version")
    resign(value); adapted = adapt(value)
    assert not any(p.kind == "trail" or p.role == "previous" for p in adapted.scene.primitives)
    assert adapted.metadata["source_snapshot"] == value["snapshot"]
    assert any(row["category"] == "singleton_path" for row in adapted.metadata["undrawn"])
    assert any(row["category"] == "previous_route" for row in adapted.metadata["undrawn"])


def test_duplicate_vehicle_or_dispatch_identity_rejected():
    for key in ("vehicle_id", "dispatch_id"):
        value = fixture(); duplicate = deepcopy(value["snapshot"]["trips"][0])
        duplicate["dispatch_id" if key == "vehicle_id" else "vehicle_id"] += "-other"
        value["snapshot"]["trips"].append(duplicate); resign(value)
        with pytest.raises(ValueError, match="duplicate"): adapt(value)


@pytest.mark.parametrize("time", [True, -1, 6])
def test_event_time_must_be_recorded_within_snapshot(time):
    value = fixture(); value["snapshot"]["events"][0]["time_s"] = time; resign(value)
    with pytest.raises(ValueError): adapt(value)


@pytest.mark.parametrize("change", [
    lambda b: b.pop("fictional-trip"),
    lambda b: b.__setitem__("fictional-trip", replace(b["fictional-trip"], source_id="wrong")),
    lambda b: b.__setitem__("fictional-trip", replace(b["fictional-trip"], license_id="unknown")),
    lambda b: b.__setitem__("fictional-trip", replace(b["fictional-trip"], independently_sourced=False)),
    lambda b: b.__setitem__("fictional-trip", replace(b["fictional-trip"], reference="Google-derived")),
])
def test_explicit_declared_display_bindings_required(change):
    sources = bindings(); change(sources)
    with pytest.raises(ValueError): adapt(fixture(), source_bindings=sources)


def test_selected_source_must_be_declared():
    with pytest.raises(ValueError): adapt(fixture(), graph_source_id="undeclared")


def test_source_permission_changes_view_only_and_is_preserved():
    value = fixture(); first = adapt(value)
    sources = bindings(); sources["fictional-graph"] = replace(sources["fictional-graph"], assumptions=("display license declaration",))
    second = adapt(value, source_bindings=sources)
    assert first.metadata["mission_hash"] == second.metadata["mission_hash"]
    assert first.scene.frame == second.scene.frame
    assert first.metadata["view_hash"] != second.metadata["view_hash"]
    assert "display license declaration" in second.metadata["source_bindings"]["fictional-graph"]["assumptions"]


def test_budgets_are_checked_without_native_context():
    with pytest.raises(ValueError, match="budget"):
        adapt(fixture(), limits=SceneLimits(max_points=2))


def test_canonical_root_validator_is_called_with_original_input(monkeypatch):
    import contracts.mission as contract
    original = contract.validate_mission
    value = fixture(); calls = []
    def inspect(mapping):
        assert mapping is value
        calls.append(deepcopy(mapping))
        return original(mapping)
    monkeypatch.setattr(contract, "validate_mission", inspect)
    adapt(value)
    assert calls == [value]


def test_root_validator_rejection_propagates(monkeypatch):
    import contracts.mission as contract
    value = fixture()
    def reject(mapping):
        raise ValueError("root-authority-rejection")
    monkeypatch.setattr(contract, "validate_mission", reject)
    with pytest.raises(ValueError, match="root-authority-rejection"):
        adapt(value)


@pytest.mark.parametrize("mutation", [
    lambda v: v["snapshot"].__setitem__("time_s", 5),
    lambda v: v["snapshot"]["events"][0]["details"]["route"].__setitem__("route_version", 3),
    lambda v: v["snapshot"]["events"][0]["details"]["route"].__setitem__("route_version", True),
    lambda v: v["snapshot"]["events"][0]["details"]["route"].__setitem__("vehicle_kind", "truck"),
    lambda v: v["snapshot"]["events"][1].__setitem__("event_id", "e1"),
    lambda v: v["snapshot"]["trips"][0]["route"].__setitem__("route_version", -1),
])
def test_original_identity_and_historical_route_conflicts_rejected(mutation):
    value = fixture(); mutation(value); resign(value)
    with pytest.raises(ValueError): adapt(value)


def test_public_input_requires_json_and_bounded_content():
    from viewer3d import mission_adapter as adapter
    value = fixture()
    value["snapshot"]["trips"][0]["position_m"] = (50, 0)
    with pytest.raises(ValueError, match="JSON"): adapt(value)
    value = fixture(); value["snapshot"]["ledger"]["cycle"] = value
    with pytest.raises(ValueError, match="budget"): adapt(value)
    value = fixture()
    original = adapter.MAX_JSON_BYTES
    try:
        adapter.MAX_JSON_BYTES = 10
        with pytest.raises(ValueError, match="budget"): adapt(value)
    finally:
        adapter.MAX_JSON_BYTES = original


def test_scene_extent_budget_does_not_move_source_coordinates():
    with pytest.raises(ValueError, match="extent"):
        adapt(fixture(), limits=SceneLimits(max_extent_m=20))


def test_an_empty_trip_frame_draws_only_supplied_graph():
    value = fixture(); value["snapshot"]["trips"] = []; value["snapshot"]["events"] = []; resign(value)
    adapted = adapt(value)
    assert all(p.kind == "road" for p in adapted.scene.primitives)
    assert adapted.metadata["source_snapshot"] == value["snapshot"]


def test_truck_kind_conversion_preserves_source_vehicle_identity():
    value = fixture(); value["snapshot"]["trips"][0]["route"]["vehicle_kind"] = "truck"
    value["snapshot"]["events"][0]["details"]["route"]["vehicle_kind"] = "truck"; resign(value)
    unit = next(p for p in adapt(value).scene.primitives if p.kind == "unit")
    assert unit.role == "supply_truck"
    assert unit.record_id == "unit:bus1"
    # The exact kind is retained in the source; scene maps truck to its supported glyph.
    assert adapt(value).metadata["source_snapshot"]["trips"][0]["route"]["vehicle_kind"] == "truck"


def test_changed_wrapper_source_does_not_replace_original_snapshot_hash():
    value = fixture(); original = value["snapshot_hash"]
    value["sources"][0]["sha256"] = "c" * 64; resign(value)
    adapted = adapt(value)
    assert adapted.scene.frame.snapshot_hash == original
    assert adapted.metadata["mission_hash"] == value["mission_hash"]
    assert adapted.metadata["source_mission"]["sources"][0]["sha256"] == "c" * 64


def test_metadata_hook_preserves_mission_authority_and_native_fields_with_fake_context(tmp_path, monkeypatch):
    from viewer3d.render import render_native
    from viewer3d.tests.test_render import Context, fake_module
    value = fixture(); adapted = adapt(value); before = deepcopy(adapted.metadata)
    context = Context(); fake_module(monkeypatch, context)
    result = render_native(adapted.scene, tmp_path / "fictional-fake.png", width=2, height=2,
                           replay_metadata=adapted.metadata)
    assert adapted.metadata == before
    assert result["replay"] == before
    assert result["frame"]["snapshot_hash"] == value["snapshot_hash"]
    assert result["replay"]["mission_hash"] == value["mission_hash"]
    assert result["replay"]["source_snapshot"] == value["snapshot"]
    assert result["provider"]["GL_VENDOR"] == "test double"
    assert result["fsr"] == "not implemented"


def test_zero_edge_and_singleton_geometry_remain_exact_without_new_vertices():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["position_m"] = [0, 0]; trip["completed_trail"] = []; trip["remaining_geometry"] = [[0, 0]]
    trip["remaining_path"] = []; trip["current_edge"] = None; trip["current_node"] = "A"
    trip["route"].update(destination_node="A", edge_ids=[], legs=[], geometry=[[0, 0]])
    value["snapshot"]["events"] = []; resign(value)
    adapted = adapt(value)
    assert not any(p.kind in {"route", "trail"} for p in adapted.scene.primitives)
    assert xy(next(p for p in adapted.scene.primitives if p.kind == "unit")) == [[0, 0]]
    assert adapted.metadata["source_snapshot"] == value["snapshot"]


def test_node_position_must_match_supplied_node_even_when_remaining_path_begins_there():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["current_edge"] = None; trip["current_node"] = "A"
    trip["position_m"] = [50, 50]
    trip["completed_trail"] = [[50, 50]]
    trip["remaining_geometry"] = [[50, 50], [100, 0], [200, 0]]
    resign(value)
    with pytest.raises(ValueError, match="current node position"):
        adapt(value)


def test_inflight_position_is_not_required_to_equal_entry_node():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["current_node"] = "A"  # Retained entry identity during current-edge travel.
    resign(value)
    adapted = adapt(value)
    assert xy(next(p for p in adapted.scene.primitives if p.kind == "unit")) == [[50, 0]]
    assert adapted.metadata["source_snapshot"]["trips"][0]["current_node"] == "A"


def test_remaining_geometry_rejects_divergent_interior_while_preserving_source():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["remaining_geometry"] = [[50, 0], [123, 77], [200, 0]]
    resign(value)
    with pytest.raises(ValueError, match="remaining geometry"):
        adapt(value)


def test_remaining_geometry_accepts_exact_partial_edge_and_pending_vertices():
    value = fixture(); graph = value["graph"]
    graph["edges"][0]["geometry"] = [[0, 0], [25, 0], [100, 0]]
    graph["edges"][1]["geometry"] = [[100, 0], [150, 0], [200, 0]]
    trip = value["snapshot"]["trips"][0]
    trip["route"]["geometry"] = [[0, 0], [25, 0], [100, 0], [150, 0], [200, 0]]
    value["snapshot"]["events"][0]["details"]["route"]["geometry"] = deepcopy(trip["route"]["geometry"])
    trip["remaining_geometry"] = [[50, 0], [100, 0], [150, 0], [200, 0]]
    resign(value)
    adapted = adapt(value)
    assert [xy(p) for p in adapted.scene.primitives if p.kind == "route" and p.role == "committed"][1] == trip["remaining_geometry"]


def test_current_edge_position_must_agree_with_progress_distance():
    value = fixture(); trip = value["snapshot"]["trips"][0]
    trip["position_m"] = [75, 0]
    trip["completed_trail"][-1] = [75, 0]
    trip["remaining_geometry"][0] = [75, 0]
    resign(value)
    with pytest.raises(ValueError, match="current edge position"):
        adapt(value)
