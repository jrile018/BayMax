import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from services.dashboard_api.replay import ReplayStore,frame_hash
from services.dashboard_api.server import make_server

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.web=self.root/'web';self.web.mkdir()
        (self.web/'index.html').write_text('<html>Dashboard</html>')
        (self.root/'private.css').write_text('secret')
        area={'area_id':'a','label':'Area','bbox_lonlat':[-122,39,-121,40],'coverage':[{'layer':'roads','status':'unavailable'}]}
        frame={'run_id':'r','scenario_id':'s','snapshot_version':1,'index':0,'time_s':0,'mode':'mock-replay','vehicles':[]}
        frame['snapshot_hash']=frame_hash(frame)
        record={'mode':'mock-replay','label':'mock','frames':[frame]}
        (self.root/'area.json').write_text(json.dumps(area));(self.root/'replay.json').write_text(json.dumps(record))
        self.store=ReplayStore(self.root/'area.json',self.root/'replay.json')
        self.server=make_server(self.store,self.web,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,method='GET'):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        c.request(method,path);r=c.getresponse();data=r.read();status=r.status;headers=dict(r.getheaders());c.close()
        return status,headers,data
    def test_situation_unavailable_without_trusted_provider(self):
        status,headers,body=self.request('/api/situation')
        self.assertEqual(status,200)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(json.loads(body),{'status':'unavailable','reason':'No accepted incident snapshot connected'})

    def test_situation_uses_trusted_provider_and_never_request_payload(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        accepted={'schema_version':'knight26-incident-v1','snapshot_hash':'accepted-hash','categories':{'stock':None}}
        self.server=make_server(self.store,self.web,port=0,situation_provider=lambda:accepted)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        status,_,body=self.request('/api/situation?source_url=https://example.invalid/forged')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body),{'status':'available','snapshot':accepted})
        self.assertEqual(self.request('/api/situation',method='POST')[0],405)

    def test_snapshot_payload_exact_and_nocache(self):
        status,headers,body=self.request('/api/frame?index=0')
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(json.loads(body),self.store.frame(0))
    def test_invalid_indices_and_query_fail(self):
        for path in ['/api/frame','/api/frame?index=-1','/api/frame?index=1','/api/frame?index=0&index=1','/api/frame?index=nan']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],400)
    def test_coverage_rejects_nan_and_reports_missing_layers(self):
        self.assertEqual(self.request('/api/coverage?lat=nan&lon=1')[0],400)
        status,_,body=self.request('/api/coverage?lat=39.5&lon=-121.5')
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['available'])
        self.assertTrue(json.loads(body)['in_loaded_area'])
    def test_path_traversal_and_unknown_path(self):
        for path in ['/%2e%2e/private.css','/../private.css','/missing.js','/api/unknown']:
            with self.subTest(path=path):self.assertEqual(self.request(path)[0],404)
        self.assertEqual(self.request('/')[0],200)
    def test_read_only_action_boundary(self):
        status,_,body=self.request('/api/dispatch',method='POST')
        self.assertEqual(status,405);self.assertIn('read-only',json.loads(body)['error'])

if __name__=='__main__':unittest.main()
