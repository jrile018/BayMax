import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts.incident import EvidenceLog, OfficialPolicy, VerifiedSource, record_fingerprint
from integration.incident_artifacts import SnapshotPublisher, VerifiedSynopsis


T0 = "2026-10-10T09:00:00Z"
T1 = "2026-10-10T10:00:00Z"
SHA = "a" * 64


def make_log():
    return EvidenceLog(
        "incident-1", [-121, 39, -120, 40],
        official_policies=[OfficialPolicy(
            "nws", "NWS", "api.weather.gov",
            ("properties.event",), ("event",), "nws-alert-v1")],
    )


def make_record(revision=1, **updates):
    record = {
        "source_id": "nws", "item_id": "alert-1", "revision": revision,
        "source_url": "https://api.weather.gov/alerts/1",
        "raw_sha256": SHA, "provider": "NWS", "license": "public domain",
        "source_type": "official_api", "category": "hazard",
        "source_kind": "official_forecast",
        "published_at": "2026-10-10T08:00:00Z", "observed_at": None,
        "valid_from": None, "valid_through": None, "message_expires_at": None,
        "first_seen_at": "2026-10-10T08:30:00Z",
        "fetched_at": "2026-10-10T08:45:00Z", "accepted_at": T0,
        "correction_available_at": None, "superseded_at": None,
        "supersedes": None, "retracted": False,
        "source_reference": {"api_fields": ["properties.event"]},
        "geometry": {"type": "Point", "coordinates": [-120.5, 39.5]},
        "precision": "point", "area_label": None, "source_uncertainty": None,
        "payload": {"event": "Flood Warning"},
    }
    record.update(updates)
    return record


def append(store, record):
    store.append(record, verification=VerifiedSource(
        record["source_id"], record["source_url"], record["raw_sha256"],
        True, record_fingerprint(record)))


