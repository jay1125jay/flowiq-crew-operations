import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('category_paper.py');spec=importlib.util.spec_from_file_location('category_paper',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ADDR='0x'+'1'*40
def cohort(flags,addr=ADDR):return {'paper_only':True,'wallets':[{'address':addr,'category_flags':flags}]}
def feed(side,price=50000,addr=ADDR):return {'paper_only':True,'btc_mid_usd':price,'wallets':{addr:side}}
class PaperTests(unittest.TestCase):
 def test_creates_only_5x_10x_accounts(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');self.assertEqual(s['account_count'],12);self.assertEqual(s['schema_version'],6);self.assertIn('SCALPER_5X',s['accounts']);self.assertIn('SCALPER_10X',s['accounts']);self.assertNotIn('SCALPER',s['accounts'])
 def test_leverage_notional_and_margin(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');p5=s['accounts']['WHALE_5X']['positions'][ADDR];p10=s['accounts']['WHALE_10X']['positions'][ADDR];self.assertEqual(p5['margin_usd'],150);self.assertEqual(p5['notional_usd'],750);self.assertEqual(p10['notional_usd'],1500)
 def test_non_whale_flip_closes_and_reopens(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'2026-10-19T00:05:00+00:00')
  for k in ('SCALPER_5X','SCALPER_10X'):self.assertEqual(s['accounts'][k]['closed_count'],1);self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertEqual(s['accounts'][k]['closed'][-1]['reason'],'SOURCE_FLIP')
 def test_whale_flip_requires_next_observation_confirmation(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'2026-10-19T00:05:00+00:00')
  for k in ('WHALE_5X','WHALE_10X'):self.assertNotIn(ADDR,s['accounts'][k]['positions']);self.assertEqual(s['accounts'][k]['pending_reversals'][ADDR]['side'],'SHORT')
  s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'2026-10-19T00:10:00+00:00')
  for k in ('WHALE_5X','WHALE_10X'):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertNotIn(ADDR,s['accounts'][k]['pending_reversals'])
 def test_swing_ignores_early_flip(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T00:30:00+00:00')
  for k in ('SWING_5X','SWING_10X'):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'LONG');self.assertEqual(s['accounts'][k]['closed_count'],0)
 def test_swing_requires_two_post_hold_reversal_observations(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:00:00+00:00')
  for k in ('SWING_5X','SWING_10X'):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'LONG');self.assertEqual(s['accounts'][k]['pending_reversals'][ADDR]['count'],1)
  s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:05:00+00:00')
  for k in ('SWING_5X','SWING_10X'):self.assertNotIn(ADDR,s['accounts'][k]['positions']);self.assertEqual(s['accounts'][k]['closed'][-1]['reason'],'SWING_REVERSAL_CONFIRMED')
 def test_swing_reversal_cancels_if_original_direction_returns(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('LONG'),'2026-10-19T01:05:00+00:00');self.assertNotIn(ADDR,s['accounts']['SWING_5X']['pending_reversals']);self.assertEqual(s['accounts']['SWING_5X']['positions'][ADDR]['side'],'LONG')
 def test_flat_closes_whale(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'2026-10-19T00:05:00+00:00');self.assertEqual(s['accounts']['WHALE_5X']['open_count'],0)
 def test_api_error_does_not_close(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),{'paper_only':True,'btc_mid_usd':50000,'wallets':{},'errors':[{'address':ADDR}]},'2026-10-19T00:05:00+00:00');self.assertEqual(s['accounts']['WHALE_5X']['open_count'],1)
 def test_10x_liquidates_without_same_cycle_reentry(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG',50000),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('LONG',45000),'2026-10-19T00:05:00+00:00');a=s['accounts']['WHALE_10X'];self.assertEqual(a['liquidations'],1);self.assertNotIn(ADDR,a['positions'])
 def test_reject_live_flag(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':True,'real_trading_enabled':True,'btc_mid_usd':50000},'2026-10-19T00:00:00+00:00')
if __name__=='__main__':unittest.main()
