"""Dispatch checks independent of optional solver installation."""
import unittest
from unittest.mock import patch

from services.hazards.wildfire import adapter, physical
from services.hazards.wildfire.tests.test_adapter import config


def physical_config():
    c = config()
    c['engine'] = 'pyretechnics'
    c['physical_assumptions'] = {'surface_only': True, 'wind_height_m': 10,
                                'foliar_moisture': 1.0, 'residence_time_s': 30}
    return c


def result_for(c):
    arrivals = [[None] * 21 for _ in range(21)]
    arrivals[10][10] = 0.0
    arrivals[10][11] = 60.0
    provenance = {'model_name': 'Pyretechnics surface Rothermel level-set',
                  'model_version': '2026.8.10', 'physical_engine_implemented': True,
                  'source_ledger': c['source_ledger'], 'scenario_kind': 'hypothetical',
                  'current_incident': False}
    return arrivals, provenance


class PhysicalDispatchTests(unittest.TestCase):
    def test_exact_physical_result_uses_common_frames_and_intervals(self):
        c = physical_config()
        with patch.object(physical, 'physical_arrivals', return_value=result_for(c)) as run:
            out = adapter.simulate(c)
        run.assert_called_once_with(c, 21, 21)
        self.assertEqual('ok', out['status'])
        self.assertTrue(out['provenance']['physical_engine_implemented'])
        self.assertEqual(60, out['arrivals_s'][10][11])
        self.assertIn({'row': 10, 'col': 11, 'start_s': 60, 'end_s': 90},
                      out['active_flame_intervals'])
        self.assertEqual(3600, out['frames'][-1]['time_s'])

    def test_default_engine_dispatches_physical(self):
        c = physical_config()
        del c['engine']
        with patch.object(physical, 'physical_arrivals', return_value=result_for(c)) as run:
            out = adapter.simulate(c)
        self.assertTrue(run.called)
        self.assertEqual('ok', out['status'])

    def test_missing_engine_stays_unavailable_without_training_fallback(self):
        c = physical_config()
        with patch.object(physical, 'physical_arrivals', side_effect=physical.BackendUnavailable('exact pin missing')):
            with patch.object(adapter, '_training_arrivals', side_effect=AssertionError('fallback')):
                out = adapter.simulate(c)
        self.assertEqual('unavailable', out['status'])
        self.assertIn('exact pin missing', out['reason'])
        self.assertFalse(out['physical_engine_implemented'])

    def test_solver_failure_is_not_disguised_as_dependency_unavailability(self):
        with patch.object(physical, 'physical_arrivals', side_effect=RuntimeError('solver failure')):
            with self.assertRaisesRegex(RuntimeError, 'solver failure'):
                adapter.simulate(physical_config())


if __name__ == '__main__':
    unittest.main()
