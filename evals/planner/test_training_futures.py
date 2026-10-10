import copy
import hashlib
import json

import pytest

from services.planner.futures.training import (
    build_training_future,
    generate_situation,
    severity_profile,
)


def test_severity_discloses_bounded_editable_assumptions():
    low = severity_profile(1)
    high = severity_profile(10)
    assert low["level"] == 1 and high["level"] == 10
    assert low["calibrated"] is False
    assert "synthetic" in low["provenance"].lower()
    assert low["road_failure_probability"] < high["road_failure_probability"]
    assert low["facility_failure_probability"] < high["facility_failure_probability"]
    assert low["additional_incident_count_range"][1] <= high["additional_incident_count_range"][1]
    assert severity_profile(5, {"road_failure_probability": 0.7})["road_failure_probability"] == 0.7
    assert severity_profile(5, {"travel_multiplier_range": [1.0, 1.4]})["travel_multiplier_range"] == [1.0, 1.4]
    for bad in ([1.5, 1.0], [0.9, 1.2], [1.0, float("inf")]):
        with pytest.raises((ValueError, TypeError)):
            severity_profile(5, {"travel_multiplier_range": bad})
    for bad in (0, 11, 2.5, True, float("nan")):
        with pytest.raises((ValueError, TypeError)):
            severity_profile(bad)
    for bad in (-0.1, 1.1, float("inf"), True):
        with pytest.raises((ValueError, TypeError)):
            severity_profile(5, {"facility_failure_probability": bad})


def test_seeded_situations_are_varied_connected_and_structurally_valid():
    cases = [generate_situation(seed, severity=7) for seed in range(12)]
    assert generate_situation(3, 7) == cases[3]
    assert len({tuple((n["x_m"], n["y_m"]) for n in s["nodes"]) for s in cases}) == len(cases)
    assert all(s["time_s"] == 0 and s["horizon_s"] > 0 for s in cases)
    for s in cases:
        nodes = {n["id"] for n in s["nodes"]}
        roads = s["roads"]
        assert len(nodes) == len(s["nodes"])
        assert all(r["source"] in nodes and r["target"] in nodes and r["travel_s"] > 0 for r in roads)
        reached = {s["command_id"]}
        while True:
            nxt = reached | {r["target"] for r in roads if r["source"] in reached}
            if nxt == reached:
                break
            reached = nxt
        assert reached == nodes
        facilities = {f["id"] for f in s["facilities"]}
        agents = set(s["communications"]["agents"])
        assert s["command_id"] in agents
        assert {v["id"] for v in s["vehicles"]} <= agents
        assert {n["id"] for n in s["nodes"] if n["kind"] == "camp"} <= agents
        assert all(v["node_id"] in nodes and v["capacity"] > 0 for v in s["vehicles"])
        assert all(f["node_id"] in nodes and f["capacity"] > 0 for f in s["facilities"])
        assert all(q["node_id"] in nodes and q["destination_id"] in facilities and q["quantity"] > 0
                   for q in s["requests"])
        assert s["goals"]["coverage_threshold_s"] == 120
        assert s["goals"]["priority_order"] == [
            "urgent_service", "supply", "coverage", "protection", "time"
        ]
        assert s["assumptions"]["calibrated"] is False


