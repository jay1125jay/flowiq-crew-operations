"""Regression checks for source isolation, bounded failure, and horse identity."""
import time
import unittest
from datetime import datetime
from unittest.mock import patch
import racing_static_collector as collector
from kra_final_runner_repair import _preserve_pre_race


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


if __name__ == '__main__':
    unittest.main()
