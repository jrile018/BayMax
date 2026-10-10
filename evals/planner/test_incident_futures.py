import copy
import hashlib
import json
from pathlib import Path

import pytest

import contracts.incident as incident_contract
from contracts.incident import EvidenceLog, OfficialPolicy, VerifiedSource, projection_input, record_fingerprint
from services.planner.futures.incident import REVIEWED_CONTRACT_SHA256, pin_incident_projection


CUT = "2026-10-10T09:00:00Z"
LATER = "2026-10-10T10:00:00Z"


def _record(*, revision=1, event="Flood Warning", accepted_at=CUT, supersedes=None):
    return {
        "source_id": "nws", "item_id": "alert-1", "revision": revision,
        "source_url": "https://api.weather.gov/alerts/1", "raw_sha256": "a" * 64,
        "provider": "NWS", "license": "public domain", "source_type": "official_api",
        "category": "hazard", "source_kind": "official_forecast",
        "published_at": "2026-10-10T08:00:00Z", "observed_at": None,
        "valid_from": None, "valid_through": None, "message_expires_at": None,
        "first_seen_at": "2026-10-10T08:30:00Z", "fetched_at": "2026-10-10T08:45:00Z",
        "accepted_at": accepted_at, "correction_available_at": accepted_at if supersedes else None,
        "superseded_at": None, "supersedes": supersedes, "retracted": False,
        "source_reference": {"api_fields": ["properties.event"]},
        "geometry": {"type": "Point", "coordinates": [-120.5, 39.5]},
        "precision": "point", "area_label": None, "source_uncertainty": None,
        "payload": {"event": event},
    }


def _log():
    return EvidenceLog("incident-1", [-121, 39, -120, 40], official_policies=[
        OfficialPolicy("nws", "NWS", "api.weather.gov", ("properties.event",),
                       ("event",), "nws-alert-v1")
    ])


def _append(store, record):
    return store.append(record, verification=VerifiedSource(
        "nws", record["source_url"], record["raw_sha256"], True,
        record_fingerprint(record)))


def _input(snapshot):
    return projection_input(snapshot, horizon_minutes=60, model_version="scenario-v1",
                            assumptions={"weather": "authored hypothetical hazard branch"})


def test_pins_full_known_at_snapshot_and_defensively_copies_inputs():
    store = _log()
    _append(store, _record())
    snapshot = store.snapshot(CUT, ledger_watermark={"seq": 7},
                              in_flight_commitments=[{"trip_id": "trip-1"}])
    projected = _input(snapshot)
    result = pin_incident_projection(snapshot, projected)
    before = json.dumps(result, sort_keys=True)
    assert result["initial_snapshot_hash"] == snapshot["snapshot_hash"]
    assert result["projection_input_hash"] == projected["projection_input_hash"]
    assert result["accepted_snapshot"]["revision_history"] == snapshot["revision_history"]
    assert result["projection_input"]["accepted_source_refs"] == snapshot["accepted_source_refs"]
    assert result["cutoff_utc"] == CUT
    assert result["ledger_watermark"] == {"seq": 7}
    assert result["in_flight_commitments"] == [{"trip_id": "trip-1"}]
    assert result["operational_outcomes_available"] is False
    assert result["calibrated"] is False
    snapshot["revision_history"][0]["payload"]["event"] = "tampered"
    projected["authored_assumptions"]["weather"] = "tampered"
    assert json.dumps(result, sort_keys=True) == before


def test_correction_creates_new_projection_without_changing_old():
    store = _log()
    _append(store, _record())
    first = pin_incident_projection(store.snapshot(CUT), _input(store.snapshot(CUT)))
    frozen = copy.deepcopy(first)
    correction = _record(revision=2, event="Flood Watch", accepted_at=LATER,
                         supersedes=["nws", "alert-1", 1])
    _append(store, correction)
    next_snapshot = store.snapshot(LATER)
    second = pin_incident_projection(next_snapshot, _input(next_snapshot))
    assert first == frozen
    assert first["initial_snapshot_hash"] != second["initial_snapshot_hash"]
    assert len(first["accepted_snapshot"]["revision_history"]) == 1
    assert len(second["accepted_snapshot"]["revision_history"]) == 2
    assert second["accepted_snapshot"]["revision_history"][0]["superseded_at"] == LATER
    assert second["projection_input"]["accepted_source_refs"][0]["revision"] == 2
    assert second["operational_outcomes_available"] is False


def test_rejects_changed_snapshot_or_projection_and_capability_escalation():
    store = _log()
    _append(store, _record())
    snapshot = store.snapshot(CUT)
    projected = _input(snapshot)
    changed = copy.deepcopy(snapshot)
    changed["cutoff_utc"] = LATER
    with pytest.raises(ValueError):
        pin_incident_projection(changed, projected)
    changed_projection = copy.deepcopy(projected)
    changed_projection["cutoff_utc"] = LATER
    with pytest.raises(ValueError):
        pin_incident_projection(snapshot, changed_projection)
    changed_projection = copy.deepcopy(projected)
    changed_projection["can_calculate_operational_outcomes"] = True
    with pytest.raises(ValueError):
        pin_incident_projection(snapshot, changed_projection)


def test_failed_refresh_keeps_last_accepted_claim_and_marks_source_stale():
    store = _log()
    _append(store, _record())
    first_snapshot = store.snapshot(CUT)
    first = pin_incident_projection(first_snapshot, _input(first_snapshot))
    later_snapshot = store.snapshot(LATER, source_health={
        "nws": {"status": "stale", "source_time": CUT, "reason": "refresh failed"}
    })
    later = pin_incident_projection(later_snapshot, _input(later_snapshot))
    assert later["accepted_snapshot"]["categories"]["hazard"] == first["accepted_snapshot"]["categories"]["hazard"]
    assert later["projection_input"]["accepted_source_refs"] == first["projection_input"]["accepted_source_refs"]
    assert later["accepted_snapshot"]["source_health"]["nws"]["status"] == "stale"
    assert later["projection_input"]["source_health"]["nws"]["reason"] == "refresh failed"
    assert later["initial_snapshot_hash"] != first["initial_snapshot_hash"]
    assert later["operational_outcomes_available"] is False
    for category in ("needs", "closures", "vehicles", "stock", "capacity"):
        assert later["accepted_snapshot"]["categories"][category] is None


def test_rejects_unsupported_version_and_does_not_erase_superseded_history():
    store = _log()
    _append(store, _record())
    first_snapshot = store.snapshot(CUT)
    correction = _record(revision=2, event="Flood Watch", accepted_at=LATER,
                         supersedes=["nws", "alert-1", 1])
    _append(store, correction)
    later_snapshot = store.snapshot(LATER)
    projected = _input(later_snapshot)
    assert len(pin_incident_projection(later_snapshot, projected)["accepted_snapshot"]["revision_history"]) == 2
    changed = copy.deepcopy(later_snapshot)
    changed["revision_history"] = changed["revision_history"][1:]
    with pytest.raises(ValueError):
        pin_incident_projection(changed, projected)
    changed_projection = copy.deepcopy(projected)
    changed_projection["model_version"] = "unknown-model"
    with pytest.raises(ValueError):
        pin_incident_projection(later_snapshot, changed_projection)


def test_dependency_is_the_independently_reviewed_frozen_contract():
    assert incident_contract.VERSION == "knight26-incident-v1"
    assert hashlib.sha256(Path(incident_contract.__file__).read_bytes()).hexdigest() == REVIEWED_CONTRACT_SHA256
