import copy
import math
import unittest

from contracts.incident import (
    EvidenceLog,
    HumanReview,
    OfficialPolicy,
    VerifiedSource,
    projection_input,
    record_fingerprint,
)


CUT = "2026-10-10T09:00:00Z"
LATER = "2026-10-10T10:00:00Z"
HASH = "a" * 64


def record(source_id="nws", item_id="alert-1", revision=1, **overrides):
    value = {
        "source_id": source_id,
        "item_id": item_id,
        "revision": revision,
        "source_url": "https://api.weather.gov/alerts/1",
        "raw_sha256": HASH,
        "provider": "NWS",
        "license": "public domain",
        "source_type": "official_api",
        "category": "hazard",
        "source_kind": "official_forecast",
        "published_at": "2026-10-10T08:00:00Z",
        "observed_at": None,
        "valid_from": None,
        "valid_through": None,
        "message_expires_at": None,
        "first_seen_at": "2026-10-10T08:30:00Z",
        "fetched_at": "2026-10-10T08:45:00Z",
        "accepted_at": CUT,
        "correction_available_at": None,
        "superseded_at": None,
        "supersedes": None,
        "retracted": False,
        "source_reference": {"api_fields": ["properties.event"]},
        "geometry": {"type": "Point", "coordinates": [-120.5, 39.5]},
        "precision": "point",
        "area_label": None,
        "source_uncertainty": None,
        "payload": {"event": "Flood Warning"},
    }
    value.update(overrides)
    return value


def verification(source_id="nws", url="https://api.weather.gov/alerts/1", raw_hash=HASH):
    return VerifiedSource(source_id, url, raw_hash, True)


def log():
    return EvidenceLog(
        "incident-1",
        [-121, 39, -120, 40],
        official_policies=[
            OfficialPolicy("nws", "NWS", "api.weather.gov",
                           ("properties.event", "properties.onset",
                            "properties.ends", "properties.expires"),
                           ("event",), "nws-alert-v1")
        ],
    )


def review(r, reviewer="dispatcher-1"):
    return HumanReview(
        (r["source_id"], r["item_id"], r["revision"]),
        r["raw_sha256"],
        reviewer,
        tuple(r["payload"]),
        r["accepted_at"],
        True,
        record_fingerprint(r),
    )