def test_future_keeps_initial_snapshot_and_samples_all_three_changing_conditions():
    s = generate_situation(18, severity=10)
    before = copy.deepcopy(s)
    future = build_training_future(s, 22)
    assert future == build_training_future(s, 22)
    assert s == before
    assert future["scenario_id"] == s["scenario_id"]
    assert future["start_time_s"] == s["time_s"]
    assert future["horizon_end_s"] == s["time_s"] + s["horizon_s"]
    lo, hi = s["assumptions"]["travel_multiplier_range"]
    assert lo <= future["travel_multiplier"] <= hi
    road_ids = {r["id"] for r in s["roads"]}
    facilities = {f["id"] for f in s["facilities"]}
    initial_requests = {q["id"] for q in s["requests"]}
    assert all(e["time_s"] > 0 and e["time_s"] <= s["horizon_s"] for e in future["truth_events"])
    assert all(e["edge_id"] in road_ids for e in future["truth_events"] if e["kind"] == "road_closed")
    assert all(e["facility_id"] in facilities for e in future["truth_events"] if e["kind"] == "facility_failed")
    assert all(e["request"]["id"] not in initial_requests and e["request"]["quantity"] > 0
               for e in future["truth_events"] if e["kind"] == "request_created")
    all_events = [build_training_future(s, seed) for seed in range(40)]
    kinds = {e["kind"] for f in all_events for e in f["truth_events"]}
    assert kinds == {"road_closed", "facility_failed", "request_created"}
    primary = {r["id"] for r in s["roads"] if r["id"].endswith("-f")}
    alternative = road_ids - primary
    closed = {e["edge_id"] for f in all_events for e in f["truth_events"] if e["kind"] == "road_closed"}
    assert closed & primary and closed & alternative
    truth_by_id = {e["id"]: e for e in future["truth_events"]}
    for o in future["observation_events"]:
        if o["id"].startswith("initial-need-"):
            assert o["time_s"] == 0
            assert o["request"]["id"] in initial_requests
            assert o["id"] not in truth_by_id
        else:
            assert o["id"] in truth_by_id
            assert o["issued_at_s"] >= truth_by_id[o["id"]]["time_s"]
        assert o["received_at_s"] >= o["issued_at_s"]
        assert o["received_at_s"] <= future["horizon_end_s"]
        assert o["recipient_id"] in s["communications"]["agents"]
        assert "seed" not in o and "truth_events" not in o
        assert o["kind"] in kinds

def test_initial_need_reports_travel_as_information_without_recreating_physical_need():
    s = generate_situation(4)
    s["assumptions"] = severity_profile(
        1, {"road_failure_probability": 0, "facility_failure_probability": 0,
            "additional_incident_count_range": [0, 0]}
    )
    s["communications"]["links"] = []
    future = build_training_future(s, 10)
    assert future["truth_events"] == []
    reports = future["observation_events"]
    assert len(reports) == len(s["requests"])
    assert {r["id"] for r in reports} == {
        f"initial-need-{request['id']}" for request in s["requests"]
    }
    assert all(r["recipient_id"] == r["source_id"] for r in reports)
    assert all(r["time_s"] == r["issued_at_s"] == r["received_at_s"] == 0
               for r in reports)



def test_directed_reverse_roads_share_physical_failure_and_all_roads_are_eligible():
    s = generate_situation(12, severity=4)
    groups = {}
    for road in s["roads"]:
        groups.setdefault(road["physical_id"], []).append(road)
    assert groups and all(len(group) == 2 for group in groups.values())
    assert all({road["source"] for road in group} == {road["target"] for road in group}
               for group in groups.values())
    s["assumptions"] = severity_profile(
        4, {"road_failure_probability": 1,
            "facility_failure_probability": 0,
            "additional_incident_count_range": [0, 0]}
    )
    future = build_training_future(s, 44)
    closed = {e["edge_id"]: e["time_s"] for e in future["truth_events"]
              if e["kind"] == "road_closed"}
    assert set(closed) == {road["id"] for road in s["roads"]}
    assert all(len({closed[road["id"]] for road in group}) == 1
               for group in groups.values())


def test_future_preserves_exact_initial_snapshot_and_canonical_hash():
    s = generate_situation(29)
    original = copy.deepcopy(s)
    future = build_training_future(s, 83)
    encoded = json.dumps(s, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert future["initial_snapshot"] == original
    assert future["snapshot_hash"] == hashlib.sha256(encoded).hexdigest()
    future["initial_snapshot"]["requests"][0]["quantity"] += 100
    assert s == original
    assert build_training_future(s, 83)["snapshot_hash"] == future["snapshot_hash"]
