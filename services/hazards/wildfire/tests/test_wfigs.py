import json
import unittest

from services.hazards.wildfire.wfigs import incident_candidate, perimeter_candidate

IRWIN = "{AACFD673-4C1B-4CDF-B9DD-128E34BD7272}"
FETCHED = "2026-10-10T17:18:10Z"


def raw(value):
    return json.dumps(value).encode("utf-8")


def point_bodies():
    ids = {"objectIdFieldName": "OBJECTID", "objectIds": [7]}
    attributes = {
        "OBJECTID": 7, "GlobalID": "a", "IrwinID": IRWIN,
        "IncidentName": "DOME", "IncidentTypeCategory": "WF",
        "FireDiscoveryDateTime": 1789486080000,
        "ModifiedOnDateTime_dt": 1791592256730,
        "IncidentSize": 6829, "PercentContained": 61,
        "FireOutDateTime": None,
        "InitialLatitude": 37.556325, "InitialLongitude": -119.614049,
    }
    features = {"spatialReference": {"wkid": 4326},
                "features": [{"attributes": attributes,
                              "geometry": {"x": -119.61618, "y": 37.566205}}]}
    return ids, features


def perimeter_bodies():
    ids = {"objectIdFieldName": "OBJECTID", "objectIds": [9]}
    attributes = {
        "OBJECTID": 9, "GlobalID": "b",
        "attr_IrwinID": IRWIN, "poly_IRWINID": IRWIN,
        "poly_IncidentName": "Dome", "poly_MapMethod": "Mixed Methods",
        "poly_PolygonDateTime": 1791430560000,
        "poly_DateCurrent": 1791633422000,
        "poly_GISAcres": 6801.9,
        "poly_FeatureAccess": "Public", "poly_FeatureStatus": "Approved",
        "poly_IsVisible": "Yes",
    }
    features = {"spatialReference": {"wkid": 4326},
                "features": [{"attributes": attributes,
                              "geometry": {"rings": [[[-119.6, 37.5], [-119.5, 37.5],
                                                     [-119.5, 37.6], [-119.6, 37.5]]]}}]}
    return ids, features


class WfigsCandidateTests(unittest.TestCase):
    def test_point_candidate_preserves_source_dates_and_unknowns(self):
        ids, features = point_bodies()
        row = incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        self.assertEqual("candidate_unreviewed", row["status"])
        self.assertEqual([-119.61618, 37.566205], row["point_lonlat"])
        self.assertEqual("2026-10-10T00:30:56.730Z", row["modified_at_utc"])
        self.assertEqual(61, row["percent_contained"])
        self.assertFalse(row["active_status_verified"])
        self.assertTrue(row["feature_reference_url"].endswith("/7"))
        self.assertNotIn("source_url", row)
        self.assertNotIn("perimeter", row)

    def test_point_null_quantities_stay_unknown(self):
        ids, features = point_bodies()
        a = features["features"][0]["attributes"]
        a["IncidentSize"] = None
        a["PercentContained"] = None
        row = incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        self.assertIsNone(row["size_acres"])
        self.assertIsNone(row["percent_contained"])

    def test_point_rejects_incomplete_or_duplicate_response(self):
        ids, features = point_bodies()
        ids["objectIds"] = [7, 8]
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        ids["objectIds"] = [7]
        features["features"].append(features["features"][0])
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        features["features"] = features["features"][:1]
        features["exceededTransferLimit"] = True
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_point_rejects_duplicate_keys_and_nonfinite_constants(self):
        ids, features = point_bodies()
        with self.assertRaises(ValueError):
            incident_candidate(b'{"objectIds":[7],"objectIds":[8]}',
                               raw(features), IRWIN, FETCHED)
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids),
                               raw(features).replace(b'"GlobalID": "a"',
                                                     b'"GlobalID": NaN'),
                               IRWIN, FETCHED)
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids),
                               raw(features).replace(b'"GlobalID": "a"',
                                                     b'"GlobalID": 1e400'),
                               IRWIN, FETCHED)

    def test_point_rejects_malformed_spatial_reference(self):
        ids, features = point_bodies()
        features["spatialReference"] = None
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_point_rejects_future_edit_and_invalid_coordinates(self):
        ids, features = point_bodies()
        features["features"][0]["attributes"]["ModifiedOnDateTime_dt"] = 1791653000000
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        features["features"][0]["attributes"]["ModifiedOnDateTime_dt"] = 1791592256730
        features["features"][0]["geometry"]["x"] = 999
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_point_rejects_fire_out_before_discovery(self):
        ids, features = point_bodies()
        features["features"][0]["attributes"]["FireOutDateTime"] = 0
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_point_rejects_malformed_fetch_timestamp(self):
        ids, features = point_bodies()
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, "2026-10-10Z")

    def test_point_rejects_oversized_json_integer(self):
        ids, features = point_bodies()
        features["features"][0]["geometry"]["x"] = 10 ** 400
        with self.assertRaises(ValueError):
            incident_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_perimeter_metadata_never_exposes_polygon(self):
        ids, features = perimeter_bodies()
        row = perimeter_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        self.assertEqual("2026-10-08T03:36:00Z", row["captured_at_utc"])
        self.assertEqual("2026-10-10T11:57:02Z", row["edited_at_utc"])
        self.assertEqual([-119.6, 37.5, -119.5, 37.6], row["bbox_lonlat"])
        self.assertTrue(row["public_approved_visible"])
        self.assertTrue(row["feature_reference_url"].endswith("/9"))
        self.assertNotIn("source_url", row)
        self.assertNotIn("rings", row)
        self.assertNotIn("geometry", row)

    def test_absent_perimeter_is_unknown_not_no_fire(self):
        row = perimeter_candidate(raw({"objectIds": []}),
                                  raw({"spatialReference": {"wkid": 4326}, "features": []}),
                                  IRWIN, FETCHED)
        self.assertEqual("perimeter_unavailable", row["status"])

    def test_perimeter_rejects_wrong_relation_or_stale_capture_confusion(self):
        ids, features = perimeter_bodies()
        a = features["features"][0]["attributes"]
        a["poly_IRWINID"] = "{00000000-0000-0000-0000-000000000000}"
        with self.assertRaises(ValueError):
            perimeter_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        a["poly_IRWINID"] = IRWIN
        a["poly_FeatureStatus"] = "Proposed"
        with self.assertRaises(ValueError):
            perimeter_candidate(raw(ids), raw(features), IRWIN, FETCHED)

    def test_perimeter_rejects_open_or_nonfinite_ring(self):
        ids, features = perimeter_bodies()
        ring = features["features"][0]["geometry"]["rings"][0]
        ring.pop()
        with self.assertRaises(ValueError):
            perimeter_candidate(raw(ids), raw(features), IRWIN, FETCHED)
        ring.append(ring[0])
        ring[1][0] = float("nan")
        with self.assertRaises(ValueError):
            perimeter_candidate(raw(ids), raw(features), IRWIN, FETCHED)


if __name__ == "__main__":
    unittest.main()
