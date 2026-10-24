import copy
import json
import tempfile
import unittest

import category_realtime_runtime as crt
import realtime_runtime as base
from test_adaptive_meta import inputs, BASE

NOW=BASE.timestamp()
A='0x'+'1'*40

def bundle(side='LONG',offset=0):
    c,f,n,m,r=inputs(side=side)
    stamp=base.iso(NOW+offset)
    for obj,field in ((c,'generated_at'),(f,'generated_at'),(m,'generated_at'),(r,'updated_at')):
        obj[field]=stamp
    c['wallets'][0]['category_flags']={cat:True for cat in crt.category.CATS}
    return dict(started_at=NOW+offset,cohorts=c,positions=f,market=m,ranking=r)

def message(now,price=50000):
    return {'channel':'bbo','data':{'coin':'BTC','time':int(now*1000),'bbo':[{'px':str(price-1)},{'px':str(price+1)}]}}

class CategoryRealtimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=base.Store(self.temp.name)
        self.runner=crt.CombinedRunner(self.store)
        self.q=base.Quotes();self.q.connected=True

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def tick(self,now=NOW,b=None,price=50000):
        self.q.receive(message(now,price),now)
        return self.runner.tick(self.q,b or bundle(),now)

    def test_six_category_accounts_bootstrap_before_first_source(self):
        c=self.runner.category_state
        self.assertEqual(set(c['accounts']),crt.EXPECTED_KEYS)
        self.assertEqual(c['account_count'],6)
        self.assertEqual(c['feed_mode'],'WAITING_FOR_FIRST_LIVE_SOURCE')
        self.assertIsNone(self.runner.category_source_id)
        for a in c['accounts'].values():
            self.assertEqual(a['starting_equity_krw'],3000000)
            self.assertEqual(a['equity_krw'],3000000)
            self.assertEqual(a['leverage'],10)
            self.assertEqual(a['open_count'],0)
        payload=json.loads((crt.Path(self.temp.name)/'category-paper-realtime.json').read_text())
        self.assertEqual(payload['version'],1)
        self.assertIsNone(payload['source_id'])
        self.assertEqual(payload['state']['account_count'],6)

    def test_six_category_accounts_are_3m_10x_and_separate(self):
        self.assertTrue(self.tick())
        c=self.runner.category_state
        self.assertEqual(set(c['accounts']),crt.EXPECTED_KEYS)
        self.assertEqual(c['account_count'],6)
        for a in c['accounts'].values():
            self.assertEqual(a['starting_equity_krw'],3000000)
            self.assertEqual(a['leverage'],10)
            self.assertLessEqual(a['margin_used_krw']+a['cost_buffer_krw'],3000000.1)
            self.assertGreaterEqual(a['free_equity_krw'],-1.0)
            self.assertLessEqual(a['total_notional_krw'],30000000.1)
        self.assertNotIn('category_competition',self.runner.state)
        payload=json.loads((crt.Path(self.temp.name)/'category-paper-realtime.json').read_text())
        self.assertEqual(payload['version'],1)
        self.assertEqual(payload['state']['account_count'],6)

    def test_same_source_marks_price_without_replaying_signal(self):
        self.tick()
        first=copy.deepcopy(self.runner.category_state)
        same=bundle('SHORT',0)
        self.tick(NOW+1,same,50100)
        self.assertEqual(self.runner.category_source_events,1)
        for key in crt.EXPECTED_KEYS:
            self.assertEqual(self.runner.category_state['accounts'][key]['positions'][A]['side'],'LONG')
        self.assertNotEqual(self.runner.category_state['accounts']['WHALE_10X']['equity_krw'],first['accounts']['WHALE_10X']['equity_krw'])
        self.assertTrue(self.runner.category_state['runtime_mark_only'])

    def test_whale_confirmation_counts_real_source_observations_not_seconds(self):
        self.tick()
        self.tick(NOW+1,bundle('SHORT',1))
        w=self.runner.category_state['accounts']['WHALE_10X']
        self.assertNotIn(A,w['positions']);self.assertEqual(w['pending_reversals'][A]['side'],'SHORT')
        same=bundle('SHORT',1)
        self.tick(NOW+2,same)
        self.assertNotIn(A,self.runner.category_state['accounts']['WHALE_10X']['positions'])
        self.tick(NOW+3,bundle('SHORT',3))
        self.assertEqual(self.runner.category_state['accounts']['WHALE_10X']['positions'][A]['side'],'SHORT')

    def test_public_payload_labels_category_and_adaptive_separately(self):
        p0=self.runner.public(self.q,None,NOW)
        self.assertEqual(p0['category_account_count'],6)
        self.assertEqual(len(p0['category_rows']),6)
        self.assertFalse(p0['category_healthy'])
        self.tick();p=self.runner.public(self.q,bundle(),NOW)
        self.assertEqual(p['category_mode'],'PC_REALTIME_6_CATEGORY_PAPER_SEPARATE_FROM_ADAPTIVE')
        self.assertEqual(p['category_account_count'],6)
        self.assertEqual(len(p['category_rows']),6)
        self.assertIn('competition',p);self.assertIn('category_competition',p)
        self.assertIsNot(p['competition'],p['category_competition'])
        self.assertTrue(p['paper_only']);self.assertFalse(p['real_trading_enabled'])

if __name__=='__main__':unittest.main()
