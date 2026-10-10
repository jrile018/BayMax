import importlib
import unittest
from test_adapter import config


def api():return importlib.import_module("services.hazards.wildfire.adapter")


class ReviewRegressions(unittest.TestCase):
    def test_grid_times_frames_budget_is_bounded(self):
        c=config(); n=129
        c["grid"]["fuel_model"]=[[101]*n for _ in range(n)]
        c["grid"]["slope_rise_run"]=[[0]*n for _ in range(n)]
        c["grid"]["aspect_deg"]=[[0]*n for _ in range(n)]
        c["output_step_s"]=60; c["training_assumptions"]["base_rate_m_s"]=50
        with self.assertRaisesRegex(ValueError,"frame.*cell|cell.*frame"):
            api().simulate(c)

    def test_decimal_steps_are_unique_and_inside_horizon(self):
        c=config(); c["horizon_s"]=.07; c["output_step_s"]=.01
        times=[f["time_s"] for f in api().simulate(c)["frames"]]
        self.assertEqual(.07,times[-1])
        self.assertTrue(all(t<=.07 for t in times))
        self.assertTrue(all(b>a for a,b in zip(times,times[1:])))

    def test_extreme_time_ratio_raises_value_error(self):
        c=config(); c["output_step_s"]=5e-324
        with self.assertRaises(ValueError):api().simulate(c)

    def test_extreme_horizon_raises_value_error(self):
        c=config(); c["horizon_s"]=1e308; c["output_step_s"]=1e308
        c["ignitions"][0]["time_s"]=1e307
        with self.assertRaises(ValueError):api().simulate(c)

    def test_wind_conversion_rejects_infinite_intermediate(self):
        with self.assertRaises(ValueError):api().wind_to_pyre(1e308,1e308)


if __name__=="__main__":unittest.main()
