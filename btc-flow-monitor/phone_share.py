"""Read-only authenticated phone bridge. No orders, credentials or ledger mutation."""
import hashlib
import gzip
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit, parse_qs

DASHBOARD = 'https://jay1125jay.github.io/flowiq-crew-operations/btc-flow-monitor/dashboard.html'
ORIGIN = 'https://jay1125jay.github.io'
VERSION = '2026.10.3'
BINARIES = {
    'nt': ('cloudflared-windows-amd64.exe', '76b2805253d0d6ffacb092a7acfbee99e7af6917835c0c5410e23f3ef5052da2'),
    'posix': ('cloudflared-linux-amd64', '053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0'),
}
URL_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com\b')


def install_client(directory):
    name, digest = BINARIES[os.name]
    target = Path(directory)/name
    target.parent.mkdir(parents=True, exist_ok=True)
    def matches(path):
        return path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    if not matches(target):
        temporary = target.with_suffix('.download')
        try:
            url = f'https://github.com/cloudflare/cloudflared/releases/download/{VERSION}/{name}'
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open('wb') as output:
                size = 0
                while chunk := response.read(1024*1024):
                    size += len(chunk)
                    if size > 150*1024*1024:
                        raise ValueError('unexpected client size')
                    output.write(chunk)
            if not matches(temporary):
                raise ValueError('client checksum mismatch')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    if os.name != 'nt':
        target.chmod(0o700)
    return target


def bridge(view, token, dashboard_html=None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, payload=None):
            body = json.dumps(payload or {}, allow_nan=False).encode()
            compressed = 'gzip' in self.headers.get('Accept-Encoding','') and len(body)>1024
            if compressed:
                body=gzip.compress(body,compresslevel=3)
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if compressed:
                self.send_header('Content-Encoding','gzip')
            if self.headers.get('Origin') in (ORIGIN, getattr(self.server,'public_origin',ORIGIN)):
                self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin'))
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Authorization')
                self.send_header('Access-Control-Max-Age', '600')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.reply(200 if self.headers.get('Origin') in (ORIGIN, getattr(self.server,'public_origin',ORIGIN)) and urlsplit(self.path).path == '/api/status' else 403)

        def do_GET(self):
            if urlsplit(self.path).path == '/dashboard.html' and dashboard_html is not None:
                body=dashboard_html.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Cache-Control','no-store')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if urlsplit(self.path).path != '/api/status':
                self.reply(404)
            elif self.headers.get('Origin') not in (None, ORIGIN, getattr(self.server,'public_origin',ORIGIN)):
                self.reply(403)
            elif not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token):
                self.reply(401)
            else:
                revision=parse_qs(urlsplit(self.path).query).get('since',[None])[0]
                self.reply(200, view.read_since(revision) if hasattr(view,'read_since') else view.read())

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class PhoneShare:
    def __init__(self, view, directory, dashboard_html=None):
        self.directory = Path(directory)/'phone'
        self.token = secrets.token_urlsafe(32)
        self.server = bridge(view, self.token, dashboard_html)
        self.direct_dashboard = dashboard_html is not None
        self.open_public_home = False
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.url = None
        self.svg = b''
        self.status = 'STARTING'
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return {'status': self.status, 'url': self.url if self.status == 'LINK_READY' else None}

    def qr(self):
        with self.lock:
            return self.svg if self.status == 'LINK_READY' else b''

    def _run(self):
        try:
            client = install_client(self.directory)
            config = self.directory/'empty.yml'
            config.write_text('{}\n')
            with self.lock:
                if self.stop.is_set():
                    return
                self.process = subprocess.Popen([str(client), '--no-autoupdate', '--config', str(config),
                    'tunnel', '--protocol', 'http2', '--url', f'http://127.0.0.1:{self.server.server_port}'],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
                process = self.process
            for line in process.stdout:
                if self.stop.is_set():
                    break
                match = URL_PATTERN.search(line)
                if match and self.url is None:
                    import qrcode
                    from qrcode.image.svg import SvgPathImage
                    self.server.public_origin = match.group(0)
                    target = match.group(0)+'/dashboard.html' if self.direct_dashboard else DASHBOARD
                    url = target+'#'+urlencode({'pc': match.group(0), 'key': self.token})
                    if self.open_public_home:
                        import webbrowser
                        webbrowser.open(url)
                    svg = qrcode.make(url, image_factory=SvgPathImage, box_size=4, border=4).to_string()
                    with self.lock:
                        self.url, self.svg, self.status = url, svg, 'LINK_READY'
                    print('PHONE LINK READY: scan the QR on the local dashboard. Keep this PC awake.', flush=True)
            if not self.stop.is_set():
                with self.lock:
                    self.status = 'DISCONNECTED'
        except Exception as exc:
            with self.lock:
                self.status = 'FAILED / '+type(exc).__name__
            print('PHONE SHARING UNAVAILABLE: local PAPER runtime continues.', flush=True)
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()

    def close(self):
        self.stop.set()
        with self.lock:
            self.status = 'STOPPED'
            process = self.process
        if process and process.poll() is None:
            process.terminate()
        if self.thread.is_alive():
            self.thread.join(timeout=7)
        self.server.shutdown()
        self.server.server_close()
