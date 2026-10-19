import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('adaptive_meta.py');s=importlib.util.spec_from_file_location('m',P);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
A='0x'+'1'*40
def coh():return {'paper_only':True,'real_trading_enabled':False,'wallets':[{'address':A,'category_flags':{'WHALE':True,'CONSISTENT':True}}]}
def feed(side='LONG',price=50000):return {'paper_only':True,'real_trading_enabled':False,'btc_mid_usd':price,'wallets':{A:side}}
class T(unittest.TestCase):
 def test_paper_only(self):
  x=m.advance({},coh(),feed(),'2026-10-19T00:00:00+00:00');self.assertTrue(x['paper_only']);self.assertFalse(x['real_trading_enabled']);self.assertIn('ADAPTIVE_META',x['decisions'])
 def test_smart_money_direction(self):
  x=m.advance({},coh(),feed('LONG'),'2026-10-19T00:00:00+00:00');self.assertEqual(x['decisions']['SMART_MONEY']['signal'],'LONG')
 def test_wait_without_edge(self):
  c={'paper_only':True,'wallets':[]};f={'paper_only':True,'btc_mid_usd':50000,'wallets':{}};x=m.advance({},c,f,'2026-10-19T00:00:00+00:00');self.assertEqual(x['decisions']['ADAPTIVE_META']['signal'],'WAIT')
 def test_market_structure_after_history(self):
  st={};c={'paper_only':True,'wallets':[]}
  for i,p in enumerate((50000,50100,50200,50300,50400,50500)):st=m.advance(st,c,{'paper_only':True,'btc_mid_usd':p,'wallets':{}},f'2026-10-19T00:{i:02d}:00+00:00')
  self.assertEqual(st['decisions']['MARKET_STRUCTURE']['signal'],'LONG')
 def test_reject_live(self):
  f=feed();f['real_trading_enabled']=True
  with self.assertRaises(ValueError):m.advance({},coh(),f,'2026-10-19T00:00:00+00:00')
if __name__=='__main__':unittest.main()
