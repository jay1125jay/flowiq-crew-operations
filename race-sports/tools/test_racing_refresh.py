"""Regression checks for source isolation, bounded failure, and horse identity."""
import time
from pathlib import Path
import unittest
from datetime import datetime
from unittest.mock import patch
import racing_static_collector as collector
from kra_final_runner_repair import _preserve_pre_race, repair_doc
import inject_horse_model as horse_model
from snapshot_guard import merge_event


def fake_boat(z, errors):
    collector.core.selected_date = lambda raw, year: 'WRONG_DAY'
    return [], [{'provider': 'BOAT', 'status': 'PASS'}]


def fake_cycle(z, errors):
    time.sleep(.05)
    assert collector.core.selected_date('<option selected>2026-10-16</option>', 2026) == '2026-10-16'
    return [], [{'provider': 'CYCLE', 'status': 'PASS'}]


def blocked(z, errors):
    time.sleep(10)
    return [], []


class RefreshTests(unittest.TestCase):
    def test_boat_date_binding_does_not_change_cycle(self):
        _, providers, _ = collector.collect_parallel(datetime(2026, 10, 16), (fake_boat, fake_cycle), 2)
        self.assertEqual([p['provider'] for p in providers], ['BOAT', 'CYCLE'])

    def test_timeout_fails_closed_and_stops_children(self):
        start = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, 'DEADLINE'):
            collector.collect_parallel(datetime(2026, 10, 16), (blocked,), .1)
        self.assertLess(time.monotonic() - start, 2)

    def test_same_number_different_horse_never_inherits_odds(self):
        old = [{'key':'N1', 'horse_name':'이전말', 'odds':3.0, 'model_p':.7}]
        new = [{'key':'N1', 'horse_name':'현재말'}]
        row = _preserve_pre_race(old, new)[0]
        self.assertNotIn('odds', row)
        self.assertNotIn('model_p', row)

    def test_matching_identity_retains_pre_race_observation(self):
        old = [{'key':'N1', 'horse_name':'현재말', 'odds':3.0}]
        row = _preserve_pre_race(old, [{'key':'N1', 'horse_name':'현재말'}])[0]
        self.assertEqual(row['odds'], 3.0)

    def test_verified_final_survives_tomorrow_selector_without_refetch(self):
        event = {'id':'H1','event_date':'2026-10-16','sport':'HORSE','status':'FINAL',
                 'outcomes':[{'key':'N1','horse_name':'가'},{'key':'N2','horse_name':'나'}],
                 'final_runner_identity':{'date':'2026-10-16','event_id':'H1','source':'KRA_SCORETABLE_DETAIL_OFFICIAL'}}
        doc = {'date':'2026-10-16','events':[event], 'providers':[{'provider':'HORSE_RUNNERS_KRA','detail':{'page_date':'2026-10-17'}}]}
        with patch('kra_final_runner_repair._fetch_event') as fetch:
            repaired, total, cleared, errors, status = repair_doc(doc)
        fetch.assert_not_called()
        self.assertEqual((repaired, total, cleared, status), (1,1,0,'PASS'))
        fresh = {'id':'H1','event_date':'2026-10-16','sport':'HORSE','status':'FINAL','outcomes':[]}
        self.assertEqual(len(merge_event(event, fresh)['outcomes']), 2)

    def test_horse_live_model_excludes_today_and_future(self):
        def race(date):
            return {'id':date,'event_date':date,'outcomes':[
                {'horse_name':date,'won':True}, {'horse_name':'loser','won':False}]}
        with patch.object(horse_model,'iter_backfill',return_value=iter([
                race('2026-10-15'),race('2026-10-16'),race('2026-10-17')])), \
                patch.object(horse_model,'HISTORY',Path('/nonexistent-raceiq-test')):
            stats, base, rows, races = horse_model.build_stats(cutoff='2026-10-16')
        self.assertEqual((rows,races), (2,1))
        self.assertNotIn('2026-10-16',stats['horse'])


if __name__ == '__main__':
    unittest.main()
