import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('adaptive_meta.py');s=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
A='0x'+'1'*40
def coh():return {'paper_only':True,'real_trading_enabled':False,'wallets':[{'address':A,'category_flags':{'WHALE':True,'CONSISTENT':True}}]}
def feed(side='LONG',price=50000):return {'paper_only':True,'real_trading_enabled':False,'btc_mid_usd':price,'wallets':{A:side}}
class T(unittest.TestCase):
 def test_six_independent_accounts(self):
  x=m.advance({},coh(),feed(),'2026-10-19T00:00:00+00:00');self.assertEqual(set(x['accounts']),set(m.ENGINES));self.assertEqual(x['schema_version'],2);self.assertFalse(x['real_trading_enabled'])
 def test_smart_money_enters_long(self):
  x=m.advance({},coh(),feed('LONG'),'2026-10-19T00:00:00+00:00');self.assertEqual(x['accounts']['SMART_MONEY']['position']['side'],'LONG')
 def test_flip_closes_and_records_costs(self):
  x=m.advance({},coh(),feed('LONG',50000),'2026-10-19T00:00:00+00:00');x=m.advance(x,coh(),feed('SHORT',51000),'2026-10-19T00:05:00+00:00');a=x['accounts']['SMART_MONEY'];self.assertEqual(a['closed_count'],1);self.assertGreater(a['closed'][0]['pnl_usd'],0);self.assertEqual(a['position']['side'],'SHORT')
 def test_wait_without_edge(self):
  c={'paper_only':True,'wallets':[]};f={'paper_only':True,'btc_mid_usd':50000,'wallets':{}};x=m.advance({},c,f,'2026-10-19T00:00:00+00:00');self.assertEqual(x['decisions']['ADAPTIVE_META']['signal'],'WAIT');self.assertIsNone(x['accounts']['ADAPTIVE_META']['position'])
 def test_market_structure_after_history(self):
  st={};c={'paper_only':True,'wallets':[]}
  for i,p in enumerate((50000,50100,50200,50300,50400,50500)):st=m.advance(st,c,{'paper_only':True,'btc_mid_usd':p,'wallets':{}},f'2026-10-19T00:{i:02d}:00+00:00')
  self.assertEqual(st['decisions']['MARKET_STRUCTURE']['signal'],'LONG')
 def test_weights_shrunk_without_sample(self):
  x=m.advance({},coh(),feed(),'2026-10-19T00:00:00+00:00');self.assertEqual(x['engine_weights']['SMART_MONEY'],.5)
 def test_reject_live(self):
  f=feed();f['real_trading_enabled']=True
  with self.assertRaises(ValueError):m.advance({},coh(),f,'2026-10-19T00:00:00+00:00')
if __name__=='__main__':unittest.main()