def envelope(as_of, value):
    return {"as_of_utc": as_of, "value": value}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "out"
        self.publisher = SnapshotPublisher(self.directory)
        self.store = make_log()
        append(self.store, make_record())

    def test_unknown_resources_and_pinned_projection(self):
        output = self.publisher.publish(
            self.store, T0, projection_request={
                "horizon_minutes": 60, "model_version": "scenario-v1",
                "assumptions": {"weather": "authored branch"}},
        )
        self.assertIsNone(output["snapshot"]["ledger_watermark"])
        self.assertIsNone(output["snapshot"]["in_flight_commitments"])
        for category in ("needs", "closures", "vehicles", "stock", "capacity"):
            self.assertIsNone(output["snapshot"]["categories"][category])
        self.assertFalse(output["capabilities"]["can_calculate_operational_outcomes"])
        self.assertFalse(output["capabilities"]["can_dispatch"])
        self.assertEqual(output["projection_input"]["initial_snapshot_hash"],
                         output["snapshot"]["snapshot_hash"])
        self.assertFalse(output["projection_input"]["can_calculate_operational_outcomes"])
        self.assertEqual(output["snapshot"]["categories"]["hazard"][0]["source_reference"],
                         {"api_fields": ["properties.event"]})

    def test_stale_health_changes_view_only(self):
        first = self.publisher.publish(self.store, T0)
        second = self.publisher.publish(self.store, T0, source_health={
            "nws": {"status": "stale", "source_time": T0, "reason": "refresh failed"}})
        self.assertEqual(first["mission_hash"], second["mission_hash"])
        self.assertNotEqual(first["snapshot"]["snapshot_hash"], second["snapshot"]["snapshot_hash"])
        self.assertNotEqual(first["view_hash"], second["view_hash"])
        self.assertEqual(first["snapshot"]["categories"], second["snapshot"]["categories"])

    def test_late_correction_preserves_prior_publication_bytes_and_commitments(self):
        commitments = [{"trip_id": "trip-1", "state": "in_flight"}]
        first = self.publisher.publish(
            self.store, T0,
            in_flight_commitments=envelope(T0, commitments),
            projection_request={"horizon_minutes": 60, "model_version": "scenario-v1",
                                "assumptions": {"weather": "authored branch"}})
        first_path = self.directory / ("publication-" + first["view_hash"] + ".json")
        original = first_path.read_bytes()
        corrected = make_record(
            2, payload={"event": "Flood Watch"}, accepted_at=T1,
            correction_available_at=T1, fetched_at=T1,
            supersedes=["nws", "alert-1", 1])
        append(self.store, corrected)
        second = self.publisher.publish(
            self.store, T1, in_flight_commitments=envelope(T0, commitments))
        self.assertNotEqual(first["mission_hash"], second["mission_hash"])
        self.assertEqual(first_path.read_bytes(), original)
        self.assertEqual(first["snapshot"]["in_flight_commitments"], commitments)
        self.assertEqual(first["snapshot"]["categories"]["hazard"][0]["payload"]["event"],
                         "Flood Warning")
        self.assertEqual(first["projection_input"]["initial_snapshot_hash"],
                         first["snapshot"]["snapshot_hash"])
        self.assertEqual(second["snapshot"]["revision_history"][0]["superseded_at"], T1)

    def test_metadata_temporal_envelopes_and_caller_mutation(self):
        ledger = {"seq": 7}
        commitments = [{"trip_id": "a"}]
        published = self.publisher.publish(
            self.store, T0,
            ledger_watermark=envelope(T0, ledger),
            in_flight_commitments=envelope(T0, commitments))
        ledger["seq"] = 9
        commitments[0]["trip_id"] = "b"
        self.assertEqual(published["snapshot"]["ledger_watermark"], {"seq": 7})
        self.assertEqual(published["snapshot"]["in_flight_commitments"], [{"trip_id": "a"}])
        self.assertEqual(published["metadata_attestations"]["ledger_watermark"]["as_of_utc"], T0)
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          ledger_watermark=envelope(T1, {"seq": 8}))
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          in_flight_commitments=envelope(T1, []))
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          ledger_watermark={"seq": 7})
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          ledger_watermark=envelope(T0, {"as_of_utc": T1}))
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          in_flight_commitments=envelope(T0, [{"as_of_utc": T1}]))

    def test_rejects_forged_log_and_tampered_snapshot_hash(self):
        fake = {"snapshot_hash": "0" * 64}
        self.assertRaises(TypeError, self.publisher.publish, fake, T0)
        with patch.object(self.store, "snapshot", return_value=fake):
            self.assertRaises(ValueError, self.publisher.publish, self.store, T0)
        self.assertFalse((self.directory / "current.json").exists())

    def test_geography_and_verified_synopsis_bind_hashes(self):
        plain = self.publisher.publish(self.store, T0)
        bound = self.publisher.publish(self.store, T0, geography_binding={
            "graph_sha256": "b" * 64, "crs": "EPSG:4326", "origin": "verified-map",
            "epoch_utc": T0})
        self.assertNotEqual(plain["mission_hash"], bound["mission_hash"])
        self.assertIsNone(plain["geography_binding"])
        synopsis = VerifiedSynopsis(
            text="Flood warning remains in effect", as_of_utc=T0,
            snapshot_hash=plain["snapshot"]["snapshot_hash"],
            reviewer_id="reviewer-1")
        with_synopsis = self.publisher.publish(self.store, T0, synopsis=synopsis)
        self.assertEqual(plain["mission_hash"], with_synopsis["mission_hash"])
        self.assertNotEqual(plain["view_hash"], with_synopsis["view_hash"])
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          synopsis=VerifiedSynopsis("bad", T0, "0" * 64, "reviewer-1"))

    def test_idempotency_and_immutable_content(self):
        first = self.publisher.publish(self.store, T0)
        path = self.directory / ("publication-" + first["view_hash"] + ".json")
        data = path.read_bytes()
        first["snapshot"]["categories"]["hazard"][0]["payload"]["event"] = "mutated"
        second = self.publisher.publish(self.store, T0)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(second["snapshot"]["categories"]["hazard"][0]["payload"]["event"],
                         "Flood Warning")
        path.write_text("tampered", encoding="utf-8")
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0)
        self.assertEqual(path.read_text(encoding="utf-8"), "tampered")

    def test_pointer_failure_leaves_old_current_and_orphan(self):
        first = self.publisher.publish(self.store, T0)
        pointer = (self.directory / "current.json").read_bytes()
        with patch.object(self.publisher, "_replace_pointer", side_effect=OSError("fault")):
            self.assertRaises(OSError, self.publisher.publish, self.store, T0,
                              source_health={"nws": {"status": "alive", "source_time": T0}})
        self.assertEqual((self.directory / "current.json").read_bytes(), pointer)
        files = list(self.directory.glob("publication-*.json"))
        self.assertEqual(len(files), 2)
        self.assertEqual(json.loads(pointer)["view_hash"], first["view_hash"])

    def test_invalid_or_symlink_output_refused(self):
        self.assertRaises(ValueError, SnapshotPublisher, self.directory / ".." / "other")
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        link = Path(self.tmp.name) / "link"
        link.symlink_to(elsewhere, target_is_directory=True)
        self.assertRaises(ValueError, SnapshotPublisher, link)
        self.directory.mkdir()
        (self.directory / "current.json").symlink_to(elsewhere / "victim")
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0)
        self.assertFalse((elsewhere / "victim").exists())

    def test_finite_and_bounded_input_and_symlink_content_refused(self):
        import math
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          ledger_watermark=envelope(T0, {"x": math.nan}))
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          ledger_watermark=envelope(T0, {"blob": "x" * 1_048_577}))
        first = self.publisher.publish(self.store, T0)
        target = Path(self.tmp.name) / "outside.json"
        target.write_text("outside", encoding="utf-8")
        content_path = self.directory / ("publication-" + first["view_hash"] + ".json")
        content_path.unlink()
        content_path.symlink_to(target)
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0)
        self.assertEqual(target.read_text(encoding="utf-8"), "outside")

    def test_rejects_invalid_payload_without_changing_pointer(self):
        first = self.publisher.publish(self.store, T0)
        pointer = (self.directory / "current.json").read_bytes()
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          geography_binding={"graph_sha256": "b" * 64})
        self.assertRaises(ValueError, self.publisher.publish, self.store, T0,
                          projection_request={"horizon_minutes": 0, "model_version": "x",
                                              "assumptions": {"a": "b"}})
        self.assertEqual((self.directory / "current.json").read_bytes(), pointer)
        self.assertEqual(json.loads(pointer)["view_hash"], first["view_hash"])


if __name__ == "__main__":
    unittest.main()
