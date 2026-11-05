import copy
import unittest
import cloud_gap_recovery as recovery


class FakeCategory:
    @staticmethod
    def advance(state, cohort, feed, now):
        out=copy.deepcopy(state)
        out.setdefault('seen',[]).append((now,feed['btc_mid_usd'],dict(feed['wallets'])))
        out['updated_at']=now
        return out


class CloudGapRecoveryTests(unittest.TestCase):
    def test_replays_only_events_after_local_timestamp(self):
        original=recovery.fetch_events
        recovery.fetch_events=lambda:[
            {'at':'2026-11-02T00:00:00+00:00','btc_mid_usd':70000,'cohort_wallets':[],'wallets':{}},
            {'at':'2026-11-02T00:05:00+00:00','btc_mid_usd':70100,'cohort_wallets':[],'wallets':{'a':'LONG'}},
            {'at':'2026-11-02T00:10:00+00:00','btc_mid_usd':70200,'cohort_wallets':[],'wallets':{'a':'FLAT'}},
        ]
        try:
            state={'updated_at':'2026-11-02T00:01:00+00:00','seen':[]}
            out,source,meta=recovery.recover(state,None,FakeCategory,'2026-11-02T00:12:00+00:00')
        finally:
            recovery.fetch_events=original
        self.assertEqual(meta['status'],'REPLAYED')
        self.assertEqual(meta['replayed_events'],2)
        self.assertEqual(len(out['seen']),2)
        self.assertEqual(source,'2026-11-02T00:10:00+00:00')
        self.assertEqual(out['seen'][0][2],{'a':'LONG'})


    def test_sparse_eight_hour_replay_is_partial_not_complete(self):
        original=recovery.fetch_events
        recovery.fetch_events=lambda:[
            {'at':'2026-11-04T17:25:27+00:00','btc_mid_usd':70000,'cohort_wallets':[],'wallets':{'a':'LONG'}},
            {'at':'2026-11-04T18:44:38+00:00','btc_mid_usd':70100,'cohort_wallets':[],'wallets':{'a':'FLAT'}},
        ]
        try:
            state={'updated_at':'2026-11-04T14:02:06+00:00','seen':[]}
            out,source,meta=recovery.recover(state,None,FakeCategory,'2026-11-04T22:21:19+00:00')
        finally:
            recovery.fetch_events=original
        self.assertEqual(meta['status'],'PARTIAL_REPLAY')
        self.assertEqual(meta['replayed_events'],2)
        self.assertGreater(meta['missing_5m_events_estimate'],90)
        self.assertLess(meta['coverage_pct'],5)
        self.assertEqual(len(out['seen']),2)


if __name__=='__main__': unittest.main()
