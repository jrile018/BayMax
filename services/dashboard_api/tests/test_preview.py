import unittest
import tempfile
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
        self.assertIn('window.KNIGHT_EARTH_TEXTURE="data:image/jpeg;base64,',html)
        self.assertIn('Earth globe and satellite imagery require an internet connection',html)
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

    def test_all_local_assets_are_embedded_in_script_order(self):
        class Store:
            def bootstrap(self):return {'mode':'mock-replay','replay':{'frame_count':1}}
            def frame(self,i):return {'snapshot_hash':'fixed'}
        with tempfile.TemporaryDirectory() as d:
            web=Path(d)
            (web/'index.html').write_text('<!doctype html><html><head><link rel="stylesheet" href="./other.css"><script src="./tools.js" defer></script><script src="./app.js" defer></script></head><body><main>Ready</main></body></html>')
            (web/'other.css').write_text('/* OTHER_STYLE */ body {color:red}')
            (web/'tools.js').write_text('/* TOOLS_FIRST */ window.tools=true;')
            (web/'app.js').write_text('/* APP_SECOND */ window.app=true;')
            html=render_preview(Store(),web)
            self.assertIn('OTHER_STYLE',html)
            self.assertNotIn('src="./',html)
            self.assertLess(html.index('const savedReplay'),html.index('TOOLS_FIRST'))
            self.assertLess(html.index('TOOLS_FIRST'),html.index('APP_SECOND'))
            self.assertLess(html.index('<main>Ready</main>'),html.index('TOOLS_FIRST'))
    def test_export_rejects_remote_or_traversing_assets(self):
        class Store:
            def bootstrap(self):return {'mode':'mock-replay','replay':{'frame_count':1}}
            def frame(self,i):return {'snapshot_hash':'fixed'}
        with tempfile.TemporaryDirectory() as d:
            web=Path(d)
            for source in ('https://example.com/x.js','../outside.js'):
                (web/'index.html').write_text('<body><script src="'+source+'" defer></script></body>')
                with self.subTest(source=source),self.assertRaises(ValueError):render_preview(Store(),web)
    def test_inline_assets_cannot_close_their_script_element(self):
        class Store:
            def bootstrap(self):return {'mode':'mock-replay','replay':{'frame_count':1}}
            def frame(self,i):return {'snapshot_hash':'fixed'}
        with tempfile.TemporaryDirectory() as d:
            web=Path(d)
            (web/'index.html').write_text('<body><script src="./tools.js" defer></script></body>')
            (web/'tools.js').write_text('const literal="</script>";')
            html=render_preview(Store(),web)
            self.assertNotIn('const literal="</script>"',html)
            self.assertIn('const literal=',html)

if __name__=='__main__':unittest.main()
