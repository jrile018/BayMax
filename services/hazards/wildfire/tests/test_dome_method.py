"""Dome research exercise: synthetic solver output cannot establish incident truth."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from services.hazards.wildfire.adapter import (
    current_incident_eligibility, simulate, validate_config,
)
from services.hazards.wildfire.physical import engine_available

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "fire" / "dome_method_hypothetical_v1.json"
IRWIN = "{AACFD673-4C1B-4CDF-B9DD-128E34BD7272}"
POINT = [-119.61617975318511, 37.56620512778412]


class DomeMethodExerciseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_inputs_are_unlocated_and_synthetic(self):
        config = self.fixture["config"]
        self.assertEqual("LOCAL_METRIC", config["grid"]["crs"])
        self.assertEqual([0, 0], config["grid"]["origin_m"])
        self.assertEqual("hypothetical", config["scenario_kind"])
        self.assertEqual("pyretechnics", config["engine"])
        self.assertEqual({"synthetic", "model_reference"},
                         {entry["kind"] for entry in config["source_ledger"]})
        self.assertFalse(self.fixture["edges"])
        validate_config(config)

    @unittest.skipUnless(engine_available(), "exact compiled Pyretechnics 2026.8.10 required")
    def test_solver_result_remains_hypothetical(self):
        result = simulate(self.fixture["config"])
        self.assertEqual("ok", result["status"])
        self.assertEqual("hypothetical", result["provenance"]["scenario_kind"])
        self.assertFalse(result["provenance"]["current_incident"])
        self.assertEqual("LOCAL_METRIC", result["grid"]["crs"])
        self.assertEqual(0, result["arrivals_s"][4][4])
        self.assertTrue(any(
            value is not None and value > 0
            for row in result["arrivals_s"] for value in row
        ))

    def test_wfigs_edit_and_fetch_cannot_substitute_for_observation(self):
        reported = {
            "incident_id": IRWIN,
            "review_status": "candidate_unreviewed",
            "incident_status": "reported_wildfire",
            "source_uri": "https://www.arcgis.com/home/item.html?id=4181a117dc9e43db8598533e29972015",
            "bbox_lonlat": [POINT[0], POINT[1], POINT[0], POINT[1]],
            "modified_at_utc": "2026-10-10T00:30:56.730Z",
            "fetched_at_utc": "2026-10-10T18:38:05Z",
            "observed_at_utc": None,
        }
        # The second form isolates the missing observation from status labels.
        # It is a test-only counterfactual, not an accepted Dome record.
        accepted_labels = copy.deepcopy(reported)
        accepted_labels["review_status"] = "accepted"
        accepted_labels["incident_status"] = "confirmed_active_wildfire"
        for record in (reported, accepted_labels):
            with self.subTest(review_status=record["review_status"]):
                gate = current_incident_eligibility(
                    [record], "2026-10-10T20:20:00Z", POINT
                )
                self.assertEqual("unavailable", gate["status"])
                self.assertFalse(gate["simulation_confirms_current_incident"])
                self.assertFalse(gate["evidence"])

    def test_real_incident_label_is_rejected(self):
        config = copy.deepcopy(self.fixture["config"])
        config["scenario_kind"] = "current_incident"
        with self.assertRaisesRegex(ValueError, "hypothetical"):
            simulate(config)


if __name__ == "__main__":
    unittest.main()
