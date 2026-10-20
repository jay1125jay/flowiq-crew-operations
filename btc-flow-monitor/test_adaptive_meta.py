import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
import adaptive_meta as m

A='0x'+'1'*40
B='0x'+'2'*40
BASE=dt.datetime(2026,10,20,tzinfo=dt.timezone.utc)
def inputs(i=0,side='LONG',price=50000):
    now=(BASE+dt.timedelta(minutes=i*5)).isoformat()
    flags=dict(paper_only=True,real_trading_enabled=False,errors=[])
    coh=dict(flags,generated_at=now,wallets=[dict(address=A,last_scanned_at=now,category_flags={'CONSISTENT':True},forward={})])
    feed=dict(flags,generated_at=now,btc_mid_usd=price,wallets={A:side},catalog_wallet_count=1,observed_wallet_count=1)
    end=int((BASE+dt.timedelta(minutes=i*5)).timestamp()*1000)
    candles=[dict(T=end-(24-j)*300000-1,o=price,h=price+10,l=price-10,c=price,v=1) for j in range(24)]
    market=dict(flags,generated_at=now,funding_rate=.00001,open_interest_btc=1000,reference_price=price,candles=candles)
    rank=dict(flags,updated_at=now,status='OK',ranked_wallets=[dict(address=A,paper_candidate=True)])
    return coh,feed,now,market,rank

def run(state=None,i=0,side='LONG',price=50000):
    return m.advance(state or {},*inputs(i,side,price))

