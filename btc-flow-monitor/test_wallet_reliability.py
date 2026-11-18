import copy
import io
import json
import tempfile
import unittest
import asyncio
import sqlite3
import threading
import time
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

    def test_live_same_timestamp_reordering_is_applied_without_rest(self):
        second = dict(self.row, tid=2, startPosition='1')
        done, statuses, blocked = pc.apply_ordered(self.ledger,
            [(1, ('whale',second,200)), (2, ('whale',self.row,200))],paper,210)
        self.assertEqual(set(done),{1,2})
        self.assertEqual(blocked,set())
        self.assertEqual(self.ledger['accounts']['whale']['source_size'],2)
        self.assertEqual(self.ledger['accounts']['whale']['last_fill']['apply_delay_ms'],110)

    def test_waiting_fill_cannot_use_original_receipt_as_execution_time(self):
        pc.apply_event(self.ledger,('whale',self.row,200),paper,20_000)
        self.assertIsNone(self.ledger['accounts']['whale']['position'])
        self.assertEqual(self.ledger['accounts']['whale']['last_fill']['processing_delay_ms'],19_800)

    def test_blocked_wallet_does_not_block_other_wallet(self):
        self.ledger['accounts']['other']=copy.deepcopy(self.account)
        broken=dict(self.row,startPosition='8')
        done,_,blocked=pc.apply_ordered(self.ledger,
            [(1,('whale',broken,200)),(2,('other',self.row,200))],paper,210)
        self.assertEqual(done,[2])
        self.assertEqual(blocked,{'whale'})
        self.assertIsNotNone(self.ledger['accounts']['other']['position'])

    def test_publication_never_runs_slow_rest_even_on_heartbeat(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            with patch.object(pc,'git',return_value=''),patch.object(pc.subprocess,'run') as run:
                pc.synchronize(root,[],True,paper)
            run.assert_not_called()

    def test_snapshot_missing_fill_unblocks_buffered_live_fill(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(':memory:') as db:
            root=Path(folder)
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            observer=pc.Observer(root,paper,db)
            now=int(time.time()*1000)
            first=dict(self.row,time=now,tid=11)
            second=dict(first,tid=12,startPosition='1')
            def message(rows,snapshot=False):
                return dict(channel='userFills',data=dict(user='whale',fills=rows,isSnapshot=snapshot))
            observer.receive(message([second]))
            self.assertIn('whale',observer.blocked_wallets)
            observer.receive(message([first],True))
            self.assertEqual(observer.ledger['accounts']['whale']['source_size'],2)
            self.assertEqual(observer.blocked_wallets,set())
            observer.receive(message([first,second],True))
            self.assertEqual(observer.ledger['accounts']['whale']['fill_count'],2)
            self.assertEqual(len(observer.pending()),2)
            self.assertTrue(all('_paper_applied_ms' in event[1] for _,event in observer.pending()))

    def test_live_close_has_actual_application_timestamp(self):
        pc.apply_event(self.ledger,('whale',self.row,200),paper,210)
        closing=dict(self.row,time=300,tid=2,side='A',startPosition='1')
        pc.apply_event(self.ledger,('whale',closing,350),paper,360)
        account=self.ledger['accounts']['whale']
        self.assertIsNone(account['position'])
        self.assertEqual(account['closed'][-1]['apply_delay_ms'],60)
        self.assertEqual(account['closed'][-1]['processing_delay_ms'],10)

    def test_failed_execution_journal_write_does_not_mutate_local_account(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(':memory:') as db:
            root=Path(folder)
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            observer=pc.Observer(root,paper,db)
            before=copy.deepcopy(observer.ledger)
            db.execute("CREATE TRIGGER reject_timing BEFORE UPDATE ON pending BEGIN SELECT RAISE(ABORT, 'disk write failure'); END")
            row=dict(self.row,time=int(time.time()*1000))
            with self.assertRaises(sqlite3.IntegrityError):
                observer.receive(dict(channel='userFills',data=dict(user='whale',fills=[row])))
            self.assertEqual(observer.ledger,before)
            self.assertEqual(len(observer.pending()),1)
            db.execute('DROP TRIGGER reject_timing')
            observer.drain()
            self.assertEqual(observer.ledger['accounts']['whale']['fill_count'],1)

    def test_recovery_merges_after_already_applied_local_events(self):
        event=('whale',dict(self.row,_paper_applied_ms=210),200)
        base=copy.deepcopy(self.ledger)
        pc.apply_event(base,event,paper)
        candidate=copy.deepcopy(base)
        candidate['accounts']['whale']['error']=None
        candidate['accounts']['whale']['fill_cursor']=150
        candidate['accounts']['whale']['last_at']='recovered'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.ledger))
            with patch.object(pc,'git',return_value=''):
                result,done=pc.synchronize(root,[(1,event)],False,paper,[(1,base,candidate)])
        self.assertEqual(result['accounts']['whale']['fill_cursor'],150)
        self.assertEqual(result['accounts']['whale']['fill_count'],1)
        self.assertEqual(done,[1])

    def test_targeted_recovery_does_not_modify_other_accounts(self):
        import datetime as dt
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            ledger=copy.deepcopy(self.ledger)
            ledger['accounts']={str(i):copy.deepcopy(self.account) for i in range(5)}
            out=data/'wallet-paper.json'
            out.write_text(json.dumps(ledger))
            (data/'selected-whales.json').write_text(json.dumps([{'address':str(i)} for i in range(5)]))
            def info(payload):
                if payload['type']=='clearinghouseState':
                    self.assertEqual(payload['user'],'1')
                    return dict(time=100,marginSummary={'accountValue':'10000'},
                        assetPositions=[{'position':{'coin':'BTC','szi':'1','entryPx':'100'}}])
                if payload['type']=='l2Book':
                    return dict(coin='BTC',time=100,levels=[[{'px':'100'}],[{'px':'100'}]])
                return [self.row]
            with patch.object(paper,'DATA',data),patch.object(paper,'OUT',out), \
                 patch.object(paper,'info',side_effect=info), \
                 patch.object(paper,'now',return_value=dt.datetime.fromtimestamp(.1,dt.timezone.utc)):
                paper.main(['1'])
            result=json.loads(out.read_text())
            for address in ('0','2','3','4'):
                self.assertEqual(result['accounts'][address],ledger['accounts'][address])
            self.assertEqual(result['accounts']['1']['fill_count'],1)


class AsyncStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_recovery_does_not_pause_live_execution(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(':memory:') as db:
            root=Path(folder)
            path=root/pc.LEDGER
            path.parent.mkdir(parents=True)
            ledger=dict(paper_only=True,real_trading_enabled=False,accounts={
                'whale':dict(cash=1_000_000,equity_krw=1_000_000,position=None,closed=[],
                             fill_count=0,fill_cursor=0,source_size=0,source_equity_usd=100_000)})
            path.write_text(json.dumps(ledger))
            observer=pc.Observer(root,paper,db)
            started,release=threading.Event(),threading.Event()
            def slow_recovery(*args):
                started.set()
                if not release.wait(3):
                    raise TimeoutError('test recovery not released')
                return copy.deepcopy(ledger)
            with patch.object(pc,'reconcile_wallet',side_effect=slow_recovery):
                task=asyncio.create_task(observer.recover())
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait,2))
                    ms=int(time.time()*1000)
                    row=dict(time=ms,tid=1,px='100',sz='1',startPosition='0',side='B',coin='BTC')
                    observer.receive(dict(channel='userFills',data=dict(user='whale',fills=[row])))
                    self.assertIsNotNone(observer.ledger['accounts']['whale']['position'])
                    self.assertFalse(release.is_set())
                finally:
                    release.set()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task


if __name__ == '__main__':
    unittest.main()
