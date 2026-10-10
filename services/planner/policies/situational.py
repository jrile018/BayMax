"""Bounded planning over the facts and legal options visible at one decision time.

The returned sequence is an allocation sketch. Call again after each committed
action or newly received fact; it is not a prediction of hidden physical events.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

_PRIORITY = ("urgent_service", "coverage", "protection", "supply", "time")
_FORBIDDEN = ("truth", "future", "seed", "latent", "sampled")
_KINDS = frozenset(("dispatch", "reposition", "wait"))


def _no_hidden(value: object, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            if any(word in key.lower() for word in _FORBIDDEN):
                raise ValueError(f"hidden input field {path}.{key}")
            _no_hidden(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _no_hidden(child, f"{path}[{index}]")


def _number(value: object, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("expected a finite number")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("expected a finite nonnegative number")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _closed_roads(observations: Sequence[Mapping], now: float) -> set[str]:
    closed: set[str] = set()
    for observation in observations:
        received = observation.get("received_at_s", now)
        if _number(received, nonnegative=True) > now:
            continue
        payload = observation.get("payload", observation)
        if not isinstance(payload, Mapping):
            continue
        kinds = {
            observation.get("kind"), observation.get("type"),
            payload.get("kind"), payload.get("type"),
        }
        if kinds.intersection(("road_closed", "road_closure", "closure")):
            road_id = payload.get(
                "edge_id", payload.get(
                    "road_id", observation.get("edge_id", observation.get("road_id"))
                )
            )
            if isinstance(road_id, str):
                closed.add(road_id)
    return closed


def _route_ok(
    route: object,
    roads: Mapping[str, Mapping] | None,
    closed: set[str],
    start: str | None,
) -> bool:
    if not isinstance(route, (list, tuple)) or any(
        not isinstance(road_id, str) for road_id in route
    ):
        return False
    if any(road_id in closed for road_id in route):
        return False
    if roads is None:
        return True
    node = start
    for road_id in route:
        road = roads.get(road_id)
        if road is None:
            return False
        source, target = road.get("source"), road.get("target")
        if node is not None and node != source:
            return False
        node = target
    return True


def _score(
    actions: Sequence[Mapping],
    coverage_by_vehicle: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, float]:
    if coverage_by_vehicle is not None and all(
        "covered_camps_after" in action for action in actions
    ):
        baseline = set().union(*(set(camps) for camps in coverage_by_vehicle.values()))
        after = {vehicle: set(camps) for vehicle, camps in coverage_by_vehicle.items()}
        for action in actions:
            after[action["vehicle_id"]] = set(action["covered_camps_after"])
        covered = set().union(*after.values())
        coverage = float(len(covered) - len(baseline))
    else:
        coverage = sum(float(a["coverage_delta"]) for a in actions)
    return {
        "urgent_service": sum(float(a["expected_urgent"]) for a in actions),
        "coverage": coverage,
        "protection": sum(float(a["protection_delta"]) for a in actions),
        "supply": sum(float(a["expected_supply"]) for a in actions),
        "time": -sum(float(a["travel_s"]) for a in actions),
    }


def _rank(
    actions: Sequence[Mapping],
    order: Sequence[str],
    coverage_by_vehicle: Mapping[str, Sequence[str]] | None,
) -> tuple:
    score = _score(actions, coverage_by_vehicle)
    return tuple(score[name] for name in order)


def _action_order(
    action: Mapping,
    order: Sequence[str],
    coverage_by_vehicle: Mapping[str, Sequence[str]] | None,
) -> tuple:
    score = _score([action], coverage_by_vehicle)
    deadline = action.get("deadline_s")
    if deadline is None:
        deadline = math.inf
    return (
        *(-score[name] for name in order),
        float(deadline),
        float(action["travel_s"]),
        str(action["id"]),
    )


def _reason(
    action: Mapping,
    total: Mapping[str, float],
    coverage_by_vehicle: Mapping[str, Sequence[str]] | None,
) -> list[str]:
    reasons = []
    if float(action["expected_urgent"]) > 0:
        reasons.append(
            f"Immediate urgent need: {action['request_id']} receives "
            f"{action['expected_urgent']:g} expected service within known constraints."
        )
    else:
        reasons.append("No urgent service is available from this chosen action.")
    selected_coverage = _score([action], coverage_by_vehicle)["coverage"]
    estimate = " (estimated from individual actions)" if coverage_by_vehicle is None else ""
    reasons.append(
        f"Coverage after the selected move changes by "
        f"{selected_coverage:+g}; the allocation totals "
        f"{total['coverage']:+g} coverage{estimate}."
    )
    reasons.append(
        f"Protection purpose: the selected action changes known protection by "
        f"{float(action['protection_delta']):+g}; the allocation totals "
        f"{total['protection']:+g} protection."
    )
    return reasons


def _wait_action(actions: Sequence[Mapping], now: float) -> dict:
    waits = [a for a in actions if a.get("kind") == "wait"]
    if waits:
        return dict(min(waits, key=lambda a: (float(a.get("travel_s", 0)), str(a.get("id")))))
    return {
        "id": "wait", "kind": "wait", "vehicle_id": None, "request_id": None,
        "quantity": 0, "route": [], "destination_id": None, "travel_s": 0,
        "expected_urgent": 0, "expected_supply": 0, "coverage_delta": 0,
        "protection_delta": 0, "explanation": {
            "known_only": True, "fallback_at_s": now
        },
    }


def plan_situation(
    knowledge: dict,
    actions: Sequence[dict],
    beam_width: int = 16,
    depth: int = 3,
) -> dict:
    """Choose a feasible visible action and a bounded contingent allocation sketch.

    Scores are lexicographic in the disclosed goal order. They retain their own
    units; no conversion between people, coverage, supplies or time is used.
    """
    beam_width = _positive_int(beam_width, "beam_width")
    depth = _positive_int(depth, "depth")
    if beam_width > 128 or depth > 16:
        raise ValueError("beam_width and depth must be at most 128 and 16")
    if not isinstance(knowledge, Mapping) or not isinstance(actions, (list, tuple)):
        raise TypeError("knowledge must be a mapping and actions a sequence")
    _no_hidden(knowledge, "knowledge")
    _no_hidden(actions, "actions")
    now = _number(knowledge["time_s"], nonnegative=True)
    goals = knowledge["goals"]
    order = goals.get("priority_order") if isinstance(goals, Mapping) else None
    if not isinstance(order, list) or len(order) != len(_PRIORITY) or set(order) != set(_PRIORITY):
        raise ValueError(f"goals.priority_order must permute {list(_PRIORITY)}")
    observations = knowledge.get("observations", [])
    if not isinstance(observations, (list, tuple)):
        raise TypeError("observations must be a sequence")
    closed = _closed_roads(observations, now)
    resources = {
        item["id"]: item for item in knowledge["resources"]
        if isinstance(item, Mapping)
    }
    requests = {
        item["id"]: item for item in knowledge["requests"]
        if isinstance(item, Mapping)
    }
    remaining = {
        request_id: _number(item["remaining"], nonnegative=True)
        for request_id, item in requests.items()
    }
    facilities_list = knowledge.get("facilities")
    facilities = None if facilities_list is None else {
        item["id"]: item for item in facilities_list
    }
    facility_free = None if facilities is None else {
        facility_id: (
            0 if item.get("failed") else max(
                0, _number(item["capacity"], nonnegative=True)
                - _number(item.get("occupied", 0), nonnegative=True)
                - _number(item.get("reserved", 0), nonnegative=True)
            )
        )
        for facility_id, item in facilities.items()
    }
    stocks = knowledge.get("stocks", {})
    supply_stock = (
        None if not isinstance(stocks, Mapping) or "supplies" not in stocks
        else _number(stocks["supplies"], nonnegative=True)
    )
    coverage_by_vehicle = knowledge.get("coverage_by_vehicle")
    if coverage_by_vehicle is not None and not isinstance(coverage_by_vehicle, Mapping):
        raise TypeError("coverage_by_vehicle must be a mapping")
    roads_list = knowledge.get("roads")
    roads = None if roads_list is None else {
        item["id"]: item for item in roads_list
    }

    feasible: list[dict] = []
    for option in actions:
        if not isinstance(option, Mapping):
            raise TypeError("actions must contain mappings")
        action = dict(option)
        kind = action.get("kind")
        if kind not in _KINDS or kind == "wait" or action.get("feasible", True) is False:
            continue
        vehicle_id = action.get("vehicle_id")
        resource = resources.get(vehicle_id)
        if resource is None or resource.get("status", "idle") != "idle":
            continue
        if action.get("forecast_margin_s") is not None and (
            _number(action["forecast_margin_s"]) < 0
        ):
            continue
        quantity = action.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            continue
        request_id = action.get("request_id")
        if kind == "dispatch":
            if request_id not in remaining or quantity < 1:
                continue
            if quantity > remaining[request_id] or quantity > _number(
                resource["capacity"], nonnegative=True
            ):
                continue
            destination_id = action.get("destination_id")
            if facility_free is not None and (
                destination_id not in facility_free
                or quantity > facility_free[destination_id]
            ):
                continue
            request_kind = action.get("request_kind", requests[request_id].get("kind"))
            if request_kind == "supply" and supply_stock is not None and quantity > supply_stock:
                continue
        elif request_id is not None or quantity != 0:
            continue
        try:
            urgent = _number(action["expected_urgent"], nonnegative=True)
            supply = _number(action["expected_supply"], nonnegative=True)
            coverage = _number(action["coverage_delta"])
            protection = _number(action["protection_delta"])
            travel = _number(action["travel_s"], nonnegative=True)
        except (KeyError, TypeError, ValueError):
            continue
        if urgent > quantity or supply > quantity:
            continue
        if coverage_by_vehicle is not None and "covered_camps_after" in action:
            covered = action["covered_camps_after"]
            if not isinstance(covered, (list, tuple)) or any(
                not isinstance(camp, str) for camp in covered
            ):
                continue
        if kind == "reposition" and (
            urgent, supply, coverage, protection
        ) == (0, 0, 0, 0):
            continue
        if not _route_ok(action.get("route"), roads, closed, resource.get("node_id")):
            continue
        if not isinstance(action.get("id"), str):
            continue
        feasible.append(action)

    # Stable order makes beam pruning and ties independent of input order.
    feasible.sort(key=lambda item: item["id"])
    best: tuple[dict, ...] = ()
    beam: list[tuple[dict, ...]] = [()]
    explored = 0
    for _ in range(depth):
        next_states: dict[tuple[str, ...], tuple[dict, ...]] = {}
        for state in beam:
            used = {item["vehicle_id"] for item in state}
            served: dict[str, int] = {}
            for item in state:
                if item["kind"] == "dispatch":
                    rid = item["request_id"]
                    served[rid] = served.get(rid, 0) + item["quantity"]
            facility_used: dict[str, int] = {}
            supply_used = 0
            for item in state:
                if item["kind"] != "dispatch":
                    continue
                dest = item["destination_id"]
                facility_used[dest] = facility_used.get(dest, 0) + item["quantity"]
                if item.get("request_kind", requests[item["request_id"]].get("kind")) == "supply":
                    supply_used += item["quantity"]
            for action in feasible:
                if action["vehicle_id"] in used:
                    continue
                rid = action.get("request_id")
                if rid is not None and served.get(rid, 0) + action["quantity"] > remaining[rid]:
                    continue
                if rid is not None and facility_free is not None and (
                    facility_used.get(action["destination_id"], 0) + action["quantity"]
                    > facility_free[action["destination_id"]]
                ):
                    continue
                if rid is not None and supply_stock is not None and (
                    action.get("request_kind", requests[rid].get("kind")) == "supply"
                    and supply_used + action["quantity"] > supply_stock
                ):
                    continue
                candidate = (*state, action)
                key = tuple(sorted(item["id"] for item in candidate))
                if key in next_states:
                    continue
                next_states[key] = candidate
                explored += 1
        if not next_states:
            break
        candidates = list(next_states.values())
        candidates.sort(key=lambda state: (
            tuple(-value for value in _rank(state, order, coverage_by_vehicle)),
            tuple(sorted(item["id"] for item in state)),
        ))
        beam = candidates[:beam_width]
        for state in beam:
            if _rank(state, order, coverage_by_vehicle) > _rank(best, order, coverage_by_vehicle):
                best = state

    if best:
        plan = sorted(best, key=lambda action: _action_order(action, order, coverage_by_vehicle))
        chosen = plan[0]
        components = _score(plan, coverage_by_vehicle)
        reasons = _reason(chosen, components, coverage_by_vehicle)
    else:
        chosen = _wait_action(actions, now)
        plan = [chosen]
        components = _score([], coverage_by_vehicle)
        reasons = [
            "Wait: no feasible move improves the disclosed priorities under current "
            "received knowledge and available resources.",
            "Coverage and protection are unchanged while waiting for a new decision.",
        ]
    return {
        "chosen_action": dict(chosen),
        "plan": [dict(item) for item in plan],
        "score_components": components,
        "reasons": reasons,
        "search_limits": {
            "beam_width": beam_width, "depth": depth,
            "feasible_options": len(feasible), "explored_states": explored,
            "global_optimum_claim": False,
        },
    }
