"""Exercise process ownership and runtime start/stop on both Windows and Linux CI."""
import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import realtime_runtime as rt

class DesktopRuntimeTests(unittest.TestCase):
    def test_other_process_blocked_then_can_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            store=rt.Store(directory)
            code='import sys; from realtime_runtime import Store; s=Store(sys.argv[1]); s.close()'
            result=subprocess.run([sys.executable,'-c',code,directory],cwd=rt.ROOT,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('another PAPER writer',result.stderr)
            store.close()
            result=subprocess.run([sys.executable,'-c',code,directory],cwd=rt.ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_bounded_start_stop_releases_port_and_store(self):
        async def idle(quotes,stop):
            while not stop.is_set():await asyncio.sleep(.01)
        def collector(directory,shared,stop):stop.wait(5)
        with tempfile.TemporaryDirectory() as directory:
            args=argparse.Namespace(state_dir=directory,host='127.0.0.1',port=0,seconds=1,open_browser=False)
            env={'PAPER_ONLY':'true','REAL_TRADING':'false'}
            with patch.dict(os.environ,env),patch.object(rt,'stream',idle),patch.object(rt,'collect_sources',collector):
                asyncio.run(rt.run(args))
                asyncio.run(rt.run(args))
            store=rt.Store(directory);store.close()

    def test_windows_autostart_controls_are_paper_only(self):
        windows=Path(__file__).with_name('windows')
        start=(windows/'START_BTC_FLOW.cmd').read_text(encoding='utf-8')
        install=(windows/'INSTALL_AUTOSTART.cmd').read_text(encoding='utf-8')
        remove=(windows/'REMOVE_AUTOSTART.cmd').read_text(encoding='utf-8')
        self.assertIn('set "PAPER_ONLY=true"',start)
        self.assertIn('set "REAL_TRADING=false"',start)
        self.assertIn('pc_runtime.py',start)
        self.assertIn('START_BTC_FLOW.cmd',install)
        self.assertIn('Register-ScheduledTask',install)
        self.assertIn('New-ScheduledTaskTrigger -AtLogOn',install)
        self.assertIn('MultipleInstances IgnoreNew',install)
        self.assertIn('RunLevel Limited',install)
        self.assertIn('Unregister-ScheduledTask',remove)
        self.assertIn('BTC FLOW PAPER Autostart',install)
        self.assertIn('BTC FLOW PAPER Autostart',remove)

if __name__=='__main__':unittest.main()
