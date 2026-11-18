import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request
import urllib.error
import re
from cash_flow_settings import SettingsStore, validate, protect, BinanceReadOnly
from wallet_phone import local_portal,WalletView


class SettingsTests(unittest.TestCase):
    def test_validation(self):
        for data in [{'budget_krw':float('nan')},{'leverage':2.5},{'leverage':True},{'daily_loss_krw':6000000},
                     {'capital_cap_krw':1},{'real_trading_enabled':True},{'compound':'yes'},
                     {'enabled_wallets':['no']}]:
            with self.assertRaises(ValueError):validate(data)
    def test_atomic_persistence_no_live_activation(self):
        with tempfile.TemporaryDirectory() as d:
            s=SettingsStore(d);result=s.save({'budget_krw':2000000,'leverage':5})
            self.assertFalse(result['live_enabled']);self.assertFalse(result['settings_applied'])
            self.assertEqual(SettingsStore(d).read()['settings']['budget_krw'],2000000)
            with self.assertRaises(ValueError): s.save({'leverage':200})
            self.assertEqual(s.read()['settings']['leverage'],5)
    def test_readonly_client_rejects_order_endpoint(self):
        c=BinanceReadOnly('A'*32,'B'*32)
        with self.assertRaises(ValueError): c.get('https://fapi.binance.com','/fapi/v1/order',{})
    def test_withdrawal_key_rejected(self):
        c=BinanceReadOnly('A'*32,'B'*32)
        with patch.object(c,'get',side_effect=[{'serverTime':1},{'enableWithdrawals':True}]):
            with self.assertRaisesRegex(ValueError,'withdrawal'):c.check()
    def test_failed_test_does_not_save(self):
        with tempfile.TemporaryDirectory() as d:
            s=SettingsStore(d)
            with patch('cash_flow_settings.BinanceReadOnly.check',side_effect=ValueError('Rejected')):
                with self.assertRaises(ValueError): s.check(dict(api_key='A'*32,secret_key='B'*32,save=True))
            self.assertFalse(s.vault.exists());self.assertIsNone(s.last_test)
    @unittest.skipUnless(os.name=='nt','Windows DPAPI only')
    def test_windows_encryption_roundtrip(self):
        value=b'not-a-real-key';cipher=protect(value)
        self.assertNotIn(value,cipher);self.assertEqual(protect(cipher,decrypt=True),value)
    @unittest.skipUnless(os.name!='nt','Non-Windows test')
    def test_no_plaintext_fallback(self):
        with self.assertRaises(ValueError):protect(b'secret')
    def test_local_csrf_and_secret_read_boundaries(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'dashboard.html';p.write_text('<head></head>')
            server=local_portal(WalletView(),None,p,SettingsStore(d));base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/') as r:html=r.read().decode()
                token=re.search(r'CASH_CSRF="([^"]+)"',html)[1]
                def post(path,csrf,origin):
                    req=urllib.request.Request(base+path,data=b'{"leverage":5}',headers={'Content-Type':'application/json','X-Cash-CSRF':csrf,'Origin':origin})
                    return urllib.request.urlopen(req)
                for csrf,origin in [('',base),(token,'https://evil.example')]:
                    with self.assertRaises(urllib.error.HTTPError) as e:post('/api/settings',csrf,origin)
                    self.assertEqual(e.exception.code,403)
                with post('/api/settings',token,base) as r:
                    body=json.load(r);self.assertEqual(body['settings']['leverage'],5)
                    self.assertNotIn('secret',json.dumps(body))
                with self.assertRaises(urllib.error.HTTPError) as e:post('/api/orders',token,base)
                self.assertEqual(e.exception.code,404)
            finally:server.shutdown();server.server_close()

if __name__=='__main__': unittest.main()
