"""Bounded public-feed smoke test. Disposable accounts, never production state."""
import argparse
from contextlib import closing
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import urllib.request
import realtime_runtime as rt

async def main():
    out=Path(__file__).parent/'browser-evidence'
    out.mkdir(exist_ok=True)
    samples=[]
    with tempfile.TemporaryDirectory(prefix='btc-paper-smoke-') as directory:
        # Reserve an ephemeral local port; no public endpoint.
        import socket
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        task=asyncio.create_task(rt.run(argparse.Namespace(state_dir=directory,host='127.0.0.1',port=port,seconds=90)))
        def read():
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=2) as response:
                return json.load(response)
        while not task.done():
            await asyncio.sleep(2)
            try:
                data=await asyncio.to_thread(read)
                row={k:data.get(k) for k in ('healthy','status','ticks','quote_at','source_at','updated_at','error')}
                samples.append(row)
                if len(samples)%10==0:print('SMOKE',json.dumps(row),flush=True)
            except Exception:
                pass
        await task
        with closing(sqlite3.connect(Path(directory)/'paper.sqlite')) as db:
            row=db.execute('SELECT body FROM state WHERE id=1').fetchone()
        state=json.loads(row[0]) if row else {}
        summary=dict(paper_only=True,real_trading_enabled=False,mode='DISPOSABLE_LIVE_SMOKE',
            ticks=state.get('ticks',0),healthy_samples=sum(bool(x['healthy']) for x in samples),
            engines=len(state.get('competition',{}).get('accounts',{})),samples=samples)
        (out/'realtime-live.json').write_text(json.dumps(summary,indent=2))
        assert summary['ticks']>=10 and summary['healthy_samples']>=3 and summary['engines']==6,summary
        print('REALTIME LIVE PASS',json.dumps({k:v for k,v in summary.items() if k!='samples'}))

if __name__=='__main__':asyncio.run(main())
