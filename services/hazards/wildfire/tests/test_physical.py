"""Focused contract and solver tests for the pinned physical wildfire backend."""
import copy
import math
import struct
import unittest
from unittest.mock import patch

from services.hazards.wildfire.physical import (
    BackendUnavailable, physical_arrivals, engine_available, _arrival_seconds,
)


def scenario(size=21):
    return {
        'scenario_id': 'synthetic-physical', 'scenario_kind': 'hypothetical',
        'epoch_utc': '2026-01-01T00:00:00Z', 'seed': 7,
        'grid': {'crs': 'LOCAL_METRIC', 'origin_m': [0, 0], 'cell_size_m': 10,
                 'fuel_model': [[101] * size for _ in range(size)],
                 'slope_rise_run': [[0] * size for _ in range(size)],
                 'aspect_deg': [[0] * size for _ in range(size)]},
        'weather': {'wind_east_m_s': 0, 'wind_north_m_s': 0,
                    'moisture_dead_1hr': 0.03, 'moisture_dead_10hr': 0.04,
                    'moisture_dead_100hr': 0.05,
                    'moisture_live_herbaceous': 0.5, 'moisture_live_woody': 0.6},
        'ignitions': [{'row': size // 2, 'col': size // 2, 'time_s': 0}],
        'horizon_s': 1800, 'output_step_s': 60,
        'source_ledger': [{'source_id': 'synthetic-grid', 'kind': 'synthetic',
                           'license': 'synthetic', 'retrieved_at_utc': '2026-01-01T00:00:00Z'}],
        'physical_assumptions': {'surface_only': True, 'wind_height_m': 10,
                                 'foliar_moisture': 1.0, 'residence_time_s': 60},
    }


class PhysicalContractTests(unittest.TestCase):
    def test_requires_explicit_supported_assumptions(self):
        base = scenario()
        variants = [dict(base, physical_assumptions={}),
                    dict(base, physical_assumptions=dict(base['physical_assumptions'], surface_only=False)),
                    dict(base, physical_assumptions=dict(base['physical_assumptions'], wind_height_m=2)),
                    dict(base, physical_assumptions=dict(base['physical_assumptions'], foliar_moisture=float('nan'))),
                    dict(base, physical_assumptions=dict(base['physical_assumptions'], residence_time_s=0))]
        for config in variants:
            with self.subTest(assumptions=config['physical_assumptions']):
                with self.assertRaises(ValueError):
                    physical_arrivals(config, 21, 21)

    def test_future_ignitions_fail_closed(self):
        config = scenario()
        config['ignitions'][0]['time_s'] = 10
        with self.assertRaises(ValueError):
            physical_arrivals(config, 21, 21)

    def test_wrong_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            physical_arrivals(scenario(), 21, 20)

    def test_missing_engine_is_explicit(self):
        if engine_available():
            self.skipTest('exact compiled engine installed')
        with self.assertRaises(BackendUnavailable):
            physical_arrivals(scenario(), 21, 21)

    def test_wrong_engine_version_is_explicit(self):
        with patch('services.hazards.wildfire.physical.importlib.metadata.version', return_value='0.0'):
            with self.assertRaisesRegex(BackendUnavailable, '2026.8.10 required'):
                physical_arrivals(scenario(), 21, 21)

    def test_direct_call_honors_physical_bounds(self):
        config = scenario()
        config['horizon_s'] = 604801
        with self.assertRaises(ValueError):
            physical_arrivals(config, 21, 21)
        with self.assertRaises(ValueError):
            physical_arrivals(scenario(), 1000, 1000)

    def test_float32_cube_range_is_validated_before_engine_import(self):
        for field, value in [('wind_east_m_s', 1e39), ('wind_east_m_s', 1e-50),
                             ('moisture_dead_1hr', 1e39), ('moisture_dead_1hr', 1e-50)]:
            config = scenario()
            config['weather'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                physical_arrivals(config, 21, 21)
        config = scenario()
        config['grid']['slope_rise_run'][0][0] = 1e39
        with self.assertRaises(ValueError):
            physical_arrivals(config, 21, 21)
        config = scenario()
        config['weather']['wind_east_m_s'] = 1e38  # component fits; km/h does not
        with self.assertRaises(ValueError):
            physical_arrivals(config, 21, 21)

    def test_near_horizon_float32_arrival_is_conservative(self):
        horizon_s = 604800.0
        exact_minutes = horizon_s / 60
        raw = struct.unpack('f', struct.pack('f', exact_minutes))[0]
        arrival = _arrival_seconds(raw, horizon_s)
        self.assertIsNotNone(arrival)
        self.assertLess(arrival, horizon_s)
        self.assertGreater(arrival, horizon_s - 1)
        with self.assertRaises(ValueError):
            _arrival_seconds(math.inf, horizon_s)
        with self.assertRaises(ValueError):
            _arrival_seconds(raw + 10, horizon_s)


@unittest.skipUnless(engine_available(), 'exact compiled Pyretechnics 2026.8.10 required')
class PhysicalSolverTests(unittest.TestCase):
    def test_ignition_grows_and_returns_seconds(self):
        config = scenario()
        arrivals, provenance = physical_arrivals(config, 21, 21)
        self.assertEqual(0, arrivals[10][10])
        spread = [a for row in arrivals for a in row if a is not None and a > 0]
        self.assertTrue(spread, 'physical fire must grow from ignition')
        self.assertGreater(min(spread), 30, 'arrival times must be seconds, not raw solver minutes')
        self.assertTrue(all(a <= 1800 for a in spread))
        self.assertTrue(provenance['physical_engine_implemented'])
        self.assertEqual('2026.8.10', provenance['model_version'])

    def test_wind_direction_changes_arrival(self):
        east = scenario()
        east['weather']['wind_east_m_s'] = 8
        west = copy.deepcopy(east)
        west['weather']['wind_east_m_s'] = -8
        a, _ = physical_arrivals(east, 21, 21)
        b, _ = physical_arrivals(west, 21, 21)
        self.assertIsNotNone(a[10][13])
        self.assertIsNotNone(b[10][7])
        self.assertTrue(a[10][7] is None or a[10][13] < a[10][7])
        self.assertTrue(b[10][13] is None or b[10][7] < b[10][13])

    def test_nonburnable_barrier_and_step_independence(self):
        config = scenario()
        for row in config['grid']['fuel_model']:
            row[11] = 91
        a, _ = physical_arrivals(config, 21, 21)
        self.assertTrue(all(row[11] is None for row in a))
        self.assertTrue(all(row[x] is None for row in a for x in range(12, 21)))
        config['output_step_s'] = 15
        b, _ = physical_arrivals(config, 21, 21)
        self.assertEqual(a, b)

    def test_repeat_is_deterministic(self):
        config = scenario()
        a, _ = physical_arrivals(config, 21, 21)
        b, _ = physical_arrivals(config, 21, 21)
        self.assertEqual(a, b)

    def test_north_and_south_wind_cardinals(self):
        north = scenario()
        north['weather']['wind_north_m_s'] = 8
        south = copy.deepcopy(north)
        south['weather']['wind_north_m_s'] = -8
        a, _ = physical_arrivals(north, 21, 21)
        b, _ = physical_arrivals(south, 21, 21)
        self.assertIsNotNone(a[13][10])
        self.assertIsNotNone(b[7][10])
        self.assertTrue(a[7][10] is None or a[13][10] < a[7][10])
        self.assertTrue(b[13][10] is None or b[7][10] < b[13][10])

    def test_uphill_spread_is_faster_than_downhill(self):
        config = scenario()
        config['grid']['slope_rise_run'] = [[0.4] * 21 for _ in range(21)]
        config['grid']['aspect_deg'] = [[180] * 21 for _ in range(21)]
        arrivals, _ = physical_arrivals(config, 21, 21)
        self.assertIsNotNone(arrivals[12][10])
        self.assertTrue(arrivals[8][10] is None or arrivals[12][10] < arrivals[8][10])

    def test_saturated_dead_fuel_does_not_spread(self):
        config = scenario()
        config['weather']['moisture_dead_1hr'] = 1.0
        config['weather']['moisture_dead_10hr'] = 1.0
        config['weather']['moisture_dead_100hr'] = 1.0
        arrivals, _ = physical_arrivals(config, 21, 21)
        self.assertEqual(0, arrivals[10][10])
        self.assertTrue(all(arrivals[y][x] is None for y in range(21) for x in range(21)
                            if (y, x) != (10, 10)))


if __name__ == '__main__':
    unittest.main()
