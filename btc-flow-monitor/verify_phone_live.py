"""Bounded real public tunnel check using synthetic PAPER values only."""
import json
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, parse_qs
from phone_share import PhoneShare, ORIGIN
from realtime_runtime import View


def main():
    view = View()
    view.update({'paper_only': True, 'real_trading_enabled': False, 'healthy': True,
                 'test_fixture': 'SYNTHETIC_PHONE_SMOKE', 'rows': [{'equity_usd': 1234.56}]})
    with tempfile.TemporaryDirectory(prefix='btc-phone-') as directory:
        share = PhoneShare(view, directory)
        share.start()
        try:
            deadline = time.monotonic()+120
            connected = False
            while time.monotonic() < deadline:
                state = share.snapshot()
                if state['status'].startswith('FAILED'):
                    raise AssertionError(state['status'])
                if state['url']:
                    parts = parse_qs(urlsplit(state['url']).fragment)
                    url = parts['pc'][0]+'/api/status'
                    headers = {'Authorization': 'Bearer '+parts['key'][0], 'Origin': ORIGIN}
                    try:
                        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as response:
                            payload = json.load(response)
                            assert response.headers['Access-Control-Allow-Origin'] == ORIGIN
                            assert payload['rows'][0]['equity_usd'] == 1234.56
                            assert payload['test_fixture'] == 'SYNTHETIC_PHONE_SMOKE'
                            connected = True
                            break
                    except (OSError, ValueError):
                        pass
                time.sleep(1)
            assert connected, 'public tunnel did not become reachable within deadline'
            with urllib.request.urlopen(urllib.request.Request(url, headers={'Origin': ORIGIN}, method='OPTIONS'), timeout=10) as response:
                assert response.headers['Access-Control-Allow-Headers'] == 'Authorization'
            try:
                urllib.request.urlopen(url, timeout=10)
                raise AssertionError('unauthenticated request accepted')
            except urllib.error.HTTPError as response:
                assert response.code == 401
            assert b'<svg' in share.qr()
        finally:
            share.close()
        assert share.process is None or share.process.poll() is not None
    print('PHONE PUBLIC TUNNEL PASS synthetic_only=true authenticated=true cors=true qr=true clean_shutdown=true')

if __name__ == '__main__':
    main()
