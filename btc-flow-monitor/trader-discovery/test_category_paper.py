import importlib.util,pathlib,unittest
P=pathlib.Path(__file__).with_name('category_paper.py')
spec=importlib.util.spec_from_file_location('category_paper',P)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
ADDR='0x'+'1'*40
ADDR2='0x'+'2'*40
def cohort(flags,addr=ADDR):
 return {'paper_only':True,'wallets':[{'address':addr,'category_flags':flags}]}
def feed(side,addr=ADDR):
 return {'paper_only':True,'btc_mid_usd':50000,'wallets':{addr:side}}
class PaperTests(unittest.TestCase):
 def test_first_observation_immediately_opens(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0')
  self.assertEqual(s['accounts']['SCALPER']['open_count'],1)
  self.assertEqual(s['accounts']['SCALPER']['positions'][ADDR]['side'],'LONG')
  self.assertEqual(s['follower_mode'],'IMMEDIATE_CURRENT_POSITION')
 def test_flip_closes_and_reopens_new_side(self):
  s=mod.advance({},cohort({'SCALPER':True}),feed('LONG'),'t0')
  s=mod.advance(s,cohort({'SCALPER':True}),feed('SHORT'),'t1')
  self.assertEqual(s['accounts']['SCALPER']['closed_count'],1)
  self.assertEqual(s['accounts']['SCALPER']['open_count'],1)
  self.assertEqual(s['accounts']['SCALPER']['positions'][ADDR]['side'],'SHORT')
  self.assertEqual(s['accounts']['SCALPER']['closed'][-1]['reason'],'SOURCE_FLIP')
 def test_flat_closes(self):
  s=mod.advance({},cohort({'WHALE':True}),feed('LONG'),'t0')
  s=mod.advance(s,cohort({'WHALE':True}),feed('FLAT'),'t1')
  self.assertEqual(s['accounts']['WHALE']['open_count'],0)
  self.assertEqual(s['accounts']['WHALE']['closed_count'],1)
  self.assertEqual(s['accounts']['WHALE']['closed'][-1]['reason'],'SOURCE_FLAT')
 def test_same_wallet_can_be_followed_by_multiple_category_accounts(self):
  flags={'WHALE':True,'HIGH_WIN_RATE':True,'SCALPER':True}
  s=mod.advance({},cohort(flags),feed('LONG'),'t0')
  self.assertEqual(s['accounts']['WHALE']['open_count'],1)
  self.assertEqual(s['accounts']['HIGH_WIN_RATE']['open_count'],1)
  self.assertEqual(s['accounts']['SCALPER']['open_count'],1)
  self.assertEqual(s['accounts']['SWING']['open_count'],0)
 def test_reject_nonpaper(self):
  with self.assertRaises(ValueError):mod.advance({},cohort({'WHALE':True}),{'paper_only':False,'btc_mid_usd':50000},'t0')
if __name__=='__main__':unittest.main()
