import unittest
from urllib.parse import urlencode

from contracts.incident import EvidenceLog, VerifiedSource, record_fingerprint
from services.hazards.wildfire.tests.test_wfigs import IRWIN, point_bodies, raw
from services.hazards.wildfire.wfigs import reported_record_proposal

BASE = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)
FIELDS = (
    "OBJECTID,GlobalID,IrwinID,IncidentName,IncidentTypeCategory,"
    "FireDiscoveryDateTime,ModifiedOnDateTime_dt,IncidentSize,PercentContained,"
    "FireOutDateTime,InitialLatitude,InitialLongitude"
)
IDS_URL = BASE + "?" + urlencode({
    "f": "json", "where": "IrwinID='" + IRWIN + "'",
    "returnIdsOnly": "true",
})
FEATURE_URL = BASE + "?" + urlencode({
    "f": "json", "where": "IrwinID='" + IRWIN + "'",
    "outFields": FIELDS, "returnGeometry": "true", "outSR": "4326",
    "orderByFields": "OBJECTID ASC", "resultRecordCount": "10",
})
FIRST = "2026-10-10T17:18:00Z"
FETCHED = "2026-10-10T17:18:10Z"
PROPOSED = "2026-10-10T18:00:00Z"


def draft(ids_url=IDS_URL, feature_url=FEATURE_URL, first=FIRST, fetched=FETCHED,
          proposed=PROPOSED):
    ids, features = point_bodies()
    return reported_record_proposal(
        raw(ids), raw(features), IRWIN, ids_query_url=ids_url,
        feature_query_url=feature_url, first_seen_at_utc=first,
        fetched_at_utc=fetched, proposed_acceptance_at_utc=proposed)


class WfigsRecordDraftTests(unittest.TestCase):
    def test_draft_is_reported_and_has_no_observation_or_operational_claim(self):
        record = draft()
        self.assertEqual("reported", record["source_kind"])
        self.assertEqual("official_api", record["source_type"])
        self.assertEqual("hazard", record["category"])
        self.assertIsNone(record["observed_at"])
        self.assertIsNone(record["published_at"])
        self.assertEqual(FEATURE_URL, record["source_url"])
        self.assertEqual([ -119.61618, 37.566205],
                         record["geometry"]["coordinates"])
        self.assertEqual(6829, record["payload"]["size_acres"])
        self.assertEqual(61, record["payload"]["percent_contained"])
        self.assertNotIn("active", record["payload"])
        self.assertEqual("2026-10-10T00:30:56.730Z",
                         record["payload"]["source_modified_at"])

    def test_draft_cannot_enter_contract_without_human_review(self):
        record = draft()
        log = EvidenceLog("dome-fire", [-120, 37, -119, 38])
        verified = VerifiedSource(
            record["source_id"], record["source_url"], record["raw_sha256"],
            True, record_fingerprint(record))
        with self.assertRaisesRegex(ValueError, "human review"):
            log.append(record, verification=verified)
        self.assertIsNone(log.snapshot(PROPOSED)["categories"]["hazard"])

    def test_rejects_unbound_or_ambiguous_query_urls(self):
        for ids_url, feature_url in (
            (IDS_URL.replace("IrwinID", "IncidentName"), FEATURE_URL),
            (IDS_URL, FEATURE_URL + "&where=1%3D1"),
            (IDS_URL, FEATURE_URL.replace("services3.arcgis.com", "example.com")),
            (IDS_URL, FEATURE_URL.replace("resultRecordCount=10",
                                          "resultRecordCount=1000")),
            ("\n" + IDS_URL, FEATURE_URL),
            (IDS_URL, "\n" + FEATURE_URL),
            (IDS_URL, FEATURE_URL.replace("services3", "services\t3")),
        ):
            with self.subTest(ids_url=ids_url, feature_url=feature_url):
                with self.assertRaises(ValueError):
                    draft(ids_url=ids_url, feature_url=feature_url)

    def test_narrow_query_requires_exactly_one_feature(self):
        ids, features = point_bodies()
        ids["objectIds"].append(8)
        extra = {
            "attributes": dict(features["features"][0]["attributes"]),
            "geometry": dict(features["features"][0]["geometry"]),
        }
        extra["attributes"]["OBJECTID"] = 8
        extra["attributes"]["IrwinID"] = "{00000000-0000-0000-0000-000000000000}"
        features["features"].append(extra)
        with self.assertRaises(ValueError):
            reported_record_proposal(
                raw(ids), raw(features), IRWIN, ids_query_url=IDS_URL,
                feature_query_url=FEATURE_URL, first_seen_at_utc=FIRST,
                fetched_at_utc=FETCHED, proposed_acceptance_at_utc=PROPOSED)

    def test_rejects_bad_trusted_time_order(self):
        with self.assertRaises(ValueError):
            draft(first="2026-10-10T17:18:11Z")
        with self.assertRaises(ValueError):
            draft(proposed="2026-10-10T17:18:09Z")


if __name__ == "__main__":
    unittest.main()
