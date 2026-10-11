"""Extract a stable boarding count from a validated RoutingExecutor snapshot.

The live ledger records selected people at dispatch_committed, followed by an
empty departure event. Intake requires both plus an arrival; reservation alone
cannot create an arrived-bus session. Current onboard lists are never counted.
"""
import math

from .contracts import SessionSeed, bounded_text, canonical_hash, canonical_json


def _mapping(value, name):
    if not isinstance(value, dict): raise ValueError(f"{name} must be an object")
    return value


def _people(value):
    if not isinstance(value, list) or not value:
        raise ValueError("evacuation boarding must contain people")
    for person_id in value: bounded_text(person_id, "person_id")
    if len(set(value)) != len(value): raise ValueError("boarding person IDs must be unique")
    return value


def session_seed(case_id, snapshot, dispatch_id):
    bounded_text(case_id, "case_id")
    bounded_text(dispatch_id, "dispatch_id")
    snapshot = _mapping(snapshot, "snapshot")
    # The supplied snapshot must be JSON with finite values, including extra fields.
    canonical_json(snapshot)
    run_id = bounded_text(snapshot.get("run_id"), "run_id")
    ledger = _mapping(snapshot.get("ledger"), "ledger")
    assignment = _mapping(_mapping(ledger.get("assignments"), "assignments").get(dispatch_id), "assignment")
    if assignment.get("dispatch_id") != dispatch_id: raise ValueError("assignment dispatch mismatch")
    vehicle_id = bounded_text(assignment.get("vehicle_id"), "vehicle_id")
    request_id = bounded_text(assignment.get("request_id"), "request_id")
    request = _mapping(_mapping(ledger.get("requests"), "requests").get(request_id), "request")
    if request.get("request_id") != request_id: raise ValueError("request identity mismatch")
    if request.get("kind") != "evacuation": raise ValueError("only evacuation trips support intake")
    destination = bounded_text(request.get("destination_node"), "destination_node")
    trips = snapshot.get("trips")
    if not isinstance(trips, list): raise ValueError("trips must be a list")
    matching = [t for t in trips if isinstance(t, dict) and t.get("dispatch_id") == dispatch_id]
    if len(matching) != 1: raise ValueError("exactly one matching routing trip required")
    trip = matching[0]
    if trip.get("vehicle_id") != vehicle_id or trip.get("request_id") != request_id:
        raise ValueError("routing trip differs from ledger assignment")
    for record in (ledger, assignment, request, trip):
        if "run_id" in record and record["run_id"] != run_id: raise ValueError("source run mismatch")
    events = ledger.get("audit_events")
    if not isinstance(events, list): raise ValueError("audit_events must be a list")
    selected = {}
    for kind in ("dispatch_committed", "departure", "arrival"):
        matches = [e for e in events if isinstance(e, dict) and e.get("type") == kind
                   and e.get("dispatch_id") == dispatch_id]
        if len(matches) != 1: raise ValueError(f"exactly one {kind} required")
        event = matches[0]
        bounded_text(event.get("event_id"), "event_id")
        _mapping(event.get("details"), "event details")
        for key, expected in (("run_id", run_id), ("vehicle_id", vehicle_id),
                              ("request_id", request_id), ("destination_node", destination)):
            if key in event and event[key] != expected: raise ValueError(f"event {key} mismatch")
            if key in event["details"] and event["details"][key] != expected:
                raise ValueError(f"event details {key} mismatch")
        when = event.get("time_s")
        if type(when) not in (int, float) or not math.isfinite(when) or when < 0:
            raise ValueError("event time must be finite and nonnegative")
        selected[kind] = event
    boarding, departure, arrival = (selected[k] for k in ("dispatch_committed", "departure", "arrival"))
    if len({e["event_id"] for e in selected.values()}) != 3: raise ValueError("event identities must differ")
    if not boarding["time_s"] <= departure["time_s"] <= arrival["time_s"]:
        raise ValueError("boarding, departure and arrival must be chronological")
    if arrival["details"].get("node_id") != destination: raise ValueError("arrival destination mismatch")
    people = _people(boarding["details"].get("person_ids"))
    assigned = _people(assignment.get("person_ids"))
    if set(assigned) != set(people): raise ValueError("assignment boarding mismatch")
    evidence = {"run_id": run_id, "dispatch_id": dispatch_id, "vehicle_id": vehicle_id,
                "request_id": request_id, "kind": "evacuation", "destination_node": destination,
                "boarding": boarding, "departure": departure, "arrival": arrival}
    return SessionSeed(case_id, run_id, dispatch_id, vehicle_id, destination, len(people),
                       boarding["event_id"], arrival["event_id"], canonical_hash(evidence),
                       departure_event_id=departure["event_id"])
