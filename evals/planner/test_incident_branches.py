import copy
import json

import pytest

from evals.planner.test_incident_futures import CUT, LATER, _append, _input, _log, _record
from services.planner.futures.incident import pin_incident_projection
from services.planner.futures.hypotheses import known_at_view, materialize_hypothetical_branches


def _base():
    store = _log()
    _append(store, _record())
    snapshot = store.snapshot(CUT, ledger_watermark={"seq": 7},
                              in_flight_commitments=[{"trip_id": "trip-1"}],
                              source_health={"nws": {"status": "alive", "source_time": CUT}})
    return store, pin_incident_projection(snapshot, _input(snapshot))


def _ref(base):
    return copy.deepcopy(base["projection_input"]["accepted_source_refs"][0])


def _spec(base):
    ref = _ref(base)
    return {
        "branch_id": "hazard-persists",
        "accepted_hazard_refs": [ref],
        "authored_assumptions": {"continuation": "Assume the cited hazard remains active for the tested interval"},
        "hypothetical_events": [{
            "event_id": "assumed-update-1", "time_utc": "2026-10-10T09:30:00Z",
            "source_ref": copy.deepcopy(ref),
            "description": "Authored possible continuation; no road implication",
        }],
    }


def test_branch_pins_exact_accepted_revision_cutoff_and_commitments_without_mutation():
    _, base = _base()
    original = copy.deepcopy(base)
    spec = _spec(base)
    result = materialize_hypothetical_branches(base, [spec])
    assert base == original
    assert result == materialize_hypothetical_branches(base, [spec])
    assert result["projection_hash"] != base["projection_hash"]
    branch = result["scenario_branches"][0]
    assert branch["accepted_hazard_refs"] == spec["accepted_hazard_refs"]
    assert branch["accepted_hazard_claims"][0]["payload"]["event"] == "Flood Warning"
    assert branch["initial_snapshot_hash"] == base["initial_snapshot_hash"]
    assert branch["projection_input_hash"] == base["projection_input_hash"]
    assert branch["cutoff_utc"] == CUT
    assert branch["ledger_watermark"] == {"seq": 7}
    assert branch["in_flight_commitments"] == [{"trip_id": "trip-1"}]
    assert branch["source_health"] == {"nws": {"status": "alive", "source_time": CUT}}
    assert branch["operational_outcomes_available"] is False
    assert branch["calibrated"] is False
    assert branch["provenance"] == "authored_hypothetical_uncalibrated"
    before = json.dumps(result, sort_keys=True)
    spec["authored_assumptions"]["continuation"] = "tampered"
    base["accepted_snapshot"]["categories"]["hazard"][0]["payload"]["event"] = "tampered"
    assert json.dumps(result, sort_keys=True) == before


def test_future_hypothesis_is_time_gated_and_never_promoted_to_accepted_evidence():
    _, base = _base()
    result = materialize_hypothetical_branches(base, [_spec(base)])
    branch = result["scenario_branches"][0]
    initial = known_at_view(branch, CUT)
    before = known_at_view(branch, "2026-10-10T09:29:59Z")
    after = known_at_view(branch, "2026-10-10T09:30:00Z")
    assert initial["hypothetical_events"] == before["hypothetical_events"] == []
    assert len(after["hypothetical_events"]) == 1
    assert after["hypothetical_events"][0]["lane"] == "authored_hypothetical"
    assert initial["accepted_hazard_claims"] == after["accepted_hazard_claims"]
    assert result["accepted_snapshot"] == base["accepted_snapshot"]
    assert result["operational_outcomes_available"] is False


def test_rejects_unaccepted_refs_type_coercion_and_operational_fields():
    _, base = _base()
    invalid = []
    spec = _spec(base); spec["accepted_hazard_refs"][0]["revision"] = True; invalid.append(spec)
    spec = _spec(base); spec["accepted_hazard_refs"][0]["raw_sha256"] = "b" * 64; invalid.append(spec)
    spec = _spec(base); spec["authored_assumptions"] = {}; invalid.append(spec)
    spec = _spec(base); spec["probability"] = 0.5; invalid.append(spec)
    spec = _spec(base); spec["hypothetical_events"][0]["road_closed"] = True; invalid.append(spec)
    spec = _spec(base); spec["hypothetical_events"][0]["time_utc"] = CUT; invalid.append(spec)
    spec = _spec(base); spec["hypothetical_events"][0]["time_utc"] = LATER; invalid.append(spec)
    for spec in invalid:
        with pytest.raises((TypeError, ValueError)):
            materialize_hypothetical_branches(base, [spec])
    with pytest.raises(ValueError):
        materialize_hypothetical_branches(base, [_spec(base), _spec(base)])


