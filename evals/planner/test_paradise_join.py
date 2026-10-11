"""The accepted California feed is context, never a Paradise forecast."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from contracts.incident import EvidenceLog, OfficialPolicy, VerifiedSource, record_fingerprint
from integration.incident_artifacts import SnapshotPublisher
from services.planner.futures.paradise_join import join_current_paradise

CUT = "2026-10-10T09:00:00Z"
ASSUMPTIONS = {
    "weather": "Authored wind-shift stress case; no verified local forecast.",
    "fuel": "Authored fuel condition; no verified fuel survey.",
    "ignition": "Authored ignition event; no observed ignition.",
}


def publication(tmp_path, *, bbox=None, local_point=False, projection_request=None):
    root = tmp_path / "accepted"
    root.parent.mkdir(parents=True, exist_ok=True)
    store = EvidenceLog(
        "ca-test", bbox or [-125, 32, -114, 42], official_policies=[
            OfficialPolicy("nws", "NWS", "api.weather.gov",
                           ("properties.event",), ("event",), "nws-alert-v1")])
    record = {
        "source_id": "nws", "item_id": "alert-1", "revision": 1,
        "source_url": "https://api.weather.gov/alerts/1",
        "raw_sha256": "a" * 64, "provider": "NWS",
        "license": "public domain", "source_type": "official_api",
        "category": "hazard", "source_kind": "official_forecast",
        "published_at": "2026-10-10T08:00:00Z", "observed_at": None,
        "valid_from": None, "valid_through": None, "message_expires_at": None,
        "first_seen_at": "2026-10-10T08:30:00Z",
        "fetched_at": "2026-10-10T08:45:00Z", "accepted_at": CUT,
        "correction_available_at": None, "superseded_at": None,
        "supersedes": None, "retracted": False,
        "source_reference": {"api_fields": ["properties.event"]},
        "geometry": {"type": "Point", "coordinates":
                     [-121.6, 39.75] if local_point else [-120.5, 39.5]},
        "precision": "point", "area_label": None,
        "source_uncertainty": None, "payload": {"event": "Flood Warning"},
    }
    store.append(record, verification=VerifiedSource(
        "nws", record["source_url"], record["raw_sha256"], True,
        record_fingerprint(record)))
    published = SnapshotPublisher(root).publish(store, CUT, projection_request=projection_request)
    return root, published


def joined(root, *, expected=None, as_of="2026-10-10T09:05:00Z"):
    pointer = json.loads((root / "current.json").read_text())
    return join_current_paradise(
        root, expected_publication_sha256=expected or pointer["publication_sha256"],
        caller_as_of_utc=as_of, horizon_minutes=60,
        authored_assumptions=ASSUMPTIONS)


def test_joins_verified_publication_to_authored_paradise_context(tmp_path):
    root, accepted = publication(tmp_path)
    before = copy.deepcopy(accepted)
    result = joined(root)
    assert result == joined(root)
    assert accepted == before
    assert result["join_version"] == "paradise-hypothetical-join-v1"
    assert result["accepted_publication"]["view_hash"] == accepted["view_hash"]
    assert result["accepted_publication"]["snapshot_hash"] == accepted["snapshot"]["snapshot_hash"]
    assert result["accepted_publication"]["cutoff_utc"] == CUT
    assert result["accepted_publication"]["source_health_as_of_utc"] == CUT
    assert result["accepted_publication"]["geography_binding"] is None
    assert result["caller_as_of_utc"] == "2026-10-10T09:05:00Z"
    assert result["horizon_end_utc"] == "2026-10-10T10:00:00.000000Z"
    assert result["horizon_expired_at_caller_as_of"] is False
    assert result["assumption_provenance"] == "authored_exercise_unverified"
    assert result["model_execution"] == "none_metadata_only"
    assert result["accepted_publication"]["published_projection_input_hash"] is None
    assert result["exercise_area"]["area_id"] == "paradise-ca"
    assert result["exercise_area"]["county_context"] == "Butte County (authored exercise label)"
    assert set(result["exercise_area"]["unavailable_layers"]) >= {
        "terrain", "fuels", "current_fire"}
    assert result["exercise_area"]["area_sha256"] == (
        "8d30c559e94bdcf6fd3db8db7c442015a874d94fb060a0273656535f2c9b0cb6")
    assert result["spatial_link_status"] == "unverified_for_paradise"
    assert result["accepted_local_hazard_refs"] == []
    assert result["pinned_projection"]["projection_input"]["horizon_minutes"] == 60
    assert result["pinned_projection"]["projection_input"]["model_version"] == "scenario-v1"
    assert result["pinned_projection"]["projection_input"]["authored_assumptions"]["weather"] == ASSUMPTIONS["weather"]
    assert result["pinned_projection"]["initial_snapshot_hash"] == accepted["snapshot"]["snapshot_hash"]
    assert result["pinned_projection"]["accepted_snapshot"]["ledger_watermark"] is None
    assert result["pinned_projection"]["accepted_snapshot"]["in_flight_commitments"] is None
    for category in ("needs", "closures", "vehicles", "stock", "capacity"):
        assert result["pinned_projection"]["accepted_snapshot"]["categories"][category] is None
    assert result["pinned_projection"]["scenario_branches"] == []
    assert result["forecast_available"] is False
    assert result["operational_outcomes_available"] is False
    assert result["calibrated"] is False
    assert result["can_dispatch"] is False
    raw = {key: value for key, value in result.items() if key != "join_hash"}
    assert result["join_hash"] == hashlib.sha256(json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()


def test_even_accepted_point_inside_paradise_does_not_become_route_or_forecast(tmp_path):
    root, _ = publication(tmp_path, local_point=True)
    result = joined(root)
    assert result["accepted_local_hazard_refs"] == []
    assert result["spatial_link_status"] == "unverified_for_paradise"
    assert result["pinned_projection"]["accepted_snapshot"]["categories"]["closures"] is None
    assert result["forecast_available"] is False


def test_rejects_tampered_publication_bytes_and_unsafe_pointer(tmp_path):
    root, _ = publication(tmp_path)
    pointer = json.loads((root / "current.json").read_text())
    artifact = root / pointer["publication_file"]
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ValueError):
        joined(root)
    artifact.write_bytes(artifact.read_bytes()[:-1])
    (root / "current.json").unlink()
    (root / "current.json").symlink_to(artifact)
    with pytest.raises(ValueError):
        joined(root, expected=pointer["publication_sha256"])


def test_rejects_area_outside_source_scope_and_invalid_assumptions(tmp_path):
    root, _ = publication(tmp_path, bbox=[-121, 39, -120, 40])
    with pytest.raises(ValueError, match="outside"):
        joined(root)
    root, _ = publication(tmp_path / "wide")
    with pytest.raises(ValueError):
        join_current_paradise(
            root, expected_publication_sha256=(
                json.loads((root / "current.json").read_text())["publication_sha256"]),
            caller_as_of_utc="2026-10-10T09:05:00Z",
            horizon_minutes=True, authored_assumptions=ASSUMPTIONS)
    with pytest.raises(ValueError):
        join_current_paradise(
            root, expected_publication_sha256=(
                json.loads((root / "current.json").read_text())["publication_sha256"]),
            caller_as_of_utc="2026-10-10T09:05:00Z",
            horizon_minutes=60, authored_assumptions={"weather": "wind"})


def test_preserves_published_projection_identity_but_derives_separate_exercise(tmp_path):
    root, accepted = publication(tmp_path, projection_request={
        "horizon_minutes": 30, "model_version": "scenario-v1",
        "assumptions": {"weather": "Published, separately authored source context."},
    })
    result = joined(root)
    assert result["accepted_publication"]["published_projection_input_hash"] == (
        accepted["projection_input"]["projection_input_hash"])
    assert result["pinned_projection"]["projection_input_hash"] != (
        accepted["projection_input"]["projection_input_hash"])
    assert result["pinned_projection"]["projection_input"]["horizon_minutes"] == 60
    assert result["forecast_available"] is False


def test_rejects_changed_reviewed_area_fixture_digest(tmp_path, monkeypatch):
    root, _ = publication(tmp_path)
    from services.planner.futures import paradise_join
    monkeypatch.setattr(paradise_join, "AREA_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="geography"):
        joined(root)


def test_trusted_publication_pin_rejects_another_valid_publication(tmp_path):
    first, _ = publication(tmp_path / "first")
    trusted = json.loads((first / "current.json").read_text())["publication_sha256"]
    second, _ = publication(tmp_path / "second", projection_request={
        "horizon_minutes": 30, "model_version": "scenario-v1",
        "assumptions": {"weather": "A separately valid published assumption."},
    })
    with pytest.raises(ValueError, match="trusted expected identity"):
        joined(second, expected=trusted)


def test_rejects_numeric_zero_instead_of_false_capability(tmp_path):
    root, _ = publication(tmp_path)
    pointer_path = root / "current.json"
    pointer = json.loads(pointer_path.read_text())
    artifact = root / pointer["publication_file"]
    doc = json.loads(artifact.read_text())
    doc["capabilities"]["can_dispatch"] = 0
    raw = (json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False) + "\n").encode()
    artifact.write_bytes(raw)
    pointer["publication_sha256"] = hashlib.sha256(raw).hexdigest()
    pointer_path.write_text(json.dumps(
        pointer, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False) + "\n")
    with pytest.raises(ValueError, match="cannot authorize operations"):
        joined(root)


def test_caller_as_of_marks_expired_horizon_without_rebasing_source(tmp_path):
    root, _ = publication(tmp_path)
    before = joined(root, as_of="2026-10-10T09:59:59.999999Z")
    exact = joined(root, as_of="2026-10-10T10:00:00Z")
    result = joined(root, as_of="2026-10-10T10:00:00.000001Z")
    assert before["horizon_expired_at_caller_as_of"] is False
    assert exact["horizon_expired_at_caller_as_of"] is True
    assert result["horizon_expired_at_caller_as_of"] is True
    assert result["accepted_publication"]["cutoff_utc"] == CUT
    assert result["horizon_end_utc"] == "2026-10-10T10:00:00.000000Z"
    with pytest.raises(ValueError, match="predate"):
        joined(root, as_of="2026-10-10T08:59:59Z")
