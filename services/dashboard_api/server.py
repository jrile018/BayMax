"""Dependency-free replay HTTP service; defaults to loopback access."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from .replay import ReplayStore

ROOT = Path(__file__).resolve().parents[2]

def make_server(store, web_root, host='127.0.0.1', port=8765):
    web_root = Path(web_root).resolve()
    class Handler(BaseHTTPRequestHandler):
        def json_response(self, status, data):
            payload=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers(); self.wfile.write(payload)

        def do_GET(self):
            request=urlsplit(self.path); path=unquote(request.path)
            try:
                query=parse_qs(request.query)
                if path=='/api/bootstrap':
                    self.json_response(200,store.bootstrap());return
                if path=='/api/frame':
                    values=query.get('index',[])
                    if len(values)!=1: raise ValueError('Provide one frame index')
                    self.json_response(200,store.frame(int(values[0])));return
                if path=='/api/coverage':
                    if len(query.get('lat',[]))!=1 or len(query.get('lon',[]))!=1:
                        raise ValueError('Provide one latitude and longitude')
                    self.json_response(200,store.coverage(float(query['lat'][0]),float(query['lon'][0])));return
                if path=='/api/health':
                    self.json_response(200,{'status':'ok','mode':store.bootstrap()['mode']});return
                if path.startswith('/api/'):
                    self.json_response(404,{'error':'Unknown endpoint'});return
                target=(web_root/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                if not target.is_relative_to(web_root) or target.suffix not in ('.html','.css','.js','.svg','.ico') or not target.is_file():
                    self.json_response(404,{'error':'File not found'});return
                payload=target.read_bytes()
                content_type={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml','.ico':'image/x-icon'}[target.suffix]
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Cache-Control','no-cache')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers(); self.wfile.write(payload)
            except (ValueError,IndexError,KeyError) as error:
                self.json_response(400,{'error':str(error)})
        def do_POST(self):
            self.json_response(405,{'error':'Replay service is read-only. Dispatch integration is not enabled.'})
    return ThreadingHTTPServer((host,port),Handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--area',type=Path,default=ROOT/'fixtures/geography/paradise/area.json')
    parser.add_argument('--replay',type=Path,default=ROOT/'fixtures/replay_ui/paradise_mock.json')
    parser.add_argument('--web',type=Path,default=ROOT/'web')
    args=parser.parse_args()
    store=ReplayStore(args.area,args.replay)
    server=make_server(store,args.web,args.host,args.port)
    print(f'Knight26 replay {store.bootstrap()["mode"]}: http://{args.host}:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
