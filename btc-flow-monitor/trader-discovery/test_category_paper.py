import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('category_paper.py');spec=importlib.util.spec_from_file_location('category_paper',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ADDR='0x'+'1'*40
def cohort(flags,addr=ADDR):return {'paper_only':True,'wallets':[{'address':addr,'category_flags':flags}]}
def feed(side,price=50000,addr=ADDR):return {'paper_only':True,'btc_mid_usd':price,'wallets':{addr:side}}
class PaperTests(unittest.TestCase):
 def test_creates_only_5x_10x_accounts(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0');self.assertEqual(s['account_count'],12);self.assertEqual(s['schema_version'],5);self.assertIn('SCALPER_5X',s['accounts']);self.assertIn('SCALPER_10X',s['accounts']);self.assertNotIn('SCALPER',s['accounts'])
 def test_leverage_notional_and_margin(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');p5=s['accounts']['WHALE_5X']['positions'][ADDR];p10=s['accounts']['WHALE_10X']['positions'][ADDR];self.assertEqual(p5['margin_usd'],150);self.assertEqual(p5['notional_usd'],750);self.assertEqual(p10['notional_usd'],1500)
 def test_non_whale_flip_closes_and_reopens(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'t1')
  for k in ('SCALPER_5X','SCALPER_10X'):self.assertEqual(s['accounts'][k]['closed_count'],1);self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertEqual(s['accounts'][k]['closed'][-1]['reason'],'SOURCE_FLIP')
 def test_whale_flip_requires_next_observation_confirmation(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'t1')
  for k in ('WHALE_5X','WHALE_10X'):
   self.assertNotIn(ADDR,s['accounts'][k]['positions']);self.assertEqual(s['accounts'][k]['pending_reversals'][ADDR]['side'],'SHORT')
  s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'t2')
  for k in ('WHALE_5X','WHALE_10X'):
   self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertNotIn(ADDR,s['accounts'][k]['pending_reversals']);self.assertEqual(s['accounts'][k]['positions'][ADDR]['entry_reason'],'WHALE_REVERSAL_CONFIRMED')
 def test_whale_pending_flip_clears_on_flat(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'t1');s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'t2');self.assertNotIn(ADDR,s['accounts']['WHALE_5X']['pending_reversals']);self.assertEqual(s['accounts']['WHALE_5X']['open_count'],0)
 def test_flat_closes(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'t1');self.assertEqual(s['accounts']['WHALE_5X']['open_count'],0);self.assertEqual(s['accounts']['WHALE_10X']['closed'][-1]['reason'],'SOURCE_FLAT')
 def test_api_error_does_not_close(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':True}),{'paper_only':True,'btc_mid_usd':50000,'wallets':{},'errors':[{'address':ADDR}]},'t1');self.assertEqual(s['accounts']['WHALE_5X']['open_count'],1)
 def test_category_change_does_not_force_exit(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':False}),feed('LONG'),'t1');self.assertEqual(s['accounts']['WHALE_5X']['open_count'],1)
 def test_10x_liquidates_without_same_cycle_reentry(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG',50000),'t0');s=mod.advance(s,cohort({'WHALE':True}),feed('LONG',45000),'t1');a=s['accounts']['WHALE_10X'];self.assertEqual(a['liquidations'],1);self.assertEqual(a['closed'][-1]['reason'],'LIQUIDATION');self.assertNotIn(ADDR,a['positions']);self.assertEqual(s['accounts']['WHALE_5X']['liquidations'],0)
 def test_closed_trade_audit_fields(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0');s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'t1');t=s['accounts']['WHALE_5X']['closed'][0]
  for k in ('entry_at','exit_at','entry_price','exit_price','liquidation_price','leverage','margin_usd','notional_usd','pnl_usd','reason'):self.assertIn(k,t)
 def test_legacy_is_preserved(self):
  old={'accounts':{'WHALE':{'cash':999,'positions':{},'closed':[]}}};s=mod.advance(old,cohort({'WHALE':False}),feed('FLAT'),'t0');self.assertIn('WHALE',s['legacy_unleveraged_accounts']);self.assertNotIn('WHALE',s['accounts'])
 def test_reject_live_flag(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':True,'real_trading_enabled':True,'btc_mid_usd':50000},'t0')
 def test_reject_nonpaper(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':False,'btc_mid_usd':50000},'t0')
if __name__=='__main__':unittest.main()
