import json
import unittest
from pathlib import Path

class MockFixtureTests(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[3]/'fixtures/replay_ui/paradise_mock.json'
        self.frames=json.loads(path.read_text())['frames']
    def test_remaining_path_follows_committed_route(self):
        for frame in self.frames:
            for vehicle in frame['vehicles']:
                route=vehicle['route_geometry_lonlat'];remaining=vehicle['remaining_path_lonlat']
                if not route: continue
                self.assertIn(vehicle['position_lonlat'],route)
                index=route.index(vehicle['position_lonlat'])
                self.assertEqual(remaining,route[index:],(frame['index'],vehicle['vehicle_id']))
    def test_reroute_decision_preserves_position_and_load(self):
        for previous,current in zip(self.frames,self.frames[1:]):
            p=previous['vehicles'][0];c=current['vehicles'][0]
            if c['route_version']!=p['route_version']:
                event=next(e for e in current['events'] if e['type']=='reroute')
                self.assertEqual(event['time_s'],current['time_s'])
                self.assertEqual(p['position_lonlat'],c['position_lonlat'])
                self.assertEqual(p['load'],c['load'])
                self.assertEqual(p['completed_trail_lonlat'],c['completed_trail_lonlat'])
    def test_future_events_not_revealed(self):
        for f in self.frames:self.assertTrue(all(e['time_s']<=f['time_s'] for e in f['events']))

if __name__=='__main__':unittest.main()
