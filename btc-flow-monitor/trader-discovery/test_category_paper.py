import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('category_paper.py')
spec=importlib.util.spec_from_file_location('category_paper',P)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ADDR='0x'+'1'*40
def cohort(flags):
 return {'paper_only':True,'wallets':[{'address':ADDR,'category_flags':flags}]}
def feed(side):
 return {'paper_only':True,'btc_mid_usd':50000,'wallets':{ADDR:side}}
class PaperTests(unittest.TestCase):
 def test_first_observation_is_baseline_only(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0')
  self.assertEqual(s['accounts']['SCALPER']['open_count'],0)
  self.assertEqual(s['accounts']['SCALPER']['equity_usd'],1000)
 def test_forward_flip_opens_then_closes(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0')
  s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'t1')
  self.assertEqual(s['accounts']['SCALPER']['open_count'],1)
  s=mod.advance(s,cohort({'SCALPER':True}),feed('FLAT'),'t2')
  self.assertEqual(s['accounts']['SCALPER']['closed_count'],1)
  self.assertEqual(s['accounts']['SCALPER']['open_count'],0)
  self.assertLess(s['accounts']['SCALPER']['equity_usd'],1000)
 def test_cohort_isolation(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0')
  s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'t1')
  self.assertEqual(s['accounts']['SWING']['open_count'],0)
  self.assertEqual(s['accounts']['WHALE']['open_count'],0)
 def test_reject_nonpaper(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':False,'btc_mid_usd':50000},'t0')
if __name__=='__main__':unittest.main()
