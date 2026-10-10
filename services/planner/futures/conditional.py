"""Reproducible synthetic conditional futures for planner stress testing."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from typing import Any


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _validate_snapshot(snapshot: Mapping[str, Any]):
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    if "time_s" not in snapshot:
        raise ValueError("snapshot must include time_s")
    start = _finite(snapshot["time_s"], "snapshot.time_s")
    observations = snapshot.get("observations", [])
    roads = snapshot.get("roads", [])
    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise TypeError("snapshot.observations must be a sequence")
    if isinstance(roads, (str, bytes)) or not isinstance(roads, Sequence):
        raise TypeError("snapshot.roads must be a sequence")
    seen = set()
    for i, road in enumerate(roads):
        if not isinstance(road, Mapping):
            raise TypeError(f"roads[{i}] must be a mapping")
        if "edge_id" not in road:
            raise ValueError(f"roads[{i}] must include edge_id")
        try:
            if road["edge_id"] in seen:
                raise ValueError(f"duplicate road edge_id: {road['edge_id']!r}")
            seen.add(road["edge_id"])
        except TypeError as exc:
            raise TypeError(f"roads[{i}].edge_id must be hashable") from exc
        offset = _finite(road.get("closure_offset_s", 0), f"roads[{i}].closure_offset_s")
        if offset < 0:
            raise ValueError("closure_offset_s must be nonnegative")
    for i, event in enumerate(observations):
        if not isinstance(event, Mapping):
            raise TypeError(f"observations[{i}] must be a mapping")
        for key in ("issued_at_s", "received_at_s"):
            if key not in event:
                raise ValueError(f"observations[{i}] must include {key}")
            if _finite(event[key], f"observations[{i}].{key}") > start:
                raise ValueError(f"observation {key} cannot be after snapshot time")
        if "time_s" in event:
            if _finite(event["time_s"], f"observations[{i}].time_s") > start:
                raise ValueError("observation time_s cannot be after snapshot time")
        if event["issued_at_s"] > event["received_at_s"]:
            raise ValueError("observation issue time cannot follow receive time")
    return start, list(observations), list(roads)


def _closed_edges(observations):
    latest = {}
    for event in observations:
        # Forecasts may describe possible future access, but cannot replace a
        # timestamped observed fact about current road state.
        if event.get("kind") not in {"road_open", "road_closed"}:
            continue
        edge = event.get("edge_id")
        order = (event["received_at_s"], str(event.get("event_id", "")), event["kind"])
        if edge is not None and (edge not in latest or order > latest[edge][0]):
            latest[edge] = (order, event)
    return {edge for edge, (_, event) in latest.items() if event.get("kind") == "road_closed"}


def build_ensemble(
    snapshot: Mapping[str, Any],
    seeds: Sequence[int],
    horizon_s: float = 300,
    assumptions: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build equal-weight synthetic tested scenarios; these are not calibrated probabilities."""
    start, initial_observations, roads = _validate_snapshot(snapshot)
    horizon = _finite(horizon_s, "horizon_s")
    if horizon < 0:
        raise ValueError("horizon_s must be nonnegative")
    if isinstance(seeds, (str, bytes)) or not isinstance(seeds, Sequence):
        raise TypeError("seeds must be a sequence")
    if assumptions is not None and not isinstance(assumptions, Mapping):
        raise TypeError("assumptions must be a mapping or None")
    seed_list, seen = [], set()
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("each seed must be an integer")
        if seed in seen:
            raise ValueError(f"duplicate seed: {seed}")
        seen.add(seed)
        seed_list.append(seed)
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    end = start + horizon
    if not math.isfinite(end):
        raise ValueError("horizon end must be finite")
    supplied = copy.deepcopy(dict(assumptions or {}))
    delay = _finite(supplied.get("observation_delay_s", 5), "observation_delay_s")
    if delay < 0:
        raise ValueError("observation_delay_s must be nonnegative")
    closed = _closed_edges(initial_observations)
    futures = []
    for seed in seed_list:
        rng = random.Random(seed)
        intensity = rng.uniform(0.8, 1.2)
        travel = rng.uniform(1.0, 1.3)
        zones = []
        for road in roads:
            zone = road.get("zone", "default")
            if road.get("uncertain_closure", True) is not False and road["edge_id"] not in closed and zone not in zones:
                zones.append(zone)
        bases = {zone: rng.uniform(25, 90) for zone in zones}
        truth, observations = [], []
        for road in roads:
            edge = road["edge_id"]
            if road.get("uncertain_closure", True) is False or edge in closed:
                continue
            zone = road.get("zone", "default")
            when = max(start + bases[zone] / intensity + float(road.get("closure_offset_s", 0)),
                       math.nextafter(start, math.inf))
            if when > end:
                continue
            event_id = f"closure-{edge}-{when:.9f}"
            truth.append({"event_id": event_id, "kind": "road_closed", "edge_id": edge, "time_s": when})
            observations.append({
                "event_id": event_id, "kind": "road_closed", "edge_id": edge,
                "issued_at_s": when, "received_at_s": when + delay,
            })
        truth.sort(key=lambda e: (e["time_s"], str(e["edge_id"])))
        observations.sort(key=lambda e: (e["received_at_s"], str(e["edge_id"])))
        futures.append({
            "seed": seed,
            "snapshot_hash": digest,
            "start_time_s": start,
            "horizon_end_s": end,
            "initial_snapshot": copy.deepcopy(dict(snapshot)),
            "assumptions": {
                "provenance": "synthetic, uncalibrated tested scenarios",
                "calibrated": False,
                "interpretation": "fractions of tested scenarios; not posterior probabilities",
                "observation_delay_s": delay,
                "user_assumptions": supplied,
            },
            "latent": {
                "wind_fire_intensity": intensity,
                "fire_intensity": intensity,
                "travel_delay_multiplier": travel,
                "closure_base_s_by_zone": bases,
            },
            "truth_events": truth,
            "observation_events": observations,
        })
    return futures


