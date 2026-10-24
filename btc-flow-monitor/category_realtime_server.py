"""Local dashboard server extension for the separate six-category realtime panel."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import realtime_runtime as base


def serve(view, host, port, phone=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ('/','/dashboard.html'):
                html=(base.ROOT/'dashboard.html').read_text(encoding='utf-8')
                html=html.replace('<head>','<head><script>window.BTC_LOCAL_RUNTIME=true;</script>',1)
                body=html.encode('utf-8');content_type,code='text/html; charset=utf-8',200
            elif path=='/api/phone-share':
                body=json.dumps(phone.snapshot() if phone else {'status':'DISABLED','url':None}).encode();content_type,code='application/json',200
            elif path=='/api/phone-qr' and phone and phone.qr():
                body=phone.qr();content_type,code='image/svg+xml',200
            elif path in ('/api/status','/healthz'):
                data=view.read();body=json.dumps(data,allow_nan=False).encode();content_type='application/json';code=200 if path=='/api/status' or data.get('healthy') else 503
            elif path in ('/dashboard-adaptive.js','/dashboard-follow.js','/dashboard-category-realtime.js',
                          '/data/whale-paper-state.json','/data/whale-ranking.json',
                          '/trader-discovery/latest.json','/trader-discovery/category-paper.json',
                          '/trader-discovery/current-positions.json'):
                body=(base.ROOT/path.lstrip('/')).read_bytes()
                content_type='application/javascript; charset=utf-8' if path.endswith('.js') else 'application/json';code=200
            else:
                self.send_error(404);return
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer((host,port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


def install():
    base.serve=serve
