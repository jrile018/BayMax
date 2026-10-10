import importlib
import json
import math
import unittest


def api():
    return importlib.import_module("services.hazards.wildfire.adapter")


def config():
    n = 21
    zero = [[0] * n for _ in range(n)]
    return {
        "scenario_id": "test", "scenario_kind": "hypothetical",
        "epoch_utc": "2026-10-10T00:00:00Z", "seed": 7,
        "engine": "training-grid",
        "training_assumptions": {"base_rate_m_s": .08,
                                 "wind_gain_per_m_s": .15,
                                 "slope_gain": 3.0,
                                 "moisture_extinction": .4,
                                 "residence_time_s": 120},
        "grid": {"crs": "LOCAL_METRIC", "origin_m": [0, 0],
                 "cell_size_m": 10, "fuel_model": [[101] * n for _ in range(n)],
                 "slope_rise_run": [r[:] for r in zero],
                 "aspect_deg": [r[:] for r in zero]},
        "weather": {"wind_east_m_s": 0, "wind_north_m_s": 0,
                    "moisture_dead_1hr": .05, "moisture_dead_10hr": .10,
                    "moisture_dead_100hr": .15,
                    "moisture_live_herbaceous": .9,
                    "moisture_live_woody": .6},
        "ignitions": [{"row": 10, "col": 10, "time_s": 0}],
        "horizon_s": 3600, "output_step_s": 300,
        "source_ledger": [{"source_id": "synthetic", "kind": "synthetic",
                           "license": "CC0-1.0", "uri": None,
                           "observed_at_utc": None,
                           "retrieved_at_utc": "2026-10-10T00:00:00Z"}],
    }


class SimulationTests(unittest.TestCase):
    def test_result_metadata_and_initial_ignition(self):
        c = config()
        result = api().simulate(c)
        self.assertEqual("ok", result["status"])
        self.assertEqual(3600, result["horizon_s"])
        grid = result["grid"]
        for key, expected in {"crs": "LOCAL_METRIC", "origin_m": [0, 0],
                              "cell_size_m": 10, "height": 21,
                              "width": 21}.items():
            self.assertEqual(expected, grid[key])
        a = result["arrivals_s"]
        self.assertEqual(21, len(a))
        self.assertTrue(all(len(row) == 21 for row in a))
        self.assertEqual(0, a[10][10])
        self.assertTrue(all(t is None or
                            (isinstance(t, (int, float)) and math.isfinite(t)
                             and 0 <= t <= 3600) for row in a for t in row))
        p = result["provenance"]
        for key, expected in {
            "model_name": "Simplified deterministic training grid",
            "model_version": "1", "physical_engine_implemented": False, "scenario_kind": "hypothetical",
            "current_incident": False, "source_ledger": c["source_ledger"],
            "seed": 7,
        }.items():
            self.assertEqual(expected, p[key])

    def test_default_physical_engine_is_explicitly_unavailable(self):
        c = config()
        del c["engine"]
        del c["training_assumptions"]
        result = api().simulate(c)
        self.assertEqual("unavailable", result["status"])
        self.assertTrue(result.get("reason"))

    def test_frames_and_intervals(self):
        r = api().simulate(config())
        frames = r["frames"]
        self.assertEqual(0, frames[0]["time_s"])
        self.assertEqual(3600, frames[-1]["time_s"])
        self.assertEqual(sorted(set(f["time_s"] for f in frames)),
                         [f["time_s"] for f in frames])
        old = set()
        for frame in frames:
            cells = {tuple(cell) for cell in frame["burned_cells"]}
            self.assertTrue(old <= cells)
            self.assertTrue(all(r["arrivals_s"][y][x] is not None and
                                r["arrivals_s"][y][x] <= frame["time_s"]
                                for y, x in cells))
            old = cells
        self.assertTrue(any(i["row"] == 10 and i["col"] == 10 and
                            i["start_s"] == 0 for i in r["burn_intervals"]))
        for i in r["burn_intervals"]:
            self.assertEqual(r["arrivals_s"][i["row"]][i["col"]], i["start_s"])
            self.assertEqual(3600, i["end_s"])

    def test_deterministic(self):
        c = config()
        self.assertEqual(json.dumps(api().simulate(c), sort_keys=True,
                                    allow_nan=False),
                         json.dumps(api().simulate(c), sort_keys=True,
                                    allow_nan=False))

    def test_calm_wind_cardinal_symmetry(self):
        a = api().simulate(config())["arrivals_s"]
        values = [a[9][10], a[11][10], a[10][9], a[10][11]]
        self.assertTrue(all(v is not None for v in values))
        self.assertLessEqual(max(values) - min(values), 600)

    def test_east_wind_favors_east(self):
        c = config()
        c["weather"]["wind_east_m_s"] = 8
        a = api().simulate(c)["arrivals_s"]
        self.assertIsNotNone(a[10][13])
        self.assertTrue(a[10][7] is None or a[10][13] < a[10][7])

    def test_nonburnable_column_blocks_spread(self):
        c = config()
        for row in c["grid"]["fuel_model"]:
            row[10] = 91
        c["ignitions"] = [{"row": 10, "col": 5, "time_s": 0}]
        a = api().simulate(c)["arrivals_s"]
        self.assertEqual(0, a[10][5])
        self.assertTrue(all(a[y][x] is None for y in range(21)
                            for x in range(10, 21)))

    def test_higher_moisture_slows_spread(self):
        dry, wet = config(), config()
        for key, value in {"moisture_dead_1hr": .30,
                           "moisture_dead_10hr": .35,
                           "moisture_dead_100hr": .40}.items():
            wet["weather"][key] = value
        da = api().simulate(dry)["arrivals_s"]
        wa = api().simulate(wet)["arrivals_s"]
        self.assertGreater(sum(t is not None for row in da for t in row),
                           sum(t is not None for row in wa for t in row))

    def test_nondivisible_horizon_has_final_frame(self):
        c = config()
        c["horizon_s"] = 3550
        self.assertEqual(3550, api().simulate(c)["frames"][-1]["time_s"])

    def test_invalid_inputs_raise_value_error(self):
        bad_fuel, bad_moisture, ragged = config(), config(), config()
        bad_fuel["grid"]["fuel_model"][0][0] = 9999
        bad_moisture["weather"]["moisture_dead_1hr"] = -.01
        ragged["grid"]["aspect_deg"][0].pop()
        for c in (bad_fuel, bad_moisture, ragged):
            with self.subTest(case=c):
                with self.assertRaises(ValueError):
                    api().simulate(c)


