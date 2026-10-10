import copy

import pytest

from services.planner.futures.conditional import (
    build_ensemble,
    condition_ensemble,
    visible_observations,
)


def sample_snapshot():
    return {
        "time_s": 100.0,
        "scenario_id": "wildfire-demo",
        "snapshot_version": 7,
        "observations": [
            {
                "event_id": "obs-open-a",
                "kind": "road_open",
                "edge_id": "a",
                "issued_at_s": 80.0,
                "received_at_s": 90.0,
            },
            {
                "event_id": "obs-closed",
                "kind": "road_closed",
                "edge_id": "already-closed",
                "issued_at_s": 95.0,
                "received_at_s": 99.0,
            },
        ],
        "roads": [
            {"edge_id": "a", "zone": "north", "closure_offset_s": 0.0, "length_m": 1200, "source": "survey"},
            {"edge_id": "b", "zone": "north", "closure_offset_s": 12.0, "length_m": 900, "target": "node-b"},
            {"edge_id": "stable", "zone": "north", "uncertain_closure": False, "length_m": 300},
            {"edge_id": "already-closed", "zone": "south", "uncertain_closure": True},
        ],
        "trips": [{"trip_id": "trip-1", "edge_id": "opaque", "progress_m": 42}],
        "ledger": {"vehicle_load": {"van-1": 3}, "custom_extension": {"x": [1, 2]}},
        "opaque_extension": {"preserve": True},
    }


def test_ensemble_is_seed_reproducible_without_mutating_snapshot():
    snapshot = sample_snapshot()
    before = copy.deepcopy(snapshot)
    first = build_ensemble(snapshot, [17, 23], horizon_s=300)
    second = build_ensemble(snapshot, [17, 23], horizon_s=300)

    assert first == second
    assert snapshot == before
    assert first[0]["initial_snapshot"] == before
    assert first[0]["snapshot_hash"] == first[1]["snapshot_hash"]
    assert len(first[0]["snapshot_hash"]) == 64
    assert first[0]["seed"] == 17
    assert first[0]["start_time_s"] == 100.0
    assert first[0]["horizon_end_s"] == 400.0
    assert "synthetic" in first[0]["assumptions"]["provenance"].lower()
    assert first[0]["assumptions"]["calibrated"] is False


def test_future_copies_and_observation_views_are_isolated_and_hide_latent_truth():
    futures = build_ensemble(sample_snapshot(), [5, 6])
    futures[0]["initial_snapshot"]["ledger"]["custom_extension"]["x"].append(3)
    t = futures[0]["horizon_end_s"]
    view = visible_observations(futures[0], t)
    assert "latent" not in view
    assert "truth_events" not in view
    assert all("seed" not in event for event in view)
    assert all(
        f"closure-{futures[0]['seed']}-" not in event.get("event_id", "")
        for event in view
    )
    if view:
        view[0]["kind"] = "tampered"
    assert futures[0]["initial_snapshot"]["observations"][0]["kind"] == "road_open"
    assert futures[1]["initial_snapshot"]["ledger"]["custom_extension"]["x"] == [1, 2]
    assert futures[0]["initial_snapshot"]["trips"] == sample_snapshot()["trips"]


def test_zone_closures_share_one_latent_clock_and_respect_declared_offsets():
    future = build_ensemble(sample_snapshot(), [31])[0]
    by_edge = {event["edge_id"]: event for event in future["truth_events"]}
    assert "stable" not in by_edge
    assert "already-closed" not in by_edge
    assert by_edge["a"]["kind"] == "road_closed"
    assert by_edge["b"]["kind"] == "road_closed"
    assert by_edge["b"]["time_s"] - by_edge["a"]["time_s"] == pytest.approx(12.0)
    base = future["latent"]["closure_base_s_by_zone"]["north"]
    intensity = future["latent"]["fire_intensity"]
    assert by_edge["a"]["time_s"] == pytest.approx(100 + base / intensity)


def test_new_observation_arrives_after_true_closure_and_visibility_is_time_cut():
    future = build_ensemble(sample_snapshot(), [42], assumptions={"observation_delay_s": 8})[0]
    assert len(future["truth_events"]) >= 1
    truth = future["truth_events"][0]
    observation = next(e for e in future["observation_events"] if e["event_id"] == truth["event_id"])
    assert observation["issued_at_s"] == truth["time_s"]
    assert observation["received_at_s"] == truth["time_s"] + 8
    assert observation not in visible_observations(future, observation["received_at_s"] - 0.01)
    assert observation in visible_observations(future, observation["received_at_s"])
    assert observation["event_id"] not in {e["event_id"] for e in visible_observations(future, truth["time_s"])}


def test_conditioning_keeps_only_stress_paths_consistent_with_timestamped_closure():
    futures = build_ensemble(sample_snapshot(), [1, 2, 3, 4])
    edge = "a"
    observed = {
        "event_id": "known-closure",
        "kind": "road_closed",
        "edge_id": edge,
        "issued_at_s": 150.0,
        "received_at_s": 160.0,
        "time_s": 150.0,
    }
    result = condition_ensemble(futures, observed)
    assert result
    assert all(
        any(e["edge_id"] == edge and e["kind"] == "road_closed" and e["time_s"] <= 150.0 for e in f["truth_events"])
        for f in result
    )
    assert all("stress" in f["assumptions"]["interpretation"].lower() for f in result)
    assert all(f.get("weight") is None for f in result)
    assert all(
        sum(e["event_id"] == observed["event_id"]
            for e in visible_observations(f, observed["received_at_s"])) == 1
        for f in result
    )
    assert all(
        all(e["event_id"] != observed["event_id"]
            for e in visible_observations(f, observed["received_at_s"] - 0.01))
        for f in result
    )




