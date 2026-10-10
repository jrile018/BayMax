import unittest
from pathlib import Path
from services.dashboard_api.replay import ReplayStore
from services.dashboard_api.export_preview import render_preview

class PreviewTests(unittest.TestCase):
    def test_export_embeds_exact_recorded_snapshots_without_external_assets(self):
        root=Path(__file__).resolve().parents[3]
        store=ReplayStore(root/'fixtures/geography/paradise/area.json',root/'fixtures/replay_ui/paradise_mock.json')
        html=render_preview(store,root/'web')
        self.assertIn('Saved mock replay',html)
        self.assertNotIn('href="./style.css"',html);self.assertNotIn('src="./app.js"',html)
        for i in range(store.bootstrap()['replay']['frame_count']):self.assertIn(store.frame(i)['snapshot_hash'],html)
        self.assertIn('CONSTRUCTED TRAINING REPLAY',html)
    def test_recorded_replay_banner_is_not_mislabeled_mock(self):
        class Store:
            def bootstrap(self):return {'mode':'recorded-replay','area':{},'replay':{'frame_count':1}}
            def frame(self,i):return {'snapshot_hash':'test'}
        root=Path(__file__).resolve().parents[3]
        html=render_preview(Store(),root/'web')
        self.assertIn('Saved recorded replay',html)
        self.assertNotIn('Saved mock replay',html)
    def test_untrusted_record_json_cannot_end_script(self):
        class Store:
            def bootstrap(self):return {'area':{},'replay':{'frame_count':1},'label':'</script><script>injection()'}
            def frame(self,i):return {'snapshot_hash':'test'}
        root=Path(__file__).resolve().parents[3]
        html=render_preview(Store(),root/'web')
        self.assertNotIn('</script><script>injection()',html)

if __name__=='__main__':unittest.main()
