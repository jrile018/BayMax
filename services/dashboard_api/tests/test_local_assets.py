"""Dependency-origin regression against the actual dashboard response policy."""
import http.client
from html.parser import HTMLParser
from pathlib import Path
import re
import threading
import unittest
from urllib.parse import urljoin,urlsplit
from services.dashboard_api.replay import ReplayStore
from services.dashboard_api.server import make_server,ROOT

class Scripts(HTMLParser):
    def __init__(self): super().__init__();self.paths=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='script' and 'src' in values:self.paths.append(values['src'])

class LocalRendererAssetsTests(unittest.TestCase):
    def test_renderer_dependencies_load_under_existing_self_csp(self):
        store=ReplayStore(ROOT/'fixtures/geography/paradise/area.json',ROOT/'fixtures/replay_ui/paradise_mock.json')
        server=make_server(store,ROOT/'web',port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def get(path):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);c.request('GET',path);r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read());c.close();return result
        try:
            status,headers,html=get('/');self.assertEqual(status,200)
            self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
            source=get('/local-3d.js')[2].decode()
            # Current renderer imports a CDN URL; 'self' excludes that origin.
            for reference in re.findall(r'https?://[^"\s\']+',source):
                self.assertEqual(urlsplit(reference).netloc,'',f'external renderer dependency blocked by CSP: {reference}')
            scripts=Scripts();scripts.feed(html.decode())
            vendor=[p for p in scripts.paths if '/vendor/three/' in p]
            self.assertEqual(len(vendor),1,'actual dashboard must deliver the bundled renderer dependency')
            self.assertLess(scripts.paths.index(vendor[0]),scripts.paths.index('./local-3d.js'))
            status,headers,body=get(urljoin('/',vendor[0]));self.assertEqual(status,200)
            self.assertIn('javascript',headers['Content-Type']);self.assertGreater(len(body),100_000)
        finally:server.shutdown();server.server_close();thread.join()
