import json
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import phone_share as phone


class PhoneBridgeTests(unittest.TestCase):
    def setUp(self):
        class View:
            def read(self):
                return {'paper_only': True, 'real_trading_enabled': False, 'marker': 'same-pc-ledger'}
        self.server = phone.bridge(View(), 'test-token')
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, path='/api/status', token='test-token', origin=phone.ORIGIN, method='GET'):
        request = urllib.request.Request(self.base+path, headers={'Origin': origin, 'Authorization': 'Bearer '+token}, method=method)
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as response:
            return response

    def test_readonly_authenticated_same_pc_state(self):
        with self.request() as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], phone.ORIGIN)
            self.assertEqual(json.load(response)['marker'], 'same-pc-ledger')

    def test_wrong_key_denied(self):
        with self.request(token='wrong') as response:
            self.assertEqual(response.status, 401)
            self.assertNotIn(b'same-pc-ledger', response.read())

    def test_other_origin_denied(self):
        with self.request(origin='https://unrelated.example') as response:
            self.assertEqual(response.status, 403)
            self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))

    def test_no_files_or_mutations(self):
        for path in ('/', '/api/phone-share', '/paper.sqlite', '/realtime_runtime.py'):
            with self.request(path=path) as response:
                self.assertEqual(response.status, 404)
        with self.request(method='POST') as response:
            self.assertEqual(response.status, 501)

    def test_preflight(self):
        with self.request(token='', method='OPTIONS') as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Access-Control-Allow-Headers'], 'Authorization')

    def test_download_hash_mismatch_never_executes(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            with patch('phone_share.urllib.request.urlopen', return_value=io.BytesIO(b'wrong binary')):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    phone.install_client(directory)
            from pathlib import Path
            self.assertEqual(list(Path(directory).iterdir()), [])

if __name__ == '__main__':
    unittest.main()