def test_authoritative_receipt_replaces_early_sampled_notice_for_same_edge():
    snapshot = {
        "time_s": 100.0,
        "observations": [],
        "roads": [{"edge_id": "edge-x", "zone": "z"}],
    }
    future = build_ensemble(snapshot, [99])[0]
    future["truth_events"] = [{
        "event_id": "truth-x", "kind": "road_closed", "edge_id": "edge-x", "time_s": 130.0,
    }]
    future["observation_events"] = [
        {
            "event_id": "sampled-x", "kind": "road_closed", "edge_id": "edge-x",
            "issued_at_s": 130.0, "received_at_s": 135.0,
        },
        {
            "event_id": "unrelated", "kind": "road_closed", "edge_id": "other",
            "issued_at_s": 132.0, "received_at_s": 137.0,
        },
    ]
    supplied = {
        "event_id": "accepted-x", "kind": "road_closed", "edge_id": "edge-x",
        "time_s": 150.0, "issued_at_s": 150.0, "received_at_s": 160.0,
    }

    conditioned = condition_ensemble([future], supplied)[0]
    assert all(
        event.get("edge_id") != "edge-x"
        for event in visible_observations(conditioned, 140.0)
        if event["kind"] == "road_closed"
    )
    at_receipt = [
        event for event in visible_observations(conditioned, 160.0)
        if event["kind"] == "road_closed" and event["edge_id"] == "edge-x"
    ]
    assert at_receipt == [supplied]
    assert any(event["event_id"] == "unrelated" for event in conditioned["observation_events"])
    assert any(event["event_id"] == "unrelated" for event in visible_observations(conditioned, 140.0))
    assert conditioned["assumptions"]["observation_process"]
    assert conditioned["initial_snapshot"] == future["initial_snapshot"]
    assert conditioned["snapshot_hash"] == future["snapshot_hash"]


@pytest.mark.parametrize("issued,received", [(170.0, 160.0), (140.0, 160.0)])
def test_conditioning_rejects_issue_time_outside_effective_receive_interval(issued, received):
    future = build_ensemble({
        "time_s": 100.0, "observations": [],
        "roads": [{"edge_id": "edge-x", "zone": "z"}],
    }, [98])[0]
    future["truth_events"] = [{
        "event_id": "truth-x", "kind": "road_closed", "edge_id": "edge-x", "time_s": 130.0,
    }]
    observation = {
        "event_id": "accepted-x", "kind": "road_closed", "edge_id": "edge-x",
        "time_s": 150.0, "issued_at_s": issued, "received_at_s": received,
    }
    with pytest.raises(ValueError):
        condition_ensemble([future], observation)



def test_conditioning_rejects_receipt_after_future_horizon():
    future = build_ensemble({
        "time_s": 100.0, "observations": [],
        "roads": [{"edge_id": "edge-x", "zone": "z"}],
    }, [97], horizon_s=100.0)[0]
    future["truth_events"] = [{
        "event_id": "truth-x", "kind": "road_closed", "edge_id": "edge-x", "time_s": 130.0,
    }]
    observation = {
        "event_id": "accepted-x", "kind": "road_closed", "edge_id": "edge-x",
        "time_s": 150.0, "issued_at_s": 150.0, "received_at_s": 201.0,
    }
    with pytest.raises(ValueError, match="after the future horizon"):
        condition_ensemble([future], observation)


def test_forecast_does_not_override_an_observed_closed_road():
    snapshot = sample_snapshot()
    snapshot["observations"].append({
        "event_id": "forecast-after-closure",
        "kind": "forecast",
        "edge_id": "already-closed",
        "issued_at_s": 99.0,
        "received_at_s": 99.0,
    })
    future = build_ensemble(snapshot, [13])[0]
    assert all(event["edge_id"] != "already-closed" for event in future["truth_events"])


@pytest.mark.parametrize(
    "snapshot,seeds,horizon",
    [
        ({**sample_snapshot(), "time_s": float("nan")}, [1], 10),
        ({**sample_snapshot(), "observations": [{**sample_snapshot()["observations"][0], "received_at_s": 101}]}, [1], 10),
        ({**sample_snapshot(), "observations": [{**sample_snapshot()["observations"][0], "issued_at_s": 101}]}, [1], 10),
        ({**sample_snapshot(), "observations": [{**sample_snapshot()["observations"][0], "time_s": float("inf")}]}, [1], 10),
        ({**sample_snapshot(), "roads": [{"edge_id": "x"}, {"edge_id": "x"}]}, [1], 10),
        (sample_snapshot(), [1, 1], 10),
        (sample_snapshot(), [1], -1),
        (sample_snapshot(), [1], float("inf")),
    ],
)
def test_invalid_inputs_are_rejected(snapshot, seeds, horizon):
    with pytest.raises((TypeError, ValueError)):
        build_ensemble(snapshot, seeds, horizon_s=horizon)


def test_observation_conditioning_does_not_mutate_inputs():
    futures = build_ensemble(sample_snapshot(), [1, 2])
    original = copy.deepcopy(futures)
    observation = {
        "event_id": "closure",
        "kind": "road_closed",
        "edge_id": "a",
        "time_s": 150,
        "issued_at_s": 150,
        "received_at_s": 151,
    }
    conditioned = condition_ensemble(futures, observation)
    assert futures == original
    if conditioned:
        conditioned[0]["assumptions"]["interpretation"] = "changed"
        assert futures[0]["assumptions"] == original[0]["assumptions"]