def visible_observations(future: Mapping[str, Any], time_s: float) -> list[dict[str, Any]]:
    """Return isolated initial and newly received observations at a time cutoff."""
    cutoff = _finite(time_s, "time_s")
    snapshot = future.get("initial_snapshot")
    if not isinstance(snapshot, Mapping):
        raise TypeError("future.initial_snapshot must be a mapping")
    visible = [
        copy.deepcopy(dict(event))
        for event in snapshot.get("observations", [])
        if _finite(event["received_at_s"], "received_at_s") <= cutoff
    ]
    visible.extend(
        copy.deepcopy(dict(event))
        for event in future.get("observation_events", [])
        if _finite(event["received_at_s"], "received_at_s") <= cutoff
    )
    visible.sort(key=lambda event: (event["received_at_s"], event.get("event_id", "")))
    return visible


def condition_ensemble(
    futures: Sequence[Mapping[str, Any]],
    observation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Keep only stress paths compatible with an observed timestamped road closure."""
    if not isinstance(observation, Mapping):
        raise TypeError("observation must be a mapping")
    if observation.get("kind") != "road_closed":
        raise ValueError("only road_closed facts can condition this ensemble")
    edge = observation.get("edge_id")
    if edge is None:
        raise ValueError("closure observation must include edge_id")
    if "time_s" in observation:
        effective = _finite(observation["time_s"], "observation.time_s")
    elif "issued_at_s" in observation:
        effective = _finite(observation["issued_at_s"], "observation.issued_at_s")
    else:
        raise ValueError("closure observation must include time_s or issued_at_s")
    if "received_at_s" not in observation:
        raise ValueError("closure observation must include received_at_s")
    received = _finite(observation["received_at_s"], "received_at_s")
    fact = copy.deepcopy(dict(observation))
    issued = _finite(fact.get("issued_at_s", effective), "issued_at_s")
    if issued < effective:
        raise ValueError("closure issue time cannot precede its effective time")
    if issued > received:
        raise ValueError("closure cannot be received before its issue time")
    fact["issued_at_s"] = issued
    compatible = []
    for future in futures:
        if not isinstance(future, Mapping):
            raise TypeError("each future must be a mapping")
        start, initial, _ = _validate_snapshot(future["initial_snapshot"])
        horizon_end = _finite(future["horizon_end_s"], "future.horizon_end_s")
        if effective < start:
            raise ValueError("closure observation predates the future start")
        if received > horizon_end:
            raise ValueError("closure observation arrives after the future horizon")
        initially_closed = edge in _closed_edges(initial)
        truth_matches = any(
            event.get("kind") == "road_closed" and event.get("edge_id") == edge
            and _finite(event["time_s"], "truth event.time_s") <= effective
            for event in future.get("truth_events", [])
        )
        if initially_closed or truth_matches:
            clone = copy.deepcopy(dict(future))
            clone["assumptions"]["interpretation"] = (
                "compatible synthetic stress cases after observed closure; "
                "fraction of tested scenarios, not posterior probability"
            )
            clone["assumptions"]["conditioned_on"] = copy.deepcopy(fact)
            clone["assumptions"]["calibrated"] = False
            clone["assumptions"]["observation_process"] = (
                "authoritative supplied receipt time replaces synthetic "
                "same-edge closure notification timing"
            )
            known = clone.setdefault("observation_events", [])
            event_id = fact.get("event_id")
            known[:] = [
                event for event in known
                if not (
                    event.get("kind") == "road_closed"
                    and event.get("edge_id") == edge
                )
                and not (
                    event_id is not None and event.get("event_id") == event_id
                )
            ]
            known.append(copy.deepcopy(fact))
            known.sort(key=lambda event: (
                event["received_at_s"], event.get("event_id", "")
            ))
            compatible.append(clone)
    return compatible
