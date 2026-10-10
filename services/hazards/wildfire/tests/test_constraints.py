import importlib
import unittest
from test_adapter import config


def api():
    return importlib.import_module("services.hazards.wildfire.adapter")


class ConstraintTests(unittest.TestCase):
    def test_uphill_north_is_faster_than_downhill(self):
        c=config()
        c["grid"]["slope_rise_run"]=[[.3]*21 for _ in range(21)]
        c["grid"]["aspect_deg"]=[[180]*21 for _ in range(21)]
        a=api().simulate(c)["arrivals_s"]
        self.assertLess(a[13][10], a[7][10])

    def test_moisture_at_extinction_stops_spread(self):
        c=config(); c["weather"]["moisture_dead_1hr"]=.4
        a=api().simulate(c)["arrivals_s"]
        self.assertEqual(1,sum(t is not None for row in a for t in row))

    def test_diagonal_cannot_jump_blocked_corner(self):
        c=config()
        c["grid"]["fuel_model"]=[[91]*21 for _ in range(21)]
        c["grid"]["fuel_model"][10][10]=101
        c["grid"]["fuel_model"][11][11]=101
        a=api().simulate(c)["arrivals_s"]
        self.assertIsNone(a[11][11])

    def test_unburnable_ignition_rejected(self):
        c=config(); c["grid"]["fuel_model"][10][10]=98
        with self.assertRaises(ValueError): api().simulate(c)

    def test_negative_or_nonfinite_fields_rejected(self):
        for field,value in (("horizon_s",-1),("output_step_s",0),("horizon_s",float("nan"))):
            c=config(); c[field]=value
            with self.subTest(field=field,value=value):
                with self.assertRaises(ValueError):api().simulate(c)

    def test_current_claim_cannot_be_assigned_to_synthetic_grid(self):
        c=config(); c["scenario_kind"]="current"
        with self.assertRaises(ValueError):api().simulate(c)

    def test_input_not_mutated(self):
        c=config(); import copy; before=copy.deepcopy(c)
        api().simulate(c)
        self.assertEqual(before,c)

    def test_output_step_only_changes_frames(self):
        a,b=config(),config(); b["output_step_s"]=90
        self.assertEqual(api().simulate(a)["arrivals_s"],api().simulate(b)["arrivals_s"])

    def test_unknown_source_date_rejected(self):
        c=config(); c["source_ledger"][0]["retrieved_at_utc"]=None
        with self.assertRaises(ValueError):api().simulate(c)

    def test_no_incident_evidence_abstains(self):
        r=api().current_incident_eligibility([],"2026-10-10T00:00:00Z",[-82.3,29.6])
        self.assertEqual("unavailable",r["status"])

    def test_future_and_stale_incident_evidence_abstains(self):
        for date in ("2026-10-11T00:00:00Z","2026-10-08T00:00:00Z"):
            r=api().current_incident_eligibility([{
              "incident_id":"x","review_status":"accepted",
              "incident_status":"confirmed_active_wildfire",
              "observed_at_utc":date,"source_uri":"https://example.org/incident",
              "bbox_lonlat":[-83,29,-82,30]}],"2026-10-10T00:00:00Z",[-82.3,29.6])
            self.assertEqual("unavailable",r["status"])


if __name__=="__main__":unittest.main()
