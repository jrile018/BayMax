"""Frozen incident contract view: accepted cutoff versus hypothetical branches."""
from copy import deepcopy
import pytest

from contracts.incident import EvidenceLog, projection_input
from viewer3d.incident_adapter import adapt_incident


def inputs():
    log = EvidenceLog("incident-fixture", [-122, 39, -120, 41])
    snapshot = log.snapshot("2026-10-10T09:00:00Z", source_health={
        "nws": {"status": "stale", "source_time": "2026-10-10T08:40:00Z",
                "reason": "refresh failed"}})
    branch = projection_input(
        snapshot, horizon_minutes=60, model_version="scenario-fixture-v1",
        assumptions={"weather": "authored training branch"})
    return snapshot, branch


def test_unknown_and_source_health_preserved_without_inferred_geometry():
    snapshot, branch = inputs()
    view = adapt_incident(snapshot, [{"branch_id": "rain", "input": branch}],
                          expected_snapshot_hash=snapshot["snapshot_hash"])
    assert view.metadata["source_snapshot"] == snapshot
    assert view.metadata["accepted_categories"] == snapshot["categories"]
    assert all(value is None for value in view.metadata["accepted_categories"].values())
    assert view.metadata["source_health"] == snapshot["source_health"]
    assert view.metadata["unconfirmed_leads"] == []
    assert view.metadata["geographic_projection"] == "none"
    assert view.metadata["operational_outcomes"] == "unavailable"
    assert view.branches[0]["label"] == "hypothetical"
    assert view.branches[0]["input"] == branch
    assert view.branches[0]["can_calculate_operational_outcomes"] is False
    snapshot["source_health"]["nws"]["reason"] = "changed after adaptation"
    branch["authored_assumptions"]["weather"] = "changed after adaptation"
    assert view.metadata["source_health"]["nws"]["reason"] == "refresh failed"
    assert view.branches[0]["input"]["authored_assumptions"]["weather"] == "authored training branch"


def test_multiple_branches_share_one_accepted_snapshot():
    snapshot, first = inputs()
    second = projection_input(
        snapshot, horizon_minutes=120, model_version="scenario-fixture-v1",
        assumptions={"weather": "second authored training branch"})
    view = adapt_incident(snapshot, [
        {"branch_id": "rain", "input": first},
        {"branch_id": "wind", "input": second},
    ], expected_snapshot_hash=snapshot["snapshot_hash"])
    assert [entry["branch_id"] for entry in view.branches] == ["rain", "wind"]
    assert all(entry["initial_snapshot_hash"] == snapshot["snapshot_hash"] for entry in view.branches)
    assert all(entry["label"] == "hypothetical" for entry in view.branches)
    assert view.metadata["cutoff_utc"] == snapshot["cutoff_utc"]


def test_rejects_wrong_trusted_hash_and_cross_snapshot_branch():
    snapshot, branch = inputs()
    with pytest.raises(ValueError, match="trusted snapshot hash"):
        adapt_incident(snapshot, [], expected_snapshot_hash="0" * 64)
    other = deepcopy(snapshot)
    other["incident_id"] = "other-incident"
    from hashlib import sha256
    import json
    other["snapshot_hash"] = sha256(json.dumps(
        {k: v for k, v in other.items() if k != "snapshot_hash"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()
    with pytest.raises(ValueError, match="same accepted snapshot"):
        adapt_incident(other, [{"branch_id": "rain", "input": branch}],
                       expected_snapshot_hash=other["snapshot_hash"])


def test_rejects_tampered_branch_and_duplicate_identity():
    snapshot, branch = inputs()
    changed = deepcopy(branch)
    changed["authored_assumptions"]["weather"] = "different"
    with pytest.raises(ValueError, match="projection input"):
        adapt_incident(snapshot, [{"branch_id": "rain", "input": changed}],
                       expected_snapshot_hash=snapshot["snapshot_hash"])
    with pytest.raises(ValueError, match="duplicate"):
        adapt_incident(snapshot, [
            {"branch_id": "rain", "input": branch},
            {"branch_id": "rain", "input": branch},
        ], expected_snapshot_hash=snapshot["snapshot_hash"])


def test_accepted_record_keeps_source_area_validity_and_provenance():
    from contracts.incident import OfficialPolicy, VerifiedSource, record_fingerprint
    policy = OfficialPolicy("nws", "NWS", "api.weather.gov",
                            ("properties.event",), ("event",), "nws-alert-v1")
    log = EvidenceLog("alachua-training", [-83, 29, -82, 30],
                      official_policies=[policy])
    record = {
        "source_id": "nws", "item_id": "alert-1", "revision": 1,
        "source_url": "https://api.weather.gov/alerts/alert-1",
        "raw_sha256": "a" * 64, "provider": "NWS", "license": "public domain",
        "source_type": "official_api", "category": "hazard",
        "source_kind": "official_forecast",
        "published_at": "2026-10-10T08:00:00Z", "observed_at": None,
        "valid_from": "2026-10-10T11:00:00Z", "valid_through": None,
        "message_expires_at": "2026-10-10T10:00:00Z",
        "first_seen_at": "2026-10-10T08:30:00Z",
        "fetched_at": "2026-10-10T08:45:00Z",
        "accepted_at": "2026-10-10T09:00:00Z",
        "correction_available_at": None, "superseded_at": None,
        "supersedes": None, "retracted": False,
        "source_reference": {"api_fields": ["properties.event"]},
        "geometry": None, "precision": "area",
        "area_label": "Alachua County", "source_uncertainty": None,
        "payload": {"event": "Flood Warning"},
    }
    log.append(record, verification=VerifiedSource(
        "nws", record["source_url"], record["raw_sha256"], True,
        record_fingerprint(record)))
    snapshot = log.snapshot("2026-10-10T09:00:00Z")
    view = adapt_incident(snapshot, [], expected_snapshot_hash=snapshot["snapshot_hash"])
    shown = view.metadata["accepted_categories"]["hazard"][0]
    assert shown == snapshot["categories"]["hazard"][0]
    assert shown["geometry"] is None
    assert shown["area_label"] == "Alachua County"
    assert shown["valid_from"] == "2026-10-10T11:00:00Z"
    assert shown["message_expires_at"] == "2026-10-10T10:00:00Z"
    assert shown["source_reference"] == {"api_fields": ["properties.event"]}
    assert view.metadata["accepted_categories"]["closures"] is None


@pytest.mark.parametrize("field, replacement", [
    ("can_calculate_operational_outcomes", 0),
    ("calibrated", 0),
    ("horizon_minutes", 60.0),
])
def test_rejects_json_type_substitution_even_when_python_values_compare_equal(field, replacement):
    snapshot, branch = inputs()
    altered = deepcopy(branch)
    altered[field] = replacement
    assert altered == branch  # Python equality loses the JSON type distinction.
    with pytest.raises(ValueError, match="projection input"):
        adapt_incident(snapshot, [{"branch_id": "rain", "input": altered}],
                       expected_snapshot_hash=snapshot["snapshot_hash"])
