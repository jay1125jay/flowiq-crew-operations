import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import adaptive_meta as engine
import realtime_runtime as rt
from test_adaptive_meta import inputs, BASE

NOW = BASE.timestamp()

def bundle(side='LONG', offset=0):
    c, f, n, m, r = inputs(side=side)
    for obj, field in ((c,'generated_at'),(f,'generated_at'),(m,'generated_at'),(r,'updated_at')):
        obj[field] = rt.iso(NOW+offset)
    return dict(started_at=NOW+offset, cohorts=c, positions=f, market=m, ranking=r)

def message(now, price=50000):
    return {'channel':'bbo','data':{'coin':'BTC','time':int(now*1000),
        'bbo':[{'px':str(price-1)},{'px':str(price+1)}]}}

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = rt.Store(self.temp.name)
        self.runner = rt.Runner(self.store)
        self.q = rt.Quotes()
        self.q.connected = True

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def tick(self, now=NOW, b=None, price=50000):
        self.q.receive(message(now,price),now)
        return self.runner.tick(self.q,b or bundle(),now)

    def test_separate_epoch_six_accounts_and_costs(self):
        self.assertTrue(self.tick())
        s = self.runner.state['competition']
        self.assertEqual(set(s['accounts']),set(engine.ENGINES))
        self.assertEqual(s['legacy_snapshot'],{})
        self.assertLess(s['accounts']['SMART_MONEY']['equity_usd'],1000)
        self.assertTrue(s['paper_only']);self.assertFalse(s['real_trading_enabled'])

    def test_one_second_evaluation_does_not_reenter(self):
        self.tick()
        first = copy.deepcopy(self.runner.state['competition']['accounts']['SMART_MONEY'])
        for second in range(1,61):self.tick(NOW+second)
        a = self.runner.state['competition']['accounts']['SMART_MONEY']
        self.assertEqual(a['closed_count'],0)
        self.assertEqual(a['fees_usd'],first['fees_usd'])
        self.assertEqual(self.runner.state['ticks'],61)
        self.assertAlmostEqual(a['funding_usd'],a['positions']['BTC']['qty']*50000*.00001/60)

    def test_persist_restart_replay_is_noop(self):
        self.tick()
        expected = copy.deepcopy(self.runner.state)
        self.store.close();self.store = rt.Store(self.temp.name)
        self.runner = rt.Runner(self.store)
        self.assertFalse(self.runner.tick(self.q,bundle(),NOW+1))
        self.assertEqual(self.runner.state,expected)
        self.assertTrue(self.tick(NOW+2))
        self.assertEqual(self.runner.state['ticks'],2)

    def test_commit_failure_cannot_publish_cash_or_cursor(self):
        self.tick()
        before = copy.deepcopy(self.runner.state)
        with patch.object(self.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.tick(NOW+1,bundle('SHORT',1))
        self.assertEqual(self.runner.state,before)
        self.assertEqual(self.store.read(),before)

    def test_single_writer_lock(self):
        with self.assertRaises(RuntimeError):rt.Store(self.temp.name)

    def test_disconnected_stale_price_and_stale_sources_block(self):
        self.tick()
        before=copy.deepcopy(self.runner.state)
        self.q.disconnect()
        self.assertFalse(self.runner.tick(self.q,bundle(),NOW+1))
        self.assertEqual(self.runner.status,'DISCONNECTED')
        self.q.connected=True;self.q.receive(message(NOW+2),NOW+2)
        self.assertFalse(self.runner.tick(self.q,bundle(),NOW+10))
        self.assertEqual(self.runner.status,'STALE_PRICE')
        self.assertFalse(self.tick(NOW+121))
        self.assertEqual(self.runner.status,'STALE_SOURCE')
        self.assertEqual(self.runner.state,before)

    def test_source_error_blocks_even_fresh_bundle(self):
        self.q.receive(message(NOW),NOW)
        self.assertFalse(self.runner.tick(self.q,bundle(),NOW,'TimeoutError'))
        self.assertFalse(self.runner.state['competition'])

    def test_source_timestamps_are_not_rewritten(self):
        b=bundle(); original=copy.deepcopy(b)
        self.tick(NOW+1,b)
        q=self.runner.state['competition']['data_quality']
        self.assertEqual(q['source_at'],rt.iso(NOW))
        self.assertEqual(b,original)
        self.assertEqual(self.runner.state['competition']['last_observation_at'],rt.iso(NOW+1))

    def test_old_generated_at_cannot_be_hidden_by_new_bundle_start(self):
        b=bundle();b['started_at']=NOW+121
        with self.assertRaises(ValueError):self.tick(NOW+121,b)
        self.assertFalse(self.runner.state['competition'])

    def test_unknown_or_partial_feed_never_advances(self):
        for field,value in [('errors',['timeout']),('observed_wallet_count',0),('real_trading_enabled',True)]:
            b=bundle();b['positions'][field]=value
            with self.assertRaises(ValueError):self.tick(NOW,b)
            self.assertFalse(self.runner.state['competition'])

    def test_out_of_order_and_future_book_rejected(self):
        self.q.receive(message(NOW),NOW)
        self.assertFalse(self.q.receive(message(NOW-1),NOW))
        with self.assertRaises(ValueError):self.q.receive(message(NOW+10),NOW)
        self.assertEqual(self.q.latest['ms'],int(NOW*1000))

    def test_invalid_spread_and_nonfinite_book_rejected(self):
        for values in [('51000','50000'),('nan','50000'),('40000','50000')]:
            m=message(NOW);m['data']['bbo']=[{'px':v} for v in values]
            with self.assertRaises(ValueError):self.q.receive(m,NOW)
        self.assertIsNone(self.q.latest)

    def test_reconnect_cannot_replay_old_quote(self):
        self.q.receive(message(NOW),NOW)
        self.q.disconnect();self.q.connected=True
        self.assertFalse(self.q.receive(message(NOW),NOW+1))
        self.assertIsNone(self.q.latest)
        self.assertTrue(self.q.receive(message(NOW+2),NOW+2))

    def test_new_source_flips_once_and_cash_reconciles(self):
        self.tick();self.tick(NOW+1,bundle('SHORT',1));self.tick(NOW+2,bundle('SHORT',1))
        for a in self.runner.state['competition']['accounts'].values():
            expected=1000+sum(t['pnl_usd'] for t in a['closed'])-sum(p['entry_fee']+p['funding_usd'] for p in a['positions'].values())
            self.assertAlmostEqual(a['cash'],expected)
        self.assertEqual(self.runner.state['competition']['accounts']['SMART_MONEY']['closed_count'],1)

    def test_derivative_signal_baseline_frozen_between_source_updates(self):
        self.tick()
        b=bundle(offset=1);b['market'].update(open_interest_btc=1200,reference_price=50500)
        self.tick(NOW+1,b,50500)
        score=self.runner.state['competition']['decisions']['DERIVATIVES']['score']
        self.tick(NOW+2,b,50500)
        self.assertEqual(self.runner.state['competition']['decisions']['DERIVATIVES']['score'],score)
        self.assertGreater(score,0)

    def test_health_hides_stale_directions(self):
        self.tick()
        p=self.runner.public(self.q,bundle(),NOW+10)
        self.assertFalse(p['healthy'])
        self.assertTrue(all(x['signal']=='WAIT' for x in p['rows']))
        self.assertTrue(all(x['confidence'] is None for x in p['rows']))

    def test_environment_requires_explicit_paper_flags(self):
        for env in ({},{'PAPER_ONLY':'true','REAL_TRADING':'true'}):
            with patch.dict(os.environ,env,clear=True):
                with self.assertRaises(ValueError):rt.safety()
        with patch.dict(os.environ,{'PAPER_ONLY':'true','REAL_TRADING':'false'},clear=True):rt.safety()

    def test_corrupt_store_not_silently_reset(self):
        with self.store.db:self.store.db.execute("INSERT INTO state VALUES (1, 'bad json')")
        with self.assertRaises(ValueError):rt.Runner(self.store)

if __name__=='__main__':unittest.main()
