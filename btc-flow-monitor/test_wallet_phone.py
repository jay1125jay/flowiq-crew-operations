import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from wallet_phone import WalletView, local_portal


class PhoneViewTests(unittest.TestCase):
    def setUp(self):
        self.view=WalletView()
        self.ledger=dict(paper_only=True,real_trading_enabled=False,
            accounts={'whale':{'cash':100,'closed':[{'net_krw':5}]}},
            archived_accounts={'old':{}},cycles=[{}])
        self.view.update(self.ledger,True,0)

    def test_direct_state_keeps_history_but_excludes_archives(self):
        result=self.view.read()
        self.assertEqual(result['accounts'],self.ledger['accounts'])
        self.assertNotIn('archived_accounts',result)
        self.assertNotIn('cycles',result)
        self.assertTrue(result['pc_live']['connected'])

    def test_unchanged_state_sends_only_heartbeat(self):
        rev=self.view.read()['pc_live']['revision']
        self.view.update(self.ledger,False,3)
        response=self.view.read_since(str(rev))
        self.assertTrue(response['unchanged'])
        self.assertNotIn('accounts',response)
        self.assertFalse(response['pc_live']['connected'])
        self.assertEqual(response['pc_live']['pending'],3)
        self.view.update(dict(self.ledger,accounts={'whale':{'cash':200}}),True,0)
        self.assertEqual(self.view.read_since(str(rev))['accounts']['whale']['cash'],200)

    def test_local_portal_denies_other_origin_and_arbitrary_files(self):
        class Share:
            def snapshot(self): return {'status':'STARTING'}
            def qr(self): return b''
        with tempfile.TemporaryDirectory() as folder:
            dashboard=Path(folder)/'dashboard.html'
            dashboard.write_text('<html><head></head><body>same dashboard</body></html>')
            server=local_portal(self.view,Share(),dashboard)
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base) as response:
                    self.assertIn(b'BTC_LOCAL_RUNTIME=true',response.read())
                with urllib.request.urlopen(base+'/api/status?since=1') as response:
                    self.assertTrue(json.load(response)['unchanged'])
                for path,headers,status in [('/api/phone-share',{'Origin':'https://unrelated.example'},403),
                                            ('/pending-paper.sqlite3',{},404),
                                            ('/api/status',{'Host':'unrelated.example'},403)]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base+path,headers=headers))
                    self.assertEqual(error.exception.code,status)
            finally:
                server.shutdown()
                server.server_close()

if __name__=='__main__': unittest.main()