class PaperTests(unittest.TestCase):
    def test_six_accounts_are_independent(self):
        s=run(); self.assertEqual(set(s['accounts']),set(m.ENGINES))
        self.assertEqual(len({id(x) for x in s['accounts'].values()}),6)
        self.assertTrue(s['paper_only']);self.assertFalse(s['real_trading_enabled'])
    def test_real_legacy_regression_preserves_snapshot(self):
        old={'schema_version':1,'accounts':{'SMART_MONEY':{'closed':[]}},'history':[{'at':'old','price':50000}]}
        s=run(old);self.assertEqual(s['legacy_snapshot'],old)
        self.assertIn('cash',s['accounts']['SMART_MONEY'])
        self.assertEqual(old['schema_version'],1)
    def test_schema2_ledgers_not_mixed_with_new_epoch(self):
        old={'schema_version':2,'accounts':{'SMART_MONEY':{'cash':1111,'closed':[{'pnl_usd':111}]}}}
        s=run(old);self.assertEqual(s['legacy_snapshot'],old);self.assertEqual(s['accounts']['SMART_MONEY']['closed_count'],0)
    def test_round_trip_and_cash_reconcile(self):
        s=run();s=run(s,1,'SHORT',51000);a=s['accounts']['SMART_MONEY']
        self.assertEqual(a['closed_count'],1);self.assertGreater(a['closed'][0]['pnl_usd'],0)
        expected=1000+sum(t['pnl_usd'] for t in a['closed'])-sum(p['entry_fee']+p['funding_usd'] for p in a['positions'].values())
        self.assertAlmostEqual(a['cash'],expected)
    def test_constant_price_roundtrip_loses_all_costs(self):
        s=run();s=run(s,1,'FLAT');a=s['accounts']['SMART_MONEY']
        self.assertLess(a['net_pnl_usd'],-.79);self.assertAlmostEqual(a['net_pnl_usd'],a['closed'][0]['pnl_usd'])
        self.assertGreater(a['fees_usd'],.49)
    def test_mark_includes_exit_slippage(self):
        a=run()['accounts']['SMART_MONEY'];self.assertLess(a['equity_usd'],999.3)
    def test_whale_original_baseline_then_change(self):
        s=run();self.assertFalse(s['accounts']['WHALE_COPY']['positions'])
        s=run(s,1,'SHORT');p=s['accounts']['WHALE_COPY']['positions'][A]
        self.assertEqual(p['side'],'SHORT');self.assertEqual(p['notional_usd'],m.NOTIONAL/3)
    def test_smart_only_classified_wallets(self):
        c,f,n,d,r=inputs();c['wallets'][0]['category_flags']={}
        self.assertEqual(m.advance({},c,f,n,d,r)['decisions']['SMART_MONEY']['signal'],'WAIT')
    def test_wait_closes_without_new_position(self):
        s=run();s=run(s,1,'FLAT');self.assertFalse(s['accounts']['SMART_MONEY']['positions'])
    def test_duplicate_is_idempotent(self):
        s=run();self.assertEqual(run(s),s)
    def test_out_of_order_rejected(self):
        s=run(i=1)
        with self.assertRaises(ValueError):run(s,0)
    def test_stale_and_future_rejected(self):
        for when in ((BASE-dt.timedelta(hours=1)).isoformat(),(BASE+dt.timedelta(seconds=1)).isoformat()):
            c,f,n,d,r=inputs();f['generated_at']=when
            with self.assertRaises(ValueError):m.advance({},c,f,n,d,r)
    def test_live_missing_flags_and_feed_errors_rejected(self):
        for key,value in [('real_trading_enabled',True),('real_trading_enabled',None),('errors',['timeout']),('observed_wallet_count',0),('btc_mid_usd',float('nan'))]:
            c,f,n,d,r=inputs();f[key]=value
            with self.assertRaises(ValueError):m.advance({},c,f,n,d,r)
    def test_partial_catalog_rejected(self):
        c,f,n,d,r=inputs();c['wallets'].append({'address':B})
        with self.assertRaises(ValueError):m.advance({},c,f,n,d,r)
    def test_candle_gap_and_future_rejected(self):
        c,f,n,d,r=inputs();d['candles'][-1]['T']+=300000
        with self.assertRaises(ValueError):m.advance({},c,f,n,d,r)
    def test_prior_requires_30_closed_trades(self):
        self.assertEqual(m.reliability({'closed':[{'pnl_usd':100}]*29}),.5)
    def test_lifetime_metrics_not_truncated(self):
        rows=[{'pnl_usd':1}]*150+[{'pnl_usd':-2}]*150
        s=m.stats(rows);self.assertEqual(s['n'],300);self.assertEqual(s['net'],-150);self.assertEqual(s['pf'],.5)
    def test_weights_bounded_and_frozen_between_closes(self):
        s=run();s['accounts']['SMART_MONEY']['closed']=[{'pnl_usd':100,'regime':'LOW_VOL'}]*50
        old=s['engine_weights'].copy();s=run(s,1)
        self.assertAlmostEqual(sum(s['engine_weights'].values()),1)
        self.assertLessEqual(max(abs(s['engine_weights'][k]-old[k]) for k in old),.01000001)
        weights=s['engine_weights'].copy();s=run(s,2);self.assertEqual(weights,s['engine_weights'])
    def test_oi_growth_alone_not_bullish(self):
        self.assertEqual(m.derivatives({'funding_rate':0,'open_interest_btc':110,'reference_price':50000},{'open_interest_btc':100,'reference_price':50000}),0)
    def test_market_trend_from_closed_candles(self):
        _,_,_,d,_=inputs()
        for i,c in enumerate(d['candles']):c.update(c=50000+i*100,h=50010+i*100,l=49990+i*100)
        score,_=m.market_structure(d['candles']);self.assertGreater(score,.15)
    def test_funding_direction(self):
        s=run();s=run(s,1);self.assertGreater(s['accounts']['SMART_MONEY']['funding_usd'],0)
        s=run(side='SHORT');s=run(s,1,'SHORT');self.assertLess(s['accounts']['SMART_MONEY']['funding_usd'],0)
    def test_risk_budget_and_insolvency(self):
        a=m.account();a['cash']=1;m.open_position(a,'BTC','LONG',50000,BASE.isoformat(),'RANGE');self.assertFalse(a['positions'])
    def test_sampled_liquidation_does_not_reenter(self):
        s=run(side='SHORT');s=run(s,1,'SHORT',200000)
        a=s['accounts']['SMART_MONEY'];self.assertEqual(a['liquidations'],1);self.assertFalse(a['positions'])
    def test_serializable_finite_output(self):
        json.dumps(run(),allow_nan=False)

if __name__=='__main__':unittest.main()