class IncidentContractTests(unittest.TestCase):
    def test_official_hazard_and_unknown_resources(self):
        store = log()
        accepted = store.append(record(), verification=verification())
        self.assertEqual(accepted["acceptance"]["method"], "official_policy")
        snap = store.snapshot(CUT)
        self.assertEqual(snap["categories"]["hazard"][0]["payload"]["event"], "Flood Warning")
        for category in ("needs", "closures", "vehicles", "stock", "capacity"):
            self.assertIsNone(snap["categories"][category])
        self.assertIsNone(snap["categories"]["hazard"][0]["valid_through"])
        self.assertEqual(snap["bbox_lonlat"], [-121, 39, -120, 40])
        with self.assertRaises(TypeError):
            store.bbox_lonlat[0] = 0

    def test_nws_onset_and_message_expiration_are_distinct(self):
        store = log()
        alert = record(valid_from="2026-10-10T12:00:00Z",
                       valid_through=None,
                       message_expires_at="2026-10-10T11:00:00Z",
                       source_reference={"api_fields": [
                           "properties.event", "properties.onset",
                           "properties.ends", "properties.expires"]})
        store.append(alert, verification=verification())
        fact = store.snapshot(CUT)["categories"]["hazard"][0]
        self.assertEqual(fact["valid_from"], "2026-10-10T12:00:00Z")
        self.assertEqual(fact["message_expires_at"], "2026-10-10T11:00:00Z")
        self.assertIsNone(fact["valid_through"])

    def test_untrusted_self_review_and_official_operational_claim_rejected(self):
        store = log()
        proposal = record(category="closures", payload={"closed": True},
                          acceptance={"method": "human_review", "reviewer_id": "fake"})
        with self.assertRaises(ValueError):
            store.append(proposal, verification=verification())
        proposal.pop("acceptance")
        with self.assertRaises(ValueError):
            store.append(proposal, verification=verification())
        self.assertIsNone(store.snapshot(CUT)["categories"]["closures"])

    def test_human_review_of_independent_operational_record(self):
        store = log()
        r = record(source_id="agency", item_id="closure-1", source_type="agency_notice",
                   source_kind="reported", provider="County", category="closures",
                   source_url="https://county.example/notices/1",
                   source_reference={"quote": "Road X closed", "page": 1},
                   payload={"road": "Road X", "closed": True},
                   geometry=None, precision="area", area_label="North district")
        store.append(r, verification=verification("agency", r["source_url"]), review=review(r))
        self.assertEqual(store.snapshot(CUT)["categories"]["closures"][0]["acceptance"]["reviewer_id"],
                         "dispatcher-1")
        self.assertIsNone(store.snapshot(CUT)["categories"]["vehicles"])

    def test_review_binds_values_category_geometry_and_source_kind(self):
        original = record(source_id="agency", item_id="closure-2",
                          source_type="agency_notice", source_kind="reported",
                          provider="County", category="closures",
                          source_url="https://county.example/notices/2",
                          source_reference={"quote": "Road X closed"},
                          payload={"road": "Road X", "closed": True},
                          geometry=None, precision="area", area_label="North district")
        authorization = review(original)
        for change in (
            {"payload": {"road": "Road X", "closed": False}},
            {"category": "capacity"},
            {"source_kind": "authored"},
            {"area_label": "South district"},
            {"source_reference": {"quote": "Road X open"}},
            {"published_at": "2026-10-10T07:00:00Z"},
            {"observed_at": "2026-10-10T08:15:00Z"},
            {"valid_from": "2026-10-10T08:00:00Z"},
            {"geometry": {"type": "Point", "coordinates": [-120.5, 39.5]},
             "precision": "point", "area_label": None},
        ):
            store = log()
            altered = copy.deepcopy(original)
            altered.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                store.append(altered,
                             verification=verification("agency", original["source_url"]),
                             review=authorization)
            self.assertEqual(store.snapshot(CUT)["revision_history"], [])

    def test_review_binds_correction_and_retraction_content(self):
        store = log()
        first = record(source_id="agency", item_id="closure-corrected",
                       source_type="agency_notice", source_kind="reported",
                       provider="County", category="closures",
                       source_url="https://county.example/correction",
                       source_reference={"quote": "Road X closed"},
                       payload={"road": "Road X", "closed": True})
        store.append(first, verification=verification("agency", first["source_url"]),
                     review=review(first))
        second = record(source_id="agency", item_id="closure-corrected", revision=2,
                        source_type="agency_notice", source_kind="reported",
                        provider="County", category="closures",
                        source_url="https://county.example/correction",
                        source_reference={"quote": "Road X reopened"},
                        payload={"road": "Road X", "closed": False},
                        accepted_at=LATER, correction_available_at=LATER,
                        supersedes=("agency", "closure-corrected", 1))
        authorization = review(second)
        for change in (
            {"retracted": True},
            {"correction_available_at": "2026-10-10T09:30:00Z"},
            {"payload": {"road": "Road Y", "closed": False}},
        ):
            altered = copy.deepcopy(second)
            altered.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                store.append(altered,
                             verification=verification("agency", first["source_url"]),
                             review=authorization)
        self.assertEqual(len(store.snapshot(CUT)["revision_history"]), 1)
        store.append(second, verification=verification("agency", first["source_url"]),
                     review=authorization)
        self.assertEqual(len(store.snapshot(LATER)["revision_history"]), 2)

    def test_observed_claim_cannot_be_known_before_observation(self):
        store = log()
        future = record(source_id="agency", item_id="future-observation",
                        source_url="https://county.example/observation",
                        provider="County", source_type="agency_notice",
                        source_kind="observed", observed_at=LATER,
                        source_reference={"quote": "Observed at 10:00"},
                        payload={"event": "observed flood"})
        with self.assertRaises(ValueError):
            store.append(future,
                         verification=verification("agency", future["source_url"]),
                         review=review(future))
        with self.assertRaises(ValueError):
            store.append(record(source_kind="observed", observed_at=LATER),
                         verification=verification())
        with self.assertRaises(ValueError):
            store.append(record(source_kind="observed", observed_at=None),
                         verification=verification())
        self.assertEqual(store.snapshot(CUT)["revision_history"], [])

    def test_inverted_hazard_validity_rejected(self):
        store = log()
        impossible = record(valid_from="2026-10-10T12:00:00Z",
                            valid_through="2026-10-10T11:00:00Z")
        with self.assertRaises(ValueError):
            store.append(impossible, verification=verification())
        self.assertEqual(store.snapshot(CUT)["revision_history"], [])

    def test_unknown_status_records_do_not_enable_operational_calculation(self):
        store = log()
        for category in ("needs", "closures", "vehicles", "stock", "capacity"):
            r = record(source_id="county", item_id=category, source_type="agency_notice",
                       source_kind="reported", provider="County", category=category,
                       source_url="https://county.example/" + category,
                       source_reference={"quote": "Status unknown"},
                       payload={"status": "unknown"},
                       geometry=None, precision="area", area_label="County")
            store.append(r, verification=verification("county", r["source_url"]),
                         review=review(r))
        snap = store.snapshot(CUT)
        result = projection_input(snap, horizon_minutes=60, model_version="model-1",
                                  assumptions={"weather": "authored branch"})
        self.assertFalse(result["can_calculate_operational_outcomes"])
        self.assertEqual(set(result["unknown_operational_categories"]),
                         {"needs", "closures", "vehicles", "stock", "capacity"})

    def test_correction_retraction_cutoff_and_immutable_inputs(self):
        store = log()
        original = record()
        store.append(original, verification=verification())
        commitments = [{"trip_id": "trip-1", "vehicle": "v-1"}]
        old = store.snapshot(CUT, ledger_watermark={"seq": 7},
                             in_flight_commitments=commitments)
        old_hash = old["snapshot_hash"]
        commitments[0]["vehicle"] = "tampered"
        correction = record(revision=2, accepted_at=LATER,
                            correction_available_at=LATER,
                            supersedes=("nws", "alert-1", 1),
                            payload={"event": "Flash Flood Warning"})
        store.append(correction, verification=verification())
        self.assertEqual(store.snapshot(CUT, ledger_watermark={"seq": 7},
                                        in_flight_commitments=[{"trip_id": "trip-1", "vehicle": "v-1"}]),
                         old)
        self.assertEqual(old["snapshot_hash"], old_hash)
        self.assertEqual(old["in_flight_commitments"][0]["vehicle"], "v-1")
        current = store.snapshot(LATER)
        self.assertEqual(current["categories"]["hazard"][0]["revision"], 2)
        self.assertEqual(current["revision_history"][0]["superseded_at"], LATER)
        self.assertIsNone(old["revision_history"][0]["superseded_at"])
        self.assertNotEqual(current["snapshot_hash"], old_hash)
        retraction = record(revision=3, accepted_at="2026-10-10T11:00:00Z",
                            correction_available_at="2026-10-10T11:00:00Z",
                            supersedes=("nws", "alert-1", 2), retracted=True,
                            payload={"event": "retracted"})
        store.append(retraction, verification=verification())
        self.assertEqual(store.snapshot(LATER), current)
        retracted_snapshot = store.snapshot("2026-10-10T11:00:00Z")
        self.assertIsNone(retracted_snapshot["categories"]["hazard"])
        self.assertTrue(retracted_snapshot["revision_history"][-1]["retracted"])

    def test_duplicate_idempotency_conflicts_and_atomic_invalid_link(self):
        store = log()
        r = record()
        store.append(r, verification=verification())
        self.assertEqual(store.append(copy.deepcopy(r), verification=verification())["revision"], 1)
        with self.assertRaises(ValueError):
            store.append(record(payload={"event": "other"}), verification=verification())
        bad = record(revision=2, accepted_at=LATER, correction_available_at=LATER,
                     supersedes=("nws", "wrong", 1))
        with self.assertRaises(ValueError):
            store.append(bad, verification=verification())
        other = record(source_id="county", item_id="claim-1", provider="County",
                       source_type="agency_notice", source_kind="reported",
                       source_url="https://county.example/claim",
                       source_reference={"quote": "No flood", "page": 2},
                       payload={"event": "No flood"})
        store.append(other, verification=verification("county", other["source_url"]),
                     review=review(other))
        snap = store.snapshot(CUT)
        self.assertEqual(len(snap["categories"]["hazard"]), 2)

    def test_validation_and_source_binding(self):
        for change in (
            {"revision": True},
            {"geometry": {"type": "Point", "coordinates": [True, 39.5]}},
            {"geometry": {"type": "Point", "coordinates": [math.nan, 39.5]}},
            {"geometry": {"type": "Point", "coordinates": [-1, 39.5]}},
            {"geometry": {"type": "LineString", "coordinates": [[-120.5, 39.5]]}},
            {"accepted_at": "2026-10-10T09:00:00+01:00"},
            {"bbox_lonlat": [0, 0, 1, 1]},
            {"valid_through": float("nan")},
        ):
            store = log()
            r = record(**change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                store.append(r, verification=verification())
        with self.assertRaises(ValueError):
            log().append(record(), verification=verification(raw_hash="b" * 64))
        with self.assertRaises(ValueError):
            log().append(record(), verification=verification(url="https://evil.example/alerts/1"))
        with self.assertRaises(ValueError):
            EvidenceLog("x", [True, 39, -120, 40])

    def test_issued_cutoff_cannot_be_rewritten_by_backdated_append(self):
        store = log()
        issued = store.snapshot(CUT)
        with self.assertRaises(ValueError):
            store.append(record(), verification=verification())
        self.assertEqual(store.snapshot(CUT), issued)

    def test_news_lead_stale_source_and_invalid_policy_kind(self):
        store = log()
        lead = record(source_id="news", item_id="report-1",
                      source_url="https://news.example/report",
                      provider="News", source_type="news",
                      source_kind="reported",
                      source_reference={"quote": "Flood reported"},
                      payload={"event": "possible flood"},
                      geometry=None, precision="area", area_label="County")
        store.append(lead, verification=verification("news", lead["source_url"]),
                     review=review(lead))
        snap = store.snapshot(CUT, source_health={
            "news": {"status": "stale", "source_time": "2026-10-10T08:45:00Z",
                     "reason": "refresh failed"}})
        self.assertIsNone(snap["categories"]["hazard"])
        self.assertEqual(len(snap["unconfirmed_leads"]), 1)
        self.assertEqual(snap["source_health"]["news"]["status"], "stale")
        with self.assertRaises(ValueError):
            store.snapshot(CUT, source_health={"news": {"status": "stale"}})
        other = log()
        with self.assertRaises(ValueError):
            other.append(record(source_kind="authored"), verification=verification())

    def test_hash_copy_and_projection_provenance(self):
        store = log()
        store.append(record(), verification=verification())
        snap = store.snapshot(CUT, ledger_watermark={"seq": 4},
                              in_flight_commitments=[{"trip_id": "t"}])
        equivalent = log()
        equivalent.append(record(), verification=verification())
        self.assertEqual(snap, equivalent.snapshot(
            CUT, ledger_watermark={"seq": 4}, in_flight_commitments=[{"trip_id": "t"}]))
        snap["categories"]["hazard"][0]["payload"]["event"] = "mutated"
        self.assertEqual(store.snapshot(CUT)["categories"]["hazard"][0]["payload"]["event"],
                         "Flood Warning")
        clean = store.snapshot(CUT)
        projection = projection_input(clean, horizon_minutes=60, model_version="model-1",
                                      assumptions={"weather": "authored training branch"})
        self.assertEqual(projection["initial_snapshot_hash"], clean["snapshot_hash"])
        self.assertEqual(projection["cutoff_utc"], CUT)
        self.assertFalse(projection["calibrated"])
        self.assertFalse(projection["can_calculate_operational_outcomes"])
        self.assertEqual(projection["frequency_label"], "uncalibrated_scenario_frequencies")
        self.assertFalse(projection_input(
            clean, horizon_minutes=60, model_version="model-1",
            assumptions={"weather": "authored"},
            training_assumptions={"vehicles": "authored training inventory",
                                  "stock": "authored training stock",
                                  "capacity": "authored training capacity",
                                  "closures": "authored training roads",
                                  "needs": "authored training needs"})[
                                      "can_calculate_operational_outcomes"])
        with self.assertRaises(ValueError):
            projection_input(clean, horizon_minutes=True, model_version="model-1",
                             assumptions={"weather": "authored"})
        altered = copy.deepcopy(clean)
        altered["categories"]["hazard"][0]["payload"]["event"] = "tampered"
        with self.assertRaises(ValueError):
            projection_input(altered, horizon_minutes=60, model_version="model-1",
                             assumptions={"weather": "authored"})


if __name__ == "__main__":
    unittest.main()
