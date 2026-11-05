"""Check wallet pool diversity without querying external APIs."""
import importlib.util
import pathlib
import unittest

P = pathlib.Path(__file__).with_name('leaderboard_expand.py')
spec=importlib.util.spec_from_file_location('lb',P)
lb=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)

def wallet(i, daily=1.0, month=1.0):
    w={}
    for period in lb.WINDOWS:
        score=daily if period=='day' else month if period=='month' else 1.0
        w[period]={'pnl_usd':score,'roi':score/1000,'volume_usd':score*100}
    return {'address':'0x'+format(i+1,'040x'),'account_value_usd':100000,'windows':w}

class LeaderboardSelectionTests(unittest.TestCase):
    def test_keeps_monthly_swing_candidates_not_only_daily(self):
        rows=[wallet(i,daily=100-i,month=1) for i in range(30)]
        rows += [wallet(100+i,daily=1,month=100-i) for i in range(30)]
        pick=lb.select(rows,[])
        ids={r['address'] for r in pick}
        self.assertLessEqual(len(pick),lb.POOL_LIMIT)
        self.assertGreaterEqual(len(pick),30)
        self.assertIn(wallet(100)['address'],ids)
        self.assertIn(wallet(0)['address'],ids)

    def test_keeps_existing_watchlist_seeds(self):
        addr='0x'+'f'*40
        picked=lb.select([wallet(i) for i in range(60)],[addr])
        self.assertEqual(picked[0]['address'],addr)
        self.assertEqual(picked[0]['seed'],'existing_watchlist')

if __name__=='__main__':
    unittest.main()
