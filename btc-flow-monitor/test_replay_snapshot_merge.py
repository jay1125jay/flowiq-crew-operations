"""Offline concurrency and coverage tests; never touch production PAPER files."""
import unittest
import replay_snapshot_merge as merge


def event(at, address='0x'+'1'*40):
    return {'id':at,'at':at,'btc_mid_usd':70000,'cohort_wallets':[],
            'wallets':{address:'LONG'}}


def log(events):
    return {'schema_version':1,'paper_only':True,'real_trading_enabled':False,'events':events}


def positions(at):
    return {'schema_version':2,'paper_only':True,'real_trading_enabled':False,
            'generated_at':at,'btc_mid_usd':70000,'wallets':{}}


class ReplayMergeTests(unittest.TestCase):
    def test_preserves_simultaneous_workflow_events(self):
        earlier='2026-11-05T10:00:00+00:00'
        later='2026-11-05T10:05:00+00:00'
        merged,pos=merge.merge(log([event(earlier)]),positions(earlier),
                               log([event(later)]),positions(later),
                               now=merge.ts('2026-11-05T10:06:00+00:00'))
        self.assertEqual([e['at'] for e in merged['events']],[earlier,later])
        self.assertEqual(merged['updated_at'],later)
        self.assertEqual(pos['generated_at'],later)
        self.assertEqual(merged['capture_health']['status'],'PASS')

    def test_sparse_snapshots_cannot_claim_pass(self):
        a='2026-11-05T02:00:00+00:00'
        b='2026-11-05T10:00:00+00:00'
        result,pos=merge.merge(log([event(b)]),positions(b),log([event(a)]),
                               positions(a),now=merge.ts('2026-11-05T10:01:00+00:00'))
        self.assertEqual(result['capture_health']['status'],'PARTIAL')
        self.assertGreater(result['capture_health']['missing_24h_estimate'],50)
        self.assertEqual(pos['generated_at'],b)

    def test_reject_live_flags(self):
        bad=log([event('2026-11-05T10:00:00+00:00')])
        bad['real_trading_enabled']=True
        with self.assertRaises(ValueError):
            merge.merge(bad,positions('2026-11-05T10:00:00+00:00'),
                        log([]),positions('2026-11-05T09:00:00+00:00'))
        

if __name__=='__main__':
    unittest.main()
