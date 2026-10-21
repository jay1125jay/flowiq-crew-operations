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

if __name__=='__main__':unittest.main()
