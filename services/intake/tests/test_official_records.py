"""Official-record integration against the frozen incident-v1 contract."""
from __future__ import annotations

from hashlib import sha256
import importlib
import os
import sys
import unittest

from services.intake.live_sources import RawDocument, SourceError
from services.intake.official_records import (
    IngestionContext, build_official_record, official_policies,
    dispatcher_synopsis,
)
from services.intake.tests.test_live_sources import NWS, USGS, packet, nws, usgs


def contract_module():
    root = os.environ.get("KNIGHT26_CONTRACT_ROOT")
    if root and root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module("contracts.incident")
    except ModuleNotFoundError:
        return None


CONTRACT = contract_module()
ACTUAL_NWS = "https://api.weather.gov/alerts?active=true&area=CA"
FETCHED = "2026-10-10T09:13:00Z"


def document(source, features, url, fetched=FETCHED):
    raw = packet(url, features).body
    return RawDocument(source, url, url, 200, (), fetched, raw,
                       sha256(raw).hexdigest())


@unittest.skipIf(CONTRACT is None, "frozen incident contract unavailable")
class OfficialRecordTests(unittest.TestCase):
    def test_nws_saved_url_area_label_and_policy_acceptance(self):
        doc = document("nws", [nws()], ACTUAL_NWS)
        context = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-125, 32, -114, 42), True)
        record, verification = build_official_record(
            doc, "urn:oid:alert-1", context, contract=CONTRACT)
        self.assertEqual(record["source_url"], ACTUAL_NWS)
        self.assertEqual(record["precision"], "area")
        self.assertEqual(record["valid_from"], "2026-10-11T22:00:00Z")
        self.assertEqual(record["payload"]["effective_at"],
                         "2026-10-10T09:01:00Z")
        self.assertEqual(record["payload"]["area_desc"], "Example area")
        self.assertIsNone(record["valid_through"])
        self.assertEqual(record["message_expires_at"], "2026-10-10T21:00:00Z")
        self.assertIn("AOI not spatially verified", record["source_uncertainty"])
        self.assertEqual(verification.extracted_record_sha256,
                         CONTRACT.record_fingerprint(record))
        log = CONTRACT.EvidenceLog("incident-1", [-125, 32, -114, 42],
                                   official_policies=official_policies(CONTRACT))
        accepted = log.append(record, verification=verification)
        self.assertEqual(accepted["acceptance"]["method"], "official_policy")
        snap = log.snapshot("2026-10-10T09:15:00Z")
        synopsis = dispatcher_synopsis(snap)
        self.assertEqual(synopsis["hazards"][0]["source_url"], ACTUAL_NWS)
        self.assertEqual(synopsis["hazards"][0]["location_label"], "Example area")
        self.assertEqual(synopsis["hazards"][0]["effective_at"],
                         "2026-10-10T09:01:00Z")
        self.assertTrue(all(v == "unknown" for v in
                            synopsis["operational_categories"].values()))
        self.assertFalse(synopsis["can_calculate_operational_outcomes"])
        with self.assertRaises(SourceError):
            dispatcher_synopsis({**snap, "cutoff_utc": "2026-10-10T10:00:00Z"})

    def test_usgs_point_depth_and_out_of_aoi_rejection(self):
        doc = document("usgs", [usgs()], USGS)
        context = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-160, 50, -140, 70), True)
        record, verification = build_official_record(
            doc, "aka2026uboihn", context, contract=CONTRACT)
        self.assertEqual(record["geometry"]["coordinates"], [-151.317, 62.569])
        self.assertEqual(record["payload"]["depth_km"], 90.7)
        self.assertEqual(record["observed_at"], "2026-10-10T09:04:23.446Z")
        log = CONTRACT.EvidenceLog("incident-2", [-160, 50, -140, 70],
                                   official_policies=official_policies(CONTRACT))
        self.assertEqual(log.append(record, verification=verification)
                         ["acceptance"]["method"], "official_policy")
        snapshot = log.snapshot("2026-10-10T09:15:00Z",
            source_health={"usgs":{"status":"alive",
                                   "source_time":"2026-10-10T09:13:00Z"}})
        synopsis = dispatcher_synopsis(snapshot)
        hazard = synopsis["hazards"][0]
        self.assertEqual(hazard["geometry"]["coordinates"], [-151.317, 62.569])
        self.assertEqual(hazard["location_label"], "Example")
        self.assertEqual(hazard["magnitude"], 2.4)
        self.assertEqual(hazard["depth_km"], 90.7)
        hazard["geometry"]["coordinates"][0] = 0
        synopsis["source_health"]["usgs"]["status"] = "failure"
        self.assertEqual(snapshot["categories"]["hazard"][0]
                         ["geometry"]["coordinates"][0], -151.317)
        self.assertEqual(snapshot["source_health"]["usgs"]["status"], "alive")
        self.assertEqual(dispatcher_synopsis(snapshot)["hazards"][0]
                         ["geometry"]["coordinates"][0], -151.317)
        wrong = IngestionContext(context.accepted_at, context.first_seen_at,
                                 (-125, 32, -114, 42), True)
        with self.assertRaises(SourceError):
            build_official_record(doc, "aka2026uboihn", wrong, contract=CONTRACT)

    def test_nws_correction_must_reference_prior_provider_id(self):
        first_doc = document("nws", [nws()], ACTUAL_NWS)
        first_ctx = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-125, 32, -114, 42), True)
        first, first_verification = build_official_record(
            first_doc, "urn:oid:alert-1", first_ctx, contract=CONTRACT)
        ref = {"identifier": "urn:oid:alert-1", "sender": "nws@example.gov",
               "sent": "2026-10-10T02:00:00-07:00",
               "@id": "https://api.weather.gov/alerts/urn:oid:alert-1"}
        second_feature = nws(
            id="https://api.weather.gov/alerts/urn:oid:alert-2",
            properties={"id": "urn:oid:alert-2", "messageType": "Update",
                        "references": [ref]})
        second_doc = document("nws", [second_feature], ACTUAL_NWS,
                              "2026-10-10T09:15:00Z")
        second_ctx = IngestionContext("2026-10-10T09:16:00Z",
            "2026-10-10T09:15:00Z", (-125, 32, -114, 42), True,
            canonical_item_id="urn:oid:alert-1", previous_revision=1,
            previous_provider_item_id="urn:oid:alert-1")
        second, second_verification = build_official_record(
            second_doc, "urn:oid:alert-2", second_ctx, contract=CONTRACT)
        self.assertEqual(second["supersedes"], ["nws", "urn:oid:alert-1", 1])
        self.assertEqual(second["correction_available_at"],
                         "2026-10-10T09:15:00Z")
        log = CONTRACT.EvidenceLog("incident-3", [-125, 32, -114, 42],
                                   official_policies=official_policies(CONTRACT))
        log.append(first, verification=first_verification)
        log.append(second, verification=second_verification)
        snap = log.snapshot("2026-10-10T09:17:00Z")
        self.assertEqual(snap["categories"]["hazard"][0]["revision"], 2)
        bad = nws(
            id="https://api.weather.gov/alerts/urn:oid:alert-2",
            properties={"id": "urn:oid:alert-2", "messageType": "Update",
                        "references": [{**ref, "identifier": "unrelated"}]})
        with self.assertRaises(SourceError):
            build_official_record(
                document("nws", [bad], ACTUAL_NWS, "2026-10-10T09:15:00Z"),
                "urn:oid:alert-2", second_ctx, contract=CONTRACT)

    def test_nws_area_only_cross_state_zones_are_explicit(self):
        feature = nws(properties={"areaDesc":"Mixed area",
                  "geocode":{"UGC":["CAZ001","AZZ001"]}})
        doc = document("nws", [feature], ACTUAL_NWS)
        context = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-125, 32, -114, 42), True)
        record, verification = build_official_record(
            doc, "urn:oid:alert-1", context, contract=CONTRACT)
        self.assertIsNone(record["geometry"])
        self.assertIn("AZ", record["source_uncertainty"])
        log = CONTRACT.EvidenceLog("incident-4", [-125, 32, -114, 42],
                                   official_policies=official_policies(CONTRACT))
        log.append(record, verification=verification)
        hazard = dispatcher_synopsis(log.snapshot("2026-10-10T09:15:00Z"))["hazards"][0]
        self.assertEqual(hazard["source_zone_prefixes"], ["AZ", "CA"])

    def test_nws_area_only_query_shape_preserves_cross_state_warning(self):
        feature = nws(properties={"geocode": {"UGC": ["CAZ001", "AZZ001"]}})
        context = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-125, 32, -114, 42), True)
        for url in (ACTUAL_NWS, NWS):
            with self.subTest(url=url):
                record, _ = build_official_record(
                    document("nws", [feature], url), "urn:oid:alert-1",
                    context, contract=CONTRACT)
                self.assertIn("AZ outside queried CA area",
                              record["source_uncertainty"])

    def test_unverified_transport_and_mismatched_bytes_fail(self):
        doc = document("usgs", [usgs()], USGS)
        context = IngestionContext("2026-10-10T09:14:00Z",
            "2026-10-10T09:12:00Z", (-160, 50, -140, 70), False)
        with self.assertRaises(SourceError):
            build_official_record(doc, "aka2026uboihn", context, contract=CONTRACT)
        tampered = RawDocument(doc.source_id, doc.request_url, doc.final_url,
                               doc.status, doc.headers, doc.fetched_at,
                               doc.raw + b" ", doc.sha256)
        context = IngestionContext(context.accepted_at, context.first_seen_at,
                                   context.bbox_lonlat, True)
        with self.assertRaises(SourceError):
            build_official_record(tampered, "aka2026uboihn", context,
                                  contract=CONTRACT)


if __name__ == "__main__":
    unittest.main()
