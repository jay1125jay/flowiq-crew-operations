import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import wallet_paper as paper
import pc_wallet_follow as pc
from publish_wallet_paper import merge_observations


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        paper._next_request = 0
        paper._rate_limited_until = 0
        self.account = dict(cash=1_000_000, equity_krw=1_000_000,
                            position=None, closed=[], fill_count=0,
                            fill_cursor=99, source_size=0, source_equity_usd=100_000)
        self.ledger = dict(paper_only=True, real_trading_enabled=False,
                           accounts={'whale': self.account})
        self.row = dict(time=100, tid=1, px='100', sz='1', startPosition='0', side='B', coin='BTC')

    def test_rate_limit_stops_other_workers_requests(self):
        error = urllib.error.HTTPError('url', 429, 'Too Many Requests', None, None)
        with patch.object(paper.urllib.request, 'urlopen', side_effect=error) as request:
            for _ in range(3):
                with self.assertRaises(urllib.error.HTTPError):
                    paper.info({'type':'l2Book'})
            self.assertEqual(request.call_count, 1)

    def test_duplicate_fill_is_not_charged_twice(self):
        event = ('whale', self.row, 200)
        self.assertEqual(pc.apply_event(self.ledger, event, paper), 'applied')
        after = copy.deepcopy(self.ledger)
        self.assertEqual(pc.apply_event(self.ledger, event, paper), 'covered')
        self.assertEqual(self.ledger, after)

    def test_stale_fill_does_not_open_position(self):
        pc.apply_event(self.ledger, ('whale', self.row, 20_000), paper)
        self.assertIsNone(self.ledger['accounts']['whale']['position'])

    def test_blocked_fill_cannot_bypass_recovery_schedule(self):
        self.row['startPosition'] = '3'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            with patch.object(pc, 'git', return_value=''), patch.object(pc.subprocess, 'run') as run:
                result, done = pc.synchronize(root, [(1, ('whale', self.row, 200))], False, paper)
            run.assert_not_called()
            self.assertEqual(done, [])
            self.assertEqual(result, self.ledger)

    def test_failed_push_does_not_acknowledge_pending_events(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            def git(_root, *args):
                if args[0] == 'push':
                    raise RuntimeError('push rejected')
                return pc.LEDGER if args[0] == 'diff' else ''
            with patch.object(pc, 'git', side_effect=git):
                with self.assertRaisesRegex(RuntimeError, 'push rejected'):
                    pc.synchronize(root, [(1, ('whale', self.row, 200))], False, paper)

    def test_same_millisecond_fills_follow_position_chain(self):
        a = copy.deepcopy(self.account)
        second = dict(self.row, tid=2, startPosition='1')
        paper.process_batch(a, [second, self.row], 100_000, 100, 100, 'stamp', 200)
        self.assertEqual(a['fill_count'], 2)
        self.assertEqual(a['source_size'], 2)

    def test_pagination_overlaps_and_deduplicates_boundary(self):
        first = [dict(self.row, time=i, tid=i) for i in range(1, 2001)]
        second = [first[-1], dict(self.row, time=2000, tid=2001),
                  dict(self.row, time=2002, tid=2002)]
        with patch.object(paper, 'info', side_effect=[first, second]) as request:
            result = paper.fetch_fills('whale', 1, 3000)
        self.assertEqual(len(result), 2002)
        self.assertEqual(request.call_args_list[1].args[0]['startTime'], 2000)

    def test_full_identical_timestamp_page_fails_without_skipping(self):
        page = [dict(self.row, time=100, tid=i) for i in range(2000)]
        with patch.object(paper, 'info', return_value=page) as request:
            with self.assertRaisesRegex(ValueError, 'pagination stalled'):
                paper.fetch_fills('whale', 100, 200)
        self.assertEqual(request.call_count, 1)

    def test_fill_query_reserves_weight_budget(self):
        with patch.object(paper.time, 'monotonic', return_value=100), \
             patch.object(paper.time, 'sleep') as sleep, \
             patch.object(paper.urllib.request, 'urlopen', return_value=io.StringIO('[]')):
            paper.info({'type':'userFillsByTime'})
        self.assertEqual(paper._next_request, 112)

    def test_cloud_recovery_preserves_other_wallet_live_fills(self):
        base = copy.deepcopy(self.ledger)
        base['accounts']['other'] = copy.deepcopy(self.account)
        candidate, latest = copy.deepcopy(base), copy.deepcopy(base)
        candidate['accounts']['whale']['fill_cursor'] = 500
        candidate['accounts']['whale']['cash'] = 990_000
        latest['accounts']['other']['fill_cursor'] = 600
        latest['accounts']['other']['cash'] = 1_010_000
        merged, applied, conflicts = merge_observations(base, candidate, latest)
        self.assertEqual(applied, ['whale'])
        self.assertEqual(merged['accounts']['whale'], candidate['accounts']['whale'])
        self.assertEqual(merged['accounts']['other'], latest['accounts']['other'])
        self.assertEqual(base['accounts']['whale']['cash'], 1_000_000)

    def test_same_wallet_concurrent_changes_are_never_overwritten(self):
        base = copy.deepcopy(self.ledger)
        candidate, latest = copy.deepcopy(base), copy.deepcopy(base)
        candidate['accounts']['whale']['fill_cursor'] = 500
        latest['accounts']['whale']['fill_cursor'] = 600
        merged, applied, conflicts = merge_observations(base, candidate, latest)
        self.assertEqual(merged, latest)
        self.assertEqual(applied, [])
        self.assertEqual(conflicts, ['whale'])

    def test_selection_change_cannot_restore_retired_whale(self):
        base = copy.deepcopy(self.ledger)
        candidate, latest = copy.deepcopy(base), copy.deepcopy(base)
        latest['accounts'] = {'new': copy.deepcopy(self.account)}
        merged, applied, conflicts = merge_observations(base, candidate, latest)
        self.assertEqual(merged, latest)
        self.assertEqual(applied, [])


if __name__ == '__main__':
    unittest.main()