def test_later_correction_requires_new_projection_and_old_branch_is_stable():
    store, base = _base()
    first = materialize_hypothetical_branches(base, [_spec(base)])
    frozen = copy.deepcopy(first)
    correction = _record(revision=2, event="Flood Watch", accepted_at=LATER,
                         supersedes=["nws", "alert-1", 1])
    _append(store, correction)
    snapshot = store.snapshot(LATER)
    next_base = pin_incident_projection(snapshot, _input(snapshot))
    with pytest.raises(ValueError):
        materialize_hypothetical_branches(next_base, [_spec(base)])
    next_spec = _spec(next_base)
    next_spec["hypothetical_events"][0]["time_utc"] = "2026-10-10T10:30:00Z"
    second = materialize_hypothetical_branches(next_base, [next_spec])
    assert first == frozen
    assert first["projection_hash"] != second["projection_hash"]
    assert second["scenario_branches"][0]["accepted_hazard_refs"][0]["revision"] == 2
    assert second["operational_outcomes_available"] is False


def test_tampered_parent_hash_or_branch_hash_is_rejected():
    _, base = _base()
    changed = copy.deepcopy(base); changed["cutoff_utc"] = LATER
    with pytest.raises(ValueError):
        materialize_hypothetical_branches(changed, [_spec(base)])
    branch = materialize_hypothetical_branches(base, [_spec(base)])["scenario_branches"][0]
    branch["hypothetical_events"][0]["description"] = "tampered"
    with pytest.raises(ValueError):
        known_at_view(branch, LATER)

@pytest.mark.parametrize("mutate", [
    lambda s: s["accepted_hazard_refs"][0].update(source_id="other"),
    lambda s: s["accepted_hazard_refs"].append(copy.deepcopy(s["accepted_hazard_refs"][0])),
    lambda s: s["hypothetical_events"][0]["source_ref"].update(item_id="different"),
    lambda s: s["hypothetical_events"].append(copy.deepcopy(s["hypothetical_events"][0])),
    lambda s: s["hypothetical_events"][0].update(time_utc="2026-10-10T09:99:00Z"),
    lambda s: s["hypothetical_events"][0].update(time_utc="2026-10-10T10:00:00Z"),
    lambda s: s["authored_assumptions"].update(continuation=" "),
    lambda s: s["hypothetical_events"][0].update(probability=0.9),
    lambda s: s.update(known_road_state="open"),
])
def test_rejects_unbound_or_operational_branch_content(mutate):
    _, base = _base()
    spec = _spec(base)
    mutate(spec)
    with pytest.raises((TypeError, ValueError)):
        materialize_hypothetical_branches(base, [spec])


def test_fractional_utc_event_and_repeated_view_are_deterministic():
    _, base = _base()
    spec = _spec(base)
    spec["hypothetical_events"][0]["time_utc"] = "2026-10-10T09:30:00.123456Z"
    result = materialize_hypothetical_branches(base, [spec])
    branch = result["scenario_branches"][0]
    earlier = known_at_view(branch, "2026-10-10T09:30:00.123455Z")
    later = known_at_view(branch, "2026-10-10T09:30:00.123456Z")
    assert earlier["hypothetical_events"] == []
    assert len(later["hypothetical_events"]) == 1
    assert later == known_at_view(branch, "2026-10-10T09:30:00.123456Z")


def test_mixed_precision_events_follow_chronological_order():
    _, base = _base()
    spec = _spec(base)
    second = copy.deepcopy(spec["hypothetical_events"][0])
    second["event_id"] = "assumed-update-2"
    second["time_utc"] = "2026-10-10T09:30:00.1Z"
    spec["hypothetical_events"].append(second)
    branch = materialize_hypothetical_branches(base, [spec])["scenario_branches"][0]
    assert [e["event_id"] for e in branch["hypothetical_events"]] == [
        "assumed-update-1", "assumed-update-2"
    ]
