"""Read-only phone display of the running wallet engine, independent of Git uploads."""
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from phone_share import PhoneShare


class WalletView:
    def __init__(self):
        self.lock = threading.Lock()
        self.ledger = None
        self.revision = 0
        self.state = {}

    def update(self, ledger, connected, pending):
        with self.lock:
            if ledger is not self.ledger:
                self.revision += 1
                self.ledger = ledger
            self.state = dict(heartbeat_ms=int(time.time()*1000), connected=connected,
                              pending=pending, revision=self.revision)

    def read(self):
        with self.lock:
            if self.ledger is None:
                return dict(paper_only=True, real_trading_enabled=False, accounts={}, pc_live=self.state)
            # The observer replaces complete ledger snapshots; these are never mutated here.
            result = {k:v for k,v in self.ledger.items() if k not in ('archived_accounts','cycles')}
            result['pc_live'] = dict(self.state)
            return result

    def read_since(self, revision):
        with self.lock:
            if str(revision) == str(self.revision):
                return dict(paper_only=True,real_trading_enabled=False,unchanged=True,pc_live=dict(self.state))
        return self.read()


def local_portal(view, share, dashboard, settings=None):
    csrf=secrets.token_urlsafe(32)
    html = dashboard.read_text(encoding='utf-8').replace('<head>',
        '<head><script>window.BTC_LOCAL_RUNTIME=true;window.CASH_CSRF='+json.dumps(csrf)+';</script>', 1).encode('utf-8')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host or self.headers.get('Origin') not in (None, 'http://'+host):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path in ('/', '/dashboard.html'):
                body, kind = html, 'text/html; charset=utf-8'
            elif path == '/api/status':
                revision=parse_qs(urlsplit(self.path).query).get('since',[None])[0]
                body, kind = json.dumps(view.read_since(revision),allow_nan=False).encode(), 'application/json'
            elif path == '/api/settings' and settings is not None:
                body, kind = json.dumps(settings.read(),allow_nan=False).encode(), 'application/json'
            elif path == '/api/phone-share':
                body, kind = json.dumps(share.snapshot()).encode(), 'application/json'
            elif path == '/api/phone-qr':
                body, kind = share.qr(), 'image/svg+xml'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            host=f'127.0.0.1:{self.server.server_port}'
            if (self.headers.get('Host')!=host or self.headers.get('Origin')!='http://'+host or
                not secrets.compare_digest(self.headers.get('X-Cash-CSRF',''),csrf) or
                self.headers.get('Content-Type')!='application/json'):
                self.send_error(403);return
            if settings is None:
                self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8192: raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise ValueError('Object required')
                path=urlsplit(self.path).path
                if path=='/api/settings': result=settings.save(data)
                elif path=='/api/binance/test': result=settings.check(data)
                elif path=='/api/binance/disconnect': result=settings.disconnect()
                else:
                    self.send_error(404);return
                body=json.dumps(result,allow_nan=False).encode();code=200
            except ValueError as e:
                body=json.dumps({'error':str(e)}).encode();code=400
            except Exception:
                body=b'{"error":"Local configuration operation failed"}';code=500
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)

        def log_message(self,*args):
            pass

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


class WalletPhone:
    def __init__(self, root, directory):
        self.view=WalletView()
        dashboard=root/'btc-flow-monitor/dashboard.html'
        html=dashboard.read_text(encoding='utf-8')
        self.share=PhoneShare(self.view,directory,dashboard_html=html)
        from cash_flow_settings import SettingsStore
        self.settings=SettingsStore(directory)
        self.portal=local_portal(self.view,self.share,root/'btc-flow-monitor/dashboard.html',self.settings)
        self.url=f'http://127.0.0.1:{self.portal.server_port}/'

    def start(self):
        self.share.start()
        print('PC LIVE DASHBOARD:',self.url,'Scan its QR from your phone.',flush=True)
        webbrowser.open(self.url)

    def close(self):
        self.share.close()
        self.portal.shutdown()
        self.portal.server_close()
