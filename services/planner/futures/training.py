"""Seeded, explicitly synthetic situations and uncertain training futures."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections.abc import Mapping
from typing import Any

from .information import diffuse_information


_DESCRIPTIONS = (
    "Minimal disruption; occasional local access or service loss.",
    "Minor disruption; sparse secondary calls and short travel delays.",
    "Limited disruption; some alternate access may be needed.",
    "Moderate disruption; new calls and isolated facilities may be affected.",
    "Material disruption; routes and response capacity need active monitoring.",
    "Elevated disruption; detours and new calls may compete for resources.",
    "High disruption; multiple access and service losses are plausible.",
    "Severe disruption; substantial route and facility uncertainty.",
    "Very severe disruption; broad secondary demands and degraded access.",
    "Extreme training stress; widespread competing failures are possible.",
)


def _probability(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ValueError(f"{name} must be finite between 0 and 1")
    return float(value)


def _range(value: Any, name: str, *, integer: bool, minimum: float) -> list:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise TypeError(f"{name} must be a two-element range")
    values = list(value)
    for part in values:
        if isinstance(part, bool) or not isinstance(part, (int, float)):
            raise TypeError(f"{name} values must be numeric")
        if not math.isfinite(float(part)) or part < minimum or (integer and (not isinstance(part, int))):
            raise ValueError(f"{name} values must be finite and >= {minimum}")
    if values[0] > values[1]:
        raise ValueError(f"{name} range must ascend")
    return values


def severity_profile(level: int, overrides: Mapping[str, Any] | None = None) -> dict:
    """Disclose editable ordinal assumptions, never calibrated probabilities."""
    if isinstance(level, bool) or not isinstance(level, int):
        raise TypeError("severity level must be an integer")
    if not 1 <= level <= 10:
        raise ValueError("severity level must be 1 through 10")
    if overrides is not None and not isinstance(overrides, Mapping):
        raise TypeError("overrides must be a mapping")
    fraction = (level - 1) / 9
    profile = {
        "level": level,
        "description": _DESCRIPTIONS[level - 1],
        "provenance": "Synthetic, instructor-editable training assumptions; not calibrated operational probabilities",
        "calibrated": False,
        "road_failure_probability": round(0.03 + 0.38 * fraction, 3),
        "travel_multiplier_range": [1.0, round(1.10 + 0.75 * fraction, 3)],
        "additional_incident_count_range": [0 if level < 7 else 1, math.ceil(level / 3)],
        "facility_failure_probability": round(0.015 + 0.30 * fraction, 3),
    }
    editable = {
        "road_failure_probability", "travel_multiplier_range",
        "additional_incident_count_range", "facility_failure_probability",
    }
    for key, value in (overrides or {}).items():
        if key not in editable:
            raise ValueError(f"unknown severity override: {key}")
        if key.endswith("_probability"):
            profile[key] = _probability(value, key)
        elif key == "travel_multiplier_range":
            profile[key] = _range(value, key, integer=False, minimum=1.0)
        else:
            profile[key] = _range(value, key, integer=True, minimum=0)
    return profile


def _rng(seed: int, key: str) -> random.Random:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an integer")
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def generate_situation(seed: int, severity: int = 5) -> dict:
    """Create a connected metric road network with variable needs and capacity."""
    profile = severity_profile(severity)
    rng = _rng(seed, "situation")
    camp_count = rng.randint(3, 5)
    junction_count = rng.randint(1, 3)
    facility_kinds = ("medical", "evacuation", "supply")
    nodes = [{"id": "command", "x_m": 0, "y_m": 0, "kind": "command"}]
    for index in range(camp_count):
        nodes.append({"id": f"camp-{index}", "x_m": rng.randint(-2500, 2500),
                      "y_m": rng.randint(-2500, 2500), "kind": "camp"})
    for index in range(junction_count):
        nodes.append({"id": f"junction-{index}", "x_m": rng.randint(-2500, 2500),
                      "y_m": rng.randint(-2500, 2500), "kind": "junction"})
    for kind in facility_kinds:
        nodes.append({"id": f"facility-{kind}", "x_m": rng.randint(-2500, 2500),
                      "y_m": rng.randint(-2500, 2500), "kind": "facility"})
    pairs = set()
    # Random spanning tree, then extra cross-links so detours exist.
    for index in range(1, len(nodes)):
        parent = rng.randrange(index)
        pairs.add((parent, index))
    for _ in range(len(nodes) // 2 + rng.randint(1, 3)):
        a, b = rng.sample(range(len(nodes)), 2)
        pairs.add(tuple(sorted((a, b))))
    roads = []
    for number, (a, b) in enumerate(sorted(pairs)):
        distance = math.hypot(nodes[a]["x_m"] - nodes[b]["x_m"],
                              nodes[a]["y_m"] - nodes[b]["y_m"])
        travel = max(10, round(distance / rng.uniform(11, 17), 1))
        for source, target, suffix in ((a, b, "f"), (b, a, "r")):
            roads.append({"id": f"road-{number}-{suffix}",
                          "physical_id": f"road-{number}",
                          "source": nodes[source]["id"],
                          "target": nodes[target]["id"], "travel_s": travel})
    facilities = [
        {"id": f"facility-{kind}", "node_id": f"facility-{kind}", "kind": kind,
         "capacity": rng.randint(10, 30)}
        for kind in facility_kinds
    ]
    vehicles = []
    for index, kind in enumerate(("ambulance", "bus", "truck")):
        vehicles.append({"id": f"vehicle-{index}", "node_id": rng.choice(nodes)["id"],
                         "kind": kind, "capacity": rng.randint(2, 5) if kind == "ambulance"
                         else rng.randint(7, 15)})
    if rng.random() < 0.55:
        vehicles.append({"id": "vehicle-3", "node_id": rng.choice(nodes)["id"],
                         "kind": rng.choice(("ambulance", "bus", "truck")), "capacity": rng.randint(4, 10)})
    requests = []
    for index in range(rng.randint(3, 5)):
        kind = rng.choice(facility_kinds)
        camp = f"camp-{rng.randrange(camp_count)}"
        request = {
            "id": f"request-{index}", "node_id": camp,
            "destination_id": f"facility-{kind}", "kind": kind,
            "quantity": rng.randint(1, 9), "deadline_s": rng.randint(170, 500),
            "source_id": camp, "initial_received_by": [camp],
        }
        if index == 0 or rng.random() < 0.35:
            request["initial_received_by"].append("command")
        requests.append(request)
    agents = ["command"] + [f"camp-{i}" for i in range(camp_count)]
    agents += [v["id"] for v in vehicles] + [f["id"] for f in facilities]
    links = []
    def link(source, target, chance=0.85):
        links.append({"source": source, "target": target,
                      "delay_s": rng.randint(1, 8),
                      "success_probability": chance,
                      "contact_interval_s": rng.choice((0, 15, 30, 45))})
    for vehicle in vehicles:
        link(vehicle["id"], "command", 0.9)
        link("command", vehicle["id"], 0.9)
    for index in range(camp_count):
        camp = f"camp-{index}"
        if index == 0 or rng.random() < 0.85:
            relay = rng.choice(vehicles)["id"] if rng.random() < 0.5 else "command"
            link(camp, relay)
            if rng.random() < 0.75:
                link(relay, camp)
    for facility in facilities:
        link(facility["id"], rng.choice(vehicles)["id"])
    return {
        "schema": "training-situation-v1", "scenario_id": f"training-{seed}",
        "time_s": 0, "horizon_s": 600, "severity": severity,
        "assumptions": profile, "nodes": nodes, "roads": roads, "vehicles": vehicles,
        "facilities": facilities, "requests": requests,
        "stocks": {"supplies": rng.randint(20, 70)},
        "communications": {"agents": agents, "links": links,
                           "initially_informed": ["command"]},
        "command_id": "command",
        "goals": {"coverage_threshold_s": 120, "priority_order": [
            "urgent_service", "supply", "coverage", "protection", "time"
        ], "description": "Prioritize urgent service and supply delivery, then accessible camp coverage and protection of people and response capacity."},
    }


def build_training_future(situation: Mapping[str, Any], seed: int) -> dict:
    """Sample physical changes and independently diffuse only detectable facts."""
    start = float(situation["time_s"])
    end = start + float(situation["horizon_s"])
    profile = copy.deepcopy(dict(situation["assumptions"]))
    road_p = _probability(profile["road_failure_probability"], "road_failure_probability")
    facility_p = _probability(profile["facility_failure_probability"], "facility_failure_probability")
    count_range = _range(profile["additional_incident_count_range"],
                         "additional_incident_count_range", integer=True, minimum=0)
    travel_range = _range(profile["travel_multiplier_range"], "travel_multiplier_range",
                          integer=False, minimum=1)
    travel_multiplier = round(_rng(seed, "travel").uniform(*travel_range), 6)
    camps = [node["id"] for node in situation["nodes"] if node["kind"] == "camp"]
    agents = set(situation["communications"]["agents"])
    truth = []
    facts = []
    road_groups = {}
    for road in situation["roads"]:
        road_groups.setdefault(road.get("physical_id", road["id"]), []).append(road)
    for physical_id, directions in road_groups.items():
        rng = _rng(seed, f"physical-road:{physical_id}")
        if rng.random() >= road_p:
            continue
        when = round(rng.uniform(start + 20, end - 20), 3)
        for road in directions:
            event = {"id": f"closure-{road['id']}", "kind": "road_closed",
                     "time_s": when, "edge_id": road["id"],
                     "physical_id": physical_id}
            truth.append(event)
            source = road["source"] if road["source"] in agents else rng.choice(camps)
            facts.append({**event, "issued_at_s": when, "source_id": source,
                          "payload": {"edge_id": road["id"], "physical_id": physical_id}})
    incident_rng = _rng(seed, "new-incidents")
    for index in range(incident_rng.randint(*count_range)):
        rng = _rng(seed, f"incident:{index}")
        kind = rng.choice(("medical", "evacuation", "supply"))
        when = round(rng.uniform(start + 25, end - 70), 3)
        camp = rng.choice(camps)
        request = {"id": f"new-request-{index}", "node_id": camp,
                   "destination_id": f"facility-{kind}", "kind": kind,
                   "quantity": rng.randint(1, 8), "deadline_s": min(end, when + rng.randint(100, 280)),
                   "source_id": camp}
        event = {"id": f"new-need-{index}", "kind": "request_created",
                 "time_s": when, "request": request}
        truth.append(event)
        facts.append({**event, "issued_at_s": when, "source_id": camp,
                      "payload": {"request": copy.deepcopy(request)}})
    for facility in situation["facilities"]:
        rng = _rng(seed, f"facility:{facility['id']}")
        if rng.random() >= facility_p:
            continue
        when = round(rng.uniform(start + 35, end - 20), 3)
        event = {"id": f"failure-{facility['id']}", "kind": "facility_failed",
                 "time_s": when, "facility_id": facility["id"]}
        truth.append(event)
        source = facility["id"] if facility["id"] in agents else rng.choice(camps)
        facts.append({**event, "issued_at_s": when, "source_id": source,
                      "payload": {"facility_id": facility["id"]}})
    for request in situation["requests"]:
        facts.append({"id": f"initial-need-{request['id']}", "kind": "request_created",
                      "time_s": start, "issued_at_s": start,
                      "source_id": request["source_id"],
                      "payload": {"request": copy.deepcopy(request)}})
    truth.sort(key=lambda event: (event["time_s"], event["id"]))
    encoded = json.dumps(situation, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {
        "schema": "training-future-v1", "scenario_id": situation["scenario_id"],
        "start_time_s": start, "horizon_end_s": end, "assumptions": profile,
        "initial_snapshot": copy.deepcopy(dict(situation)),
        "snapshot_hash": hashlib.sha256(encoded).hexdigest(),
        "travel_multiplier": travel_multiplier, "truth_events": truth,
        "observation_events": diffuse_information(
            facts, situation["communications"], end, seed
        ),
    }
