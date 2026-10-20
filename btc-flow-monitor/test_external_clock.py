import contextlib
import datetime as dt
import importlib.util
import io
import os
import pathlib
import unittest
from unittest.mock import patch

P=pathlib.Path(__file__).parent/'external-clock'/'scheduler.py'
S=importlib.util.spec_from_file_location('btc_external_clock',P)
m=importlib.util.module_from_spec(S);S.loader.exec_module(m)
NOW=dt.datetime(2026,10,21,tzinfo=dt.timezone.utc)

class ExternalClockTests(unittest.TestCase):
    def row(self,age,status='completed'):
        return {'created_at':(NOW-dt.timedelta(seconds=age)).isoformat(),'status':status}
    def test_empty_history_dispatches(self):
        self.assertEqual(m.decision([],NOW),'DISPATCH')
    def test_active_run_skips(self):
        self.assertEqual(m.decision([self.row(30,'in_progress')],NOW),'SKIP_ACTIVE')
    def test_recent_completed_skips(self):
        self.assertEqual(m.decision([self.row(120)],NOW),'SKIP_RECENT')
    def test_old_completed_allows(self):
        self.assertEqual(m.decision([self.row(300)],NOW),'DISPATCH')
    def test_stuck_run_blocks(self):
        with self.assertRaises(ValueError):m.decision([self.row(1300,'queued')],NOW)
    def test_unknown_status_blocks(self):
        with self.assertRaises(ValueError):m.decision([self.row(300,'unknown')],NOW)
    def test_future_timestamp_blocks(self):
        with self.assertRaises(ValueError):m.decision([self.row(-120)],NOW)
    def test_disabled_makes_no_requests(self):
        with patch.dict(os.environ,{},clear=True),patch.object(m,'request') as req,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(),0);req.assert_not_called()
    def test_missing_secret_blocks(self):
        env={'BTC_SCHEDULER_ENABLED':'true','PAPER_ONLY':'true','REAL_TRADING':'false'}
        with patch.dict(os.environ,env,clear=True),patch.object(m,'request') as req,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(),1);req.assert_not_called()
    def test_live_flag_blocks(self):
        env={'BTC_SCHEDULER_ENABLED':'true','PAPER_ONLY':'true','REAL_TRADING':'true','BTC_GITHUB_TOKEN':'test'}
        with patch.dict(os.environ,env,clear=True),patch.object(m,'request') as req,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(),1);req.assert_not_called()
    def test_dispatch_calls_only_locked_workflow(self):
        env={'BTC_SCHEDULER_ENABLED':'true','PAPER_ONLY':'true','REAL_TRADING':'false','BTC_GITHUB_TOKEN':'test'}
        with patch.dict(os.environ,env,clear=True),patch.object(m,'request',side_effect=[{'workflow_runs':[]},{'accepted':True}]) as req,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(),0)
            self.assertEqual(req.call_args.args,('test','/dispatches',{'ref':'main'}))
            self.assertEqual(req.call_count,2)
    def test_dispatch_timeout_does_not_retry_or_leak(self):
        env={'BTC_SCHEDULER_ENABLED':'true','PAPER_ONLY':'true','REAL_TRADING':'false','BTC_GITHUB_TOKEN':'fake-private-test'}
        out=io.StringIO()
        with patch.dict(os.environ,env,clear=True),patch.object(m,'request',side_effect=[{'workflow_runs':[]},TimeoutError('fake-private-test')]) as req,contextlib.redirect_stdout(out):
            self.assertEqual(m.main(),1);self.assertEqual(req.call_count,2)
        self.assertNotIn('fake-private-test',out.getvalue())

if __name__=='__main__':unittest.main()