class WindTests(unittest.TestCase):
    def test_wind_speed_and_from_direction(self):
        for east, north, direction in ((0, -1, 0), (-1, 0, 90),
                                       (0, 1, 180), (1, 0, 270)):
            with self.subTest(east=east, north=north):
                speed, degrees = api().wind_to_pyre(east, north)
                self.assertAlmostEqual(3.6, speed)
                self.assertAlmostEqual(direction, degrees % 360)

    def test_calm_wind(self):
        speed, degrees = api().wind_to_pyre(0, 0)
        self.assertEqual(0, speed)
        self.assertTrue(math.isfinite(degrees))


class EdgeAccessTests(unittest.TestCase):
    def hazard(self):
        return {"grid": {"crs": "LOCAL_METRIC", "origin_m": [0, 0],
                         "cell_size_m": 10, "width": 2, "height": 2},
                "arrivals_s": [[None, 10], [None, None]], "horizon_s": 100,
                "provenance": {"source_ledger": [{"source_id": "synthetic"}]}}

    def edge(self, points):
        return [{"edge_id": "e", "geometry_m": points}]

    def test_crossing_edge_closure_and_provenance(self):
        rows = api().edge_access(self.hazard(),
                                 self.edge([[0, 5], [20, 5]]), 3)
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("e", row["edge_id"])
        self.assertEqual("forecast", row["status"])
        self.assertEqual([{"start_s": 10, "end_s": 100}],
                         row["closed_intervals"])
        self.assertEqual(3, row["issued_time_s"])
        self.assertIn("synthetic", row["source_ids"])

    def test_safety_buffer_moves_closure_earlier(self):
        row = api().edge_access(self.hazard(),
                                self.edge([[0, 5], [20, 5]]), 0,
                                safety_buffer_s=5)[0]
        self.assertEqual([{"start_s": 5, "end_s": 100}],
                         row["closed_intervals"])

    def test_outside_domain_is_unknown(self):
        row = api().edge_access(self.hazard(),
                                self.edge([[-5, 5], [5, 5]]), 0)[0]
        self.assertEqual("unknown", row["status"])

    def test_boundary_touch_closes_conservatively(self):
        row = api().edge_access(self.hazard(),
                                self.edge([[0, 10], [10, 10]]), 0)[0]
        self.assertIn({"start_s": 10, "end_s": 100},
                      row["closed_intervals"])

    def test_null_arrival_has_no_closure(self):
        row = api().edge_access(self.hazard(),
                                self.edge([[1, 1], [2, 2]]), 0)[0]
        self.assertEqual([], row["closed_intervals"])


if __name__ == "__main__":
    unittest.main()
