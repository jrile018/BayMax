import json
import tempfile
import unittest
from pathlib import Path
from services.dashboard_api.replay import ReplayStore, frame_hash

class ReplayStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.area = {"area_id":"test", "label":"Test area", "bbox_lonlat":[-122,39,-121,40], "coverage":[{"layer":"roads","status":"available"}]}
        (self.root/'area.json').write_text(json.dumps(self.area))
        self.frames = [{"run_id":"run", "scenario_id":"scenario", "snapshot_version":1, "index":0, "time_s":0, "mode":"mock-replay", "vehicles":[{"vehicle_id":"v", "position_lonlat":[-121.5,39.5]}]}, {"run_id":"run", "scenario_id":"scenario", "snapshot_version":2, "index":1, "time_s":30, "mode":"mock-replay", "vehicles":[{"vehicle_id":"v", "position_lonlat":[-121.4,39.5]}]}]
        for f in self.frames: f['snapshot_hash'] = frame_hash(f)
        self.replay = {"mode":"mock-replay", "label":"Hand-authored training replay", "description":"No route solver or physical fire", "frames":self.frames}
        self.path=self.root/'replay.json'
        self.write()
    def tearDown(self): self.tmp.cleanup()
    def write(self): self.path.write_text(json.dumps(self.replay))
    def store(self): return ReplayStore(self.root/'area.json', self.path)
    def test_frame_is_recorded_without_mutation(self):
        s=self.store();f=s.frame(1)
        self.assertEqual(f['vehicles'][0]['position_lonlat'],[-121.4,39.5])
        f['vehicles'][0]['position_lonlat'][0]=0
        self.assertEqual(s.frame(1),self.frames[1])
        self.assertEqual(s.bootstrap()['replay']['frame_times_s'],[0,30])
    def test_index_bounds(self):
        s=self.store()
        for i in [-1,2,1.5,True]:
            with self.subTest(i=i), self.assertRaises((ValueError,IndexError)): s.frame(i)
    def test_corrupt_hash_rejected(self):
        self.replay['frames'][1]['time_s']=35; self.write()
        with self.assertRaisesRegex(ValueError,'hash'): self.store()
    def test_non_monotonic_time_rejected(self):
        self.replay['frames'][1]['time_s']=-1
        self.replay['frames'][1]['snapshot_hash']=frame_hash(self.replay['frames'][1]);self.write()
        with self.assertRaisesRegex(ValueError,'time'):self.store()
    def test_cross_run_rejected(self):
        self.replay['frames'][1]['run_id']='different'
        self.replay['frames'][1]['snapshot_hash']=frame_hash(self.replay['frames'][1]);self.write()
        with self.assertRaisesRegex(ValueError,'identity'):self.store()
    def test_invalid_position_rejected(self):
        self.replay['frames'][1]['vehicles'][0]['position_lonlat']=[-121,float('nan')]
        with self.assertRaises((ValueError,TypeError)):frame_hash(self.replay['frames'][1])
    def test_global_coverage_honest(self):
        s=self.store()
        self.assertTrue(s.coverage(39.5,-121.5)['available'])
        self.assertFalse(s.coverage(51.5,-0.1)['available'])
        for lat,lon in [(91,0),(0,181),(float('nan'),0)]:
            with self.assertRaises(ValueError):s.coverage(lat,lon)

if __name__=='__main__': unittest.main()
