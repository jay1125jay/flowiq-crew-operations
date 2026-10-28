import importlib.util,pathlib,unittest,copy
P=pathlib.Path(__file__).with_name('category_paper.py');spec=importlib.util.spec_from_file_location('category_paper',P);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ADDR='0x'+'1'*40

def cohort(flags,addr=ADDR):return {'paper_only':True,'wallets':[{'address':addr,'category_flags':flags}]}
def feed(side,price=50000,addr=ADDR):return {'paper_only':True,'btc_mid_usd':price,'wallets':{addr:side}}
def many_swing(n=6):
 addrs=['0x'+format(i+1,'040x') for i in range(n)]
 coh={'paper_only':True,'wallets':[{'address':a,'category_flags':{'SWING':True}} for a in addrs]}
 fd={'paper_only':True,'btc_mid_usd':50000,'wallets':{a:'LONG' for a in addrs}}
 return addrs,coh,fd

class PaperTests(unittest.TestCase):
 def test_creates_only_5x_10x_accounts(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');self.assertEqual(s['account_count'],6);self.assertEqual(s['schema_version'],8);self.assertNotIn('SCALPER_5X',s['accounts']);self.assertIn('SCALPER_10X',s['accounts']);self.assertNotIn('SCALPER',s['accounts'])
 def test_leverage_notional_and_margin(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');p5=s['accounts']['WHALE_10X']['positions'][ADDR];p10=s['accounts']['WHALE_10X']['positions'][ADDR];self.assertGreater(p5['margin_usd'],0);self.assertAlmostEqual(p5['notional_usd'],p5['margin_usd']*10);self.assertAlmostEqual(p10['notional_usd'],p10['margin_usd']*10)
 def test_non_whale_flip_closes_and_reopens(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'2026-10-19T00:05:00+00:00')
  for k in ('SCALPER_10X',):self.assertEqual(s['accounts'][k]['closed_count'],1);self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertEqual(s['accounts'][k]['closed'][-1]['reason'],'SOURCE_FLIP')
 def test_whale_flip_requires_next_observation_confirmation(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'2026-10-19T00:05:00+00:00')
  for k in ('WHALE_10X',):self.assertNotIn(ADDR,s['accounts'][k]['positions']);self.assertEqual(s['accounts'][k]['pending_reversals'][ADDR]['side'],'SHORT')
  s=mod.advance(s,cohort({'WHALE':True}),feed('SHORT'),'2026-10-19T00:10:00+00:00')
  for k in ('WHALE_10X',):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'SHORT');self.assertNotIn(ADDR,s['accounts'][k]['pending_reversals'])
 def test_swing_ignores_early_flip(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T00:30:00+00:00')
  for k in ('SWING_10X',):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'LONG');self.assertEqual(s['accounts'][k]['closed_count'],0)
 def test_swing_requires_two_post_hold_reversal_observations(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:00:00+00:00')
  for k in ('SWING_10X',):self.assertEqual(s['accounts'][k]['positions'][ADDR]['side'],'LONG');self.assertEqual(s['accounts'][k]['pending_reversals'][ADDR]['count'],1)
  s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:05:00+00:00')
  for k in ('SWING_10X',):self.assertNotIn(ADDR,s['accounts'][k]['positions']);self.assertEqual(s['accounts'][k]['closed'][-1]['reason'],'SWING_REVERSAL_CONFIRMED')
 def test_swing_reversal_cancels_if_original_direction_returns(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('SHORT'),'2026-10-19T01:00:00+00:00');s=mod.advance(s,cohort({'SWING':True}),feed('LONG'),'2026-10-19T01:05:00+00:00');self.assertNotIn(ADDR,s['accounts']['SWING_10X']['pending_reversals']);self.assertEqual(s['accounts']['SWING_10X']['positions'][ADDR]['side'],'LONG')
 def test_flat_closes_whale(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'2026-10-19T00:05:00+00:00');self.assertEqual(s['accounts']['WHALE_10X']['open_count'],0)
 def test_api_error_does_not_close(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),{'paper_only':True,'btc_mid_usd':50000,'wallets':{},'errors':[{'address':ADDR}]},'2026-10-19T00:05:00+00:00');self.assertEqual(s['accounts']['WHALE_10X']['open_count'],1)
 def test_10x_liquidates_without_same_cycle_reentry(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG',50000),'2026-10-19T00:00:00+00:00');s=mod.advance(s,cohort({'WHALE':True}),feed('LONG',45000),'2026-10-19T00:05:00+00:00');a=s['accounts']['WHALE_10X'];self.assertEqual(a['liquidations'],1);self.assertNotIn(ADDR,a['positions'])
 def test_reject_live_flag(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':True,'real_trading_enabled':True,'btc_mid_usd':50000},'2026-10-19T00:00:00+00:00')

class SwingCapitalTests(unittest.TestCase):
 def test_three_million_each_and_near_target_notional(self):
  s=mod.advance({},cohort({'SWING':True}),feed('LONG'),'2026-10-22T00:00:00+00:00')
  a5=s['accounts']['SWING_10X'];a10=s['accounts']['SWING_10X']
  for a in (a5,a10):
   self.assertEqual(a['starting_equity_krw'],3000000);self.assertEqual(a['starting_equity_usd'],2000);self.assertEqual(a['krw_per_usd'],1500);self.assertEqual(a['fx_mode'],'FIXED_SIMULATION_NOT_LIVE_FX');self.assertLessEqual(a['margin_used_krw']+a['cost_buffer_krw'],3000000.10)
  self.assertGreater(a10['total_notional_krw'],29500000);self.assertLess(a10['total_notional_krw'],30000000)
 def test_six_targets_share_account_capital_equally(self):
  addrs,coh,fd=many_swing(6);s=mod.advance({},coh,fd,'2026-10-22T00:00:00+00:00')
  for lev,target in ((10,30000000),):
   a=s['accounts'][f'SWING_{lev}X'];self.assertEqual(a['open_count'],6);margins=[a['positions'][x]['margin_usd'] for x in addrs];self.assertLess(max(margins)-min(margins),1e-9);self.assertLessEqual(a['margin_used_krw']+a['cost_buffer_krw'],3000000.10);self.assertGreater(a['total_notional_krw'],target*0.98);self.assertLess(a['total_notional_krw'],target)
 def test_archive_once_and_do_not_reset_on_next_run(self):
  old=mod._new_account('SWING',10);old['capital_epoch']='OLD_TEST';old['cash']=1234;old['closed']=[{'pnl_usd':234}]
  s={'accounts':{'SWING_10X':copy.deepcopy(old)},'legacy_unleveraged_accounts':{}}
  s=mod.advance(s,cohort({'SWING':True}),feed('LONG'),'2026-10-22T00:00:00+00:00');self.assertEqual(s['capital_archives'][0]['account'],old);a=copy.deepcopy(s['accounts']['SWING_10X']);s=mod.advance(s,cohort({'SWING':True}),feed('LONG'),'2026-10-22T00:05:00+00:00');self.assertEqual(len(s['capital_archives']),1);self.assertEqual(s['accounts']['SWING_10X']['cash'],a['cash']);self.assertEqual(s['accounts']['SWING_10X']['started_at'],a['started_at'])
 def test_other_categories_share_new_budget(self):
  s=mod.advance({},cohort({'WHALE':True,'SWING':True}),feed('LONG'),'2026-10-22T00:00:00+00:00')
  for key,a in s['accounts'].items():
   if a['category']!='SWING':self.assertEqual(a['starting_equity_usd'],2000)
  self.assertGreater(s['accounts']['WHALE_10X']['positions'][ADDR]['margin_usd'],0)

class TenOnlyTests(unittest.TestCase):
 def test_all_six_budgets_and_retired_history(self):
  _,c,f=many_swing(2)
  for w in c['wallets']:w['category_flags']={cat:True for cat in mod.CATS}
  old={'category':'SWING','leverage':5,'cash':1234,'positions':{},'closed':[]}
  s=mod.advance({'accounts':{'SWING_5X':copy.deepcopy(old)},'legacy_unleveraged_accounts':{}},c,f,'2026-10-24T00:00:00+00:00')
  self.assertEqual(len(s['accounts']),6)
  self.assertEqual(s['capital_archives'][0]['account'],old)
  for a in s['accounts'].values():
   self.assertEqual(a['leverage'],10);self.assertEqual(a['starting_equity_krw'],3000000)
   self.assertGreater(a['total_notional_krw'],29500000);self.assertLess(a['total_notional_krw'],30000000)
   expected=a['equity_usd']-a['margin_used_usd']-a['remaining_execution_buffer_usd'];self.assertAlmostEqual(a['free_equity_usd'],expected,places=2);self.assertAlmostEqual(a['free_equity_krw'],a['free_equity_usd']*1500,places=1)
   self.assertEqual(a['open_count'],2)
  s=mod.advance(s,c,f,'2026-10-24T00:05:00+00:00')
  self.assertEqual(len(s['capital_archives']),1)

if __name__=='__main__':unittest.main()
