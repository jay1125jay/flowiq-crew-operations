import importlib.util, pathlib, unittest
P=pathlib.Path(__file__).with_name('trader_discovery.py'); S=importlib.util.spec_from_file_location('td',P); td=importlib.util.module_from_spec(S); S.loader.exec_module(td)

def f(t,start,sz,side,pnl='0'):
 return {'coin':'BTC','time':t,'tid':t,'startPosition':str(start),'sz':str(sz),'side':side,'closedPnl':pnl,'px':'100','fee':'0'}

def rank(**kw):
 d={'address':'0x'+'1'*40,'history_sample_closes':100,'history_sample_win_rate_pct':70,'history_sample_net_pnl_usd':20000,'history_avg_fill_notional_usd':30000,'forward_closes':100,'forward_net_pnl_usd':10000,'forward_drawdown_usd':100,'forward_profit_factor':2,'forward_largest_win_share_pct':5,'forward_observed_days':8,'verified_whale':False}; d.update(kw); return d

class TraderDiscoveryTests(unittest.TestCase):
 def test_complete_episode(self):
  e=td.holding_episodes([f(1000,0,1,'B'),f(61000,1,1,'A')]); self.assertEqual(len(e),1); self.assertEqual(e[0]['holding_seconds'],60)
 def test_partial_close_does_not_finish_episode(self):
  e=td.holding_episodes([f(1000,0,2,'B'),f(61000,2,1,'A'),f(121000,1,1,'A')]); self.assertEqual(len(e),1); self.assertEqual(e[0]['holding_seconds'],120)
 def test_reversal_closes_and_reopens(self):
  e=td.holding_episodes([f(1000,0,1,'B'),f(61000,1,2,'A'),f(121000,-1,1,'B')]); self.assertEqual([x['side'] for x in e],['LONG','SHORT'])
 def test_scalper_and_core_categories(self):
  fills=[]
  for i in range(10):
   t=i*120000; fills += [f(t,0,1,'B'),f(t+60000,1,1,'A')]
  x=td.classify(rank(),fills); self.assertTrue(x['category_flags']['SCALPER']); self.assertTrue(x['category_flags']['WHALE']); self.assertTrue(x['category_flags']['HIGH_WIN_RATE']); self.assertTrue(x['category_flags']['HIGH_PROFIT']); self.assertTrue(x['category_flags']['CONSISTENT'])
 def test_swing(self):
  fills=[]
  for i in range(5):
   t=i*20000000; fills += [f(t,0,1,'B'),f(t+18000000,1,1,'A')]
  self.assertTrue(td.classify(rank(),fills)['category_flags']['SWING'])

if __name__=='__main__': unittest.main()
