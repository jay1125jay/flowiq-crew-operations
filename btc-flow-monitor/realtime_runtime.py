#!/usr/bin/env python3
"""Single-host, one-second PAPER research runner. Public data only; no order client."""
import argparse
import asyncio
import copy
import datetime as dt
import json
import os
from pathlib import Path
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import adaptive_meta as engine

ROOT = Path(__file__).resolve().parent
WS_URL = 'wss://api.hyperliquid.xyz/ws'
SOURCE_TTL = 120
QUOTE_TTL = 5


def iso(seconds):
    return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()


def safety():
    if os.getenv('PAPER_ONLY') != 'true' or os.getenv('REAL_TRADING') != 'false':
        raise ValueError('PAPER_ONLY=true and REAL_TRADING=false required')


class Store:
    """State and dedup cursor commit together. One process per persistent directory."""
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = (directory / 'writer.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if self.lock.seek(0, 2) == 0:
                    self.lock.write(b'0')
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError('another PAPER writer owns this directory')
        try:
            self.db = sqlite3.connect(directory / 'paper.sqlite')
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        except Exception:
            self.lock.close()
            raise

    def read(self):
        row = self.db.execute('SELECT body FROM state WHERE id=1').fetchone()
        if not row:
            return {'version': 1, 'competition': {}, 'quote_ms': 0, 'tick': 0,
                    'source_id': None, 'baseline': {}, 'current_market': {}, 'ticks': 0}
        state = json.loads(row[0])
        if state['version'] != 1:
            raise ValueError('unsupported runtime state')
        engine.safe(state['competition'])
        if state['competition']['schema_version'] != engine.VERSION:
            raise ValueError('runtime schema changed; explicit migration required')
        return state

    def save(self, state):
        body = json.dumps(state, allow_nan=False, separators=(',', ':'))
        with self.db:
            self.db.execute('INSERT INTO state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (body,))

    def close(self):
        self.db.close()
        self.lock.close()


class Quotes:
    def __init__(self):
        self.connected = False
        self.latest = None
        self.reconnects = 0
        self.highwater = 0

    def disconnect(self):
        self.connected = False
        self.latest = None

    def receive(self, message, now):
        if message.get('channel') != 'bbo':
            return False
        data = message['data']
        if data['coin'] != 'BTC':
            return False
        timestamp = int(data['time'])
        if timestamp <= self.highwater:
            return False
        age = now - timestamp / 1000
        if not 0 <= age <= QUOTE_TTL:
            raise ValueError('stale/future quote')
        bid, ask = (engine.number(row['px']) for row in data['bbo'])
        if not 1000 < bid <= ask < 1000000 or ask / bid - 1 > .005:
            raise ValueError('invalid or wide BTC book')
        self.highwater = timestamp
        self.latest = {'ms': timestamp, 'received_at': now, 'price': (bid + ask) / 2}
        return True


class Runner:
    def __init__(self, store):
        self.store = store
        self.state = store.read()
        self.status = 'WARMUP'
        self.evaluated_at = None
        self.last_error = None

    def tick(self, quotes, bundle, now, source_error=None):
        self.evaluated_at = iso(now)
        self.last_error = source_error
        if not quotes.connected or not quotes.latest:
            self.status = 'DISCONNECTED'
            return False
        q = quotes.latest
        if not 0 <= now-q['ms']/1000 <= QUOTE_TTL or not 0 <= now-q['received_at'] <= QUOTE_TTL:
            self.status = 'STALE_PRICE'
            return False
        if bundle is None or source_error:
            self.status = 'WAIT_SOURCE'
            return False
        if not 0 <= now-bundle['started_at'] <= SOURCE_TTL:
            self.status = 'STALE_SOURCE'
            return False
        if int(now) <= self.state['tick'] or q['ms'] <= self.state['quote_ms']:
            self.status = 'WAIT_NEW_PRICE'
            return False
        c, f, m, r = (bundle[k] for k in ('cohorts', 'positions', 'market', 'ranking'))
        # Validate real source times; never relabel old inputs as new observations.
        for obj, field in ((c, 'generated_at'), (f, 'generated_at'), (m, 'generated_at'), (r, 'updated_at')):
            engine.fresh(obj[field], iso(now), SOURCE_TTL)
        new = copy.deepcopy(self.state)
        source_id = f['generated_at']
        if new['source_id'] is not None and engine.stamp(source_id) < engine.stamp(new['source_id']):
            raise ValueError('out-of-order source bundle')
        if source_id != new['source_id']:
            new['baseline'] = new['current_market']
            new['current_market'] = {k: m[k] for k in ('funding_rate', 'open_interest_btc', 'reference_price')}
            new['source_id'] = source_id
        previous_at = new['competition'].get('last_observation_at')
        gap = now-engine.stamp(previous_at).timestamp() if previous_at else 0
        competition = engine.advance(new['competition'], c, f, iso(now), m, r,
            execution={'at': iso(now), 'price': q['price']}, signal_baseline=new['baseline'])
        competition['runtime_mode'] = 'REALTIME_PAPER_SEPARATE_EPOCH'
        competition['data_quality']['continuity'] = {
            'target_interval_seconds': 1, 'last_gap_seconds': gap,
            'gap_count': new.get('gap_count', 0) + int(gap > QUOTE_TTL),
            'status': 'GAPPED' if gap > QUOTE_TTL else 'OBSERVED_OK',
            'note': 'One-second evaluation target; source cadences are separately reported.'}
        competition['data_quality']['source_started_at'] = iso(bundle['started_at'])
        competition['data_quality']['quote_at'] = iso(q['ms']/1000)
        competition['control'] = 'Separate realtime epoch. Existing GitHub control and category ledgers are not imported or modified.'
        new.update(competition=competition, quote_ms=q['ms'], tick=int(now), ticks=new['ticks']+1,
                   gap_count=competition['data_quality']['continuity']['gap_count'])
        # Publish only after durable commit. A crash cannot persist cash without its cursor.
        self.store.save(new)
        self.state = new
        self.status = 'RUNNING'
        return True

    def public(self, quotes, bundle, now):
        competition = self.state['competition']
        healthy = (self.status in ('RUNNING', 'WAIT_NEW_PRICE') and quotes.connected
            and quotes.latest is not None and 0 <= now-quotes.latest['ms']/1000 <= QUOTE_TTL
            and bundle is not None and 0 <= now-bundle['started_at'] <= SOURCE_TTL
            and self.evaluated_at is not None and 0 <= now-engine.stamp(self.evaluated_at).timestamp() <= QUOTE_TTL)
        return dict(paper_only=True, real_trading_enabled=False, healthy=healthy,
            status=self.status if healthy else 'WAIT / '+self.status,
            evaluated_at=self.evaluated_at, updated_at=competition.get('updated_at'),
            quote_at=iso(quotes.latest['ms']/1000) if quotes.latest else None,
            source_at=bundle['positions']['generated_at'] if bundle else None,
            reconnects=quotes.reconnects, ticks=self.state['ticks'],
            target_interval_seconds=1, source_refresh_seconds=60,
            btc_mid_usd=competition.get('btc_mid_usd'), profitability='UNPROVEN',
            epoch='REALTIME_PAPER_SEPARATE_EPOCH', error=self.last_error,
            competition=copy.deepcopy(competition),
            rows=[dict(engine=k, signal=competition.get('decisions', {}).get(k, {}).get('signal', 'WAIT') if healthy else 'WAIT',
                confidence=competition.get('decisions', {}).get(k, {}).get('confidence') if healthy else None,
                **{f: a.get(f) for f in ('equity_usd','net_pnl_usd','profit_factor','mdd_pct','win_rate_pct','closed_count','fees_usd','unrealized_pnl_usd')})
                for k, a in competition.get('accounts', {}).items()])


class Sources:
    def __init__(self):
        self.lock = threading.Lock()
        self.bundle = None
        self.error = None

    def get(self):
        with self.lock:
            return self.bundle, self.error

    def set(self, bundle, error):
        with self.lock:
            self.bundle, self.error = bundle, error


def collect_sources(directory, shared, stop):
    # Isolated writable copy: existing GitHub data and ledgers remain untouched.
    work = directory/'collector'
    if not work.exists():
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns('__pycache__', 'browser-evidence', '*.sqlite*'))
    else:
        # Upgrade code without resetting the collector's accumulated forward evidence.
        for source in ROOT.rglob('*.py'):
            destination = work/source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    scripts = ['trader-discovery/leaderboard_expand.py', 'scripts/whale_ranker.py',
        'trader-discovery/trader_discovery.py', 'collect_adaptive_market.py',
        'trader-discovery/current_positions.py']
    while not stop.is_set():
        started = time.time()
        try:
            for script in scripts:
                remaining = 100-(time.time()-started)
                if remaining <= 0 or stop.is_set():
                    raise TimeoutError('collection deadline')
                with subprocess.Popen([sys.executable, str(work/script)], cwd=work,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
                    end = time.monotonic()+remaining
                    while child.poll() is None:
                        if stop.wait(.25) or time.monotonic() >= end:
                            child.kill()
                            child.wait()
                            raise TimeoutError('collection stopped or timed out')
                    if child.returncode:
                        raise RuntimeError('collector process failed')
            def read(path):
                return json.loads((work/path).read_text())
            bundle = dict(started_at=started, cohorts=read('trader-discovery/latest.json'),
                positions=read('trader-discovery/current-positions.json'),
                market=read('data/adaptive-market.json'), ranking=read('data/whale-ranking.json'))
            engine.validate_inputs(bundle['cohorts'], bundle['positions'], bundle['market'], bundle['ranking'], iso(time.time()))
            shared.set(bundle, None)
        except Exception as exc:
            shared.set(None, type(exc).__name__)
        stop.wait(max(1, 60-(time.time()-started)))


async def stream(quotes, stop):
    from websockets.asyncio.client import connect
    delay = 1
    while not stop.is_set():
        try:
            async with connect(WS_URL, open_timeout=15, ping_interval=20, ping_timeout=20,
                               max_size=65536, max_queue=4) as ws:
                quotes.disconnect()
                quotes.connected = True
                await ws.send(json.dumps({'method':'subscribe', 'subscription':{'type':'bbo','coin':'BTC'}}))
                last_ping = time.monotonic()
                while not stop.is_set():
                    if time.monotonic()-last_ping >= 20:
                        await ws.send('{"method":"ping"}')
                        last_ping = time.monotonic()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    except asyncio.TimeoutError:
                        continue
                    if quotes.receive(json.loads(raw), time.time()):
                        delay = 1
        except asyncio.CancelledError:
            raise
        except Exception:
            quotes.reconnects += 1
        finally:
            quotes.disconnect()
        await asyncio.sleep(delay+random.random())
        delay = min(30, delay*2)


class View:
    def __init__(self):
        self.lock = threading.Lock()
        self.body = b'{}'
        self.at = 0

    def update(self, payload):
        with self.lock:
            self.body = json.dumps(payload, allow_nan=False).encode()
            self.at = time.time()

    def read(self):
        with self.lock:
            data = json.loads(self.body)
            if time.time()-self.at > QUOTE_TTL:
                data.update(healthy=False, status='WAIT / RUNTIME_STALE')
                for row in data.get('rows', []):
                    row.update(signal='WAIT', confidence=None)
            return data


def serve(view, host, port, phone=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ('/', '/dashboard.html'):
                html = (ROOT/'dashboard.html').read_text(encoding='utf-8')
                html = html.replace('<head>', '<head><script>window.BTC_LOCAL_RUNTIME=true;</script>', 1)
                body = html.encode('utf-8')
                content_type, code = 'text/html; charset=utf-8', 200
            elif path == '/api/phone-share':
                body = json.dumps(phone.snapshot() if phone else {'status': 'DISABLED', 'url': None}).encode()
                content_type, code = 'application/json', 200
            elif path == '/api/phone-qr' and phone and phone.qr():
                body = phone.qr()
                content_type, code = 'image/svg+xml', 200
            elif path in ('/api/status', '/healthz'):
                data = view.read()
                body = json.dumps(data, allow_nan=False).encode()
                content_type = 'application/json'
                code = 200 if path == '/api/status' or data.get('healthy') else 503
            elif path in ('/dashboard-adaptive.js', '/dashboard-follow.js',
                          '/data/whale-paper-state.json', '/data/whale-ranking.json',
                          '/trader-discovery/latest.json', '/trader-discovery/category-paper.json',
                          '/trader-discovery/current-positions.json'):
                # Explicit allowlist: never expose source code or the local SQLite ledger.
                body = (ROOT/path.lstrip('/')).read_bytes()
                content_type = 'application/javascript; charset=utf-8' if path.endswith('.js') else 'application/json'
                code = 200
            else:
                self.send_error(404)
                return
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def run(args):
    safety()
    directory = Path(args.state_dir).resolve()
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError('state directory must be outside source tree')
    store = Store(directory)
    stop = threading.Event()
    server = worker = task = phone = None
    previous_signals = {}
    loop = asyncio.get_running_loop()
    try:
        runner, quotes, sources, view = Runner(store), Quotes(), Sources(), View()
        quotes.highwater = runner.state['quote_ms']
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_signals[signum] = signal.getsignal(signum)
            if os.name == 'nt':
                signal.signal(signum, lambda *_: stop.set())
            else:
                loop.add_signal_handler(signum, stop.set)
        if getattr(args, 'share_phone', False):
            from phone_share import PhoneShare
            phone = PhoneShare(view, directory)
        server = serve(view, args.host, args.port, phone)
        if phone:
            phone.start()
        worker = threading.Thread(target=collect_sources, args=(directory, sources, stop), daemon=True)
        worker.start()
        task = asyncio.create_task(stream(quotes, stop))
        print(f'BTC FLOW PAPER ONLY | http://{args.host}:{server.server_port}/', flush=True)
        print(f'State: {directory} | Stop: Ctrl+C | Keep PC awake.', flush=True)
        if getattr(args, 'open_browser', False):
            import webbrowser
            webbrowser.open(f'http://{args.host}:{server.server_port}/')
        deadline = time.monotonic()+args.seconds if args.seconds else float('inf')
        last_status = None
        while not stop.is_set() and time.monotonic() < deadline:
            start = time.monotonic()
            bundle, error = sources.get()
            try:
                runner.tick(quotes, bundle, time.time(), error)
            except (ValueError, KeyError, TypeError) as exc:
                runner.status = 'INVALID_INPUT'
                runner.last_error = type(exc).__name__
            view.update(runner.public(quotes, bundle, time.time()))
            if runner.status != last_status:
                print(f'{iso(time.time())} {runner.status}', flush=True)
                last_status = runner.status
            if task.done():
                task.result()
                raise RuntimeError('stream task stopped')
            await asyncio.sleep(max(0, 1-(time.monotonic()-start)))
    finally:
        stop.set()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if phone is not None:
            phone.close()
        if server is not None:
            server.shutdown()
            server.server_close()
        if worker is not None:
            worker.join(timeout=5)
        store.close()
        for signum, handler in previous_signals.items():
            if os.name != 'nt':
                loop.remove_signal_handler(signum)
            signal.signal(signum, handler)
        print('STOPPED: PAPER state preserved.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--share-phone', action='store_true')
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--seconds', type=int, default=0, help='bounded smoke run; 0 runs until stopped')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
